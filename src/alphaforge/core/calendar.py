"""Trading calendars — session membership, bar grids, annualization, funding schedules.

ONE calendar abstraction (buildabilityCritique.md ruling 3.3): dataDesign.md's
``TradingCalendar`` (``expected_bar_opens``, ``is_session``) and execDesign.md's
``BarCalendar`` (``periods_per_year``, bar arithmetic, funding instants) are the same
object, merged here. Annualization factors are never hard-coded downstream — they come
from :meth:`TradingCalendar.periods_per_year` so an equities session calendar (~252-day
basis, via the ``exchange_calendars`` package) plugs in later without engine changes.

All timestamps are UTC epoch milliseconds (:data:`~alphaforge.core.time.Ms`); all
ranges are half-open ``[start_ms, end_ms)``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Final

from alphaforge.core import time as core_time
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import AssetClass

__all__ = [
    "Always24x7Calendar",
    "TradingCalendar",
    "calendar_for",
]

_MS_PER_HOUR: Final[int] = 3_600_000
_MS_PER_DAY: Final[int] = 86_400_000


class TradingCalendar(ABC):
    """Defines when bars exist, how many there are per year, and where funding falls.

    Crypto: a bar every Δ, around the clock (:class:`Always24x7Calendar`). Equities
    later: exchange sessions filter the 24/7 grid — gap detection, bar-availability
    math, and annualization all consult this object, never their own constants.
    """

    @abstractmethod
    def is_session(self, ts: Ms) -> bool:
        """Return True iff the market trades at instant ``ts`` (epoch ms, UTC)."""

    @abstractmethod
    def expected_bar_opens(self, start_ms: Ms, end_ms: Ms, tf: Timeframe) -> list[Ms]:
        """Return every ``tf`` bar open the market should produce in ``[start_ms, end_ms)``.

        This is the reference grid for gap detection: missing bars are this set minus
        the lake's actual ``ts_open`` values. ``start_ms`` unaligned is ceiled to the
        next valid open; ``end_ms`` is exclusive. Result is sorted ascending.
        """

    @abstractmethod
    def periods_per_year(self, tf: Timeframe) -> float:
        """Return the annualization factor: bars of ``tf`` per year on this calendar.

        24/7 crypto: 8760.0 (1h), 2190.0 (4h), 365.0 (1d) — leap days ignored
        (<0.3% effect). The single source for Sharpe/vol/covariance annualization;
        hard-coding 8760 anywhere else is a bug.
        """

    @abstractmethod
    def floor_bar(self, ts: Ms, tf: Timeframe) -> Ms:
        """Return the open (``ts_open``) of the ``tf`` bar containing ``ts``."""

    @abstractmethod
    def next_bar_open(self, ts: Ms, tf: Timeframe) -> Ms:
        """Return the open of the first ``tf`` bar strictly after ``ts``."""

    def funding_events_in(self, start_ms: Ms, end_ms: Ms, interval_hours: int) -> list[Ms]:
        """Return scheduled perp funding-settlement instants in ``[start_ms, end_ms)``.

        Settlements are anchored at UTC midnight and repeat every ``interval_hours``
        (per-instrument; from the instruments table): 8h -> 00/08/16 UTC, 4h ->
        00/04/.../20 UTC, 1h -> every hour. Epoch 0 is a UTC midnight, so events are
        exactly the integer multiples of ``interval_hours`` in the half-open range,
        sorted ascending.

        SCHEDULE HELPER ONLY (leakageCritique.md finding 6): the backtest and live
        ledger apply funding by iterating the stored ``funding_events`` table — actual
        settled rates with their own ``available_at`` — never this clock. Use this for
        scheduling, gap-checking the funding history, and expected-event counts.

        Raises:
            ValueError: if ``interval_hours`` is not a positive divisor of 24 (the
                anchored daily pattern would not repeat).
        """
        if interval_hours <= 0 or 24 % interval_hours != 0:
            raise ValueError(
                f"interval_hours must be a positive divisor of 24 "
                f"(Binance uses 8, 4, or 1); got {interval_hours}"
            )
        interval_ms = interval_hours * _MS_PER_HOUR
        first = -(-start_ms // interval_ms) * interval_ms  # ceil to next aligned instant
        return list(range(first, end_ms, interval_ms))


class Always24x7Calendar(TradingCalendar):
    """Calendar for markets that never close (crypto perp/spot).

    Every instant is a session; the bar grid is the full aligned grid, so all bar
    arithmetic delegates to the pure-integer kernel in :mod:`alphaforge.core.time`.
    Stateless — share one instance via :func:`calendar_for`.
    """

    __slots__ = ()

    def is_session(self, ts: Ms) -> bool:
        """Return True for every ``ts`` — a 24/7 market is always in session."""
        return True

    def expected_bar_opens(self, start_ms: Ms, end_ms: Ms, tf: Timeframe) -> list[Ms]:
        """Return all aligned ``tf`` opens in ``[start_ms, end_ms)`` (full grid, no gaps)."""
        return core_time.expected_bar_opens(start_ms, end_ms, tf)

    def periods_per_year(self, tf: Timeframe) -> float:
        """Return ``tf.bars_per_year`` (365-day year, 24 hours a day)."""
        return tf.bars_per_year

    def floor_bar(self, ts: Ms, tf: Timeframe) -> Ms:
        """Return :func:`alphaforge.core.time.floor_bar` — every aligned bar exists."""
        return core_time.floor_bar(ts, tf)

    def next_bar_open(self, ts: Ms, tf: Timeframe) -> Ms:
        """Return :func:`alphaforge.core.time.next_bar_open` — every aligned bar exists."""
        return core_time.next_bar_open(ts, tf)


_ALWAYS_24X7: Final[Always24x7Calendar] = Always24x7Calendar()


def calendar_for(asset_class: AssetClass) -> TradingCalendar:
    """Return the trading calendar for ``asset_class`` (shared stateless instance).

    CRYPTO_PERP and CRYPTO_SPOT map to the singleton :class:`Always24x7Calendar`.

    Raises:
        NotImplementedError: for EQUITY (and any future asset class) — the equities
            session calendar (via ``exchange_calendars``) is explicitly post-v1; see
            buildabilityCritique.md §5 backlog.
    """
    if asset_class in (AssetClass.CRYPTO_PERP, AssetClass.CRYPTO_SPOT):
        return _ALWAYS_24X7
    raise NotImplementedError(
        f"no TradingCalendar registered for asset class {asset_class.value!r}: "
        "equities session calendars (exchange_calendars) are post-v1; "
        "only crypto_perp/crypto_spot are supported"
    )
