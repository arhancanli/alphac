"""Unit tests for the Broker ABC value types and the CCXTBroker NotArmed stub.

Covers: OrderBook ladder validation (ordering, positivity, crossed-book),
BrokerAck/OpenOrder invariants, the Broker ABC abstractness, and the CCXTBroker
arming contract (every order-mutating call raises NotArmedError; read-only
methods proxy a client or raise when none is given; is_armed needs BOTH gates).

All offline; no network. execDesign.md §8.1 / §8.5, leakageCritique.md finding 8.
"""

from __future__ import annotations

import pytest

from alphaforge.core.errors import NotArmedError
from alphaforge.core.types import (
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
)
from alphaforge.execution import ARM_ENV_VAR, CCXTBroker
from alphaforge.execution.broker import (
    Broker,
    BrokerAck,
    OpenOrder,
    OrderBook,
)

BTC = "BINANCE:PERP:BTCUSDT"


def _order(*, client_order_id: str = "af-c1-btc", side: Side = Side.BUY) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        instrument_id=BTC,
        side=side,
        qty=1.0,
        order_type=OrderType.MARKET,
        decision_ts=3_600_000,
        decision_price=100.0,
        reason="rebalance",
    )


# --------------------------------------------------------------------- OrderBook


def test_order_book_accepts_well_formed_ladders() -> None:
    book = OrderBook(
        instrument_id=BTC,
        bids=((100.0, 5.0), (99.0, 10.0)),
        asks=((101.0, 3.0), (102.0, 5.0)),
        ts=0,
    )
    assert book.side_for(Side.BUY) == book.asks
    assert book.side_for(Side.SELL) == book.bids


def test_order_book_rejects_bids_not_descending() -> None:
    with pytest.raises(ValueError, match="strictly descending"):
        OrderBook(instrument_id=BTC, bids=((99.0, 1.0), (100.0, 1.0)), asks=(), ts=0)


def test_order_book_rejects_asks_not_ascending() -> None:
    with pytest.raises(ValueError, match="strictly ascending"):
        OrderBook(instrument_id=BTC, bids=(), asks=((102.0, 1.0), (101.0, 1.0)), ts=0)


def test_order_book_rejects_equal_adjacent_prices() -> None:
    with pytest.raises(ValueError, match="strictly descending"):
        OrderBook(instrument_id=BTC, bids=((100.0, 1.0), (100.0, 1.0)), asks=(), ts=0)


def test_order_book_rejects_crossed_book() -> None:
    with pytest.raises(ValueError, match="crossed book"):
        OrderBook(instrument_id=BTC, bids=((101.0, 1.0),), asks=((101.0, 1.0),), ts=0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_order_book_rejects_non_positive_price(bad: float) -> None:
    with pytest.raises(ValueError, match="price"):
        OrderBook(instrument_id=BTC, bids=((bad, 1.0),), asks=(), ts=0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_order_book_rejects_non_positive_size(bad: float) -> None:
    with pytest.raises(ValueError, match="size"):
        OrderBook(instrument_id=BTC, bids=((100.0, bad),), asks=(), ts=0)


def test_order_book_one_sided_is_allowed() -> None:
    asks_only = OrderBook(instrument_id=BTC, bids=(), asks=((101.0, 1.0),), ts=0)
    assert asks_only.side_for(Side.SELL) == ()
    bids_only = OrderBook(instrument_id=BTC, bids=((100.0, 1.0),), asks=(), ts=0)
    assert bids_only.side_for(Side.BUY) == ()


# ---------------------------------------------------------------- BrokerAck / OpenOrder


def test_broker_ack_accepted_requires_broker_order_id() -> None:
    with pytest.raises(ValueError, match="requires a broker_order_id"):
        BrokerAck(accepted=True, client_order_id="x", broker_order_id=None)


def test_broker_ack_rejection_may_omit_broker_order_id() -> None:
    ack = BrokerAck(accepted=False, client_order_id="x", broker_order_id=None, reason="nope")
    assert not ack.accepted
    assert ack.broker_order_id is None
    assert ack.reason == "nope"


def test_open_order_filled_qty_cannot_exceed_qty() -> None:
    with pytest.raises(ValueError, match="cannot exceed qty"):
        OpenOrder(
            client_order_id="x",
            broker_order_id="b",
            instrument_id=BTC,
            side=Side.BUY,
            qty=1.0,
            filled_qty=2.0,
            status=OrderStatus.PARTIAL,
        )


def test_open_order_valid_partial() -> None:
    oo = OpenOrder(
        client_order_id="x",
        broker_order_id="b",
        instrument_id=BTC,
        side=Side.BUY,
        qty=2.0,
        filled_qty=1.0,
        status=OrderStatus.PARTIAL,
    )
    assert oo.filled_qty == 1.0


# --------------------------------------------------------------------- Broker ABC


def test_broker_is_abstract() -> None:
    with pytest.raises(TypeError):
        Broker()  # type: ignore[abstract]


# ------------------------------------------------------------------- CCXTBroker


def test_ccxt_submit_raises_not_armed() -> None:
    broker = CCXTBroker(paper=True)
    with pytest.raises(NotArmedError, match="Phase-8"):
        broker.submit(_order())


def test_ccxt_cancel_raises_not_armed() -> None:
    broker = CCXTBroker(paper=True)
    with pytest.raises(NotArmedError, match="deliberate"):
        broker.cancel("af-c1-btc")


def test_ccxt_submit_raises_even_when_both_gates_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both arming gates satisfied; v1 still refuses to place a real order.
    monkeypatch.setenv(ARM_ENV_VAR, "1")
    broker = CCXTBroker(paper=False)
    assert broker.is_armed() is True
    with pytest.raises(NotArmedError):
        broker.submit(_order())


def test_ccxt_is_armed_needs_both_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ARM_ENV_VAR, raising=False)
    assert CCXTBroker(paper=False).is_armed() is False  # env missing
    monkeypatch.setenv(ARM_ENV_VAR, "1")
    assert CCXTBroker(paper=True).is_armed() is False  # config still paper
    assert CCXTBroker(paper=False).is_armed() is True  # both set
    monkeypatch.setenv(ARM_ENV_VAR, "0")
    assert CCXTBroker(paper=False).is_armed() is False  # wrong env value


def test_ccxt_read_only_raises_without_client() -> None:
    broker = CCXTBroker(client=None)
    with pytest.raises(NotArmedError):
        broker.positions()
    with pytest.raises(NotArmedError):
        broker.account()
    with pytest.raises(NotArmedError):
        broker.order_book(BTC)
    with pytest.raises(NotArmedError):
        broker.open_orders()


def test_ccxt_read_only_proxy_with_client() -> None:
    # positions/open_orders return empty (no adapter yet) when a client exists;
    # account/order_book still raise (no v1 adapter wired for them).
    broker = CCXTBroker(client=object())
    assert broker.positions() == []
    assert broker.open_orders() == []
    with pytest.raises(NotArmedError):
        broker.account()
