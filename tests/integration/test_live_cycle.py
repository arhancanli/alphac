"""Integration: the REAL decision stack run LIVE through the PAPER loop, end to end.

Wires the genuine Phase-6 brain -- SignalService (over a FeatureEngine + PIT
universe) -> BlendStrategy in LIVE mode (mu_provider) -> RankEqualVolFallback ->
vol-target -> DrawdownLadder -> weights_to_orders -> PreTradeChecker -> the real
PaperBroker (filling by WALKING a FakeOrderBookSource) -> the real TradingStore --
over a synthetic tmp_path lake, and runs several consecutive hourly cycles.

Asserts the loop's contract end to end:

* the paper book EVOLVES across cycles (orders fill, positions/equity persist);
* the equity curve + position snapshots are persisted per cycle;
* N/M cycle accounting is correct (every run cycle counts);
* re-running an already-done cycle_ts is idempotently SKIPPED (no double orders).

Fully OFFLINE: the lake is synthetic Parquet under tmp_path, the order book is a
canned FakeOrderBookSource, every wall-clock read is injected. No network.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
from alphaforge.live.loop import LiveLoop
from alphaforge.live.store import TradingStore
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.risk import (
    KillSwitch,
    PreTradeChecker,
    RiskLimits,
    StalenessBreaker,
)
from alphaforge.signals.blending import BlendWeights
from alphaforge.signals.service import SignalService
from alphaforge.signals.sizing import MU_ANN_COLUMN

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z, bar-aligned
N_BARS = 900
MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
LISTED = T0 - 365 * 24 * HOUR


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
    """One finite-window cross-sectional momentum alpha (enough to size a book)."""
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
    """A deep two-sided book centered on the instrument's close at bar ``idx``."""
    px = float(per_inst[iid][min(idx, len(per_inst[iid]) - 1)])
    bids = ((px * 0.9995, 1.0e6), (px * 0.999, 2.0e6))
    asks = ((px * 1.0005, 1.0e6), (px * 1.001, 2.0e6))
    return OrderBook(instrument_id=iid, bids=bids, asks=asks, ts=ts)


# --------------------------------------------------------------------------- adapters


class _Watermark:
    """Lake freshness via the reader's freshest fully-available bar open."""

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
    """The lake is pre-seeded; the updater is a no-op (the loop still drives it)."""

    def __init__(self) -> None:
        self.calls = 0

    def update(self, *, as_of: Ms) -> object:
        self.calls += 1
        return None


class _Instruments:
    """PIT universe members x instrument record at a cycle."""

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
    """Live mu_ann seam over the real SignalService (the BlendStrategy contract)."""

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


# --------------------------------------------------------------------------- env


class _Env:
    __slots__ = ("book_source", "broker", "closes", "loop", "store")

    def __init__(
        self,
        loop: LiveLoop,
        store: TradingStore,
        broker: PaperBroker,
        book_source: FakeOrderBookSource,
        closes: Mapping[str, np.ndarray],
    ) -> None:
        self.loop = loop
        self.store = store
        self.broker = broker
        self.book_source = book_source
        self.closes = closes


@pytest.fixture
def env(tmp_path: Path) -> Iterator[_Env]:
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

    book_source = FakeOrderBookSource()
    instruments_now = {iid: _instrument(iid) for iid in MEMBERS}
    broker = PaperBroker(
        instruments_now, cost_model, book_source=book_source, initial_cash=100_000.0
    )
    trading = TradingStore(tmp_path / "trading.sqlite")
    strategy = BlendStrategy(
        settings,
        mu_provider=_MuProvider(service, T0),
        cov_min_periods=240,
    )
    loop = LiveLoop(
        settings,
        store=trading,
        broker=broker,
        order_manager=OrderManager(broker, trading),
        reconciler=Reconciler(broker, trading),
        strategy=strategy,
        pretrade=PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model),
        ladder=strategy.ladder,
        staleness=StalenessBreaker(max_bars=settings.risk.staleness_max_bars),
        kill=KillSwitch(tmp_path / "KILL"),
        alerter=LogAlerter(),
        updater=_NoopUpdater(),
        watermark=_Watermark(reader),
        cost_inputs_factory=_CostFactory(reader),
        ctx_factory=_CtxFactory(reader),
        instruments_factory=_Instruments(universe, store_inst),
        clock=lambda: T0 + N_BARS * HOUR,  # well after the lake's last bar
    )
    try:
        yield _Env(loop, trading, broker, book_source, closes)
    finally:
        trading.close()
        store_inst.close()


def _set_books(env: _Env, *, idx: int, ts: Ms) -> None:
    """Refresh the canned books to the bar-``idx`` prices for every member."""
    for iid in MEMBERS:
        env.book_source.set_book(_book_for(env.closes, iid, idx=idx, ts=ts))


# --------------------------------------------------------------------------- tests


def test_three_consecutive_cycles_evolve_the_paper_book(env: _Env) -> None:
    """The real stack, live, trades a real book across 3 cycles; state persists."""
    cycle_a = T0 + (N_BARS - 3) * HOUR
    cycle_b = cycle_a + HOUR
    cycle_c = cycle_b + HOUR

    statuses: list[str] = []
    for k, cts in enumerate((cycle_a, cycle_b, cycle_c)):
        _set_books(env, idx=N_BARS - 3 + k, ts=cts)
        report = env.loop.run_cycle(cts)
        statuses.append(report.status)

    # Every cycle completed (the decision stack produced a clean 'ok' bar).
    assert statuses == ["ok", "ok", "ok"]

    # The book evolved: at least one cycle filled orders and opened positions.
    assert len(env.broker.fills) >= 1
    assert env.broker.positions(), "the live stack should have opened a paper book"

    # Equity + positions persisted per cycle (one equity row per run cycle).
    curve = env.store.equity_curve()
    persisted_cycles = {row[0] for row in curve}
    assert {cycle_a, cycle_b, cycle_c} <= persisted_cycles
    assert env.store.positions_at(cycle_c)  # final book snapshot present

    # A paper_state blob was saved for resume.
    latest = env.store.latest_paper_state()
    assert latest is not None and latest[0] == cycle_c


def test_cycle_accounting_counts_every_run(env: _Env) -> None:
    """N/M expected-vs-run accounting reflects exactly the cycles that ran."""
    cycles = [T0 + (N_BARS - 3 + k) * HOUR for k in range(3)]
    for k, cts in enumerate(cycles):
        _set_books(env, idx=N_BARS - 3 + k, ts=cts)
        env.loop.run_cycle(cts)

    expected, run_, skipped = env.store.expected_vs_run(cycles[0], cycles[-1], HOUR)
    assert expected == 3
    assert run_ == 3  # every cycle reached an 'ok' decision
    assert skipped == 0


def test_replaying_a_done_cycle_is_idempotently_skipped(env: _Env) -> None:
    """A second run of the SAME cycle_ts books NO new orders (crash-replay safety)."""
    cts = T0 + (N_BARS - 2) * HOUR
    _set_books(env, idx=N_BARS - 2, ts=cts)

    first = env.loop.run_cycle(cts)
    assert first.status == "ok"
    fills_after_first = len(env.broker.fills)
    orders_after_first = len(env.store.orders_for_cycle(cts))

    # Replay the identical bar -- the store gate refuses it (already terminal).
    second = env.loop.run_cycle(cts)
    assert second.status == "skipped"
    assert "terminal" in second.detail
    assert len(env.broker.fills) == fills_after_first  # NO double fill
    assert len(env.store.orders_for_cycle(cts)) == orders_after_first  # NO double order
    assert env.loop.missed_cycles >= 1


def test_boot_recovery_then_first_cycle_is_clean(env: _Env) -> None:
    """recover_on_boot on a fresh store is a no-op, then the first cycle runs ok."""
    env.loop.recover_on_boot()  # nothing to recover -> clean
    cts = T0 + (N_BARS - 1) * HOUR
    _set_books(env, idx=N_BARS - 1, ts=cts)
    report = env.loop.run_cycle(cts)
    assert report.status == "ok"
    # The boot reconcile saw an empty book; the cycle then persisted equity.
    assert env.store.equity_curve()
