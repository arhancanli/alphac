"""Outbound alerting for the live loop (execDesign.md s9.4, buildabilityCritique.md s1).

v1 alerting is OUTBOUND ONLY: the loop pushes INFO/WARN/CRITICAL messages and the
daily tearsheet to the operator's phone, and the brake is the file-sentinel
kill-switch (``touch var/KILL``) -- there is deliberately NO inbound command
poller (no ``/halt`` or ``/kill`` over Telegram), so the alerting path cannot be
turned into a remote control surface. The kill-switch lives in
:mod:`alphaforge.risk.killswitch`; this module merely provides
:meth:`Alerter.alert_halt` so a halt is announced loudly.

Implementations
---------------
- :class:`TelegramAlerter` -- raw Telegram Bot API over an injectable
  :class:`httpx.Client` (no python-telegram-bot dependency). Tests inject a
  ``MockTransport``-backed client; nothing here ever touches the real network in
  tests.
- :class:`LogAlerter` -- structlog fallback used when no Telegram token is
  configured; every alert still lands in the JSONL log.
- :class:`MultiAlerter` -- fans one alert out to several alerters (e.g. Telegram +
  log), tolerating a single alerter's failure so one broken sink never silences
  the rest.

Use :func:`build_alerter` to pick the right implementation from config/env.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from alphaforge.core.logging import get_logger

__all__ = [
    "AlertLevel",
    "Alerter",
    "LogAlerter",
    "MultiAlerter",
    "TelegramAlerter",
    "build_alerter",
]

_log = get_logger("alphaforge.live.alerts")

_TELEGRAM_API_BASE = "https://api.telegram.org"


class AlertLevel(StrEnum):
    """Alert severity. INFO is routine, WARN is actionable, CRITICAL means the
    system halted or is at risk and a human must look now."""

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@runtime_checkable
class Alerter(Protocol):
    """The outbound-alert sink the live loop holds.

    Concrete sinks must be total over delivery failure: ``alert`` reports a
    problem rather than raising, so a dead network never crashes the trading
    loop. The convenience methods (``info``/``warn``/``critical``/``alert_halt``)
    are thin wrappers over :meth:`alert`.
    """

    def alert(self, level: AlertLevel, message: str) -> bool:
        """Deliver ``message`` at ``level``; return True on success, False on failure."""
        ...

    def send_tearsheet(self, path: Path, caption: str) -> bool:
        """Deliver the daily tearsheet image at ``path`` with ``caption``; True on success."""
        ...


class _AlerterMixin:
    """Shared level-convenience wrappers for Alerter implementations."""

    def alert(self, level: AlertLevel, message: str) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def info(self, message: str) -> bool:
        """Send an INFO alert."""
        return self.alert(AlertLevel.INFO, message)

    def warn(self, message: str) -> bool:
        """Send a WARN alert."""
        return self.alert(AlertLevel.WARN, message)

    def critical(self, message: str) -> bool:
        """Send a CRITICAL alert."""
        return self.alert(AlertLevel.CRITICAL, message)

    def alert_halt(self, reason: str) -> bool:
        """Announce that trading has halted (the kill-switch engaged elsewhere).

        This module does NOT own the kill-switch
        (:mod:`alphaforge.risk.killswitch` does); it only broadcasts a CRITICAL
        notice so the halt is never silent.
        """
        return self.alert(AlertLevel.CRITICAL, f"TRADING HALTED: {reason}")


class TelegramAlerter(_AlerterMixin):
    """Outbound Telegram alerter over the raw Bot API (``sendMessage``/``sendPhoto``).

    Args:
        token: the bot token from ``@BotFather`` (env ``TELEGRAM_BOT_TOKEN``).
        chat_id: the destination chat id (env ``TELEGRAM_CHAT_ID``).
        http: injectable :class:`httpx.Client`. Tests pass a ``MockTransport``-backed
            client; ``None`` constructs a default 10s-timeout client owned by the
            process. The client is treated as owned by the caller when injected.

    Delivery is best-effort: a transport error or non-2xx response is logged and
    returns ``False`` -- never raised -- so the live loop is never killed by a
    flaky network or a Telegram outage.
    """

    __slots__ = ("_chat_id", "_http", "_owns_http", "_token")

    def __init__(self, token: str, chat_id: str, *, http: httpx.Client | None = None) -> None:
        if not token:
            raise ValueError("TelegramAlerter requires a non-empty token")
        if not chat_id:
            raise ValueError("TelegramAlerter requires a non-empty chat_id")
        self._token = token
        self._chat_id = chat_id
        self._owns_http = http is None
        self._http = http if http is not None else httpx.Client(timeout=10.0)

    def _method_url(self, method: str) -> str:
        """Return the Bot API endpoint URL for ``method`` (token kept out of logs)."""
        return f"{_TELEGRAM_API_BASE}/bot{self._token}/{method}"

    def alert(self, level: AlertLevel, message: str) -> bool:
        """POST ``message`` to ``sendMessage`` with a level prefix; True on a 2xx reply."""
        text = f"[{level.value.upper()}] {message}"
        payload = {"chat_id": self._chat_id, "text": text, "disable_notification": False}
        try:
            resp = self._http.post(self._method_url("sendMessage"), data=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.warning("telegram_alert_failed", level=level.value, error=str(exc))
            return False
        return True

    def send_tearsheet(self, path: Path, caption: str) -> bool:
        """POST the image at ``path`` to ``sendPhoto`` with ``caption``; True on 2xx.

        Missing file or a delivery failure is logged and returns ``False``.
        """
        if not path.is_file():
            _log.warning("telegram_tearsheet_missing", path=str(path))
            return False
        try:
            with path.open("rb") as fh:
                resp = self._http.post(
                    self._method_url("sendPhoto"),
                    data={"chat_id": self._chat_id, "caption": caption},
                    files={"photo": (path.name, fh, "image/png")},
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.warning("telegram_tearsheet_failed", path=str(path), error=str(exc))
            return False
        return True

    def close(self) -> None:
        """Close the underlying client iff this alerter created it."""
        if self._owns_http:
            self._http.close()


class LogAlerter(_AlerterMixin):
    """Fallback alerter that writes every alert to the structlog JSONL sink.

    Used when no Telegram token is configured, and inside :class:`MultiAlerter`
    as a durable record of every alert regardless of network reachability.
    Always succeeds (logging does not fail the trading loop).
    """

    __slots__ = ()

    def alert(self, level: AlertLevel, message: str) -> bool:
        """Emit ``message`` at the structlog level matching ``level``; always True."""
        if level is AlertLevel.CRITICAL:
            _log.critical("alert", level=level.value, message=message)
        elif level is AlertLevel.WARN:
            _log.warning("alert", level=level.value, message=message)
        else:
            _log.info("alert", level=level.value, message=message)
        return True

    def send_tearsheet(self, path: Path, caption: str) -> bool:
        """Log the tearsheet path and caption; always True (no transport)."""
        _log.info("tearsheet", path=str(path), caption=caption)
        return True


class MultiAlerter(_AlerterMixin):
    """Fan one alert out to several alerters, tolerating individual failures.

    A single sink raising or returning ``False`` does not stop the others, and
    does not raise: :meth:`alert` returns ``True`` iff *every* sink succeeded,
    so the loop can still tell whether delivery was fully clean while never being
    killed by one broken sink. A typical wiring is ``[TelegramAlerter, LogAlerter]``
    so the JSONL log always records the alert even if Telegram is down.
    """

    __slots__ = ("_alerters",)

    def __init__(self, alerters: list[Alerter]) -> None:
        if not alerters:
            raise ValueError("MultiAlerter requires at least one alerter")
        self._alerters = tuple(alerters)

    def alert(self, level: AlertLevel, message: str) -> bool:
        """Send to every sink; True iff all succeeded (failures are logged, not raised)."""
        all_ok = True
        for alerter in self._alerters:
            try:
                ok = alerter.alert(level, message)
            except Exception as exc:  # one sink must never kill the loop
                _log.warning("multi_alert_sink_failed", error=str(exc))
                ok = False
            all_ok = all_ok and ok
        return all_ok

    def send_tearsheet(self, path: Path, caption: str) -> bool:
        """Send the tearsheet to every sink; True iff all succeeded."""
        all_ok = True
        for alerter in self._alerters:
            try:
                ok = alerter.send_tearsheet(path, caption)
            except Exception as exc:  # one sink must never kill the loop
                _log.warning("multi_tearsheet_sink_failed", error=str(exc))
                ok = False
            all_ok = all_ok and ok
        return all_ok


def build_alerter(
    token: str | None,
    chat_id: str | None,
    *,
    http: httpx.Client | None = None,
) -> Alerter:
    """Construct the right alerter from config/env.

    With both ``token`` and ``chat_id`` present, returns a :class:`MultiAlerter`
    of ``[TelegramAlerter, LogAlerter]`` (phone push plus a durable log record).
    Otherwise returns a bare :class:`LogAlerter` -- a token-less deployment still
    records every alert in the JSONL log rather than silently dropping it.
    """
    if token and chat_id:
        return MultiAlerter([TelegramAlerter(token, chat_id, http=http), LogAlerter()])
    return LogAlerter()
