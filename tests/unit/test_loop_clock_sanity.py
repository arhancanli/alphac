"""Unit tests for the LiveLoop per-cycle clock-sanity wiring (Phase-8, section 4).

The loop OPTIONALLY consults a :class:`ClockSanityCheck` once per cycle to
compare the LOCAL wall clock against the exchange server time. The contract
(buildabilityCritique.md section 4, last bullet) is ALERT + COUNT, never HALT:

* an IN-SKEW cycle does NOT alert, does NOT increment ``clock_skew_alerts``, and
  leaves ``CycleReport.clock_skew`` False -- trading proceeds exactly as before;
* an OUT-OF-SKEW cycle fires exactly one WARN alert, increments
  ``clock_skew_alerts``, and sets ``CycleReport.clock_skew`` True -- but STILL
  trades (the data path is guarded by the staleness breaker, so a clock skew is a
  TIMING warning, not a data-integrity stop);
* ``clock_sanity=None`` (the default; backtests/tests) skips the check cleanly --
  no alert, ``clock_skew_alerts`` stays 0, the report flag stays False;
* a clock SOURCE that raises never disturbs the cycle (the probe is swallowed
  into a no-skew result, so a flaky exchange-time fetch cannot fail a cycle).

The injected :class:`ClockSanity` is a SELF-CONTAINED reimplementation of the
documented ``ops/clock.py`` contract over a :class:`FakeExchangeTimeSource`
(canned exchange time), so this test composes with the loop's structural
``ClockSanityCheck`` seam WITHOUT importing ``ops/clock.py`` (built disjointly).
Everything is deterministic and OFFLINE: a FakeOrderBookSource feeds the broker,
a fixed strategy/updater/watermark feed the loop, no network, no ./data, no real
clock (every time read is injected).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.order_manager import OrderManager
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import Reconciler
from alphaforge.live.alerts import AlertLevel, LogAlerter
from alphaforge.live.loop import ClockSanityCheck, LiveLoop
from alphaforge.live.store import TradingStore
from alphaforge.risk import (
    DrawdownLadder,
    KillSwitch,
    PreTradeChecker,
    RiskLimits,
    StalenessBreaker,
)

HOUR = 3_600_000
LISTED = 1_577_836_800_000
T0 = LISTED + 1000 * HOUR  # a cycle_ts well after listing
NOW = T0 + 90_000  # the injected wall-clock instant the loop reads each cycle
BTC = "BINANCE:PERP:BTCUSDT"

# A deep two-sided book; mid = 100.5 (the strategy can size + fill against it).
_BIDS = ((100.0, 50.0), (99.0, 100.0))
_ASKS = ((101.0, 50.0), (102.0, 100.0))


def _make_instrument() -> Instrument:
    return Instrument(
        instrument_id=BTC,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def _make_book() -> OrderBook:
    return OrderBook(instrument_id=BTC, bids=_BIDS, asks=_ASKS, ts=T0)


# --------------------------------------------------------------------------- loop fakes


class _FakeUpdater:
    """A data updater that records nothing useful and never touches the network."""

    def update(self, *, as_of: Ms) -> object:
        del as_of
        return None


class _FreshWatermark:
    """Reports the lake is ALWAYS fresh so the freshness gate short-circuits."""

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        del instrument_ids, as_of
        return 1 << 62


class _FixedCostInputs:
    """Constant (adv_quote, sigma_daily) so the pre-trade gate always passes."""

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        del instrument_id, decision_ts
        return (1e12, 0.02)


class _FakeCostFactory:
    """Builds the constant cost inputs per cycle (the loop's cost seam)."""

    def __call__(self, cycle_ts: Ms, instrument_ids: Sequence[str]) -> _FixedCostInputs:
        del cycle_ts, instrument_ids
        return _FixedCostInputs()


class _FakeContext:
    """A minimal StrategyContext stand-in carrying the decision inputs."""

    def __init__(
        self,
        *,
        ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> None:
        self.ts = ts
        self.equity = equity
        self.positions = dict(positions)
        self.instruments = dict(instruments)
        self.tf = Timeframe.H1


class _FakeContextFactory:
    """Builds :class:`_FakeContext` objects (the loop's ctx seam)."""

    def __call__(
        self,
        *,
        cycle_ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> _FakeContext:
        return _FakeContext(
            ts=cycle_ts, equity=equity, positions=positions, instruments=instruments
        )


class _ScriptedStrategy:
    """Returns a fixed long target every decision (drives a real fill on the book)."""

    def __init__(self, targets: Mapping[str, float]) -> None:
        self._targets = dict(targets)

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        return dict(self._targets)


class _FakeInstruments:
    """Returns a fixed tradable universe at every cycle (the loop's PIT seam)."""

    def __init__(self, instruments: Mapping[str, Instrument]) -> None:
        self._instruments = dict(instruments)

    def __call__(self, cycle_ts: Ms) -> Mapping[str, Instrument]:
        del cycle_ts
        return dict(self._instruments)


class _RecordingAlerter(LogAlerter):
    """A LogAlerter that also records every (level, message) for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[AlertLevel, str]] = []

    def alert(self, level: AlertLevel, message: str) -> bool:
        self.records.append((level, message))
        return super().alert(level, message)


# ------------------------------------------------------- clock-sanity contract fakes
#
# These reimplement the documented ops/clock.py contract EXACTLY (so the loop's
# structural ClockSanityCheck seam is exercised against the same shape builder A
# ships) without importing ops/clock.py, which is built in a disjoint file.


class _FakeExchangeTimeSource:
    """Canned exchange server time (the ExchangeTimeSource Protocol shape).

    ``server_time_ms`` returns a fixed value; tests set it relative to the loop's
    injected ``now`` to drive an in-skew or out-of-skew check deterministically.
    A negative ``raises`` flag instead raises, to prove a flaky source can never
    disturb the cycle.
    """

    def __init__(self, server_ms: Ms, *, raises: bool = False) -> None:
        self._server_ms = server_ms
        self._raises = raises

    def server_time_ms(self) -> Ms:
        if self._raises:
            raise RuntimeError("exchange time fetch failed")
        return self._server_ms


@dataclass(frozen=True, slots=True)
class _ClockCheck:
    """Mirror of ops/clock.py ClockCheck: (local_ms, exchange_ms, skew_ms, ok)."""

    local_ms: Ms
    exchange_ms: Ms
    skew_ms: int
    ok: bool


class _ClockSanity:
    """Mirror of the documented ops/clock.py ClockSanity over a time source.

    ``check(now=...)`` returns a :class:`_ClockCheck` whose ``skew_ms`` is the
    SIGNED local-minus-exchange skew and ``ok`` is ``|skew| <= max_skew_ms`` --
    the exact contract the loop's :class:`ClockSanityCheck` seam consumes.
    """

    def __init__(self, source: _FakeExchangeTimeSource, *, max_skew_ms: int = 2000) -> None:
        self._source = source
        self._max_skew_ms = max_skew_ms

    def check(self, *, now: Ms) -> _ClockCheck:
        exchange_ms = self._source.server_time_ms()
        skew_ms = int(now) - int(exchange_ms)
        return _ClockCheck(
            local_ms=now,
            exchange_ms=exchange_ms,
            skew_ms=skew_ms,
            ok=abs(skew_ms) <= self._max_skew_ms,
        )


# --------------------------------------------------------------------------- harness


def _build_loop(
    tmp_path: Path,
    *,
    clock_sanity: ClockSanityCheck | None,
    alerter: _RecordingAlerter,
) -> tuple[LiveLoop, TradingStore, PaperBroker]:
    """Wire a LiveLoop over real broker/store/risk + the clock-sanity seam.

    Reuses the established loop test surfaces (PaperBroker over a canned book,
    real TradingStore/risk stack) so the clock-sanity path is exercised inside a
    fully real, fill-producing cycle -- the in-skew case must NOT change any
    trading behavior, which only a real cycle can prove.
    """
    inst = _make_instrument()
    src = FakeOrderBookSource()
    src.set_book(_make_book())
    cost_model = TransactionCostModel()
    instrument_map = {inst.instrument_id: inst}
    broker = PaperBroker(instrument_map, cost_model, book_source=src, initial_cash=100_000.0)
    store = TradingStore(tmp_path / "trading.sqlite")
    settings = Settings()
    ladder = DrawdownLadder(
        dd_half_frac=abs(settings.risk.dd_halve_gross),
        dd_flat_frac=abs(settings.risk.dd_flat_halt),
    )
    loop = LiveLoop(
        settings,
        store=store,
        broker=broker,
        order_manager=OrderManager(broker, store),
        reconciler=Reconciler(broker, store),
        strategy=_ScriptedStrategy({BTC: 0.10}),
        pretrade=PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model),
        ladder=ladder,
        staleness=StalenessBreaker(max_bars=settings.risk.staleness_max_bars),
        kill=KillSwitch(tmp_path / "KILL"),
        alerter=alerter,
        clock_sanity=clock_sanity,
        updater=_FakeUpdater(),
        watermark=_FreshWatermark(),
        cost_inputs_factory=_FakeCostFactory(),
        ctx_factory=_FakeContextFactory(),  # type: ignore[arg-type]
        instruments_factory=_FakeInstruments(instrument_map),
        clock=lambda: NOW,
    )
    return loop, store, broker


@pytest.fixture
def alerter() -> _RecordingAlerter:
    return _RecordingAlerter()


def _warn_records(alerter: _RecordingAlerter) -> list[str]:
    return [msg for level, msg in alerter.records if level is AlertLevel.WARN]


# --------------------------------------------------------------------------- in-skew


class TestInSkew:
    """An in-skew cycle is a quiet success: no alert, no count, flag clear."""

    def test_in_skew_cycle_does_not_alert_or_count(
        self, tmp_path: Path, alerter: _RecordingAlerter
    ) -> None:
        # Exchange time 500 ms behind local -> |skew| = 500 <= 2000 ms -> ok.
        clock = _ClockSanity(_FakeExchangeTimeSource(NOW - 500), max_skew_ms=2000)
        loop, store, broker = _build_loop(tmp_path, clock_sanity=clock, alerter=alerter)
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # The cycle ran and traded EXACTLY as without a clock check.
        assert report.status == "ok"
        assert report.traded is True
        assert len(broker.fills) >= 1
        # No skew: flag clear, counter zero, no WARN about the clock.
        assert report.clock_skew is False
        assert loop.clock_skew_alerts == 0
        assert all("CLOCK SKEW" not in msg for msg in _warn_records(alerter))


# --------------------------------------------------------------------------- out-of-skew


class TestOutOfSkew:
    """An out-of-skew cycle ALERTS + COUNTS + flags, but STILL trades (no halt)."""

    def test_out_of_skew_cycle_alerts_counts_and_flags(
        self, tmp_path: Path, alerter: _RecordingAlerter
    ) -> None:
        # Exchange time 5000 ms behind local -> skew = +5000 ms > 2000 -> breach.
        clock = _ClockSanity(_FakeExchangeTimeSource(NOW - 5000), max_skew_ms=2000)
        loop, store, broker = _build_loop(tmp_path, clock_sanity=clock, alerter=alerter)
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # NOT halted: the cycle still decided + traded (the data path is guarded).
        assert report.status == "ok"
        assert report.traded is True
        assert len(broker.fills) >= 1
        # The breach is surfaced: report flag set, counter incremented once.
        assert report.clock_skew is True
        assert loop.clock_skew_alerts == 1
        # Exactly one WARN names the signed skew so the operator sees magnitude.
        skew_warns = [msg for msg in _warn_records(alerter) if "CLOCK SKEW" in msg]
        assert len(skew_warns) == 1
        assert "+5000 ms" in skew_warns[0]

    def test_negative_skew_is_reported_signed(
        self, tmp_path: Path, alerter: _RecordingAlerter
    ) -> None:
        # Local BEHIND the exchange -> negative skew, still a breach, signed in text.
        clock = _ClockSanity(_FakeExchangeTimeSource(NOW + 9000), max_skew_ms=2000)
        loop, store, _broker = _build_loop(tmp_path, clock_sanity=clock, alerter=alerter)
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        assert report.clock_skew is True
        assert loop.clock_skew_alerts == 1
        skew_warns = [msg for msg in _warn_records(alerter) if "CLOCK SKEW" in msg]
        assert len(skew_warns) == 1
        assert "-9000 ms" in skew_warns[0]

    def test_breach_counter_accumulates_across_cycles(
        self, tmp_path: Path, alerter: _RecordingAlerter
    ) -> None:
        # Two skewed cycles -> the counter reflects EVERY breach (soak accounting).
        clock = _ClockSanity(_FakeExchangeTimeSource(NOW - 5000), max_skew_ms=2000)
        loop, store, _broker = _build_loop(tmp_path, clock_sanity=clock, alerter=alerter)
        try:
            assert loop.run_cycle(T0).clock_skew is True
            assert loop.run_cycle(T0 + HOUR).clock_skew is True
        finally:
            store.close()
        assert loop.clock_skew_alerts == 2


# --------------------------------------------------------------------------- disabled


class TestNoClockSanity:
    """clock_sanity=None skips the check cleanly -- the default backtest/test path."""

    def test_none_skips_cleanly(self, tmp_path: Path, alerter: _RecordingAlerter) -> None:
        loop, store, broker = _build_loop(tmp_path, clock_sanity=None, alerter=alerter)
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # The cycle runs normally with NO clock probe at all.
        assert report.status == "ok"
        assert report.traded is True
        assert len(broker.fills) >= 1
        assert report.clock_skew is False
        assert loop.clock_skew_alerts == 0
        assert all("CLOCK SKEW" not in msg for msg in _warn_records(alerter))


# --------------------------------------------------------------------------- robustness


class TestProbeRobustness:
    """A clock SOURCE that raises must never disturb the cycle (probe is total)."""

    def test_raising_source_does_not_fail_the_cycle(
        self, tmp_path: Path, alerter: _RecordingAlerter
    ) -> None:
        clock = _ClockSanity(_FakeExchangeTimeSource(0, raises=True), max_skew_ms=2000)
        loop, store, broker = _build_loop(tmp_path, clock_sanity=clock, alerter=alerter)
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # The probe raised, was swallowed to a no-skew result, and the cycle ran.
        assert report.status == "ok"
        assert report.traded is True
        assert len(broker.fills) >= 1
        assert report.clock_skew is False
        assert loop.clock_skew_alerts == 0


# --------------------------------------------------------------------------- seam shape


def test_clock_sanity_fake_satisfies_the_loop_seam() -> None:
    """The contract reimplementation satisfies the loop's structural seam.

    A regression guard: if the loop's ``ClockSanityCheck`` shape drifts from the
    documented ops/clock.py contract this fails, catching a decoupling break.
    """
    sanity: ClockSanityCheck = _ClockSanity(_FakeExchangeTimeSource(NOW))
    assert isinstance(sanity, ClockSanityCheck)
    result = sanity.check(now=NOW)
    assert result.ok is True
    assert result.skew_ms == 0
