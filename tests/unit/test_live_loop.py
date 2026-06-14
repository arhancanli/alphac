"""Unit tests for LiveLoop -- the single-timer hourly PAPER cycle (execDesign.md 9.2).

Load-bearing assertions:

* run_cycle happy path: target weights -> orders -> PaperBroker (walks a canned
  book) -> persisted fills + equity + an 'ok' cycle row.
* KILL sentinel: cycle finishes 'skipped' with NO orders; the heartbeat (tick
  loop) survives.
* staleness: an updater that never produces a fresh bar -> 'skipped', no orders.
* a cycle exception -> 'failed' and the loop SURVIVES (the next bar still runs).
* C1 firewall: a TransientBrokerError / sqlite3.OperationalError (both OUTSIDE
  the old allowlist) is caught -> 'failed', the loop survives, the next bar is
  'ok'; SystemExit PROPAGATES (crash-recovery contract); run_forever continues
  past a raising cycle.
* C8: a multi-bar wall-clock jump counts the slept-through bar opens into
  missed_cycles.
* C9: a partially-stale-but-tradeable cycle WARN-alerts + increments the degraded
  counter; a dropped (un-markable) book instrument is counted on the report.
* C4-persist: the loop records the live DrawdownLadder snapshot each cycle; after
  a rearm the persisted state reflects NORMAL.
* deterministic client_order_ids (weights_to_orders bakes (cycle_ts, instrument)).
* ladder FLAT_HALTED -> all-zero targets flow through (no opening orders).
* idempotency: re-running an already-terminal cycle_ts is SKIPPED (no 2nd fill).
* paper_state blob round-trips through the loop codec and restores the book.

Everything is deterministic and OFFLINE: a FakeOrderBookSource feeds the broker,
a fake updater/watermark/cost-inputs/strategy/context feed the loop; no network,
no ./data, no real clock (every time read is injected).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest

from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import (
    AccountState,
    AssetClass,
    MarketType,
)
from alphaforge.costs import TransactionCostModel
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.order_manager import OrderManager, TransientBrokerError
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import Reconciler
from alphaforge.live.alerts import Alerter, AlertLevel, LogAlerter
from alphaforge.live.loop import (
    CycleReport,
    LiveLoop,
    WatermarkSource,
    decode_paper_state,
    encode_paper_state,
)
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
BTC = "BINANCE:PERP:BTCUSDT"

# A deep two-sided book; mid = 100.5.
_BIDS = ((100.0, 50.0), (99.0, 100.0))
_ASKS = ((101.0, 50.0), (102.0, 100.0))


def make_instrument(instrument_id: str = BTC) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=symbol.removesuffix("USDT"),
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


def make_book(instrument_id: str = BTC, *, ts: int = T0) -> OrderBook:
    return OrderBook(instrument_id=instrument_id, bids=_BIDS, asks=_ASKS, ts=ts)


# --------------------------------------------------------------------------- fakes


class FakeUpdater:
    """A data updater that records its invocations; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[Ms] = []

    def update(self, *, as_of: Ms) -> object:
        self.calls.append(as_of)
        return None


class FreshWatermark:
    """Reports the lake is ALWAYS fresh (covers any cycle_ts) so the gate passes.

    Returns a value far in the future so ``latest >= cycle_ts`` holds regardless
    of the injected clock -- the freshness wait short-circuits immediately and the
    cycle proceeds to the decision (the staleness path is exercised separately by
    :class:`StaleWatermark`).
    """

    def __init__(self, *, latest: Ms | None = None) -> None:
        self._latest = latest

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        del instrument_ids, as_of
        return self._latest if self._latest is not None else 1 << 62


class StaleWatermark:
    """Reports the lake never has the just-closed bar (a dead feed)."""

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        del instrument_ids, as_of
        return None


class DegradedWatermark:
    """Reports a lake that is ONE bar behind ``cycle_ts`` -- stale but tradeable.

    The freshest bar open it returns is fixed at ``latest`` (default ``T0 -
    HOUR``, i.e. one bar before the ``T0`` cycle). The just-closed bar therefore
    never lands within grace, but the StalenessBreaker (``max_bars=2``) still
    allows trading -- the C9 'degraded' path: trade on a partially-stale lake and
    WARN-alert + count it.
    """

    def __init__(self, *, latest: Ms = T0 - HOUR) -> None:
        self._latest = latest

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        del instrument_ids, as_of
        return self._latest


class FixedCostInputs:
    """Constant (adv_quote, sigma_daily) for every instrument and timestamp."""

    def __init__(self, *, adv: float = 1e12, sigma: float = 0.02) -> None:
        self._adv = adv
        self._sigma = sigma

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        del instrument_id, decision_ts
        return (self._adv, self._sigma)


class FakeCostFactory:
    """Builds a :class:`FixedCostInputs` per cycle (the loop's cost seam)."""

    def __init__(self, inputs: FixedCostInputs) -> None:
        self._inputs = inputs

    def __call__(self, cycle_ts: Ms, instrument_ids: Sequence[str]) -> FixedCostInputs:
        del cycle_ts, instrument_ids
        return self._inputs


class FakeContext:
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


class FakeContextFactory:
    """Builds :class:`FakeContext` objects (the loop's ctx seam)."""

    def __call__(
        self,
        *,
        cycle_ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> FakeContext:
        return FakeContext(ts=cycle_ts, equity=equity, positions=positions, instruments=instruments)


class ScriptedStrategy:
    """Returns scripted target weights and records the equity it observed.

    ``targets`` is returned for every decision; ``ladder`` (the SAME instance the
    loop holds) is updated with the observed equity so the loop's ladder-state
    contract is exercised exactly as the real BlendStrategy does it.
    """

    def __init__(
        self, targets: Mapping[str, float], *, ladder: DrawdownLadder | None = None
    ) -> None:
        self._targets = dict(targets)
        self._ladder = ladder
        self.seen_equity: list[float] = []

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        equity = float(ctx.equity)  # type: ignore[attr-defined]
        self.seen_equity.append(equity)
        if self._ladder is not None:
            self._ladder.update(equity)
            if self._ladder.gross_multiplier() == 0.0:
                return dict.fromkeys(self._targets, 0.0)
            return {k: v * self._ladder.gross_multiplier() for k, v in self._targets.items()}
        return dict(self._targets)


class BoomStrategy:
    """Raises on decision -- exercises the loop's cycle-failure isolation."""

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        raise ValueError("synthetic decision failure")


class TransientStrategy:
    """Raises a :class:`TransientBrokerError` -- a retry-exhausted transport blip.

    This exception is NOT an :class:`AlphaForgeError` and was OUTSIDE the loop's
    old curated allowlist, so it used to ESCAPE run_cycle and kill the 24/7 loop
    (C1). The broadened catch-all must now backstop it into a 'failed' cycle.
    """

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        raise TransientBrokerError("retry-exhausted transport blip")


class OperationalErrorStrategy:
    """Raises a ``sqlite3.OperationalError`` -- a db lock, also outside the old list."""

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        raise sqlite3.OperationalError("database is locked")


class SystemExitStrategy:
    """Raises ``SystemExit`` -- a simulated hard crash; it MUST propagate.

    The crash-recovery contract requires SystemExit/KeyboardInterrupt to escape
    run_cycle (so recover_on_boot runs on restart). The catch-all must catch
    ``Exception`` only, never ``BaseException``.
    """

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        raise SystemExit("simulated SIGKILL")


class CountingStrategy:
    """Returns the scripted targets and counts how many cycles it decided.

    Used to drive run_forever across several ticks and prove the loop continued
    past a raising cycle (the failing tick is a DIFFERENT strategy instance).
    """

    def __init__(self, targets: Mapping[str, float]) -> None:
        self._targets = dict(targets)
        self.n_calls = 0

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        self.n_calls += 1
        return dict(self._targets)


class FakeInstruments:
    """Returns a fixed tradable universe at every cycle (the loop's PIT seam)."""

    def __init__(self, instruments: Mapping[str, Instrument]) -> None:
        self._instruments = dict(instruments)

    def __call__(self, cycle_ts: Ms) -> Mapping[str, Instrument]:
        del cycle_ts
        return dict(self._instruments)


class RecordingAlerter(LogAlerter):
    """A LogAlerter that also records every alert (level, message) for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[AlertLevel, str]] = []

    def alert(self, level: AlertLevel, message: str) -> bool:
        self.records.append((level, message))
        return super().alert(level, message)


# --------------------------------------------------------------------------- harness


class Clock:
    """A monotone-ish injectable clock the loop reads via ``now``."""

    def __init__(self, start: Ms) -> None:
        self.t = start

    def __call__(self) -> Ms:
        return self.t

    def advance(self, ms: Ms) -> None:
        self.t += ms


ETH = "BINANCE:PERP:ETHUSDT"


def build_loop(
    tmp_path: Path,
    *,
    targets: Mapping[str, float] | None = None,
    watermark: WatermarkSource | None = None,
    strategy: object | None = None,
    use_ladder: bool = False,
    alerter: Alerter | None = None,
    clock: Clock | None = None,
    uncovered_instrument: str | None = None,
) -> tuple[LiveLoop, TradingStore, PaperBroker, ScriptedStrategy | object]:
    """Wire a LiveLoop over real broker/store/risk + injected decision/data seams.

    ``uncovered_instrument`` (C9) adds a second instrument to the PIT universe and
    the broker's instrument map but registers NO order book for it, so the loop
    cannot mark it and DROPS it from sizing (the count under test). The scripted
    strategy still targets only the covered instrument, so the drop is the only
    effect.
    """
    inst = make_instrument()
    src = FakeOrderBookSource()
    src.set_book(make_book())
    cost_model = TransactionCostModel()
    instrument_map = {inst.instrument_id: inst}
    if uncovered_instrument is not None:
        # In the universe + broker map, but with NO registered book -> dropped.
        instrument_map[uncovered_instrument] = make_instrument(uncovered_instrument)
    broker = PaperBroker(instrument_map, cost_model, book_source=src, initial_cash=100_000.0)
    store = TradingStore(tmp_path / "trading.sqlite")
    settings = Settings()
    order_manager = OrderManager(broker, store)
    reconciler = Reconciler(broker, store)
    ladder = DrawdownLadder(
        dd_half_frac=abs(settings.risk.dd_halve_gross),
        dd_flat_frac=abs(settings.risk.dd_flat_halt),
    )
    strat: object
    if strategy is not None:
        strat = strategy
    else:
        strat = ScriptedStrategy(
            targets if targets is not None else {BTC: 0.10},
            ladder=ladder if use_ladder else None,
        )
    pretrade = PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model)
    staleness = StalenessBreaker(max_bars=settings.risk.staleness_max_bars)
    kill = KillSwitch(tmp_path / "KILL")
    loop = LiveLoop(
        settings,
        store=store,
        broker=broker,
        order_manager=order_manager,
        reconciler=reconciler,
        strategy=strat,  # type: ignore[arg-type]
        pretrade=pretrade,
        ladder=ladder,
        staleness=staleness,
        kill=kill,
        alerter=alerter if alerter is not None else LogAlerter(),
        updater=FakeUpdater(),
        watermark=watermark if watermark is not None else FreshWatermark(),
        cost_inputs_factory=FakeCostFactory(FixedCostInputs()),
        ctx_factory=FakeContextFactory(),  # type: ignore[arg-type]
        instruments_factory=FakeInstruments(dict(instrument_map)),
        clock=clock if clock is not None else (lambda: T0 + 90_000),
    )
    return loop, store, broker, strat


@pytest.fixture
def loop_env(tmp_path: Path) -> Iterator[tuple[LiveLoop, TradingStore, PaperBroker, object]]:
    loop, store, broker, strat = build_loop(tmp_path)
    try:
        yield loop, store, broker, strat
    finally:
        store.close()


# --------------------------------------------------------------------------- happy path


class TestHappyPath:
    def test_run_cycle_persists_fill_equity_and_ok(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, store, broker, _ = loop_env
        report = loop.run_cycle(T0)

        assert report.status == "ok"
        assert report.traded is True
        assert report.n_filled >= 1
        cycle = store.get_cycle(T0)
        assert cycle is not None and cycle.status == "ok"
        # The PaperBroker walked the book and booked a real fill.
        assert len(broker.fills) >= 1
        # Equity + positions snapshots persisted under cycle_ts.
        curve = store.equity_curve()
        assert curve and curve[-1][0] == T0
        assert store.positions_at(T0)  # at least one position snapshot

    def test_paper_state_persisted_and_restorable(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, store, broker, _ = loop_env
        loop.run_cycle(T0)
        latest = store.latest_paper_state()
        assert latest is not None
        _cycle_ts, blob = latest
        restored = decode_paper_state(blob)
        # The restored state reproduces the live broker's cash + positions.
        assert restored.cash == pytest.approx(broker.state.cash)
        assert set(restored.positions) == set(broker.state.positions)

    def test_deterministic_client_order_ids(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, store, _broker, _ = loop_env
        loop.run_cycle(T0)
        orders = store.orders_for_cycle(T0)
        assert orders
        for rec in orders:
            # weights_to_orders bakes (cycle_ts, instrument) into the id.
            assert rec.client_order_id.startswith(f"rb-{T0}-")

    def test_driving_ingest_happens_before_read(self, tmp_path: Path) -> None:
        loop, store, _broker, _ = build_loop(tmp_path)
        updater = loop._updater  # the FakeUpdater
        try:
            loop.run_cycle(T0)
        finally:
            store.close()
        assert isinstance(updater, FakeUpdater)
        assert updater.calls, "the loop must DRIVE the updater each cycle (one clock)"


# --------------------------------------------------------------------------- kill switch


class TestKillSwitch:
    def test_kill_sentinel_skips_with_no_orders(self, tmp_path: Path) -> None:
        loop, store, broker, _ = build_loop(tmp_path)
        (tmp_path / "KILL").write_text("stop\n", encoding="utf-8")
        try:
            report = loop.run_cycle(T0)
            assert report.status == "skipped"
            assert report.n_orders == 0
            assert broker.fills == []
            cycle = store.get_cycle(T0)
            assert cycle is not None and cycle.status == "skipped"
        finally:
            store.close()

    def test_run_forever_heartbeat_survives_kill(self, tmp_path: Path) -> None:
        # The KILL sentinel stops TRADING but the tick loop keeps running.
        clock = Clock(T0 + 90_000)
        alerter = RecordingAlerter()
        loop, store, broker, _ = build_loop(tmp_path, alerter=alerter, clock=clock)
        (tmp_path / "KILL").write_text("stop\n", encoding="utf-8")
        ticks = {"n": 0}

        def sleeper(_s: float) -> None:
            ticks["n"] += 1
            clock.advance(HOUR)  # advance wall clock so deadlines recompute
            if ticks["n"] >= 5:
                raise KeyboardInterrupt  # stop the otherwise-infinite heartbeat

        loop._sleeper = sleeper  # inject the heartbeat sleeper
        try:
            with pytest.raises(KeyboardInterrupt):
                loop.run_forever()
        finally:
            store.close()
        # No trading happened while halted, but the halt was announced (heartbeat).
        assert broker.fills == []
        assert any(level is AlertLevel.CRITICAL for level, _ in alerter.records)


# --------------------------------------------------------------------------- staleness


class TestStaleness:
    def test_stale_feed_skips_without_orders(self, tmp_path: Path) -> None:
        loop, store, broker, _ = build_loop(tmp_path, watermark=StaleWatermark())
        # Make grace elapse on the second clock read so the loop gives up promptly.
        calls = {"n": 0}

        def clock() -> Ms:
            calls["n"] += 1
            # First read opens the cycle; later reads are far past the grace.
            return T0 + 90_000 + (calls["n"] * 10 * HOUR)

        loop._clock = clock
        loop._sleeper = lambda _s: None
        try:
            report = loop.run_cycle(T0)
            assert report.status == "skipped"
            assert broker.fills == []
            cycle = store.get_cycle(T0)
            assert cycle is not None and cycle.status == "skipped"
        finally:
            store.close()


# --------------------------------------------------------------------------- failure isolation


class TestFailureIsolation:
    def test_cycle_exception_fails_and_loop_survives(self, tmp_path: Path) -> None:
        alerter = RecordingAlerter()
        loop, store, broker, _ = build_loop(tmp_path, strategy=BoomStrategy(), alerter=alerter)
        try:
            report = loop.run_cycle(T0)
            assert report.status == "failed"
            assert "synthetic decision failure" in report.detail
            assert broker.fills == []
            cycle = store.get_cycle(T0)
            assert cycle is not None and cycle.status == "failed"
            # A CRITICAL alert fired for the failed cycle.
            assert any(level is AlertLevel.CRITICAL for level, _ in alerter.records)
            # The loop SURVIVES: the next bar runs to completion.
            next_loop, _store2, _broker2, _ = build_loop(tmp_path / "nested")
            try:
                ok = next_loop.run_cycle(T0 + HOUR)
                assert ok.status == "ok"
            finally:
                _store2.close()
        finally:
            store.close()


# --------------------------------------------------------------------------- idempotency


class TestIdempotency:
    def test_rerun_terminal_cycle_is_skipped(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, _store, broker, _ = loop_env
        first = loop.run_cycle(T0)
        assert first.status == "ok"
        n_fills_after_first = len(broker.fills)

        # Re-run the SAME cycle_ts: the store's start_cycle gate refuses it.
        second = loop.run_cycle(T0)
        assert second.status == "skipped"
        assert "terminal" in second.detail
        # No second fill booked (the broker is also idempotent on the id).
        assert len(broker.fills) == n_fills_after_first
        assert loop.missed_cycles >= 1


# --------------------------------------------------------------------------- ladder halt


class TestLadderHalt:
    def test_flat_halted_produces_no_opening_orders(self, tmp_path: Path) -> None:
        # Drive the ladder into FLAT_HALTED by feeding a crash equity through the
        # strategy, then assert the resulting all-zero targets open no position.
        inst = make_instrument()
        src = FakeOrderBookSource()
        src.set_book(make_book())
        cost_model = TransactionCostModel()
        broker = PaperBroker(
            {inst.instrument_id: inst}, cost_model, book_source=src, initial_cash=100_000.0
        )
        store = TradingStore(tmp_path / "trading.sqlite")
        settings = Settings()
        ladder = DrawdownLadder(
            dd_half_frac=abs(settings.risk.dd_halve_gross),
            dd_flat_frac=abs(settings.risk.dd_flat_halt),
        )
        # Pre-trip the ladder: a 20% drawdown from a higher HWM -> FLAT_HALTED.
        ladder.update(200_000.0)
        ladder.update(100_000.0)
        assert ladder.gross_multiplier() == 0.0
        strat = ScriptedStrategy({BTC: 0.10}, ladder=ladder)
        loop = LiveLoop(
            settings,
            store=store,
            broker=broker,
            order_manager=OrderManager(broker, store),
            reconciler=Reconciler(broker, store),
            strategy=strat,
            pretrade=PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model),
            ladder=ladder,
            staleness=StalenessBreaker(max_bars=settings.risk.staleness_max_bars),
            kill=KillSwitch(tmp_path / "KILL"),
            alerter=LogAlerter(),
            updater=FakeUpdater(),
            watermark=FreshWatermark(),
            cost_inputs_factory=FakeCostFactory(FixedCostInputs()),
            ctx_factory=FakeContextFactory(),  # type: ignore[arg-type]
            instruments_factory=FakeInstruments({inst.instrument_id: inst}),
            clock=lambda: T0 + 90_000,
        )
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # Flat targets on a flat book -> no opening order, no fill, but still 'ok'.
        assert report.status == "ok"
        assert report.traded is False
        assert broker.positions() == []


# --------------------------------------------------------------------------- codec


class TestPaperStateCodec:
    def test_round_trip_after_a_fill(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, _store, broker, _ = loop_env
        loop.run_cycle(T0)
        blob = encode_paper_state(broker.snapshot_state())
        restored = decode_paper_state(blob)
        assert restored.cash == pytest.approx(broker.state.cash)
        assert restored.acks.keys() == broker.state.acks.keys()
        assert len(restored.fills) == len(broker.state.fills)
        assert len(restored.audits) == len(broker.state.audits)

    def test_decode_rejects_unknown_version(self) -> None:
        with pytest.raises(ValueError, match="version"):
            decode_paper_state('{"version": 999}')


# --------------------------------------------------------------------------- scheduling


class TestScheduling:
    def test_next_deadline_is_next_bar_close_plus_grace(
        self, loop_env: tuple[LiveLoop, TradingStore, PaperBroker, object]
    ) -> None:
        loop, _store, _broker, _ = loop_env
        # now mid-bar -> deadline is next bar open + grace (90s default).
        now = T0 + HOUR // 2
        deadline = loop.next_deadline(now)
        assert deadline == T0 + HOUR + 90_000

    def test_run_forever_runs_bounded_cycles(self, tmp_path: Path) -> None:
        # The loop always waits for the next bar close + grace; the injected
        # sleeper advances the wall clock each tick so a deadline is reached
        # (the real loop relies on real wall time elapsing across ticks).
        clock = Clock(T0 + HOUR // 2)
        loop, store, broker, _ = build_loop(tmp_path, clock=clock)
        loop._sleeper = lambda _s: clock.advance(HOUR)
        try:
            loop.run_forever(max_cycles=1)
        finally:
            store.close()
        # Exactly one cycle ran; it traded against the fresh book.
        assert len(broker.fills) >= 1


# --------------------------------------------------------------------------- boot recovery


class TestBootRecovery:
    """recover_on_boot must not pollute the canonical equity curve on a fresh boot.

    Regression for the soak bug: the fresh-boot opening-equity seed was keyed at
    ``floor_bar(now)``; when the first traded cycle ran at an EARLIER cycle_ts
    (replaying historical bars under a future-pinned clock) the seed survived as a
    phantom trailing equity point, breaking the per-cycle N/M accounting. A truly
    fresh boot now short-circuits BEFORE the seed, so the equity curve contains
    exactly one row per traded cycle.
    """

    def test_fresh_boot_writes_no_phantom_equity_row(self, tmp_path: Path) -> None:
        # Clock pinned WELL AHEAD of the cycles we then run (the soak scenario).
        boot_now = T0 + 5 * HOUR
        loop, store, _broker, _ = build_loop(tmp_path, clock=Clock(boot_now))
        try:
            loop.recover_on_boot()
            # Fresh boot wrote nothing: no equity row at floor_bar(now) (or anywhere).
            assert store.equity_curve() == []

            ran = [T0, T0 + HOUR]
            for cts in ran:
                assert loop.run_cycle(cts).status == "ok"

            # Exactly one equity row per run cycle, in order -- no phantom seed row
            # at floor_bar(boot_now) trailing the real cycles.
            curve_ts = [row[0] for row in store.equity_curve()]
            assert curve_ts == ran
            expected, run_, skipped = store.expected_vs_run(ran[0], ran[-1], HOUR)
            assert (expected, run_, skipped) == (2, 2, 0)
            assert loop.missed_cycles == 0
        finally:
            store.close()

    def test_non_fresh_boot_reconciles_without_phantom_row(self, tmp_path: Path) -> None:
        # After a real cycle the store has equity history and the broker book holds
        # the position, so a re-boot is NOT fresh: the reconcile path runs. With the
        # in-memory broker book intact (the production restart restores it from the
        # paper_state blob; here it simply never died) reconcile is a clean no-op
        # and adds no spurious equity row.
        loop, store, broker, _ = build_loop(tmp_path, clock=Clock(T0 + 90_000))
        try:
            assert loop.run_cycle(T0).status == "ok"
            assert broker.positions()  # the book is non-flat after the trade
            n_rows = len(store.equity_curve())
            loop.recover_on_boot()  # non-fresh: reconciles against the intact book
            assert len(store.equity_curve()) == n_rows  # no phantom row added
        finally:
            store.close()


# --------------------------------------------------------------------------- report shape


def test_cycle_report_is_frozen() -> None:
    report = CycleReport(
        cycle_ts=T0,
        status="ok",
        traded=True,
        n_orders=1,
        n_filled=1,
        n_rejected=0,
        equity=100_000.0,
        detail="x",
    )
    with pytest.raises(AttributeError):
        report.status = "failed"  # type: ignore[misc]


def test_account_state_shape_used_by_loop() -> None:
    # Sanity: the loop reads equity_quote/cash_quote/positions off AccountState.
    state = AccountState(equity_quote=1.0, cash_quote=1.0, positions=(), ts=T0)
    assert state.equity_quote == 1.0 and state.cash_quote == 1.0


# ----------------------------------------------------- C1: exception firewall


class RaiseOnceStrategy:
    """Raises on its FIRST decision, then returns scripted targets thereafter.

    Drives the run_forever-level firewall: the loop must SURVIVE the failing
    cycle and run the next bar to completion.
    """

    def __init__(self, targets: Mapping[str, float]) -> None:
        self._targets = dict(targets)
        self.n_calls = 0

    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        self.n_calls += 1
        if self.n_calls == 1:
            raise TransientBrokerError("first-cycle transport blip")
        return dict(self._targets)


class TestExceptionFirewall:
    """C1: the catch-all backstops EVERY normal exception; BaseException propagates."""

    def test_transient_broker_error_fails_cycle_and_loop_survives(self, tmp_path: Path) -> None:
        alerter = RecordingAlerter()
        loop, store, broker, _ = build_loop(tmp_path, strategy=TransientStrategy(), alerter=alerter)
        try:
            # A TransientBrokerError (NOT an AlphaForgeError) used to ESCAPE and kill
            # the loop; it must now be caught -> 'failed', never raised.
            report = loop.run_cycle(T0)
            assert report.status == "failed"
            assert "TransientBrokerError" in report.detail
            assert broker.fills == []
            assert store.get_cycle(T0) is not None
            assert store.get_cycle(T0).status == "failed"  # type: ignore[union-attr]
            assert any(level is AlertLevel.CRITICAL for level, _ in alerter.records)
            # The loop SURVIVES: swap in a working strategy and the NEXT bar runs 'ok'.
            loop._strategy = ScriptedStrategy({BTC: 0.10})  # type: ignore[assignment]
            assert loop.run_cycle(T0 + HOUR).status == "ok"
        finally:
            store.close()

    def test_sqlite_operational_error_is_caught(self, tmp_path: Path) -> None:
        # A db-lock OperationalError was also outside the old allowlist.
        loop, store, _broker, _ = build_loop(tmp_path, strategy=OperationalErrorStrategy())
        try:
            report = loop.run_cycle(T0)
            assert report.status == "failed"
            assert "OperationalError" in report.detail
        finally:
            store.close()

    def test_system_exit_propagates_preserving_recovery_contract(self, tmp_path: Path) -> None:
        # SystemExit (a simulated hard crash) MUST escape run_cycle so that on the
        # next process start recover_on_boot runs. The catch-all is Exception, not
        # BaseException, so this propagates.
        loop, store, _broker, _ = build_loop(tmp_path, strategy=SystemExitStrategy())
        try:
            with pytest.raises(SystemExit):
                loop.run_cycle(T0)
            # The interrupted cycle is left 'running' (recovery resolves it later).
            cycle = store.get_cycle(T0)
            assert cycle is not None and cycle.status == "running"
        finally:
            store.close()

    def test_run_forever_continues_past_a_raising_cycle(self, tmp_path: Path) -> None:
        # Drive a few ticks; the first decided cycle RAISES (TransientBrokerError),
        # the loop logs+alerts and CONTINUES, and later cycles complete 'ok'.
        clock = Clock(T0 + HOUR // 2)
        alerter = RecordingAlerter()
        strat = RaiseOnceStrategy({BTC: 0.10})
        loop, store, _broker, _ = build_loop(tmp_path, strategy=strat, alerter=alerter, clock=clock)
        loop._sleeper = lambda _s: clock.advance(HOUR)
        try:
            loop.run_forever(max_cycles=3)
            # All three scheduled cycles were attempted (the loop never exited early).
            assert strat.n_calls == 3
            # The first failed, the rest are terminal 'ok' -- the loop survived.
            statuses = [c.status for c in store.cycles_since(0)]
            assert statuses.count("failed") == 1
            assert statuses.count("ok") == 2
            assert any(level is AlertLevel.CRITICAL for level, _ in alerter.records)
        finally:
            store.close()


# ----------------------------------------------------- C8: slept-through bars


class TestMissedCyclesAccounting:
    """C8: a multi-bar wall-clock jump counts the slept-through bar opens."""

    def test_multi_bar_jump_counts_intervening_bars(self, tmp_path: Path) -> None:
        # Start mid-bar; the first tick lands on bar T0+HOUR. The second wake jumps
        # the clock 4 bars forward in one tick (laptop slept), landing on T0+5*HOUR.
        # The 3 bars in between (T0+2,3,4*HOUR) were slept through -> 3 missed.
        clock = Clock(T0 + HOUR // 2)
        loop, store, broker, _ = build_loop(tmp_path, clock=clock)

        jumps = {"n": 0}

        def sleeper(_s: float) -> None:
            jumps["n"] += 1
            # First outer iteration's single tick advances one bar (reaches the
            # first deadline); the second iteration's tick jumps 4 bars.
            clock.advance(HOUR if jumps["n"] == 1 else 4 * HOUR)

        loop._sleeper = sleeper
        try:
            loop.run_forever(max_cycles=2)
        finally:
            store.close()
        # Two cycles ran (both traded the fresh book); 3 bars were slept through.
        assert len(broker.fills) >= 1
        assert loop.missed_cycles == 3

    def test_no_jump_counts_no_missed(self, tmp_path: Path) -> None:
        # A steady cadence (one bar per wake) slept through nothing.
        clock = Clock(T0 + HOUR // 2)
        loop, store, _broker, _ = build_loop(tmp_path, clock=clock)
        loop._sleeper = lambda _s: clock.advance(HOUR)
        try:
            loop.run_forever(max_cycles=3)
        finally:
            store.close()
        assert loop.missed_cycles == 0


# ----------------------------------------------------- C9: degraded + dropped


class TestDegradedAndDropped:
    """C9: partial staleness WARN-alerts + counts; dropped book instruments count."""

    def test_partially_stale_cycle_alerts_warn_and_counts(self, tmp_path: Path) -> None:
        alerter = RecordingAlerter()
        # The clock must advance past the ingest grace so the loop reaches the
        # staleness breaker (which, one bar behind, still allows trading).
        calls = {"n": 0}

        def clock() -> Ms:
            calls["n"] += 1
            # First read opens the cycle at T0+90s; later reads are past the grace
            # (but still within the 2-bar staleness window for a 1-bar-old lake).
            return T0 + 90_000 + calls["n"] * 1000

        loop, store, _broker, _ = build_loop(
            tmp_path, watermark=DegradedWatermark(), alerter=alerter
        )
        loop._clock = clock
        loop._sleeper = lambda _s: None
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        # Tradeable but degraded: it decided, fired a WARN, and counted the cycle.
        assert report.status == "ok"
        assert report.degraded is True
        assert loop.degraded_cycles == 1
        assert any(level is AlertLevel.WARN for level, _ in alerter.records)

    def test_dropped_book_instrument_is_counted(self, tmp_path: Path) -> None:
        # ETH is in the universe + broker map but has NO registered book; it cannot
        # be marked and is dropped from sizing. The strategy targets only BTC.
        loop, store, _broker, _ = build_loop(
            tmp_path, targets={BTC: 0.10}, uncovered_instrument=ETH
        )
        try:
            report = loop.run_cycle(T0)
        finally:
            store.close()
        assert report.status == "ok"
        assert report.dropped_book_instruments == 1
        assert loop.dropped_book_instruments == 1


# ----------------------------------------------------- C4-persist: ladder state


class TestLadderStatePersistence:
    """C4-persist: the loop records the LIVE ladder snapshot each cycle."""

    def test_loop_records_ladder_state_each_cycle(self, tmp_path: Path) -> None:
        loop, store, _broker, _ = build_loop(tmp_path, use_ladder=True)
        try:
            assert loop.run_cycle(T0).status == "ok"
            snap = store.last_ladder_state()
            assert snap is not None
            assert snap.cycle_ts == T0
            # A healthy first cycle: NORMAL, full gross.
            assert snap.state == "normal"
            assert snap.gross_mult == 1.0
        finally:
            store.close()

    def test_persisted_state_reflects_normal_after_rearm(self, tmp_path: Path) -> None:
        # Drive the SHARED ladder into FLAT_HALTED, record it, then rearm and run
        # again: the persisted snapshot must reflect NORMAL (not a stale halt).
        loop, store, _broker, _ = build_loop(tmp_path, use_ladder=True)
        ladder = loop._ladder
        try:
            # Pre-trip the ladder: a 20% drawdown from a higher HWM -> FLAT_HALTED.
            ladder.update(200_000.0)
            ladder.update(100_000.0)
            assert ladder.gross_multiplier() == 0.0
            assert loop.run_cycle(T0).status == "ok"
            halted = store.last_ladder_state()
            assert halted is not None and halted.state == "flat_halted"
            assert halted.gross_mult == 0.0

            # A human rearms; the next recorded cycle reflects NORMAL again.
            ladder.rearm()
            assert ladder.gross_multiplier() == 1.0
            assert loop.run_cycle(T0 + HOUR).status == "ok"
            rearmed = store.last_ladder_state()
            assert rearmed is not None
            assert rearmed.cycle_ts == T0 + HOUR
            assert rearmed.state == "normal"
            assert rearmed.gross_mult == 1.0
        finally:
            store.close()
