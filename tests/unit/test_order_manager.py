"""Unit tests for alphaforge.execution.order_manager (OrderManager).

Load-bearing guarantees under test (execDesign.md section 8.3):

- Persist-before-submit: the intent NEW row exists even if the very next broker
  submit raises (crash-safety -- recovery can never miss an order we tried).
- Idempotent replay: placing the same cycle's orders twice contacts the broker
  exactly once per ``client_order_id`` (the post-crash double-submit guard).
- Transport-only retry: a flaky broker (raises N transient errors then succeeds)
  is retried to a single logical fill on the SAME ``client_order_id``; a
  definitive reject (``BrokerAck.accepted == False``) is recorded and NOT retried.
- Partial fill: filled_qty is recorded (status PARTIAL), residual not chased.
- Walked-book audit (leakageCritique.md finding 8) is persisted with each fill.

The first half drives a hand-built FakeBroker/FakeStore so the persist/submit
ordering and counts are asserted precisely. The second half runs the *real*
:class:`~alphaforge.execution.paper.PaperBroker` and
:class:`~alphaforge.live.store.TradingStore` so the contract is exercised against
the shipped surfaces (no network -- the book is a canned FakeOrderBookSource).
All fakes are in-memory; retry backoff is driven to ~zero so tests are instant
and deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaforge.core.instruments import Instrument
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
from alphaforge.execution.broker import BrokerAck, OrderBook
from alphaforge.execution.order_manager import (
    OrderManager,
    OrderStore,
    PlacementReport,
    SubmitBroker,
    TransientBrokerError,
)
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker
from alphaforge.live.store import FillAudit, OrderRecord, TradingStore

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z (1h-aligned)
LISTED = 1_577_836_800_000
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"


def _order(
    *,
    coid: str,
    iid: str = BTC,
    side: Side = Side.BUY,
    qty: float = 1.0,
    price: float = 101.0,
) -> OrderRequest:
    """Build an OrderRequest with a caller-supplied deterministic client_order_id."""
    return OrderRequest(
        client_order_id=coid,
        instrument_id=iid,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=False,
        decision_ts=T0,
        decision_price=price,
        reason="rebalance",
    )


# --------------------------------------------------------------------------- fakes


def _record(order: OrderRequest, status: OrderStatus, *, filled_qty: float = 0.0) -> OrderRecord:
    """Build an OrderRecord mirroring what TradingStore would persist."""
    return OrderRecord(
        client_order_id=order.client_order_id,
        cycle_ts=T0,
        instrument_id=order.instrument_id,
        side=order.side,
        order_type=order.order_type.value,
        qty=order.qty,
        reduce_only=order.reduce_only,
        status=status.value,
        filled_qty=filled_qty,
        avg_fill_price=order.decision_price if filled_qty > 0.0 else None,
        decision_ts=order.decision_ts,
        decision_price=order.decision_price,
        reason=order.reason,
        created_ms=T0,
        updated_ms=T0,
    )


class FakeStore:
    """In-memory OrderStore: records the full intent->terminal lifecycle.

    Exposes ``events`` so tests can assert the exact persist-before-submit
    ordering and call counts. The fill/partial boundary mirrors TradingStore: an
    order is FILLED once cumulative ``filled_qty >= qty`` (within a lot epsilon),
    else PARTIAL.
    """

    _QTY_EPS = 1e-12

    def __init__(self) -> None:
        self._orders: dict[str, OrderRecord] = {}
        self._intents: dict[str, OrderRequest] = {}
        self.fills: dict[str, list[Fill]] = {}
        self.audits: dict[str, list[FillAudit | None]] = {}
        self.events: list[tuple[str, str]] = []  # (op, client_order_id), in order

    def record_intent(self, req: OrderRequest, cycle_ts: int, *, now: int) -> None:
        self.events.append(("record_intent", req.client_order_id))
        if req.client_order_id in self._orders:  # idempotent on the id
            return
        self._intents[req.client_order_id] = req
        self._orders[req.client_order_id] = _record(req, OrderStatus.NEW)

    def mark_submitted(self, client_order_id: str, *, now: int) -> None:
        self.events.append(("mark_submitted", client_order_id))
        self._set_status(client_order_id, OrderStatus.SUBMITTED)

    def mark_filled(self, fill: Fill, *, now: int, audit: FillAudit | None = None) -> None:
        self.events.append(("mark_filled", fill.client_order_id))
        self.fills.setdefault(fill.client_order_id, []).append(fill)
        self.audits.setdefault(fill.client_order_id, []).append(audit)
        rec = self._orders[fill.client_order_id]
        new_filled = rec.filled_qty + fill.qty
        status = (
            OrderStatus.FILLED if new_filled >= rec.qty - self._QTY_EPS else OrderStatus.PARTIAL
        )
        self._orders[fill.client_order_id] = OrderRecord(
            client_order_id=rec.client_order_id,
            cycle_ts=rec.cycle_ts,
            instrument_id=rec.instrument_id,
            side=rec.side,
            order_type=rec.order_type,
            qty=rec.qty,
            reduce_only=rec.reduce_only,
            status=status.value,
            filled_qty=new_filled,
            avg_fill_price=fill.price,
            decision_ts=rec.decision_ts,
            decision_price=rec.decision_price,
            reason=rec.reason,
            created_ms=rec.created_ms,
            updated_ms=now,
        )

    def mark_rejected(self, client_order_id: str, *, now: int) -> None:
        self.events.append(("mark_rejected", client_order_id))
        self._set_status(client_order_id, OrderStatus.REJECTED)

    def get(self, client_order_id: str) -> OrderRecord | None:
        return self._orders.get(client_order_id)

    def _set_status(self, coid: str, status: OrderStatus) -> None:
        rec = self._orders[coid]
        self._orders[coid] = OrderRecord(
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


class FakeBroker:
    """A broker that fully fills every accepted order, tracking submit counts.

    Books each fill onto the ``fills``/``audits`` lists exactly like PaperBroker,
    so OrderManager's tail-attribution reads them back. Idempotent on
    ``client_order_id``: a re-submit returns the prior ack and books no 2nd fill.
    """

    def __init__(self) -> None:
        self.submit_calls: list[str] = []  # client_order_ids, in order
        self._acks: dict[str, BrokerAck] = {}
        self._fills: list[Fill] = []
        self._audits: list[FillAudit] = []

    @property
    def fills(self) -> list[Fill]:
        return self._fills

    @property
    def audits(self) -> list[FillAudit]:
        return self._audits

    def submit(self, order: OrderRequest) -> BrokerAck:
        prior = self._acks.get(order.client_order_id)
        if prior is not None:
            return prior
        self.submit_calls.append(order.client_order_id)
        ack = self._do_submit(order)
        self._acks[order.client_order_id] = ack
        return ack

    def _do_submit(self, order: OrderRequest) -> BrokerAck:
        self._book_fill(order, order.qty)
        return BrokerAck(
            accepted=True,
            client_order_id=order.client_order_id,
            broker_order_id=f"bx-{order.client_order_id}",
        )

    def _book_fill(self, order: OrderRequest, qty: float) -> None:
        self._fills.append(
            Fill(
                client_order_id=order.client_order_id,
                instrument_id=order.instrument_id,
                side=order.side,
                qty=qty,
                price=order.decision_price,
                fee_quote=qty * order.decision_price * 5e-4,
                liquidity=Liquidity.TAKER,
                ts=order.decision_ts,
            )
        )
        self._audits.append(
            FillAudit(
                walked_price=order.decision_price,
                modeled_price=order.decision_price - 0.05,
                slippage_bps=5.0,
                book_exhausted=False,
            )
        )


class SubmitRaisesBroker(FakeBroker):
    """Broker whose submit raises immediately -- tests persist-before-submit."""

    def submit(self, order: OrderRequest) -> BrokerAck:
        self.submit_calls.append(order.client_order_id)
        raise TransientBrokerError("boom")


class FlakyBroker(FakeBroker):
    """Raises TransientBrokerError the first ``fail_times`` calls, then fills once.

    Records every attempt's client_order_id so the test can assert the id is held
    constant across retries (broker idempotency).
    """

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._fail_times = fail_times
        self._seen = 0

    def submit(self, order: OrderRequest) -> BrokerAck:
        self._seen += 1
        if self._seen <= self._fail_times:
            self.submit_calls.append(order.client_order_id)
            raise TransientBrokerError(f"transient #{self._seen}")
        return super().submit(order)


class RejectBroker(FakeBroker):
    """Broker that returns a definitive ``accepted=False`` ack (must NOT be retried)."""

    def _do_submit(self, order: OrderRequest) -> BrokerAck:
        return BrokerAck(
            accepted=False,
            client_order_id=order.client_order_id,
            broker_order_id=None,
            reason="insufficient_balance",
        )


class PartialBroker(FakeBroker):
    """Broker that fills only ``fill_frac`` of the requested qty (PARTIAL)."""

    def __init__(self, fill_frac: float) -> None:
        super().__init__()
        self._frac = fill_frac

    def _do_submit(self, order: OrderRequest) -> BrokerAck:
        self._book_fill(order, order.qty * self._frac)
        return BrokerAck(
            accepted=True,
            client_order_id=order.client_order_id,
            broker_order_id=f"bx-{order.client_order_id}",
            reason="partial: book exhausted",
        )


def _om(
    broker: SubmitBroker,
    store: OrderStore,
    *,
    max_attempts: int = 3,
    backoff_base_s: float = 1e-9,
) -> OrderManager:
    """Build an OrderManager with near-zero backoff and a no-op sleeper (instant)."""
    return OrderManager(
        broker,
        store,
        max_attempts=max_attempts,
        backoff_base_s=backoff_base_s,
        sleeper=lambda _s: None,
    )


# --------------------------------------------------------------------------- real fixtures


def _instrument(iid: str = BTC) -> Instrument:
    """A perp Instrument mirroring the PaperBroker test factory."""
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


def _paper_broker(*, thin: bool = False) -> PaperBroker:
    """A real PaperBroker on a canned book (deep, or thin enough to partial-fill)."""
    inst = _instrument()
    src = FakeOrderBookSource()
    asks = ((101.0, 1.0),) if thin else ((101.0, 100.0),)
    src.set_book(OrderBook(instrument_id=BTC, bids=((100.0, 100.0),), asks=asks, ts=T0))
    return PaperBroker({BTC: inst}, TransactionCostModel(), book_source=src, initial_cash=1e6)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_fakes_satisfy_protocols() -> None:
    """FakeBroker / FakeStore structurally satisfy the runtime-checkable Protocols."""
    assert isinstance(FakeBroker(), SubmitBroker)
    assert isinstance(FakeStore(), OrderStore)


def test_real_surfaces_satisfy_protocols(tmp_path: Path) -> None:
    """The shipped PaperBroker and TradingStore satisfy the OrderManager Protocols."""
    assert isinstance(_paper_broker(), SubmitBroker)
    with TradingStore(tmp_path / "trading.sqlite") as store:
        assert isinstance(store, OrderStore)


# ---------------------------------------------------------------------------
# Persist-before-submit
# ---------------------------------------------------------------------------


def test_intent_persisted_before_submit_even_if_submit_raises() -> None:
    """record_intent happens before submit, so a raising submit still leaves a NEW row."""
    store = FakeStore()
    broker = SubmitRaisesBroker()
    om = _om(broker, store, max_attempts=1)
    order = _order(coid="af-c1-btc")

    with pytest.raises(TransientBrokerError):
        om.place([order], cycle_ts=T0, now=T0)

    row = store.get("af-c1-btc")
    assert row is not None
    assert row.status == OrderStatus.NEW.value
    # record_intent strictly preceded the (failed) submit attempt.
    assert store.events[0] == ("record_intent", "af-c1-btc")
    assert broker.submit_calls == ["af-c1-btc"]


def test_place_happy_path_fills_and_records() -> None:
    """A fully-filling broker yields a FILLED row: record_intent -> submit -> fill."""
    store = FakeStore()
    broker = FakeBroker()
    report = _om(broker, store).place([_order(coid="af-c1-btc")], cycle_ts=T0, now=T0)

    assert report.filled == 1
    assert report.partial == 0
    assert report.submitted == 0
    assert report.rejected == 0
    assert report.skipped_replay == 0
    row = store.get("af-c1-btc")
    assert row is not None and row.status == OrderStatus.FILLED.value
    assert store.events == [
        ("record_intent", "af-c1-btc"),
        ("mark_submitted", "af-c1-btc"),
        ("mark_filled", "af-c1-btc"),
    ]


def test_fill_persisted_with_walked_book_audit() -> None:
    """The walked-book audit (finding 8) is forwarded to the store with the fill."""
    store = FakeStore()
    broker = FakeBroker()
    _om(broker, store).place([_order(coid="af-c1-btc")], cycle_ts=T0, now=T0)

    audits = store.audits["af-c1-btc"]
    assert len(audits) == 1
    audit = audits[0]
    assert audit is not None
    assert audit.slippage_bps == 5.0
    assert audit.book_exhausted is False


# ---------------------------------------------------------------------------
# Idempotent replay (crash recovery)
# ---------------------------------------------------------------------------


def test_idempotent_replay_submits_once_per_id() -> None:
    """Replaying the same cycle's orders contacts the broker once per id."""
    store = FakeStore()
    broker = FakeBroker()
    om = _om(broker, store)
    orders = [_order(coid="af-c1-btc", iid=BTC), _order(coid="af-c1-eth", iid=ETH)]

    first = om.place(orders, cycle_ts=T0, now=T0)
    assert first.filled == 2 and first.skipped_replay == 0
    assert sorted(broker.submit_calls) == ["af-c1-btc", "af-c1-eth"]

    # Replay (post-crash): terminal rows already exist -> skip resubmission.
    second = om.place(orders, cycle_ts=T0, now=T0)
    assert second.skipped_replay == 2
    assert second.filled == 0 and second.submitted == 0
    assert sorted(broker.submit_calls) == ["af-c1-btc", "af-c1-eth"]  # not re-contacted


def test_replay_skips_only_terminal_resubmits_nonterminal() -> None:
    """A replayed batch resubmits an order left non-terminal (NEW) by a prior crash."""
    store = FakeStore()
    broker = FakeBroker()
    om = _om(broker, store)
    order = _order(coid="af-c1-btc")
    # Simulate a crash after persist-intent but before submit: a NEW row exists.
    store.record_intent(order, T0, now=T0)
    store.events.clear()

    report = om.place([order], cycle_ts=T0, now=T0)
    assert report.skipped_replay == 0
    assert report.filled == 1
    assert broker.submit_calls == ["af-c1-btc"]


def test_idempotent_replay_real_paper_broker(tmp_path: Path) -> None:
    """Against the real PaperBroker + TradingStore: replay books no second fill."""
    broker = _paper_broker()
    with TradingStore(tmp_path / "trading.sqlite") as store:
        om = _om(broker, store)
        order = _order(coid="af-c1-btc", qty=1.0)

        first = om.place([order], cycle_ts=T0, now=T0)
        assert first.filled == 1
        assert len(broker.fills) == 1

        second = om.place([order], cycle_ts=T0, now=T0)
        assert second.skipped_replay == 1 and second.filled == 0
        # The broker's idempotency + the store's terminal-skip both hold: one fill.
        assert len(broker.fills) == 1
        assert len(store.fills_for("af-c1-btc")) == 1


# ---------------------------------------------------------------------------
# Transport-only retry
# ---------------------------------------------------------------------------


def test_flaky_broker_retried_to_single_fill_same_id() -> None:
    """Two transient failures then success -> one logical fill, same id each attempt."""
    store = FakeStore()
    broker = FlakyBroker(fail_times=2)
    report = _om(broker, store, max_attempts=3).place(
        [_order(coid="af-c1-btc")], cycle_ts=T0, now=T0
    )

    assert report.filled == 1
    # Three submit attempts, all the SAME client_order_id (broker idempotency).
    assert broker.submit_calls == ["af-c1-btc", "af-c1-btc", "af-c1-btc"]
    # Exactly one fill recorded (no double-fill from the retries).
    assert len(store.fills["af-c1-btc"]) == 1


def test_retry_exhaustion_reraises_transient() -> None:
    """When transient failures exceed max_attempts, the original error propagates."""
    store = FakeStore()
    broker = FlakyBroker(fail_times=5)
    with pytest.raises(TransientBrokerError):
        _om(broker, store, max_attempts=3).place([_order(coid="af-c1-btc")], cycle_ts=T0, now=T0)
    assert broker.submit_calls == ["af-c1-btc"] * 3  # exactly max_attempts tries
    row = store.get("af-c1-btc")
    assert row is not None and row.status == OrderStatus.NEW.value  # intent durable


def test_definitive_reject_not_retried() -> None:
    """An accepted=False ack is recorded once and never retried (fail-fast)."""
    store = FakeStore()
    broker = RejectBroker()
    report = _om(broker, store, max_attempts=3).place(
        [_order(coid="af-c1-btc")], cycle_ts=T0, now=T0
    )

    assert report.rejected == 1 and report.filled == 0
    assert broker.submit_calls == ["af-c1-btc"]  # ONE call, not retried
    row = store.get("af-c1-btc")
    assert row is not None and row.status == OrderStatus.REJECTED.value


# ---------------------------------------------------------------------------
# Partial fill
# ---------------------------------------------------------------------------


def test_partial_fill_recorded_residual_not_chased() -> None:
    """A 40% fill records filled_qty, status PARTIAL; the residual is not chased."""
    store = FakeStore()
    broker = PartialBroker(fill_frac=0.4)
    report = _om(broker, store).place([_order(coid="af-c1-btc", qty=10.0)], cycle_ts=T0, now=T0)

    assert report.partial == 1 and report.filled == 0 and report.submitted == 0
    row = store.get("af-c1-btc")
    assert row is not None
    assert row.status == OrderStatus.PARTIAL.value
    assert row.filled_qty == pytest.approx(4.0)
    assert broker.submit_calls == ["af-c1-btc"]  # no second submit chasing the residual


def test_partial_fill_real_paper_broker_thin_book(tmp_path: Path) -> None:
    """A thin real book partial-fills and flags book_exhausted in the audit."""
    broker = _paper_broker(thin=True)  # only 1.0 on the ask
    with TradingStore(tmp_path / "trading.sqlite") as store:
        report = _om(broker, store).place([_order(coid="af-c1-btc", qty=5.0)], cycle_ts=T0, now=T0)
        assert report.partial == 1
        row = store.get("af-c1-btc")
        assert row is not None and row.status == OrderStatus.PARTIAL.value
        assert row.filled_qty == pytest.approx(1.0)
        recorded = store.fills_for("af-c1-btc")
        assert len(recorded) == 1
        assert recorded[0].audit is not None and recorded[0].audit.book_exhausted is True


# ---------------------------------------------------------------------------
# Construction validation + edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("max_attempts", "base"), [(0, 1.0), (1, 0.0), (1, -1.0)])
def test_invalid_construction_rejected(max_attempts: int, base: float) -> None:
    """max_attempts < 1 or backoff_base_s <= 0 raise ValueError at construction."""
    with pytest.raises(ValueError):
        OrderManager(FakeBroker(), FakeStore(), max_attempts=max_attempts, backoff_base_s=base)


def test_empty_batch_is_noop() -> None:
    """Placing no orders contacts neither broker nor store and reports zeros."""
    store = FakeStore()
    broker = FakeBroker()
    report: PlacementReport = _om(broker, store).place([], cycle_ts=T0, now=T0)
    assert report.n_attempted == 0
    assert report.skipped_replay == 0
    assert broker.submit_calls == []
    assert store.events == []
