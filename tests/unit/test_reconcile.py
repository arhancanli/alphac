"""Unit tests for alphaforge.execution.reconcile (Reconciler).

Load-bearing guarantees under test (execDesign.md sections 8.4, 9.3):

- In-flight resolution: a non-terminal stored intent is resolved against broker
  truth -- left alone if still working, fills ingested if the broker filled it
  while we were down, marked REJECTED if the submit never landed.
- Position classification: AGREE / DIVERGENT / ORPHAN / MISSING over the union of
  broker and book positions, with the documented quantity tolerance.
- Equity comparison: within tolerance -> ok; beyond tolerance -> halt.
- Beyond-tolerance position OR equity divergence raises ReconciliationError (the
  loop halts trading and alerts).
- Crash recovery: a SUBMITTED-but-unconfirmed intent is driven terminal on
  reconcile, and the integration path runs against the real PaperBroker +
  TradingStore.

All fakes are in-memory; deterministic and offline (the real PaperBroker walks a
canned FakeOrderBookSource, no network).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from alphaforge.core.errors import ReconciliationError
from alphaforge.core.instruments import Instrument
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
from alphaforge.execution.broker import OpenOrder, OrderBook
from alphaforge.execution.order_manager import OrderManager
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.execution.reconcile import (
    BrokerView,
    InflightResolution,
    Reconciler,
    ReconStatus,
    ReconStore,
    ReconTolerance,
)
from alphaforge.live.store import OrderRecord, TradingStore

T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z (1h-aligned)
LISTED = 1_577_836_800_000
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"


# --------------------------------------------------------------------------- fakes


def _intent(
    coid: str,
    iid: str,
    status: OrderStatus,
    *,
    qty: float = 1.0,
    filled_qty: float = 0.0,
) -> OrderRecord:
    """An OrderRecord standing in for a stored intent at ``status``.

    ``filled_qty`` is the realized base quantity already on the row: 0.0 for a
    NEW/SUBMITTED intent the broker never filled, > 0 for a settled PARTIAL.
    """
    return OrderRecord(
        client_order_id=coid,
        cycle_ts=T0,
        instrument_id=iid,
        side=Side.BUY,
        order_type=OrderType.MARKET.value,
        qty=qty,
        reduce_only=False,
        status=status.value,
        filled_qty=filled_qty,
        avg_fill_price=101.0 if filled_qty > 0.0 else None,
        decision_ts=T0,
        decision_price=101.0,
        reason="rebalance",
        created_ms=T0,
        updated_ms=T0,
    )


def _fill(coid: str, iid: str, *, qty: float, price: float = 101.0) -> Fill:
    return Fill(
        client_order_id=coid,
        instrument_id=iid,
        side=Side.BUY,
        qty=qty,
        price=price,
        fee_quote=qty * price * 5e-4,
        liquidity=Liquidity.TAKER,
        ts=T0,
    )


def _pos(iid: str, qty: float, *, avg: float = 101.0) -> Position:
    return Position(instrument_id=iid, qty=qty, avg_entry_price=avg, opened_ts=T0)


@dataclass(frozen=True, slots=True)
class _FillRow:
    """Minimal fills_for row: only ``fill`` is read by the reconciler."""

    fill: Fill


class FakeBroker:
    """Authoritative broker double: positions, equity, open orders, fill log."""

    def __init__(
        self,
        *,
        positions: Sequence[Position] = (),
        equity: float = 1_000_000.0,
        open_orders: Sequence[OpenOrder] = (),
        fills: Sequence[Fill] = (),
    ) -> None:
        self._positions = list(positions)
        self._equity = equity
        self._open = list(open_orders)
        self._fills = list(fills)

    def positions(self) -> list[Position]:
        return list(self._positions)

    def account(self) -> AccountState:
        return AccountState(
            equity_quote=self._equity,
            cash_quote=self._equity,
            positions=tuple(self._positions),
            ts=T0,
        )

    def open_orders(self) -> list[OpenOrder]:
        return list(self._open)

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)


class FakeStore:
    """In-memory ReconStore: intents, fill ingestion, and a book snapshot."""

    def __init__(
        self,
        *,
        intents: Sequence[OrderRecord] = (),
        positions: Sequence[Position] = (),
        equity: float = 1_000_000.0,
        recorded_fills: dict[str, int] | None = None,
    ) -> None:
        self._intents = {o.client_order_id: o for o in intents}
        self._positions = tuple(positions)
        self._equity = equity
        # client_order_id -> number of fills already on file (for dedup).
        self._fill_counts: dict[str, int] = dict(recorded_fills or {})
        self.ingested: list[Fill] = []
        self.rejected: list[str] = []

    def open_intents(self) -> list[OrderRecord]:
        terminal = {
            OrderStatus.FILLED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.CANCELED.value,
        }
        return [o for o in self._intents.values() if o.status not in terminal]

    def mark_filled(self, fill: Fill, *, now: int, audit: object | None = None) -> None:
        self.ingested.append(fill)
        self._fill_counts[fill.client_order_id] = self._fill_counts.get(fill.client_order_id, 0) + 1
        # The store advances the order; emulate by driving it to FILLED.
        rec = self._intents.get(fill.client_order_id)
        if rec is not None:
            self._intents[fill.client_order_id] = _replace_status(rec, OrderStatus.FILLED)

    def mark_rejected(self, client_order_id: str, *, now: int) -> None:
        self.rejected.append(client_order_id)
        rec = self._intents.get(client_order_id)
        if rec is not None:
            self._intents[client_order_id] = _replace_status(rec, OrderStatus.REJECTED)

    def fills_for(self, client_order_id: str) -> Sequence[object]:
        return [_FillRow(_fill(client_order_id, BTC, qty=1.0))] * self._fill_counts.get(
            client_order_id, 0
        )

    def positions_at(self, cycle_ts: int) -> tuple[Position, ...]:
        return self._positions

    def equity_curve(self, start: int | None = None) -> list[tuple[int, float, float, int]]:
        # One row so the reconciler has a "latest" book snapshot to read.
        return [(T0, self._equity, self._equity, len(self._positions))]


def _replace_status(rec: OrderRecord, status: OrderStatus) -> OrderRecord:
    return OrderRecord(
        client_order_id=rec.client_order_id,
        cycle_ts=rec.cycle_ts,
        instrument_id=rec.instrument_id,
        side=rec.side,
        order_type=rec.order_type,
        qty=rec.qty,
        reduce_only=rec.reduce_only,
        status=status.value,
        filled_qty=rec.filled_qty,
        avg_fill_price=rec.avg_fill_price,
        decision_ts=rec.decision_ts,
        decision_price=rec.decision_price,
        reason=rec.reason,
        created_ms=rec.created_ms,
        updated_ms=rec.updated_ms,
    )


def _open_order(coid: str, iid: str) -> OpenOrder:
    return OpenOrder(
        client_order_id=coid,
        broker_order_id=f"bx-{coid}",
        instrument_id=iid,
        side=Side.BUY,
        qty=1.0,
        filled_qty=0.0,
        status=OrderStatus.NEW,
    )


# --------------------------------------------------------------------------- real fixtures


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


def _paper_broker() -> PaperBroker:
    inst = _instrument()
    src = FakeOrderBookSource()
    src.set_book(
        OrderBook(instrument_id=BTC, bids=((100.0, 100.0),), asks=((101.0, 100.0),), ts=T0)
    )
    return PaperBroker({BTC: inst}, TransactionCostModel(), book_source=src, initial_cash=1e6)


def _order(coid: str, *, qty: float = 1.0) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        instrument_id=BTC,
        side=Side.BUY,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=False,
        decision_ts=T0,
        decision_price=101.0,
        reason="rebalance",
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_fakes_satisfy_protocols() -> None:
    """FakeBroker / FakeStore structurally satisfy the runtime-checkable Protocols."""
    assert isinstance(FakeBroker(), BrokerView)
    assert isinstance(FakeStore(), ReconStore)


def test_real_surfaces_satisfy_protocols(tmp_path: Path) -> None:
    """The shipped PaperBroker and TradingStore satisfy the Reconciler Protocols."""
    assert isinstance(_paper_broker(), BrokerView)
    with TradingStore(tmp_path / "trading.sqlite") as store:
        assert isinstance(store, ReconStore)


# ---------------------------------------------------------------------------
# Position classification
# ---------------------------------------------------------------------------


def test_agree_when_positions_match() -> None:
    """Equal signed qty within tolerance classifies AGREE and ok stays True."""
    broker = FakeBroker(positions=[_pos(BTC, 2.0)])
    store = FakeStore(positions=[_pos(BTC, 2.0)])
    report = Reconciler(broker, store).reconcile(as_of=T0)
    assert report.ok is True
    assert len(report.instruments) == 1
    assert report.instruments[0].status is ReconStatus.AGREE
    assert report.adoptions == ()


def test_divergent_both_hold_mismatched_qty() -> None:
    """Both sides hold the instrument but differ beyond tolerance -> DIVERGENT, halt."""
    broker = FakeBroker(positions=[_pos(BTC, 2.0)])
    store = FakeStore(positions=[_pos(BTC, 1.0)])
    with pytest.raises(ReconciliationError):
        Reconciler(broker, store).reconcile(as_of=T0)


def test_orphan_broker_only() -> None:
    """Broker holds a position the book does not -> ORPHAN, halt; status named in error."""
    broker = FakeBroker(positions=[_pos(BTC, 3.0)])
    store = FakeStore(positions=[])
    with pytest.raises(ReconciliationError, match=ReconStatus.ORPHAN.value):
        Reconciler(broker, store).reconcile(as_of=T0)


def test_missing_book_only() -> None:
    """Book holds a position the broker does not -> MISSING, halt."""
    broker = FakeBroker(positions=[])
    store = FakeStore(positions=[_pos(BTC, 3.0)])
    with pytest.raises(ReconciliationError, match=ReconStatus.MISSING.value):
        Reconciler(broker, store).reconcile(as_of=T0)


def test_tiny_qty_drift_within_tolerance_agrees() -> None:
    """A sub-tolerance qty drift (0.05% < 0.1%) classifies AGREE, ok True."""
    broker = FakeBroker(positions=[_pos(BTC, 1000.0)])
    store = FakeStore(positions=[_pos(BTC, 1000.5)])  # 0.05% drift
    report = Reconciler(broker, store).reconcile(as_of=T0)
    assert report.ok is True
    assert report.instruments[0].status is ReconStatus.AGREE


def test_agree_instrument_does_not_halt_alongside_clean_book() -> None:
    """An AGREE instrument with matching equity yields a clean, no-raise report.

    The classification machinery (AGREE vs the divergent trio) is exercised
    end-to-end on the happy path; the divergent classifications are asserted via
    the halt-message tests above, which is the only observable surface when the
    reconciler refuses to trade.
    """
    broker = FakeBroker(positions=[_pos(BTC, 1.0), _pos(ETH, 5.0)], equity=1e6)
    store = FakeStore(positions=[_pos(BTC, 1.0), _pos(ETH, 5.0)], equity=1e6)
    report = Reconciler(broker, store).reconcile(as_of=T0)
    assert report.ok is True
    assert {r.status for r in report.instruments} == {ReconStatus.AGREE}
    assert report.adoptions == ()


# ---------------------------------------------------------------------------
# Equity comparison
# ---------------------------------------------------------------------------


def test_equity_within_tolerance_ok() -> None:
    """A sub-0.5% equity drift keeps ok True."""
    broker = FakeBroker(equity=1_000_000.0)
    store = FakeStore(equity=1_002_000.0)  # 0.2% drift
    report = Reconciler(broker, store).reconcile(as_of=T0)
    assert report.equity_within is True and report.ok is True


def test_equity_divergence_beyond_tolerance_raises() -> None:
    """A >0.5% equity divergence raises ReconciliationError (the loop halts)."""
    broker = FakeBroker(equity=1_000_000.0)
    store = FakeStore(equity=1_050_000.0)  # 5% drift
    with pytest.raises(ReconciliationError):
        Reconciler(broker, store).reconcile(as_of=T0)


# ---------------------------------------------------------------------------
# In-flight resolution (crash recovery)
# ---------------------------------------------------------------------------


def test_inflight_left_alone_when_still_working() -> None:
    """A SUBMITTED intent still in broker.open_orders() is left in flight."""
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED)
    broker = FakeBroker(open_orders=[_open_order("af-c1-btc", BTC)])
    store = FakeStore(intents=[intent])
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert len(res) == 1
    r: InflightResolution = res[0]
    assert r.found_open is True
    assert r.resolved_status == OrderStatus.SUBMITTED.value
    assert store.rejected == [] and store.ingested == []


def test_inflight_broker_fill_ingested() -> None:
    """A SUBMITTED intent the broker has since filled gets its fill ingested -> FILLED."""
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED, qty=1.0)
    broker = FakeBroker(fills=[_fill("af-c1-btc", BTC, qty=1.0)])
    store = FakeStore(intents=[intent])  # store has 0 fills on file
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert len(store.ingested) == 1
    assert res[0].broker_fills_ingested == 1
    assert res[0].resolved_status == OrderStatus.FILLED.value
    assert store.rejected == []


def test_inflight_dedups_broker_fills_already_on_file() -> None:
    """A broker fill already recorded is NOT re-ingested (only the unrecorded tail is).

    Two broker fills, one already on file: only the second is written through, so
    a partial-then-resume crash recovery never double-books the first.
    """
    intent = _intent("af-c1-btc", BTC, OrderStatus.PARTIAL, qty=2.0)
    broker = FakeBroker(fills=[_fill("af-c1-btc", BTC, qty=1.0), _fill("af-c1-btc", BTC, qty=1.0)])
    store = FakeStore(intents=[intent], recorded_fills={"af-c1-btc": 1})  # 1 on file
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert len(store.ingested) == 1  # only the unrecorded tail fill
    assert res[0].broker_fills_ingested == 1
    assert res[0].resolved_status == OrderStatus.FILLED.value
    assert store.rejected == []


def test_inflight_never_landed_rejected() -> None:
    """A SUBMITTED intent neither working nor with any broker fill is REJECTED."""
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED)
    broker = FakeBroker()  # no open orders, no fills
    store = FakeStore(intents=[intent])
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert store.rejected == ["af-c1-btc"]
    assert res[0].resolved_status == OrderStatus.REJECTED.value
    assert res[0].found_open is False


def test_inflight_settled_partial_survives_not_rejected() -> None:
    """A stored PARTIAL (filled_qty > 0) the broker reports no new fills for is NOT rejected.

    This is the C2 invariant: resolve_in_flight runs on every non-fresh boot, not
    only post-crash. A legitimately PARTIAL order whose residual was deliberately
    not chased (the broker really holds the filled quantity) must survive a routine
    restart intact -- rewriting it to REJECTED would be an audit lie about a real
    position and would fire on the first thin-book partial. The PARTIAL status and
    filled_qty are preserved; mark_rejected is never called.
    """
    intent = _intent("af-c1-btc", BTC, OrderStatus.PARTIAL, qty=2.0, filled_qty=1.0)
    broker = FakeBroker()  # no open order, no fills the store has not seen
    store = FakeStore(intents=[intent])
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert store.rejected == []  # NEVER downgraded to REJECTED
    assert store.ingested == []  # nothing new to ingest
    assert len(res) == 1
    assert res[0].resolved_status == OrderStatus.PARTIAL.value
    assert res[0].found_open is False
    assert res[0].broker_fills_ingested == 0
    # The stored row is untouched: status PARTIAL, filled_qty preserved.
    surviving = store.open_intents()
    assert len(surviving) == 1
    assert surviving[0].status == OrderStatus.PARTIAL.value
    assert surviving[0].filled_qty == 1.0


def test_inflight_settled_partial_idempotent_across_reboots() -> None:
    """A survived PARTIAL is left untouched on every subsequent resolve pass.

    Because the order stays non-terminal (PARTIAL) it reappears in open_intents on
    the next boot; the resolver must keep leaving it alone (no reject, no churn) so
    repeated routine restarts never corrupt a real partial position.
    """
    intent = _intent("af-c1-btc", BTC, OrderStatus.PARTIAL, qty=2.0, filled_qty=1.0)
    broker = FakeBroker()
    store = FakeStore(intents=[intent])
    recon = Reconciler(broker, store)
    first = recon.resolve_in_flight(as_of=T0)
    second = recon.resolve_in_flight(as_of=T0 + 3_600_000)
    assert first[0].resolved_status == OrderStatus.PARTIAL.value
    assert second[0].resolved_status == OrderStatus.PARTIAL.value
    assert store.rejected == []
    assert store.ingested == []


def test_inflight_submitted_broker_filled_updated_to_filled() -> None:
    """A SUBMITTED intent the broker actually filled is updated to FILLED, not rejected.

    The genuine 'broker did fill more of it' case: a zero-filled SUBMITTED whose
    fill landed while we were down is ingested and driven to its true filled state.
    """
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED, qty=1.0, filled_qty=0.0)
    broker = FakeBroker(fills=[_fill("af-c1-btc", BTC, qty=1.0)])
    store = FakeStore(intents=[intent])  # store has 0 fills on file
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert len(store.ingested) == 1
    assert res[0].broker_fills_ingested == 1
    assert res[0].resolved_status == OrderStatus.FILLED.value
    assert store.rejected == []  # an order the broker filled is never REJECTED


def test_inflight_new_zero_fill_still_rejected() -> None:
    """A stored NEW with zero filled_qty and no broker fill is still correctly REJECTED.

    The fix preserves the genuine reject case: an order the broker never filled
    (filled_qty == 0) whose submit never landed is the only kind that gets REJECTED.
    """
    intent = _intent("af-c1-btc", BTC, OrderStatus.NEW, qty=1.0, filled_qty=0.0)
    broker = FakeBroker()  # no open orders, no fills
    store = FakeStore(intents=[intent])
    res = Reconciler(broker, store).resolve_in_flight(as_of=T0)
    assert store.rejected == ["af-c1-btc"]
    assert res[0].resolved_status == OrderStatus.REJECTED.value
    assert res[0].found_open is False


def test_inflight_idempotent_second_pass_noop() -> None:
    """Re-running resolve on a now-terminal store finds nothing to resolve."""
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED)
    broker = FakeBroker()
    store = FakeStore(intents=[intent])
    recon = Reconciler(broker, store)
    recon.resolve_in_flight(as_of=T0)
    store.rejected.clear()
    second = recon.resolve_in_flight(as_of=T0)
    assert second == ()  # the intent is terminal now -> not in open_intents
    assert store.rejected == []


def test_reconcile_runs_inflight_first() -> None:
    """reconcile() resolves in-flight before classifying (the recovered book is compared)."""
    intent = _intent("af-c1-btc", BTC, OrderStatus.SUBMITTED)
    broker = FakeBroker()
    store = FakeStore(intents=[intent])
    report = Reconciler(broker, store).reconcile(as_of=T0)
    assert len(report.inflight) == 1
    assert report.inflight[0].resolved_status == OrderStatus.REJECTED.value


# ---------------------------------------------------------------------------
# Integration: real PaperBroker + TradingStore
# ---------------------------------------------------------------------------


def test_reconcile_real_surfaces_agree_after_a_trade(tmp_path: Path) -> None:
    """After a clean fill through OrderManager, broker and book agree on reconcile."""
    broker = _paper_broker()
    with TradingStore(tmp_path / "trading.sqlite") as store:
        om = OrderManager(broker, store, sleeper=lambda _s: None, backoff_base_s=1e-9)
        om.place([_order("af-c1-btc", qty=1.0)], cycle_ts=T0, now=T0)
        # The loop snapshots positions + equity each cycle; emulate that persist.
        account = broker.account()
        store.snapshot_positions(T0, account.positions)
        store.snapshot_equity(T0, account)

        report = Reconciler(broker, store).reconcile(as_of=T0)
        assert report.ok is True
        assert all(r.status is ReconStatus.AGREE for r in report.instruments)


def test_reconcile_real_surfaces_orphan_when_book_unsnapshotted(tmp_path: Path) -> None:
    """A broker position the book never snapshotted is an ORPHAN beyond tolerance -> halt."""
    broker = _paper_broker()
    with TradingStore(tmp_path / "trading.sqlite") as store:
        om = OrderManager(broker, store, sleeper=lambda _s: None, backoff_base_s=1e-9)
        om.place([_order("af-c1-btc", qty=1.0)], cycle_ts=T0, now=T0)
        # Persist equity (so a book snapshot exists) but NOT the position -> the
        # book is flat while the broker holds 1.0 BTC: an ORPHAN.
        store.snapshot_equity(T0, broker.account())
        with pytest.raises(ReconciliationError):
            Reconciler(broker, store).reconcile(as_of=T0)


# ---------------------------------------------------------------------------
# Tolerance validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"qty_rel": -1e-3}, {"qty_abs_floor": -1.0}, {"equity_rel": float("nan")}],
)
def test_invalid_tolerance_rejected(kwargs: dict[str, float]) -> None:
    """Negative or NaN tolerances raise at construction."""
    with pytest.raises(ValueError):
        ReconTolerance(**kwargs)
