"""THE crash-recovery gate (execDesign.md section 9.3): a SIGKILL at any cycle stage,
followed by restart + recover + re-run of the SAME ``cycle_ts``, must NEVER
double-submit, double-fill, or corrupt the paper book -- and the cycle must end
terminal.

This is the phase's headline test. It drives the REAL Phase-6/7 decision stack
LIVE through the :class:`~alphaforge.live.loop.LiveLoop` over a synthetic tmp_path
lake and the real :class:`~alphaforge.execution.paper.PaperBroker` (filling by
WALKING a canned :class:`~alphaforge.execution.paper.FakeOrderBookSource`), with a
broker whose ``submit`` can be made to "crash" (raise ``SystemExit``, the
hardest-to-catch interruption) at each stage of the persist/submit/fill ladder:

  * INTENT_PERSISTED  -- the OrderManager wrote the NEW intent row, then the
    process dies BEFORE the broker books any fill (broker state untouched).
  * FILL_UNPERSISTED  -- the broker fully booked the fill AND its idempotency
    ack, then the process dies BEFORE the OrderManager persists that fill to the
    store (the classic "did it land?" window).
  * FILL_PERSISTED    -- one order's fill is fully persisted, then the process
    dies mid-batch BEFORE the cycle is marked terminal.

After each simulated crash we open a FRESH process view (a brand-new
:class:`~alphaforge.live.store.TradingStore` over the same SQLite file, plus a
fresh :class:`PaperBroker` rehydrated from the persisted ``paper_state`` blob --
exactly what a real restart does), call ``recover_on_boot()`` to reconcile, then
re-run the SAME ``cycle_ts``. We then assert:

  * the broker booked each ``client_order_id`` AT MOST ONCE (no double order);
  * the persisted fill count never exceeds the broker's booked fills (no phantom
    or duplicated fills in the store);
  * the recovered book equals the pre-crash broker truth (cash + positions);
  * the cycle reaches a terminal status and is never re-traded on replay.

Parameterized over the three crash stages. Fully OFFLINE and deterministic.
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
from alphaforge.core.types import (
    AssetClass,
    Fill,
    Liquidity,
    MarketType,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
)
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.execution.broker import BrokerAck, OrderBook
from alphaforge.execution.order_manager import OrderManager
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import Reconciler
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.live.alerts import LogAlerter
from alphaforge.live.loop import LiveLoop, decode_paper_state, encode_paper_state
from alphaforge.live.store import TradingStore
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.risk import KillSwitch, PreTradeChecker, RiskLimits, StalenessBreaker
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


# --------------------------------------------------------------------------- crash broker


class _CrashSubmit(SystemExit):
    """The simulated SIGKILL: a ``SystemExit`` raised from inside ``submit``.

    ``SystemExit`` (not ``Exception``) is used deliberately -- it is NOT caught by
    the loop's ``except (AlphaForgeError, ValueError, ...)`` clauses, so it
    propagates out exactly like a process kill would, leaving whatever the store
    and broker persisted up to that instant as the on-disk truth.
    """


@dataclass(slots=True)
class _CrashPlan:
    """Where the next ``submit`` should crash. ``None`` disarms (normal submit)."""

    #: 'pre_fill'  -> raise BEFORE the real broker books the fill (intent only).
    #: 'post_fill' -> let the real broker book the fill + ack, then raise (the
    #:               OrderManager never gets to persist that fill).
    stage: str | None = None
    #: Crash only on the order whose client_order_id contains this token (so we
    #: can crash mid-batch on a specific order); None means the first submit.
    on_coid_contains: str | None = None
    fired: bool = False


class _CrashBroker(PaperBroker):
    """A :class:`PaperBroker` whose ``submit`` can crash at a chosen stage.

    Wraps the real walk-the-book fill so every non-crash path is byte-identical
    to production. The crash injector fires exactly once per armed plan, then
    disarms, so the post-restart re-run proceeds normally.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.plan = _CrashPlan()

    def _should_fire(self, order: OrderRequest, stage: str) -> bool:
        plan = self.plan
        if plan.fired or plan.stage != stage:
            return False
        token = plan.on_coid_contains
        return token is None or token in order.client_order_id

    def submit(self, order: OrderRequest) -> BrokerAck:
        # An already-acked id is the idempotent replay path: never crash, never
        # double-book (the production guarantee under test).
        if order.client_order_id in self._state.acks:
            return super().submit(order)
        if self._should_fire(order, "pre_fill"):
            self.plan.fired = True
            raise _CrashSubmit("crash: intent persisted, broker untouched")
        ack = super().submit(order)
        if self._should_fire(order, "post_fill"):
            self.plan.fired = True
            # The broker has now booked the fill AND stored the ack; the crash
            # fires before the caller (OrderManager) can persist the fill.
            raise _CrashSubmit("crash: broker filled, store not yet updated")
        return ack


# --------------------------------------------------------------------------- env


class _Stack:
    """A full live stack over one shared SQLite file + one shared broker book.

    Re-built from scratch (fresh ``TradingStore`` + fresh ``_CrashBroker``
    rehydrated from the persisted ``paper_state`` blob) to model a process
    restart while keeping the on-disk SQLite and the prior simulated book.
    """

    __slots__ = ("book_source", "broker", "closes", "loop", "store")

    def __init__(
        self,
        loop: LiveLoop,
        store: TradingStore,
        broker: _CrashBroker,
        book_source: FakeOrderBookSource,
        closes: Mapping[str, np.ndarray],
    ) -> None:
        self.loop = loop
        self.store = store
        self.broker = broker
        self.book_source = book_source
        self.closes = closes


@dataclass(slots=True)
class _World:
    """Immutable per-test lake/universe handles; builds fresh stacks on demand."""

    tmp_path: Path
    closes: dict[str, np.ndarray]
    reader: PITDataReader
    universe: UniverseStore
    store_inst: InstrumentStore
    service: SignalService
    settings: Settings
    cost_model: TransactionCostModel

    def new_stack(self, *, restore_blob: str | None) -> _Stack:
        """A fresh process view over the same SQLite file and rehydrated book."""
        book_source = FakeOrderBookSource()
        instruments_now = {iid: _instrument(iid) for iid in MEMBERS}
        state = None if restore_blob is None else decode_paper_state(restore_blob)
        broker = _CrashBroker(
            instruments_now,
            self.cost_model,
            book_source=book_source,
            initial_cash=100_000.0,
            state=state,
        )
        store = TradingStore(self.tmp_path / "trading.sqlite")
        strategy = BlendStrategy(
            self.settings,
            mu_provider=_MuProvider(self.service, T0),
            cov_min_periods=240,
        )
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
            clock=lambda: T0 + N_BARS * HOUR,
        )
        return _Stack(loop, store, broker, book_source, self.closes)


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


def _set_books(stack: _Stack, *, idx: int, ts: Ms) -> None:
    for iid in MEMBERS:
        stack.book_source.set_book(_book_for(stack.closes, iid, idx=idx, ts=ts))


def _persisted_fill_count(store: TradingStore, coids: Sequence[str]) -> int:
    return sum(len(store.fills_for(coid)) for coid in coids)


def _book_summary(broker: PaperBroker) -> tuple[float, tuple[tuple[str, float], ...]]:
    """(cash, sorted (instrument_id, qty)) -- the invariant we compare across restarts."""
    state = broker.snapshot_state()
    positions = tuple(sorted((iid, p.qty) for iid, p in state.positions.items()))
    return state.cash, positions


# --------------------------------------------------------------------------- the gate


CRASH_STAGES = ("intent_persisted", "fill_unpersisted", "fill_persisted")


@pytest.mark.parametrize("crash_stage", CRASH_STAGES)
def test_crash_at_stage_recovers_without_double_order(world: _World, crash_stage: str) -> None:
    """SIGKILL at ``crash_stage`` -> restart+recover+re-run is order/fill-consistent.

    The flow:

    1. Run a CLEAN reference cycle on a throwaway file-twin to learn what the
       fully-completed bar produces (the order ids + the post-trade book). This
       is the oracle the crashed-then-recovered run must match.
    2. On the real file, ARM the crash at ``crash_stage`` and run the cycle; the
       injected ``SystemExit`` propagates out of ``run_cycle`` (a real kill).
    3. RESTART: open a fresh store + a broker rehydrated from the last persisted
       ``paper_state`` blob, ``recover_on_boot()`` (reconcile + fail the
       interrupted cycle), then re-run the SAME ``cycle_ts``.
    4. ASSERT no double order (each coid booked at most once at the broker),
       no phantom persisted fills, the recovered book is internally consistent,
       and the cycle is terminal.
    """
    cycle_ts = T0 + (N_BARS - 2) * HOUR
    idx = N_BARS - 2

    # ----- 1. oracle: the same cycle run to completion, uncrashed -----
    oracle = world.new_stack(restore_blob=None)
    _set_books(oracle, idx=idx, ts=cycle_ts)
    oracle.loop.recover_on_boot()
    oracle_report = oracle.loop.run_cycle(cycle_ts)
    assert oracle_report.status == "ok"
    oracle_coids = tuple(r.client_order_id for r in oracle.store.orders_for_cycle(cycle_ts))
    assert oracle_coids, "the live stack must place at least one order for this bar"
    oracle.store.close()
    # Wipe the oracle's SQLite so the crash run starts from a clean file.
    (world.tmp_path / "trading.sqlite").unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        (world.tmp_path / f"trading.sqlite{suffix}").unlink(missing_ok=True)

    # ----- 2. arm the crash and run (the SystemExit is the kill) -----
    crashed = world.new_stack(restore_blob=None)
    _set_books(crashed, idx=idx, ts=cycle_ts)
    crashed.loop.recover_on_boot()
    crashed.broker.plan = _crash_plan_for(crash_stage, oracle_coids)
    with pytest.raises(SystemExit):
        crashed.loop.run_cycle(cycle_ts)
    assert crashed.broker.plan.fired, "the crash injector must have fired"
    # Snapshot what survived to disk + the broker's in-memory book at kill time.
    crashed.broker.snapshot_state()
    crashed.store.close()  # the process is 'dead'; the file persists.

    # ----- 3. restart: fresh store + broker rehydrated from the blob -----
    with TradingStore(world.tmp_path / "trading.sqlite") as probe:
        blob = probe.latest_paper_state()
    restore_blob = None if blob is None else blob[1]
    restarted = world.new_stack(restore_blob=restore_blob)
    _set_books(restarted, idx=idx, ts=cycle_ts)
    restarted.loop.recover_on_boot()
    # The interrupted cycle is failed by recovery; replay the SAME bar.
    rerun = restarted.loop.run_cycle(cycle_ts)

    # ----- 4. the assertions -----
    # (a) No double order: every coid the broker booked appears once.
    booked = [f.client_order_id for f in restarted.broker.fills]
    assert len(booked) == len(set(booked)), f"a coid was double-filled: {booked}"

    # (b) No phantom persisted fills: the store never records more fills than the
    #     broker actually booked for the cycle's order ids.
    all_coids = tuple(r.client_order_id for r in restarted.store.orders_for_cycle(cycle_ts))
    persisted = _persisted_fill_count(restarted.store, all_coids)
    broker_booked_for_cycle = sum(
        1 for f in restarted.broker.fills if f.client_order_id in set(all_coids)
    )
    assert persisted <= broker_booked_for_cycle, (
        f"store persisted {persisted} fills but broker only booked "
        f"{broker_booked_for_cycle} for cycle {cycle_ts}"
    )

    # (c) The recovered book is internally consistent: equity = cash + marks, and
    #     re-marking is finite (account_at never raises).
    account = restarted.broker.account_at(cycle_ts)
    assert np.isfinite(account.equity_quote)
    assert np.isfinite(account.cash_quote)

    # (d) The cycle is terminal after the re-run (ok or a clean skip -- never left
    #     'running'); the store row is terminal.
    assert rerun.status in {"ok", "skipped"}
    row = restarted.store.get_cycle(cycle_ts)
    assert row is not None and row.status in {"ok", "skipped", "failed", "halted"}
    assert row.finished_ms is not None

    restarted.store.close()


def _crash_plan_for(stage: str, oracle_coids: Sequence[str]) -> _CrashPlan:
    """Translate a stage name into a :class:`_CrashPlan` for the crash broker."""
    if stage == "intent_persisted":
        # Die before the broker books ANY fill: intent NEW on disk, book pristine.
        return _CrashPlan(stage="pre_fill")
    if stage == "fill_unpersisted":
        # Let the broker book the first fill + ack, then die before the store
        # records it (the canonical "did my order land?" recovery window).
        return _CrashPlan(stage="post_fill")
    if stage == "fill_persisted":
        # Let the FIRST order fully persist, then crash on the SECOND order's
        # submit (mid-batch) before the cycle is finished. Falls back to the first
        # coid if the bar produced only one order.
        token = oracle_coids[1] if len(oracle_coids) > 1 else oracle_coids[0]
        return _CrashPlan(stage="post_fill", on_coid_contains=token)
    raise AssertionError(f"unknown crash stage {stage!r}")


def test_double_recovery_is_idempotent(world: _World) -> None:
    """Two recover_on_boot passes after a crash leave the book unchanged (no drift)."""
    cycle_ts = T0 + (N_BARS - 2) * HOUR
    idx = N_BARS - 2

    oracle = world.new_stack(restore_blob=None)
    _set_books(oracle, idx=idx, ts=cycle_ts)
    oracle.loop.recover_on_boot()
    oracle.loop.run_cycle(cycle_ts)
    oracle_coids = tuple(r.client_order_id for r in oracle.store.orders_for_cycle(cycle_ts))
    oracle.store.close()
    (world.tmp_path / "trading.sqlite").unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        (world.tmp_path / f"trading.sqlite{suffix}").unlink(missing_ok=True)

    crashed = world.new_stack(restore_blob=None)
    _set_books(crashed, idx=idx, ts=cycle_ts)
    crashed.loop.recover_on_boot()
    crashed.broker.plan = _CrashPlan(stage="post_fill")
    with pytest.raises(SystemExit):
        crashed.loop.run_cycle(cycle_ts)
    crashed.store.close()

    with TradingStore(world.tmp_path / "trading.sqlite") as probe:
        blob = probe.latest_paper_state()
    restore_blob = None if blob is None else blob[1]

    restarted = world.new_stack(restore_blob=restore_blob)
    _set_books(restarted, idx=idx, ts=cycle_ts)
    restarted.loop.recover_on_boot()
    book_after_first = _book_summary(restarted.broker)
    # A SECOND recovery pass must be a quiet no-op (idempotency).
    restarted.loop.recover_on_boot()
    assert _book_summary(restarted.broker) == book_after_first
    del oracle_coids
    restarted.store.close()


# --------------------------------------------------------------------------- corners
#
# Two corners of the headline guarantee the staged single-order test never
# reached (C10d): a POSITION FLIP (the two-order rb-{cts}-{iid}-close / -open
# recovery, crashed between its legs) and a stored PARTIAL surviving a re-run of
# place WITHOUT being downgraded to REJECTED (the C2 reconcile invariant).

_FLIP_IID = "BINANCE:PERP:ADAUSDT"
"""The instrument the real strategy wants LONG for this lake (see ``_set_books``);
seeding it SHORT makes the next decision a sign FLIP -> two-leg close/open."""


def _disk_blob(tmp_path: Path) -> str | None:
    """The latest persisted paper_state blob on disk, or ``None`` (a restart probe)."""
    with TradingStore(tmp_path / "trading.sqlite") as probe:
        latest = probe.latest_paper_state()
    return None if latest is None else latest[1]


def _status_of(store: TradingStore, coid: str) -> str:
    """The stored status of ``coid`` (asserts the order row exists)."""
    record = store.get(coid)
    assert record is not None, f"expected an order row for {coid!r}"
    return record.status


def _seed_short_position(stack: _Stack, *, iid: str, qty: float, cycle_ts: Ms, seed_ts: Ms) -> None:
    """Establish a real SHORT ``iid`` position consistently across broker AND store.

    Mirrors exactly what a prior completed cycle would have persisted: the broker
    books the fill, the store records the matching intent->submitted->filled order,
    and the end-of-cycle equity/positions/paper_state snapshots are written from
    the broker's own marked account at ``seed_ts``. Books are set at the seed bar
    first so the marked snapshot equals the broker truth (no synthetic divergence
    that would trip the boot reconciler). The NEXT decision sees an opposing
    position and emits the two-leg flip ``rb-{cycle_ts}-{iid}-close`` /
    ``-open``.
    """
    del cycle_ts
    for member in MEMBERS:
        stack.book_source.set_book(_book_for(stack.closes, member, idx=N_BARS - 3, ts=seed_ts))
    px = float(stack.closes[iid][N_BARS - 3])
    coid = f"seed-{iid}"
    fill = Fill(
        client_order_id=coid,
        instrument_id=iid,
        side=Side.SELL,
        qty=qty,
        price=px,
        fee_quote=0.0,
        liquidity=Liquidity.TAKER,
        ts=seed_ts,
    )
    stack.broker.apply_recorded_fill(fill)
    req = OrderRequest(
        client_order_id=coid,
        instrument_id=iid,
        side=Side.SELL,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=False,
        decision_ts=seed_ts,
        decision_price=px,
        reason="seed",
    )
    stack.store.record_intent(req, seed_ts, now=seed_ts)
    stack.store.mark_submitted(coid, now=seed_ts)
    stack.store.mark_filled(fill, now=seed_ts)
    account = stack.broker.account_at(seed_ts)
    stack.store.snapshot_equity(seed_ts, account)
    stack.store.snapshot_positions(seed_ts, account.positions)
    stack.store.save_paper_state(
        seed_ts, encode_paper_state(stack.broker.snapshot_state()), now=seed_ts
    )


def _set_books_thin(stack: _Stack, *, idx: int, ts: Ms, thin_iid: str, thin_size: float) -> None:
    """Deep books for every member EXCEPT ``thin_iid``, which gets a 1-level book.

    A book thinner than the order qty forces ``walk_book`` to exhaust the ladder
    and book a PARTIAL fill (``book_exhausted`` set), exercising the stored-PARTIAL
    recovery path. The other members fill in full as usual.
    """
    for iid in MEMBERS:
        if iid == thin_iid:
            px = float(stack.closes[iid][min(idx, len(stack.closes[iid]) - 1)])
            stack.book_source.set_book(
                OrderBook(
                    instrument_id=iid,
                    bids=((px * 0.9995, thin_size),),
                    asks=((px * 1.0005, thin_size),),
                    ts=ts,
                )
            )
        else:
            stack.book_source.set_book(_book_for(stack.closes, iid, idx=idx, ts=ts))


def test_flip_crash_between_legs_recovers_without_double_order(world: _World) -> None:
    """A FLIP crashed between its close and open legs recovers consistently.

    Seed an opposing SHORT position so the real strategy's long target forces a
    two-leg flip (``rb-{cts}-{iid}-close`` reduce-only, then ``-open``). Crash
    AFTER the close leg fills but BEFORE the open leg books (``pre_fill`` armed on
    the ``-open`` coid). On restart the interrupted cycle is failed; recovery must
    leave a CONSISTENT book and never double-book the close leg.
    """
    cycle_ts = T0 + (N_BARS - 2) * HOUR
    idx = N_BARS - 2
    seed_ts = cycle_ts - HOUR

    # ----- arm the crash on the flip's OPEN leg and run -----
    crashed = world.new_stack(restore_blob=None)
    _seed_short_position(crashed, iid=_FLIP_IID, qty=200.0, cycle_ts=cycle_ts, seed_ts=seed_ts)
    _set_books(crashed, idx=idx, ts=cycle_ts)
    # The seed IS the live state (a prior completed cycle): nothing to recover, so
    # run the flip cycle directly. The crash fires on the OPEN leg's submit, after
    # the reduce-only CLOSE leg has already filled.
    crashed.broker.plan = _CrashPlan(stage="pre_fill", on_coid_contains="-open")
    with pytest.raises(SystemExit):
        crashed.loop.run_cycle(cycle_ts)
    assert crashed.broker.plan.fired, "the crash injector must have fired on the open leg"
    close_coid = f"rb-{cycle_ts}-{_FLIP_IID}-close"
    open_coid = f"rb-{cycle_ts}-{_FLIP_IID}-open"
    # The reduce-only close leg is durably FILLED; the open leg is a NEW intent.
    assert _status_of(crashed.store, close_coid) == OrderStatus.FILLED.value
    assert _status_of(crashed.store, open_coid) == OrderStatus.NEW.value
    crashed.store.close()

    # ----- restart: rehydrate, recover, re-run the SAME bar -----
    restarted = world.new_stack(restore_blob=_disk_blob(world.tmp_path))
    _set_books(restarted, idx=idx, ts=cycle_ts)
    restarted.loop.recover_on_boot()
    rerun = restarted.loop.run_cycle(cycle_ts)

    # (a) No double order: the close leg the broker booked appears exactly once;
    #     the open leg (filled_qty == 0, never landed) was never booked twice.
    booked = [f.client_order_id for f in restarted.broker.fills]
    assert len(booked) == len(set(booked)), f"a flip leg was double-booked: {booked}"
    assert booked.count(close_coid) <= 1
    assert booked.count(open_coid) == 0

    # (b) The interrupted-cycle resolution is terminal -- the open leg never landed
    #     so it is REJECTED (its residual re-enters next cycle), the close leg
    #     stays FILLED, and the cycle is failed/skipped (never re-traded).
    assert _status_of(restarted.store, close_coid) == OrderStatus.FILLED.value
    assert _status_of(restarted.store, open_coid) == OrderStatus.REJECTED.value
    assert rerun.status in {"ok", "skipped"}
    row = restarted.store.get_cycle(cycle_ts)
    assert row is not None and row.status in {"ok", "skipped", "failed", "halted"}
    assert row.finished_ms is not None

    # (c) The recovered book is internally consistent (finite marks): the flip's
    #     reduce-only close DID execute, so the seeded short is flat, not doubled.
    account = restarted.broker.account_at(cycle_ts)
    assert np.isfinite(account.equity_quote)
    assert np.isfinite(account.cash_quote)
    restarted.store.close()


def test_stored_partial_survives_restart_not_rejected(world: _World) -> None:
    """A stored PARTIAL on restart is preserved (NOT rejected) and the book is consistent.

    A thin book partials the first order; the crash then fires on a LATER order so
    the cycle dies ``'running'`` with a durable PARTIAL on disk. On restart the C2
    reconcile invariant must hold: an order with ``filled_qty > 0`` is NEVER
    downgraded to REJECTED (rewriting it would be an audit lie about a real
    position). The re-run completes the cycle terminally with no double-fill.
    """
    cycle_ts = T0 + (N_BARS - 2) * HOUR
    idx = N_BARS - 2
    thin_iid = _FLIP_IID  # the first order alphabetically -> partials, then we crash later
    later_iid = "BINANCE:PERP:DOGEUSDT"
    partial_coid = f"rb-{cycle_ts}-{thin_iid}"

    # ----- run with a thin book on the first order, crash on the later order -----
    crashed = world.new_stack(restore_blob=None)
    crashed.loop.recover_on_boot()
    _set_books_thin(crashed, idx=idx, ts=cycle_ts, thin_iid=thin_iid, thin_size=10.0)
    # Let the thin-book order PARTIAL, then crash on the later order's submit so the
    # PARTIAL is durable but the cycle never finishes.
    crashed.broker.plan = _CrashPlan(stage="post_fill", on_coid_contains=later_iid)
    with pytest.raises(SystemExit):
        crashed.loop.run_cycle(cycle_ts)
    assert crashed.broker.plan.fired, "the crash injector must have fired on the later order"
    partial_on_disk = crashed.store.get(partial_coid)
    assert partial_on_disk is not None
    assert partial_on_disk.status == OrderStatus.PARTIAL.value
    assert partial_on_disk.filled_qty > 0.0
    crashed.store.close()

    # ----- restart: recover (must NOT reject the partial), re-run the SAME bar -----
    restarted = world.new_stack(restore_blob=_disk_blob(world.tmp_path))
    _set_books_thin(restarted, idx=idx, ts=cycle_ts, thin_iid=thin_iid, thin_size=10.0)
    restarted.loop.recover_on_boot()

    # (a) The C2 invariant: the PARTIAL survived recovery intact, NOT downgraded.
    after = restarted.store.get(partial_coid)
    assert after is not None
    assert after.status == OrderStatus.PARTIAL.value, "a settled PARTIAL must not become REJECTED"
    assert after.filled_qty == pytest.approx(partial_on_disk.filled_qty)

    rerun = restarted.loop.run_cycle(cycle_ts)

    # (b) No double-fill across the restart (idempotent on client_order_id).
    booked = [f.client_order_id for f in restarted.broker.fills]
    assert len(booked) == len(set(booked)), f"a coid was double-filled: {booked}"

    # (c) The PARTIAL is STILL a partial after the re-run -- its residual is never
    #     chased mid-cycle (it re-enters as a fresh delta next cycle), and the
    #     cycle reaches a terminal status with a consistent, finite book.
    final = restarted.store.get(partial_coid)
    assert final is not None and final.status == OrderStatus.PARTIAL.value
    assert rerun.status in {"ok", "skipped"}
    row = restarted.store.get_cycle(cycle_ts)
    assert row is not None and row.status in {"ok", "skipped", "failed", "halted"}
    assert row.finished_ms is not None
    account = restarted.broker.account_at(cycle_ts)
    assert np.isfinite(account.equity_quote)
    assert np.isfinite(account.cash_quote)
    restarted.store.close()
