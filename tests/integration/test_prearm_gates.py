"""Phase-8 PRE-ARM gate tests (C3/C5/C7/C10): real-money readiness, execution layer.

Each test pins one hazard the pre-arm gates close, asserting the FIXED behavior
under the exact condition that used to be wrong. These touch ONLY the execution /
live layer (broker, reconciler, store, loop recovery); the crypto
feature/signal/covariance path is untouched.

- C3  -- ``Reconciler`` marks broker equity via ``account_at(as_of)`` (the reconcile
         instant), not the last fill's timestamp, so equity is compared at the same
         time as the positions it is compared against.
- C5  -- boot recovery calls ``broker.fetch_order(coid)`` for every SUBMITTED-but-
         unfilled intent and ingests any returned :class:`Fill` idempotently
         (mid-submit-crash recovery).
- C7  -- the recovery book-sync reconciles FIRST against broker truth and snapshots
         only when there are real adoptions, keyed at ``as_of`` (no tautological
         write-then-compare).
- C10a -- ``PaperBroker.submit`` records the idempotency ack BEFORE booking the fill,
         so a crash in that window cannot double-fill on replay.
- C10b -- ``TradingStore`` opens the irreplaceable ledger with
         ``PRAGMA synchronous=FULL`` (durable across OS crash / power loss).
- C10c -- the reconciler's equity ladder is two-tier: 0.5% drift -> WARN (no halt),
         2% drift -> HALT (``ReconciliationError``).

Fully offline and deterministic (real PaperBroker walks a canned book; no network).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from alphaforge.config.settings import Settings
from alphaforge.core.errors import ReconciliationError
from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms
from alphaforge.core.types import (
    AccountState,
    AssetClass,
    Fill,
    Liquidity,
    MarketType,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from alphaforge.costs import TransactionCostModel
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.order_manager import OrderManager
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import (
    EquityStatus,
    Reconciler,
    ReconStatus,
    ReconTolerance,
)
from alphaforge.live.alerts import AlertLevel, LogAlerter
from alphaforge.live.loop import LiveLoop
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
T0 = LISTED + 1000 * HOUR
BTC = "BINANCE:PERP:BTCUSDT"


# --------------------------------------------------------------------------- helpers


def _instrument(iid: str = BTC) -> Instrument:
    symbol = iid.split(":")[2]
    return Instrument(
        instrument_id=iid,
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


def _book(*, ts: Ms = T0, mid: float = 100.5) -> OrderBook:
    half = 0.5
    return OrderBook(
        instrument_id=BTC,
        bids=((mid - half, 100.0),),
        asks=((mid + half, 100.0),),
        ts=ts,
    )


def _book_source(*, mid: float = 100.5) -> FakeOrderBookSource:
    src = FakeOrderBookSource()
    src.set_book(_book(mid=mid))
    return src


def _paper_broker(src: FakeOrderBookSource | None = None) -> PaperBroker:
    source = src if src is not None else _book_source()
    return PaperBroker(
        {BTC: _instrument()}, TransactionCostModel(), book_source=source, initial_cash=1e6
    )


def _order(coid: str, *, qty: float = 1.0, decision_ts: Ms = T0) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        instrument_id=BTC,
        side=Side.BUY,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=False,
        decision_ts=decision_ts,
        decision_price=100.5,
        reason="rebalance",
    )


def _fill(coid: str, *, qty: float = 1.0, price: float = 100.5, ts: Ms = T0) -> Fill:
    return Fill(
        client_order_id=coid,
        instrument_id=BTC,
        side=Side.BUY,
        qty=qty,
        price=price,
        fee_quote=qty * price * 5e-4,
        liquidity=Liquidity.TAKER,
        ts=ts,
    )


# --------------------------------------------------------------------------- C3


class _MarkRecordingBroker(PaperBroker):
    """A PaperBroker that records the ``ts`` every ``account_at`` is marked at."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.marked_at: list[Ms] = []

    def account_at(self, ts: Ms) -> AccountState:
        self.marked_at.append(ts)
        return super().account_at(ts)


def test_c3_account_at_timestamp_alignment(tmp_path: Path) -> None:
    """C3: reconcile marks broker equity at ``as_of`` -- NOT at the last fill's ts.

    A fill lands at ``T0`` (the fill ts), but the reconcile happens a full bar
    LATER at ``as_of``. The OLD code marked equity via ``account()`` (which uses
    ``fills[-1].ts == T0``); the FIX marks via ``account_at(as_of)``. We assert
    the broker was asked to mark equity at exactly ``as_of`` and never at the
    stale fill timestamp, so equity is valued at the same instant as the
    positions it is compared against.
    """
    broker = _MarkRecordingBroker(
        {BTC: _instrument()}, TransactionCostModel(), book_source=_book_source(), initial_cash=1e6
    )
    as_of = T0 + HOUR  # the reconcile instant, a bar AFTER the fill
    with TradingStore(tmp_path / "trading.sqlite") as store:
        om = OrderManager(broker, store, sleeper=lambda _s: None, backoff_base_s=1e-9)
        om.place([_order("af-c1-btc", qty=1.0)], cycle_ts=T0, now=T0)
        account = broker.account_at(as_of)
        store.snapshot_positions(as_of, account.positions)
        store.snapshot_equity(as_of, account)

        broker.marked_at.clear()
        report = Reconciler(broker, store).reconcile(as_of=as_of)

    assert report.ok is True
    # The reconcile MUST have marked broker equity at the reconcile instant.
    assert as_of in broker.marked_at
    # And it must NEVER fall back to the stale last-fill ts (T0) for that mark.
    assert T0 not in broker.marked_at


# --------------------------------------------------------------------------- harness (C5/C7)


class _StubSeam:
    """A do-nothing seam usable for updater/watermark/factories in recovery-only tests."""

    def update(self, *, as_of: Ms) -> object:
        del as_of
        return None

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        del instrument_ids, as_of
        return 1 << 62  # always fresh

    def __call__(self, *args: object, **kwargs: object) -> object:  # cost/ctx factory stub
        del args, kwargs
        return None


class _Instruments:
    def __init__(self, instruments: Mapping[str, Instrument]) -> None:
        self._instruments = dict(instruments)

    def __call__(self, cycle_ts: Ms) -> Mapping[str, Instrument]:
        del cycle_ts
        return dict(self._instruments)


class _Strategy:
    def on_bar_close(self, ctx: object) -> Mapping[str, float]:
        del ctx
        return {}


class _RecordingAlerter(LogAlerter):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[AlertLevel, str]] = []

    def alert(self, level: AlertLevel, message: str) -> bool:
        self.records.append((level, message))
        return super().alert(level, message)


def _build_loop(
    tmp_path: Path,
    *,
    broker: PaperBroker,
    store: TradingStore,
    alerter: LogAlerter | None = None,
    clock_ms: Ms = T0 + HOUR,
) -> LiveLoop:
    """A LiveLoop over the given real broker/store + inert decision/data seams.

    Only the boot-recovery path is exercised in these tests, so the strategy /
    cost / context seams are inert stubs; the broker, store, reconciler, and risk
    objects are real.
    """
    settings = Settings()
    cost_model = TransactionCostModel()
    seam = _StubSeam()
    ladder = DrawdownLadder(
        dd_half_frac=abs(settings.risk.dd_halve_gross),
        dd_flat_frac=abs(settings.risk.dd_flat_halt),
    )
    return LiveLoop(
        settings,
        store=store,
        broker=broker,
        order_manager=OrderManager(broker, store),
        reconciler=Reconciler(broker, store),
        strategy=_Strategy(),  # type: ignore[arg-type]
        pretrade=PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model),
        ladder=ladder,
        staleness=StalenessBreaker(max_bars=settings.risk.staleness_max_bars),
        kill=KillSwitch(tmp_path / "KILL"),
        alerter=alerter if alerter is not None else LogAlerter(),
        updater=seam,
        watermark=seam,
        cost_inputs_factory=seam,  # type: ignore[arg-type]
        ctx_factory=seam,  # type: ignore[arg-type]
        instruments_factory=_Instruments({BTC: _instrument()}),
        clock=lambda: clock_ms,
    )


# --------------------------------------------------------------------------- C5


class _FetchOrderBroker(PaperBroker):
    """A PaperBroker whose ``fetch_order`` returns a venue fill for a chosen coid.

    Models the live-broker hazard PaperBroker itself never has: the order WAS
    executed at the venue during the submit->persist crash window, so a query by
    ``client_order_id`` finds it even though nothing is in our state yet.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._lost: dict[str, Fill] = {}
        self.fetch_calls: list[str] = []

    def arm_lost_fill(self, fill: Fill) -> None:
        self._lost[fill.client_order_id] = fill

    def fetch_order(self, client_order_id: str) -> Fill | None:
        self.fetch_calls.append(client_order_id)
        return self._lost.get(client_order_id)


def test_c5_fetch_order_on_boot(tmp_path: Path) -> None:
    """C5: a SUBMITTED-but-unpersisted intent whose fill the venue holds is recovered.

    Setup: the store has a SUBMITTED intent at ``filled_qty == 0`` and NO fill
    row (the classic 'submit landed, persist crashed' window). The broker's
    ``fetch_order`` reports the venue executed it. On boot the loop must query by
    coid, ingest the fill idempotently (store advances to FILLED, broker books
    the position), and reconcile cleanly -- never mark it REJECTED.
    """
    src = _book_source()
    broker = _FetchOrderBroker(
        {BTC: _instrument()}, TransactionCostModel(), book_source=src, initial_cash=1e6
    )
    coid = "af-c5-btc"
    lost = _fill(coid, qty=1.0, ts=T0)
    broker.arm_lost_fill(lost)

    store = TradingStore(tmp_path / "trading.sqlite")
    # Open + finish a prior cycle so the store is NOT a fresh boot, and seed a
    # book snapshot consistent with a flat pre-fill book.
    store.start_cycle(T0, now=T0)
    store.record_intent(_order(coid, qty=1.0), T0, now=T0)
    store.mark_submitted(coid, now=T0)
    store.finish_cycle(T0, "ok", "submitted, persist crashed", now=T0)
    store.snapshot_equity(T0, broker.account_at(T0))  # flat book, equity == cash
    store.snapshot_positions(T0, ())

    loop = _build_loop(tmp_path, broker=broker, store=store, clock_ms=T0 + HOUR)
    loop.recover_on_boot()

    assert coid in broker.fetch_calls, "boot must query the venue by client_order_id"
    rec = store.get(coid)
    assert rec is not None and rec.status == OrderStatus.FILLED.value
    assert len(store.fills_for(coid)) == 1, "the recovered fill must be persisted exactly once"
    # The broker booked the position from the recovered fill.
    assert any(abs(p.qty - 1.0) < 1e-9 for p in broker.positions())

    # Idempotent: a second boot re-discovers nothing new and books no 2nd fill.
    loop.recover_on_boot()
    assert len(store.fills_for(coid)) == 1
    store.close()


def test_c5_paper_fetch_order_returns_none() -> None:
    """C5: the plain PaperBroker has no lost-fill window -- fetch_order is always None."""
    assert _paper_broker().fetch_order("af-anything") is None


# --------------------------------------------------------------------------- C7


def test_c7_reconcile_before_snapshot(tmp_path: Path) -> None:
    """C7: recovery adopts broker truth via a reconcile probe, keyed at ``as_of``.

    A mid-batch crash leaves a durable store fill the restored broker blob has
    not seen and an equity/position snapshot that predates it. On boot the loop
    replays the durable fill onto the broker, then -- reconcile-FIRST -- adopts
    that broker truth into the book by snapshotting at ``as_of`` (the clock), NOT
    at ``floor_bar(now)``. We assert the adopted snapshot is keyed at ``as_of``
    and the gate reconcile then agrees.
    """
    src = _book_source()
    broker = _paper_broker(src)
    coid = "af-c7-btc"
    as_of = T0 + 5 * HOUR  # deliberately not bar-floored-equal to a prior cycle

    store = TradingStore(tmp_path / "trading.sqlite")
    # A prior committed cycle exists (so this is not a fresh boot), with a flat
    # book snapshot -- the snapshot that PREDATES the durable fill below.
    store.start_cycle(T0, now=T0)
    store.record_intent(_order(coid, qty=1.0), T0, now=T0)
    store.mark_submitted(coid, now=T0)
    store.snapshot_equity(T0, broker.account_at(T0))  # equity == initial cash, flat
    store.snapshot_positions(T0, ())
    # The fill is DURABLE in the store but the broker blob never captured it
    # (the cycle died before its end-of-cycle snapshot). mark_filled advances the
    # order and records the fill row; the broker is still flat.
    store.mark_filled(_fill(coid, qty=1.0, ts=T0), now=T0)
    store.finish_cycle(T0, "ok", "fill durable, blob stale", now=T0)
    assert not broker.positions(), "precondition: broker book lags the durable fill"

    loop = _build_loop(tmp_path, broker=broker, store=store, clock_ms=as_of)
    loop.recover_on_boot()

    # The book was adopted from broker truth and keyed at as_of (NOT floor_bar).
    curve = store.equity_curve()
    assert curve[-1][0] == as_of, "the adopted snapshot must be keyed at as_of"
    adopted = store.positions_at(as_of)
    assert any(abs(p.qty - 1.0) < 1e-9 for p in adopted), "broker truth must be adopted into book"
    # And the gate reconcile now agrees (no spurious halt, no tautology).
    report = Reconciler(broker, store).reconcile(as_of=as_of, resolve_inflight=False)
    assert report.ok is True
    assert all(r.status is ReconStatus.AGREE for r in report.instruments)
    store.close()


def test_c7_clean_restart_writes_no_snapshot(tmp_path: Path) -> None:
    """C7: when the book already agrees, recovery writes NOTHING (no tautological write).

    A clean restart with an up-to-date snapshot must leave the book untouched --
    the reconcile-first probe finds agreement, so no new snapshot row is written
    and the gate reconcile is a genuine comparison rather than a rubber stamp.
    """
    src = _book_source()
    broker = _paper_broker(src)
    coid = "af-c7clean-btc"

    store = TradingStore(tmp_path / "trading.sqlite")
    om = OrderManager(broker, store, sleeper=lambda _s: None, backoff_base_s=1e-9)
    store.start_cycle(T0, now=T0)
    om.place([_order(coid, qty=1.0)], cycle_ts=T0, now=T0)
    account = broker.account_at(T0)
    store.snapshot_positions(T0, account.positions)
    store.snapshot_equity(T0, account)
    store.finish_cycle(T0, "ok", "clean", now=T0)
    rows_before = len(store.equity_curve())

    loop = _build_loop(tmp_path, broker=broker, store=store, clock_ms=T0 + HOUR)
    loop.recover_on_boot()

    assert len(store.equity_curve()) == rows_before, "a clean restart must add no snapshot row"
    store.close()


# --------------------------------------------------------------------------- C10a


class _AckOrderObservingBroker(PaperBroker):
    """A PaperBroker that records whether the ack was present when ``_book_fill`` ran."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.ack_present_at_book: bool | None = None

    def _book_fill(self, order, inst, book, walked):  # type: ignore[no-untyped-def]
        # C10a: by the time the fill is booked, the idempotency ack MUST already
        # be recorded -- otherwise a crash here would, on replay, re-walk and
        # double-fill.
        self.ack_present_at_book = order.client_order_id in self._state.acks
        super()._book_fill(order, inst, book, walked)


def test_c10a_ack_before_book(tmp_path: Path) -> None:
    """C10a: the idempotency ack is recorded BEFORE the fill is booked."""
    broker = _AckOrderObservingBroker(
        {BTC: _instrument()}, TransactionCostModel(), book_source=_book_source(), initial_cash=1e6
    )
    ack = broker.submit(_order("af-c10a-btc", qty=1.0))
    assert ack.accepted is True
    assert broker.ack_present_at_book is True, "ack must be in acks before _book_fill runs"
    del tmp_path


# --------------------------------------------------------------------------- C10b


def test_c10b_synchronous_full(tmp_path: Path) -> None:
    """C10b: the trading ledger is opened with PRAGMA synchronous=FULL (durable).

    SQLite reports synchronous as an integer: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA.
    The irreplaceable order/fill ledger must be FULL (2) so a committed fill
    survives an OS crash / power loss, not merely a process crash.
    """
    with TradingStore(tmp_path / "trading.sqlite") as store:
        (level,) = store._conn.execute("PRAGMA synchronous").fetchone()
    assert int(level) == 2, f"expected synchronous=FULL (2), got {level!r}"


# --------------------------------------------------------------------------- C10c


class _FixedEquityBroker:
    """A minimal BrokerView whose equity is fixed -- drives the equity ladder directly."""

    def __init__(self, equity: float) -> None:
        self._equity = equity

    def positions(self) -> list[Position]:
        return []

    def account(self) -> AccountState:
        return self.account_at(T0)

    def account_at(self, ts: Ms) -> AccountState:
        return AccountState(
            equity_quote=self._equity, cash_quote=self._equity, positions=(), ts=ts
        )

    def open_orders(self) -> list[object]:
        return []

    @property
    def fills(self) -> list[Fill]:
        return []


class _FixedEquityStore:
    """A minimal ReconStore with a fixed book equity and no positions/intents."""

    def __init__(self, equity: float) -> None:
        self._equity = equity

    def open_intents(self) -> list[object]:
        return []

    def mark_filled(self, fill: Fill, *, now: Ms, audit: object | None = None) -> None:
        raise AssertionError("not exercised")

    def mark_rejected(self, client_order_id: str, *, now: Ms) -> None:
        raise AssertionError("not exercised")

    def fills_for(self, client_order_id: str) -> Sequence[object]:
        return ()

    def positions_at(self, cycle_ts: Ms) -> tuple[Position, ...]:
        return ()

    def equity_curve(self, start: Ms | None = None) -> list[tuple[Ms, float, float, int]]:
        return [(T0, self._equity, self._equity, 0)]


def _equity_report(book_equity: float, broker_equity: float):  # type: ignore[no-untyped-def]
    recon = Reconciler(
        _FixedEquityBroker(broker_equity),  # type: ignore[arg-type]
        _FixedEquityStore(book_equity),  # type: ignore[arg-type]
    )
    return recon


def test_c10c_equity_warn_halt_ladder() -> None:
    """C10c: equity ladder is two-tier -- 0.5% drift WARNs (no halt), 2% drift HALTs."""
    base = 1_000_000.0

    # (a) sub-0.5% drift -> OK, trades silently.
    ok_report = _equity_report(base, base * 1.002).reconcile(as_of=T0, resolve_inflight=False)
    assert ok_report.equity_status is EquityStatus.OK
    assert ok_report.ok is True

    # (b) 1% drift (between 0.5% and 2%) -> WARN, but DOES NOT raise, ok stays True.
    warn_report = _equity_report(base, base * 1.01).reconcile(as_of=T0, resolve_inflight=False)
    assert warn_report.equity_status is EquityStatus.WARN
    assert warn_report.ok is True
    assert warn_report.equity_within is False  # beyond the 0.5% WARN bound

    # (c) 3% drift (beyond 2%) -> HALT: ReconciliationError is raised.
    with pytest.raises(ReconciliationError):
        _equity_report(base, base * 1.03).reconcile(as_of=T0, resolve_inflight=False)

    # The classifier itself agrees with the ladder tiers.
    tol = ReconTolerance()
    assert tol.equity_status(base, base * 1.002) is EquityStatus.OK
    assert tol.equity_status(base, base * 1.01) is EquityStatus.WARN
    assert tol.equity_status(base, base * 1.03) is EquityStatus.HALT


def test_c10c_warn_does_not_raise_but_alerts_on_boot(tmp_path: Path) -> None:
    """C10c: a WARN-tier equity drift on boot recovery alerts WARN but never halts."""
    src = _book_source()
    broker = _paper_broker(src)
    coid = "af-c10c-btc"

    store = TradingStore(tmp_path / "trading.sqlite")
    om = OrderManager(broker, store, sleeper=lambda _s: None, backoff_base_s=1e-9)
    store.start_cycle(T0, now=T0)
    om.place([_order(coid, qty=1.0)], cycle_ts=T0, now=T0)
    account = broker.account_at(T0)
    store.snapshot_positions(T0, account.positions)
    # Seed a book equity ~1% BELOW broker truth -> a WARN-tier drift (>0.5%, <2%).
    drifted = AccountState(
        equity_quote=account.equity_quote * 0.99,
        cash_quote=account.cash_quote * 0.99,
        positions=account.positions,
        ts=T0,
    )
    store.snapshot_equity(T0, drifted)
    store.finish_cycle(T0, "ok", "warn drift", now=T0)

    alerter = _RecordingAlerter()
    loop = _build_loop(tmp_path, broker=broker, store=store, alerter=alerter, clock_ms=T0 + HOUR)
    # Must NOT raise (WARN, not HALT).
    loop.recover_on_boot()
    assert any(
        lvl is AlertLevel.WARN and "equity WARN" in msg for lvl, msg in alerter.records
    ), "a WARN-tier equity drift must alert WARN on boot"
    store.close()
