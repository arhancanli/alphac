"""Unit tests for :mod:`alphaforge.live.alerts` (offline, no network, tmp_path only).

``TelegramAlerter`` is driven through an :class:`httpx.MockTransport`-backed client
so the real Telegram API is never contacted: tests assert the exact POST payload
(chat_id, level-prefixed text, endpoint) and the best-effort failure contract
(transport/4xx errors return ``False`` rather than raising). ``LogAlerter`` and
``MultiAlerter`` fan-out / fault-tolerance are checked with capture doubles, and
:func:`build_alerter` selection is verified for the token / token-less paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from alphaforge.live.alerts import (
    Alerter,
    AlertLevel,
    LogAlerter,
    MultiAlerter,
    TelegramAlerter,
    build_alerter,
)

TOKEN = "123456:TESTBOTTOKEN"
CHAT = "987654321"


@dataclass
class _Captured:
    """A single captured outbound request (method path + parsed payload)."""

    path: str
    content: bytes
    content_type: str


def _client(captures: list[_Captured], *, status: int = 200) -> httpx.Client:
    """Build an httpx.Client whose transport records requests and returns ``status``.

    No socket is opened: :class:`httpx.MockTransport` invokes the handler in-process.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captures.append(
            _Captured(
                path=request.url.path,
                content=request.content,
                content_type=request.headers.get("content-type", ""),
            )
        )
        return httpx.Response(status, json={"ok": status < 400})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _form(content: bytes) -> dict[str, str]:
    """Parse an application/x-www-form-urlencoded body into a dict."""
    from urllib.parse import parse_qsl

    return dict(parse_qsl(content.decode()))


# ------------------------------------------------------------- TelegramAlerter


class TestTelegramAlerter:
    def test_alert_posts_expected_payload(self) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        assert alerter.alert(AlertLevel.WARN, "drawdown tier 2") is True
        assert len(caps) == 1
        cap = caps[0]
        assert cap.path == f"/bot{TOKEN}/sendMessage"
        payload = _form(cap.content)
        assert payload["chat_id"] == CHAT
        assert payload["text"] == "[WARN] drawdown tier 2"

    def test_level_prefix_for_each_level(self) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        alerter.info("a")
        alerter.warn("b")
        alerter.critical("c")
        texts = [_form(c.content)["text"] for c in caps]
        assert texts == ["[INFO] a", "[WARN] b", "[CRITICAL] c"]

    def test_alert_halt_is_critical_with_reason(self) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        assert alerter.alert_halt("equity divergence 2.4%") is True
        text = _form(caps[0].content)["text"]
        assert text == "[CRITICAL] TRADING HALTED: equity divergence 2.4%"

    def test_token_kept_in_url_not_in_payload(self) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        alerter.info("hi")
        assert TOKEN in caps[0].path
        assert TOKEN not in caps[0].content.decode()

    def test_non_2xx_returns_false_not_raise(self) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps, status=429))
        assert alerter.alert(AlertLevel.INFO, "rate limited") is False

    def test_transport_error_returns_false_not_raise(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        alerter = TelegramAlerter(TOKEN, CHAT, http=client)
        assert alerter.critical("network down") is False

    def test_empty_token_rejected(self) -> None:
        with pytest.raises(ValueError, match="token"):
            TelegramAlerter("", CHAT)

    def test_empty_chat_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="chat_id"):
            TelegramAlerter(TOKEN, "")

    def test_injected_client_not_closed_on_close(self) -> None:
        """An injected client is owned by the caller: close() must not shut it."""
        client = _client([])
        alerter = TelegramAlerter(TOKEN, CHAT, http=client)
        alerter.close()
        assert client.is_closed is False
        client.close()

    def test_send_tearsheet_posts_photo(self, tmp_path: Path) -> None:
        png = tmp_path / "tearsheet.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        assert alerter.send_tearsheet(png, caption="Day P&L +1.2%") is True
        assert caps[0].path == f"/bot{TOKEN}/sendPhoto"
        # multipart body carries the caption and the file bytes.
        body = caps[0].content
        assert b"Day P&L +1.2%" in body
        assert b"fakeimage" in body
        assert caps[0].content_type.startswith("multipart/form-data")

    def test_send_tearsheet_missing_file_returns_false(self, tmp_path: Path) -> None:
        caps: list[_Captured] = []
        alerter = TelegramAlerter(TOKEN, CHAT, http=_client(caps))
        assert alerter.send_tearsheet(tmp_path / "nope.png", caption="x") is False
        assert caps == []  # never attempted the POST


# ------------------------------------------------------------------ LogAlerter


class TestLogAlerter:
    def test_alert_always_succeeds(self) -> None:
        alerter = LogAlerter()
        assert alerter.alert(AlertLevel.INFO, "ok") is True
        assert alerter.warn("w") is True
        assert alerter.critical("c") is True
        assert alerter.alert_halt("reason") is True

    def test_send_tearsheet_always_succeeds(self, tmp_path: Path) -> None:
        assert LogAlerter().send_tearsheet(tmp_path / "any.png", caption="x") is True

    def test_emits_to_structlog(self) -> None:
        """Every level lands in the structlog stream (captured)."""
        import structlog

        cap = structlog.testing.LogCapture()
        structlog.configure(processors=[cap])
        try:
            LogAlerter().alert(AlertLevel.CRITICAL, "halt now")
        finally:
            structlog.reset_defaults()
        assert len(cap.entries) == 1
        assert cap.entries[0]["message"] == "halt now"
        assert cap.entries[0]["log_level"] == "critical"


# ---------------------------------------------------------------- MultiAlerter


@dataclass
class _Capture(Alerter):
    """A capture Alerter double recording calls and returning a configurable result."""

    result: bool = True
    raises: bool = False
    alerts: list[tuple[AlertLevel, str]] = field(default_factory=list)
    tearsheets: list[tuple[str, str]] = field(default_factory=list)

    def alert(self, level: AlertLevel, message: str) -> bool:
        if self.raises:
            raise RuntimeError("sink down")
        self.alerts.append((level, message))
        return self.result

    def send_tearsheet(self, path: Path, caption: str) -> bool:
        if self.raises:
            raise RuntimeError("sink down")
        self.tearsheets.append((str(path), caption))
        return self.result


class TestMultiAlerter:
    def test_fans_out_to_all(self) -> None:
        a, b = _Capture(), _Capture()
        multi = MultiAlerter([a, b])
        assert multi.alert(AlertLevel.WARN, "msg") is True
        assert a.alerts == [(AlertLevel.WARN, "msg")]
        assert b.alerts == [(AlertLevel.WARN, "msg")]

    def test_all_ok_only_when_every_sink_ok(self) -> None:
        good, bad = _Capture(result=True), _Capture(result=False)
        multi = MultiAlerter([good, bad])
        assert multi.alert(AlertLevel.INFO, "m") is False
        # The good sink still received it despite the bad result.
        assert good.alerts == [(AlertLevel.INFO, "m")]

    def test_one_raising_sink_does_not_stop_others_or_raise(self) -> None:
        boom, good = _Capture(raises=True), _Capture()
        multi = MultiAlerter([boom, good])
        result = multi.alert(AlertLevel.CRITICAL, "halt")
        assert result is False  # boom counted as failure
        assert good.alerts == [(AlertLevel.CRITICAL, "halt")]  # still delivered

    def test_tearsheet_fans_out(self, tmp_path: Path) -> None:
        a, b = _Capture(), _Capture()
        multi = MultiAlerter([a, b])
        png = tmp_path / "t.png"
        assert multi.send_tearsheet(png, caption="cap") is True
        assert a.tearsheets == [(str(png), "cap")]
        assert b.tearsheets == [(str(png), "cap")]

    def test_tearsheet_tolerates_raising_sink(self, tmp_path: Path) -> None:
        boom, good = _Capture(raises=True), _Capture()
        multi = MultiAlerter([boom, good])
        png = tmp_path / "t.png"
        assert multi.send_tearsheet(png, caption="cap") is False
        assert good.tearsheets == [(str(png), "cap")]

    def test_empty_alerter_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            MultiAlerter([])

    def test_convenience_wrappers_route_through_alert(self) -> None:
        cap = _Capture()
        multi = MultiAlerter([cap])
        multi.info("i")
        multi.warn("w")
        multi.critical("c")
        multi.alert_halt("r")
        assert cap.alerts == [
            (AlertLevel.INFO, "i"),
            (AlertLevel.WARN, "w"),
            (AlertLevel.CRITICAL, "c"),
            (AlertLevel.CRITICAL, "TRADING HALTED: r"),
        ]


# --------------------------------------------------------------- build_alerter


class TestBuildAlerter:
    def test_token_and_chat_builds_multi_with_telegram(self) -> None:
        caps: list[_Captured] = []
        alerter = build_alerter(TOKEN, CHAT, http=_client(caps))
        assert isinstance(alerter, MultiAlerter)
        # It actually drives Telegram (one POST) and the log together.
        assert alerter.alert(AlertLevel.INFO, "wired") is True
        assert len(caps) == 1
        assert caps[0].path == f"/bot{TOKEN}/sendMessage"

    def test_no_token_falls_back_to_log_alerter(self) -> None:
        assert isinstance(build_alerter(None, CHAT), LogAlerter)
        assert isinstance(build_alerter(TOKEN, None), LogAlerter)
        assert isinstance(build_alerter(None, None), LogAlerter)
        assert isinstance(build_alerter("", ""), LogAlerter)

    def test_log_fallback_still_records(self) -> None:
        alerter = build_alerter(None, None)
        assert alerter.alert(AlertLevel.CRITICAL, "no telegram but logged") is True
