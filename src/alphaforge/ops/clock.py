"""Per-cycle exchange clock-sanity check (buildabilityCritique.md section 4, Phase 8).

Why this matters
----------------
The live loop wakes at bar close + a fixed grace and reads the just-closed bar to
decide. Two clock failures silently corrupt that decision and neither raises on
its own:

- A drifting LOCAL clock moves the loop's notion of "bar close" away from the
  exchange's. Wake too early and the just-closed bar is not yet queryable -> the
  ingest watermark lags -> the staleness gate fires or, worse, a stale prior bar
  is read. Wake too late and the decision is made on data that already moved.
- A stale EXCHANGE feed (or a local clock that ran ahead) makes recent bars look
  unchanging. Unchanging prices read as LOW volatility, and the vol-targeting
  overlay LEVERS UP into what is actually a data outage -- exactly the failure
  the staleness breaker exists to stop. The breaker catches a frozen feed; THIS
  check catches the clock drift that lets a frozen feed look fresh.

So the defense is two-layered: the staleness breaker (data side) plus this
clock-sanity check (time side). Once per cycle the loop compares its local wall
clock against the exchange server time and alerts when the absolute skew exceeds
``max_skew_ms`` (default 2000 ms, per buildabilityCritique.md: "assert clock
sanity ... alert on > 2s"). The check NEVER halts on its own -- it returns a
:class:`ClockCheck` and lets the caller decide (alert, count, or gate); a clock
read must not be able to crash the trading loop.

Contract
--------
``skew_ms = local_ms - exchange_ms`` (positive => local clock is AHEAD of the
exchange). ``ok`` iff ``abs(skew_ms) <= max_skew_ms``. All times are integer
epoch milliseconds UTC (:data:`~alphaforge.core.time.Ms`). The exchange time
comes through the :class:`ExchangeTimeSource` protocol so tests inject a canned
source and nothing here ever touches the real network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from alphaforge.core.time import Ms

__all__ = [
    "CCXTExchangeTimeSource",
    "ClockCheck",
    "ClockSanity",
    "ExchangeTimeSource",
    "FakeExchangeTimeSource",
]


@runtime_checkable
class ExchangeTimeSource(Protocol):
    """A source of the exchange's authoritative server time, in epoch ms UTC.

    Implementations must return a single integer epoch-millisecond reading per
    call. They MAY perform network I/O (the ccxt source does); callers treat the
    call as potentially slow and never invoke it on the hot decision path more
    than once per cycle.
    """

    def server_time_ms(self) -> Ms:
        """Return the exchange server time as integer epoch milliseconds UTC."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ClockCheck:
    """The result of one :meth:`ClockSanity.check`.

    - ``local_ms``: the local wall-clock reading the caller passed in.
    - ``exchange_ms``: the exchange server-time reading.
    - ``skew_ms``: ``local_ms - exchange_ms`` (positive => local AHEAD of exchange).
    - ``ok``: ``True`` iff ``abs(skew_ms) <= max_skew_ms`` for the threshold the
      :class:`ClockSanity` was built with.
    """

    local_ms: Ms
    exchange_ms: Ms
    skew_ms: int
    ok: bool

    def describe(self) -> str:
        """One-line operator summary, e.g. ``'clock ok: skew=+12ms (<=2000ms)'``."""
        verdict = "ok" if self.ok else "SKEW ALERT"
        sign = "+" if self.skew_ms >= 0 else "-"
        return f"clock {verdict}: skew={sign}{abs(self.skew_ms)}ms"


class ClockSanity:
    """Compares local wall-clock time against an exchange server clock per cycle.

    Args:
        source: the :class:`ExchangeTimeSource` queried for exchange server time.
        max_skew_ms: tolerated absolute skew before :attr:`ClockCheck.ok` flips to
            ``False``. Default 2000 ms (buildabilityCritique.md: alert on > 2s).
            Must be ``>= 0``.

    Raises:
        ValueError: if ``max_skew_ms < 0``.
    """

    __slots__ = ("_max_skew_ms", "_source")

    def __init__(self, source: ExchangeTimeSource, *, max_skew_ms: int = 2000) -> None:
        if max_skew_ms < 0:
            raise ValueError(f"max_skew_ms must be >= 0, got {max_skew_ms}")
        self._source = source
        self._max_skew_ms = max_skew_ms

    @property
    def max_skew_ms(self) -> int:
        """The tolerated absolute skew threshold in milliseconds."""
        return self._max_skew_ms

    def check(self, *, now: Ms) -> ClockCheck:
        """Read the exchange clock and compare it against local ``now``.

        ``now`` is the local wall-clock reading (the loop passes
        :func:`~alphaforge.core.time.now_ms`); it is injected so the check is
        deterministic in tests. Computes ``skew_ms = now - exchange_ms`` and
        flags ``ok`` iff ``abs(skew_ms) <= max_skew_ms``. The boundary is
        INCLUSIVE: a skew of exactly ``max_skew_ms`` is still ``ok``.

        Any exception from the source propagates to the caller -- the loop wraps
        this call so a transient exchange-time fetch failure becomes an alert, not
        a crash; this method does not swallow errors so a persistent failure stays
        visible.

        Args:
            now: local wall-clock epoch milliseconds UTC.

        Returns:
            A :class:`ClockCheck` with the readings, signed skew, and verdict.
        """
        exchange_ms = self._source.server_time_ms()
        skew_ms = int(now) - int(exchange_ms)
        ok = abs(skew_ms) <= self._max_skew_ms
        return ClockCheck(local_ms=now, exchange_ms=exchange_ms, skew_ms=skew_ms, ok=ok)


class CCXTExchangeTimeSource:
    """Exchange server time via a ccxt-shaped client.

    Prefers the unified ``client.fetch_time()`` (returns epoch ms) and falls back
    to the Binance USDT-M raw ``fapiPublicGetTime`` endpoint (payload
    ``{"serverTime": <ms>}``) when the unified method is absent. Both are public,
    unauthenticated, single-shot calls. The client is injectable so tests pass a
    fake with no network access.

    Args:
        client: a ccxt-shaped client exposing ``fetch_time`` and/or
            ``fapiPublicGetTime``.

    Raises:
        AttributeError: if the client exposes neither time endpoint (surfaced at
            first :meth:`server_time_ms` call, not construction).
    """

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def server_time_ms(self) -> Ms:
        """Return the exchange server time as integer epoch milliseconds UTC.

        Tries ``fetch_time()`` first, then ``fapiPublicGetTime()['serverTime']``.

        Raises:
            AttributeError: the client exposes no usable time endpoint.
        """
        fetch_time = getattr(self._client, "fetch_time", None)
        if callable(fetch_time):
            return int(fetch_time())
        raw = getattr(self._client, "fapiPublicGetTime", None)
        if callable(raw):
            payload: Any = raw()
            return int(payload["serverTime"])
        raise AttributeError(
            "ccxt client exposes neither fetch_time nor fapiPublicGetTime; "
            "cannot read exchange server time"
        )


class FakeExchangeTimeSource:
    """A canned :class:`ExchangeTimeSource` for deterministic offline tests.

    Returns a fixed epoch-ms reading (or, when seeded with a sequence, the next
    reading per call, repeating the last value once exhausted). No network.

    Args:
        server_time_ms: the single fixed exchange reading, OR ``None`` when a
            sequence is supplied.
        sequence: optional successive readings; each call pops the next one and
            the final value is sticky thereafter. Exactly one of
            ``server_time_ms`` / ``sequence`` must be given.

    Raises:
        ValueError: if neither or both of ``server_time_ms`` / ``sequence`` is
            given, or ``sequence`` is empty.
    """

    __slots__ = ("_calls", "_seq")

    def __init__(
        self,
        server_time_ms: Ms | None = None,
        *,
        sequence: list[Ms] | None = None,
    ) -> None:
        if (server_time_ms is None) == (sequence is None):
            raise ValueError("provide exactly one of server_time_ms or sequence")
        if sequence is not None and not sequence:
            raise ValueError("sequence must be non-empty")
        if server_time_ms is not None:
            self._seq: list[Ms] = [server_time_ms]
        else:
            self._seq = list(sequence or [])
        self._calls = 0

    @property
    def call_count(self) -> int:
        """Number of times :meth:`server_time_ms` has been called (test assertion hook)."""
        return self._calls

    def server_time_ms(self) -> Ms:
        """Return the next canned reading (sticky on the last once the sequence is exhausted)."""
        idx = min(self._calls, len(self._seq) - 1)
        self._calls += 1
        return self._seq[idx]
