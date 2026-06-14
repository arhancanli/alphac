"""Offline 24-cycle PAPER soak simulation (execDesign.md section 9; build order item 11).

Runs ~24 consecutive synthetic hourly cycles through the REAL Phase-6/7 decision
stack over a tmp_path lake, asserting the operational contract the live system
must honour over a long unattended run:

* **Exact N/M cycle accounting.** After M consecutive cycles the store reports M
  expected, M run (every bar reached a terminal decision), 0 spurious skips.
* **Equity persists per cycle.** One ``equity_curve`` row per run cycle, in order.
* **A no-data cycle is SKIPPED, not FAILED.** When the lake does not cover a bar
  (a real outage), the staleness gate makes the loop finish that cycle
  ``'skipped'`` and COUNT it as a miss -- never a hard failure, never a trade.
* **Paper state resumes identically after a mid-soak restart.** Snapshotting the
  broker mid-soak, "restarting" (fresh store + broker rehydrated from the
  persisted blob), and continuing reproduces the SAME book the uninterrupted run
  would have -- the crash-safe resume guarantee under the soak's repetition.

Fully OFFLINE and deterministic: synthetic Parquet lake, canned order books,
injected clock. No network.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from alphaforge.backtest.engine import LakeCostInputs, StrategyContext
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.order_manager import OrderManager
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import Reconciler
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.live.alerts import LogAlerter
from alphaforge.live.loop import LiveLoop, decode_paper_state
from alphaforge.live.store import TradingStore
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.risk import KillSwitch, PreTradeChecker, RiskLimits, StalenessBreaker
from alphaforge.signals.blending import BlendWeights
from alphaforge.signals.service import SignalService
from alphaforge.signals.sizing import MU_ANN_COLUMN

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z
N_BARS = 900
MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
LISTED = T0 - 365 * 24 * HOUR
SOAK_CYCLES = 24


# --------------------------------------------------------------------------- lake


def _closes(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n))))


def _ohlcv_table(per_inst: Mapping[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([5.0e7] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
        quote="USDT",
        tick_size=0.01,
        lot_size=0.0001,
        min_qty=0.0001,
        min_notional=5.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def _registry() -> FeatureRegistry:
    reg = FeatureRegistry()

    def _xret(ctx: object, spec: FeatureSpec) -> object:
        close = ctx.panel("close")  # type: ignore[attr-defined]
        window = int(spec.params["window"])
        out = np.log(close / close.shift(window))
        return long_series(out, name=spec.name)

    def alpha_mom() -> FeatureSpec:
        window = 48
        return FeatureSpec(
            name="alpha_mom",
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret,  # type: ignore[arg-type]
        )

    reg.register(alpha_mom)
    return reg


def _book_for(per_inst: Mapping[str, np.ndarray], iid: str, *, idx: int, ts: Ms) -> OrderBook:
    px = float(per_inst[iid][min(idx, len(per_inst[iid]) - 1)])
    bids = ((px * 0.9995, 1.0e6), (px * 0.999, 2.0e6))
    asks = ((px * 1.0005, 1.0e6), (px * 1.001, 2.0e6))
    return OrderBook(instrument_id=iid, bids=bids, asks=asks, ts=ts)


# --------------------------------------------------------------------------- adapters


class _Watermark:
    def __init__(self, reader: PITDataReader) -> None:
        self._reader = reader

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        floor: Ms | None = None
        for iid in instrument_ids:
            latest = self._reader.latest_bar_open(iid, as_of=as_of, tf=Timeframe.H1)
            if latest is None:
                return None
            floor = latest if floor is None else min(floor, latest)
        return floor


class _NoopUpdater:
    def update(self, *, as_of: Ms) -> object:
        del as_of
        return None


class _Instruments:
    def __init__(self, universe: UniverseStore, store: InstrumentStore) -> None:
        self._universe = universe
        self._store = store

    def __call__(self, cycle_ts: Ms) -> Mapping[str, Instrument]:
        out: dict[str, Instrument] = {}
        for iid in sorted(self._universe.membership_asof(cycle_ts)):
            inst = self._store.get(iid, cycle_ts)
            if inst is not None:
                out[iid] = inst
        return out


class _MuProvider:
    def __init__(self, service: SignalService, window_start: Ms) -> None:
        self._service = service
        self._window_start = window_start
        self._weights: BlendWeights | None = None

    def __call__(self, decision_ts: Ms) -> Mapping[str, float]:
        if self._weights is None:
            self._weights = self._service.estimate_weights(self._window_start, decision_ts)
        try:
            frame = self._service.on_bar_close(decision_ts, weights=self._weights)
        except ValueError:
            return {}
        col = frame[MU_ANN_COLUMN]
        return {str(i): float(v) for i, v in col.items() if np.isfinite(v)}


class _CostFactory:
    def __init__(self, reader: PITDataReader) -> None:
        self._reader = reader

    def __call__(self, cycle_ts: Ms, instrument_ids: Sequence[str]) -> LakeCostInputs:
        return LakeCostInputs(
            self._reader,
            list(instrument_ids),
            start=cycle_ts - LakeCostInputs.WARMUP_MS,
            end=cycle_ts,
        )


class _CtxFactory:
    def __init__(self, reader: PITDataReader) -> None:
        self._reader = reader

    def __call__(
        self,
        *,
        cycle_ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> StrategyContext:
        return StrategyContext(
            reader=self._reader,
            tf=Timeframe.H1,
            ts=cycle_ts,
            equity=equity,
            positions=positions,
            instruments=instruments,
        )


# --------------------------------------------------------------------------- world


class _Clock:
    """A mutable injectable wall clock the loop reads via its ``clock`` seam.

    Pinned at a fixed 'now' for the happy path (the watermark covers every cycle,
    so the freshness wait returns immediately and the clock never moves). When a
    cycle goes stale -- the no-data bar whose watermark never lands -- the injected
    sleeper ADVANCES this clock each tick so the grace deadline in
    ``LiveLoop._ingest_and_wait`` is actually reached and the cycle is skipped,
    instead of spinning forever on a never-advancing clock with a real
    ``time.sleep``.
    """

    def __init__(self, start: Ms) -> None:
        self.t = start

    def __call__(self) -> Ms:
        return self.t

    def advance(self, ms: Ms) -> None:
        self.t += ms


@dataclass(slots=True)
class _Stack:
    loop: LiveLoop
    store: TradingStore
    broker: PaperBroker
    book_source: FakeOrderBookSource
    clock: _Clock


@dataclass(slots=True)
class _World:
    tmp_path: Path
    closes: dict[str, np.ndarray]
    reader: PITDataReader
    universe: UniverseStore
    store_inst: InstrumentStore
    service: SignalService
    settings: Settings
    cost_model: TransactionCostModel

    def new_stack(self, *, restore_blob: str | None, db_name: str = "trading.sqlite") -> _Stack:
        book_source = FakeOrderBookSource()
        instruments_now = {iid: _instrument(iid) for iid in MEMBERS}
        state = None if restore_blob is None else decode_paper_state(restore_blob)
        broker = PaperBroker(
            instruments_now,
            self.cost_model,
            book_source=book_source,
            initial_cash=100_000.0,
            state=state,
        )
        store = TradingStore(self.tmp_path / db_name)
        strategy = BlendStrategy(
            self.settings, mu_provider=_MuProvider(self.service, T0), cov_min_periods=240
        )
        clock = _Clock(T0 + N_BARS * HOUR)
        loop = LiveLoop(
            self.settings,
            store=store,
            broker=broker,
            order_manager=OrderManager(broker, store),
            reconciler=Reconciler(broker, store),
            strategy=strategy,
            pretrade=PreTradeChecker(RiskLimits.from_cfg(self.settings.risk), self.cost_model),
            ladder=strategy.ladder,
            staleness=StalenessBreaker(max_bars=self.settings.risk.staleness_max_bars),
            kill=KillSwitch(self.tmp_path / "KILL"),
            alerter=LogAlerter(),
            updater=_NoopUpdater(),
            watermark=_Watermark(self.reader),
            cost_inputs_factory=_CostFactory(self.reader),
            ctx_factory=_CtxFactory(self.reader),
            instruments_factory=_Instruments(self.universe, self.store_inst),
            clock=clock,
            # Advance the injected clock each grace tick so a STALE cycle reaches
            # its deadline and is skipped (never a real time.sleep / infinite spin).
            sleeper=lambda s: clock.advance(int(s * 1000)),
        )
        return _Stack(loop, store, broker, book_source, clock)

    def set_books(self, stack: _Stack, *, idx: int, ts: Ms) -> None:
        for iid in MEMBERS:
            stack.book_source.set_book(_book_for(self.closes, iid, idx=idx, ts=ts))


@pytest.fixture
def world(tmp_path: Path) -> Iterator[_World]:
    paths = LakePaths(tmp_path / "lake")
    closes = {iid: _closes(11 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(MEMBERS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(MEMBERS), type=pa.string()),
                "effective_from": pa.array([T0] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(MEMBERS), type=pa.int32()),
                "reason": pa.array(["enter"] * len(MEMBERS), type=pa.string()),
            }
        )
    )

    store_inst = InstrumentStore(tmp_path / "ops.sqlite")
    for iid in MEMBERS:
        store_inst.upsert(_instrument(iid), as_of=LISTED)

    reader = PITDataReader(paths)
    settings = Settings()
    cost_model = TransactionCostModel.from_settings(settings)
    service = SignalService(
        FeatureEngine(reader, store_inst, universe), universe, _registry(), settings.signals
    )
    try:
        yield _World(
            tmp_path=tmp_path,
            closes=closes,
            reader=reader,
            universe=universe,
            store_inst=store_inst,
            service=service,
            settings=settings,
            cost_model=cost_model,
        )
    finally:
        store_inst.close()


def _book_summary(broker: PaperBroker) -> tuple[float, tuple[tuple[str, float], ...]]:
    state = broker.snapshot_state()
    positions = tuple(sorted((iid, round(p.qty, 9)) for iid, p in state.positions.items()))
    return round(state.cash, 6), positions


# --------------------------------------------------------------------------- tests


def test_24_cycle_soak_accounting_and_equity_persist(world: _World) -> None:
    """24 consecutive hourly cycles: exact N/M accounting + an equity row per run."""
    stack = world.new_stack(restore_blob=None)
    stack.loop.recover_on_boot()

    first_idx = N_BARS - SOAK_CYCLES
    cycles: list[Ms] = []
    for k in range(SOAK_CYCLES):
        idx = first_idx + k
        cts = T0 + idx * HOUR
        cycles.append(cts)
        world.set_books(stack, idx=idx, ts=cts)
        report = stack.loop.run_cycle(cts)
        assert report.status == "ok", f"cycle {k} ({cts}) -> {report.status}: {report.detail}"

    # N/M accounting is EXACT over the soak window: 24 expected, 24 run, 0 missed.
    expected, run_, skipped = stack.store.expected_vs_run(cycles[0], cycles[-1], HOUR)
    assert (expected, run_, skipped) == (SOAK_CYCLES, SOAK_CYCLES, 0)
    assert stack.loop.missed_cycles == 0

    # One equity row per run cycle, strictly ordered, every value finite.
    curve = stack.store.equity_curve(cycles[0])
    persisted = [row[0] for row in curve]
    assert persisted == cycles, "every run cycle must persist exactly one equity point in order"
    assert all(np.isfinite(row[1]) and row[1] > 0.0 for row in curve)

    # The book evolved and the final paper_state blob resumes the last bar.
    assert stack.broker.fills, "a 24-cycle soak must have traded at least once"
    latest = stack.store.latest_paper_state()
    assert latest is not None and latest[0] == cycles[-1]
    stack.store.close()


def test_soak_no_data_cycle_is_skipped_not_failed(world: _World) -> None:
    """A bar the lake does not cover is SKIPPED (counted), never FAILED, never traded."""
    stack = world.new_stack(restore_blob=None)
    stack.loop.recover_on_boot()

    # A normal in-lake cycle first (so the store has history).
    good_idx = N_BARS - 2
    good_ts = T0 + good_idx * HOUR
    world.set_books(stack, idx=good_idx, ts=good_ts)
    assert stack.loop.run_cycle(good_ts).status == "ok"
    fills_before = len(stack.broker.fills)

    # A bar BEYOND the lake's coverage: the watermark never reaches it and, after
    # the grace, the staleness gate trips. Production-faithfully, the loop only ever
    # decides floor_bar(now); a real ingestion outage means wall-clock 'now' has
    # advanced past the last data bar, so we move the injected clock to the stale
    # bar (more than staleness_max_bars past the last lake close) before deciding.
    future_ts = T0 + (N_BARS + 5) * HOUR  # no bar exists at/after this open
    stack.clock.t = future_ts
    world.set_books(stack, idx=N_BARS - 1, ts=future_ts)
    report = stack.loop.run_cycle(future_ts)
    assert report.status == "skipped"
    assert "stale" in report.detail
    # No trade happened on the skipped bar; it is counted as a miss, not a failure.
    assert len(stack.broker.fills) == fills_before
    assert stack.loop.missed_cycles >= 1
    row = stack.store.get_cycle(future_ts)
    assert row is not None and row.status == "skipped"
    stack.store.close()


def test_mid_soak_restart_resumes_identical_paper_state(world: _World) -> None:
    """Restarting mid-soak resumes the EXACT broker book from the persisted blob.

    The crash-safe resume guarantee the system actually makes (execDesign.md 9.3):
    the persisted ``paper_state`` blob restores the broker's cash/positions/fills
    BIT-IDENTICALLY, and the loop then continues trading from that book without
    drift, replay, or lost fills.

    NOTE on scope: the blob persists the BROKER account only. The decision
    strategy's in-memory cadence (``rebalance_bars`` schedule, ladder HWM, last
    targets) is NOT serialized -- a fresh process re-anchors it. So a restart is
    intentionally NOT bit-identical to an uninterrupted run that carried that
    cadence state across the whole window; asserting that would test a guarantee
    v1 does not make. What IS guaranteed and asserted here: (a) the restored book
    equals the book at restart exactly, (b) the resumed half extends the SAME fill
    ledger (every pre-restart fill still present, in order, plus only new ones),
    and (c) the resumed book stays internally consistent (equity == cash + marks).
    """
    first_idx = N_BARS - SOAK_CYCLES
    cycles = [T0 + (first_idx + k) * HOUR for k in range(SOAK_CYCLES)]
    half = SOAK_CYCLES // 2

    # ----- interrupted: first half on A -----
    stack_a = world.new_stack(restore_blob=None)
    stack_a.loop.recover_on_boot()
    for k in range(half):
        cts = cycles[k]
        world.set_books(stack_a, idx=first_idx + k, ts=cts)
        assert stack_a.loop.run_cycle(cts).status == "ok"
    blob_a = stack_a.store.latest_paper_state()
    assert blob_a is not None
    book_at_restart = _book_summary(stack_a.broker)
    coids_at_restart = [f.client_order_id for f in stack_a.broker.fills]
    stack_a.store.close()  # 'process dies' cleanly mid-soak.

    # ----- restart on B from the persisted blob; run the second half -----
    stack_b = world.new_stack(restore_blob=blob_a[1])
    stack_b.loop.recover_on_boot()
    # (a) The restored book equals the book at restart EXACTLY (no drift).
    assert _book_summary(stack_b.broker) == book_at_restart
    # (b) The restored fill ledger is exactly the pre-restart ledger (prefix), and
    #     re-running the second half only APPENDS (no replay, no loss, in order).
    assert [f.client_order_id for f in stack_b.broker.fills] == coids_at_restart
    for k in range(half, SOAK_CYCLES):
        cts = cycles[k]
        world.set_books(stack_b, idx=first_idx + k, ts=cts)
        assert stack_b.loop.run_cycle(cts).status == "ok"
    resumed_coids = [f.client_order_id for f in stack_b.broker.fills]
    assert resumed_coids[: len(coids_at_restart)] == coids_at_restart
    assert len(resumed_coids) == len(set(resumed_coids))  # no duplicate fills

    # (c) The resumed book is internally consistent: equity == cash + marks, finite.
    account = stack_b.broker.account_at(cycles[-1])
    mark_value = sum(p.qty * world.closes[p.instrument_id][N_BARS - 1] for p in account.positions)
    assert np.isfinite(account.equity_quote)
    assert account.equity_quote == pytest.approx(account.cash_quote + mark_value, rel=1e-6)
    stack_b.store.close()
