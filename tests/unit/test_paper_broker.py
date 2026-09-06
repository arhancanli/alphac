"""Unit tests for PaperBroker: walk-the-book fills, idempotency, state, accounting.

Load-bearing assertions (execDesign.md §8.2, leakageCritique.md finding 8):

* MARKET fills price by WALKING the canned order book to the cent (multi-level
  size-weighted average), NOT by the cost model.
* a book thinner than the requested qty fills partially and flags
  ``book_exhausted`` -- liquidity is never invented.
* the taker fee is charged via the shared TransactionCostModel.
* every fill records a slippage cross-check (walked vs modeled, in bps) -- the
  genuine validation signal that the model is NOT the fill.
* submit is idempotent on client_order_id (resubmit -> prior ack, no 2nd fill).
* PaperState round-trips: serialize -> restore -> identical book and cash.
* reduce / flip accounting mirrors the Ledger (realized PnL, avg_entry reset).

All deterministic and offline via FakeOrderBookSource (no network).
"""

from __future__ import annotations

import math

import pytest

from alphaforge.core.instruments import Instrument
from alphaforge.core.types import (
    AssetClass,
    Fill,
    Liquidity,
    MarketType,
    OrderRequest,
    OrderType,
    Side,
)
from alphaforge.costs import TransactionCostModel
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.paper import (
    FakeOrderBookSource,
    PaperBroker,
    PaperState,
    walk_book,
)

HOUR = 3_600_000
T0 = 3_600_000
LISTED = 1_577_836_800_000
BTC = "BINANCE:PERP:BTCUSDT"
TAKER_PERP_FRAC = 5e-4  # cost-model default perp taker fee

# A book deep enough on both sides for clean multi-level walks.
#   asks: 101 x3, 102 x5, 103 x20  (BUY consumes these, cheapest first)
#   bids: 100 x5,  99 x10           (SELL consumes these, highest first)
_BIDS = ((100.0, 5.0), (99.0, 10.0))
_ASKS = ((101.0, 3.0), (102.0, 5.0), (103.0, 20.0))


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


def make_book(
    *,
    instrument_id: str = BTC,
    bids: tuple[tuple[float, float], ...] = _BIDS,
    asks: tuple[tuple[float, float], ...] = _ASKS,
    ts: int = T0,
) -> OrderBook:
    return OrderBook(instrument_id=instrument_id, bids=bids, asks=asks, ts=ts)


def make_broker(
    *,
    book: OrderBook | None = None,
    initial_cash: float = 100_000.0,
    state: PaperState | None = None,
) -> tuple[PaperBroker, FakeOrderBookSource, Instrument]:
    inst = make_instrument()
    src = FakeOrderBookSource()
    src.set_book(book if book is not None else make_book())
    cm = TransactionCostModel()
    broker = PaperBroker(
        {inst.instrument_id: inst},
        cm,
        book_source=src,
        initial_cash=initial_cash,
        state=state,
    )
    return broker, src, inst


def make_order(
    *,
    client_order_id: str = "af-c1-btc",
    side: Side = Side.BUY,
    qty: float = 6.0,
    reduce_only: bool = False,
    decision_ts: int = T0,
    reason: str = "rebalance",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        instrument_id=BTC,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=reduce_only,
        decision_ts=decision_ts,
        decision_price=101.0,
        reason=reason,
    )


def test_position_marks_reuse_account_snapshot_and_disclose_source() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(qty=2.0))

    account = broker.account_at(T0)
    marks = broker.position_marks_at(T0)

    assert account.positions[0].instrument_id == BTC
    assert marks == {BTC: (100.5, "order_book_mid")}


# ------------------------------------------------------------------- walk_book


def test_walk_book_buy_multilevel_to_the_cent() -> None:
    # BUY 6: 3@101 + 3@102 = (303 + 306) / 6 = 101.5
    walked = walk_book(make_book(), Side.BUY, 6.0)
    assert walked.filled_qty == 6.0
    assert walked.avg_price == 101.5
    assert walked.levels_consumed == 2
    assert walked.book_exhausted is False
    assert walked.is_partial is False


def test_walk_book_sell_multilevel_to_the_cent() -> None:
    # SELL 6: 5@100 + 1@99 = (500 + 99) / 6
    walked = walk_book(make_book(), Side.SELL, 6.0)
    assert walked.filled_qty == 6.0
    assert math.isclose(walked.avg_price, 599.0 / 6.0, rel_tol=0, abs_tol=1e-12)
    assert walked.levels_consumed == 2


def test_walk_book_exact_single_level() -> None:
    walked = walk_book(make_book(), Side.BUY, 3.0)
    assert walked.filled_qty == 3.0
    assert walked.avg_price == 101.0
    assert walked.levels_consumed == 1


def test_walk_book_thin_book_partial_and_exhausted() -> None:
    # Ask depth = 3 + 5 + 20 = 28; request 100 -> partial fill of 28, exhausted.
    walked = walk_book(make_book(), Side.BUY, 100.0)
    assert walked.filled_qty == 28.0
    assert walked.book_exhausted is True
    assert walked.is_partial is True
    # avg = (3*101 + 5*102 + 20*103) / 28
    assert math.isclose(walked.avg_price, (303.0 + 510.0 + 2060.0) / 28.0, abs_tol=1e-12)


def test_walk_book_empty_side_fills_nothing() -> None:
    book = make_book(asks=())
    walked = walk_book(book, Side.BUY, 5.0)
    assert walked.filled_qty == 0.0
    assert walked.avg_price == 0.0
    assert walked.book_exhausted is True


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_walk_book_rejects_bad_qty(bad: float) -> None:
    with pytest.raises(ValueError, match="qty"):
        walk_book(make_book(), Side.BUY, bad)


# ------------------------------------------------------- submit: fill exactness + fee


def test_submit_buy_walks_book_and_charges_taker_fee() -> None:
    broker, _, _ = make_broker()
    ack = broker.submit(make_order(qty=6.0))
    assert ack.accepted is True
    assert ack.broker_order_id == "paper-af-c1-btc"

    fills = broker.fills
    assert len(fills) == 1
    fill = fills[0]
    assert fill.qty == 6.0
    assert fill.price == 101.5
    assert fill.liquidity is Liquidity.TAKER
    # fee = |qty| * price * taker_frac
    expected_fee = 6.0 * 101.5 * TAKER_PERP_FRAC
    assert math.isclose(fill.fee_quote, expected_fee, abs_tol=1e-12)

    # cash = 100000 - notional - fee
    notional = 6.0 * 101.5
    assert math.isclose(broker.cash, 100_000.0 - notional - expected_fee, abs_tol=1e-9)

    pos = broker.positions()
    assert len(pos) == 1
    assert pos[0].qty == 6.0
    assert pos[0].avg_entry_price == 101.5


def test_submit_sell_opens_short_with_signed_qty() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(side=Side.SELL, qty=6.0))
    pos = broker.positions()
    assert pos[0].qty == -6.0  # short
    assert math.isclose(pos[0].avg_entry_price, 599.0 / 6.0, abs_tol=1e-12)


def test_submit_partial_fill_flags_book_exhausted() -> None:
    broker, _, _ = make_broker()
    ack = broker.submit(make_order(qty=100.0))  # ask depth only 28
    assert ack.accepted is True
    assert "partial" in ack.reason
    audit = broker.audits[0]
    assert audit.book_exhausted is True
    assert audit.filled_qty == 28.0
    assert broker.positions()[0].qty == 28.0


def test_submit_rejects_when_book_side_empty() -> None:
    broker, _, _ = make_broker(book=make_book(asks=()))
    ack = broker.submit(make_order(side=Side.BUY, qty=1.0))
    assert ack.accepted is False
    assert "book_empty" in ack.reason
    assert broker.fills == []
    assert broker.positions() == []


def test_submit_unknown_instrument_raises() -> None:
    broker, _, _ = make_broker()
    bad = OrderRequest(
        client_order_id="af-c1-eth",
        instrument_id="BINANCE:PERP:ETHUSDT",
        side=Side.BUY,
        qty=1.0,
        order_type=OrderType.MARKET,
        decision_ts=T0,
        decision_price=100.0,
        reason="rebalance",
    )
    with pytest.raises(KeyError, match="ETHUSDT"):
        broker.submit(bad)


def test_submit_limit_order_not_supported() -> None:
    broker, _, _ = make_broker()
    limit = OrderRequest(
        client_order_id="af-c1-btc",
        instrument_id=BTC,
        side=Side.BUY,
        qty=1.0,
        order_type=OrderType.LIMIT,
        decision_ts=T0,
        decision_price=100.0,
        reason="rebalance",
    )
    with pytest.raises(NotImplementedError, match="MARKET"):
        broker.submit(limit)


# ----------------------------------------------------- slippage cross-check (finding 8)


def test_audit_records_walked_vs_modeled_slippage() -> None:
    broker, _, inst = make_broker()
    broker.submit(make_order(side=Side.BUY, qty=6.0))
    audit = broker.audits[0]

    # The FILL is the walked price, not the modeled price -- that is the whole point.
    assert audit.walked_price == 101.5
    assert audit.mid_price == 100.5  # (best bid 100 + best ask 101) / 2

    cm = TransactionCostModel()
    expected_modeled = 100.5 * (1.0 + (cm.half_spread_frac(inst) + cm.latency_frac(inst)))
    assert math.isclose(audit.modeled_price, expected_modeled, abs_tol=1e-9)
    assert audit.walked_price != pytest.approx(audit.modeled_price)

    # slippage_bps adverse-positive: a BUY filled above the model is positive.
    raw = (audit.walked_price - audit.modeled_price) / audit.modeled_price
    assert math.isclose(audit.slippage_bps, raw * 1e4, abs_tol=1e-9)
    assert audit.slippage_bps > 0.0


def test_audit_slippage_sign_normalized_for_sell() -> None:
    # A SELL filling BELOW the modeled price is adverse -> positive slippage.
    broker, _, inst = make_broker()
    broker.submit(make_order(side=Side.SELL, qty=6.0))
    audit = broker.audits[0]
    cm = TransactionCostModel()
    expected_modeled = audit.mid_price * (1.0 - (cm.half_spread_frac(inst) + cm.latency_frac(inst)))
    assert math.isclose(audit.modeled_price, expected_modeled, abs_tol=1e-9)
    assert audit.slippage_bps > 0.0  # walked below modeled -> adverse-positive


# --------------------------------------------------------------------- idempotency


def test_resubmit_returns_prior_ack_no_double_fill() -> None:
    broker, _, _ = make_broker()
    order = make_order(qty=6.0)
    ack1 = broker.submit(order)
    cash_after_first = broker.cash
    ack2 = broker.submit(order)  # same client_order_id

    assert ack2 == ack1
    assert len(broker.fills) == 1
    assert broker.cash == cash_after_first
    assert broker.positions()[0].qty == 6.0


def test_resubmit_rejected_order_stays_rejected() -> None:
    broker, _, _ = make_broker(book=make_book(asks=()))
    order = make_order(side=Side.BUY, qty=1.0)
    ack1 = broker.submit(order)
    ack2 = broker.submit(order)
    assert ack1.accepted is False
    assert ack2 == ack1
    assert broker.fills == []


def test_distinct_client_ids_each_fill() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", qty=3.0))
    broker.submit(make_order(client_order_id="af-c2-btc", qty=3.0))
    assert len(broker.fills) == 2
    # The fake book is static (does not deplete between orders), so each 3-unit
    # BUY clears the top ask level (size 3) at 101 -> VWAP 101 on 6 units.
    pos = broker.positions()[0]
    assert pos.qty == 6.0
    assert math.isclose(pos.avg_entry_price, 101.0, abs_tol=1e-12)


# ----------------------------------------------------------------- state round-trip


def test_state_roundtrip_identical_book() -> None:
    broker, _, inst = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=6.0))
    broker.submit(make_order(client_order_id="af-c2-btc", side=Side.SELL, qty=2.0))

    snap = broker.snapshot_state()

    # Restore a fresh broker from the snapshot; it must reproduce the book exactly.
    src2 = FakeOrderBookSource()
    src2.set_book(make_book())
    restored = PaperBroker(
        {inst.instrument_id: inst},
        TransactionCostModel(),
        book_source=src2,
        state=snap,
    )

    assert restored.cash == broker.cash
    assert restored.positions() == broker.positions()
    assert restored.fills == broker.fills
    assert restored.audits == broker.audits

    # Idempotency state survives the round-trip: a known id does not re-fill.
    n_before = len(restored.fills)
    restored.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=6.0))
    assert len(restored.fills) == n_before


def test_state_copy_isolates_original() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(qty=6.0))
    snap = broker.snapshot_state()
    # Mutating the original after snapshot must not change the snapshot.
    broker.submit(make_order(client_order_id="af-c2-btc", qty=3.0))
    assert len(snap.fills) == 1
    assert len(broker.fills) == 2


def test_state_constructor_resume_does_not_alias() -> None:
    broker, _, inst = make_broker()
    broker.submit(make_order(qty=6.0))
    snap = broker.snapshot_state()
    src2 = FakeOrderBookSource()
    src2.set_book(make_book())
    restored = PaperBroker(
        {inst.instrument_id: inst},
        TransactionCostModel(),
        book_source=src2,
        state=snap,
    )
    restored.submit(make_order(client_order_id="af-c2-btc", qty=3.0))
    # The snapshot we passed in must be untouched by the restored broker.
    assert len(snap.fills) == 1


# --------------------------------------------------------- reduce / close / flip


def test_reduce_books_realized_pnl_keeps_avg_entry() -> None:
    # Open long 6 @ 101.5, then SELL 2 (reduce). Sell walks bids: 2@100 = 100.
    broker, _, _ = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=6.0))
    cash_after_open = broker.cash
    broker.submit(
        make_order(client_order_id="af-c2-btc", side=Side.SELL, qty=2.0, reduce_only=True)
    )
    pos = broker.positions()[0]
    assert pos.qty == 4.0
    assert pos.avg_entry_price == 101.5  # unchanged on a reduce

    # Cash effect of the reduce: + (2 * 100) - fee.
    sell_price = 100.0
    fee = 2.0 * sell_price * TAKER_PERP_FRAC
    assert math.isclose(broker.cash, cash_after_open + 2.0 * sell_price - fee, abs_tol=1e-9)


def test_exact_close_removes_position() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=5.0))
    broker.submit(
        make_order(client_order_id="af-c2-btc", side=Side.SELL, qty=5.0, reduce_only=True)
    )
    assert broker.positions() == []


def test_flip_resets_avg_entry_to_fill_price() -> None:
    # Long 3 @ 101, then SELL 8 -> close 3, open short 5. Sell walks bids:
    # 5@100 + 3@99 = (500 + 297) / 8 = 99.625 fill price for the whole 8.
    broker, _, _ = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=3.0))
    broker.submit(make_order(client_order_id="af-c2-btc", side=Side.SELL, qty=8.0))
    pos = broker.positions()[0]
    assert pos.qty == -5.0  # flipped to short 5
    flip_price = (5 * 100.0 + 3 * 99.0) / 8.0
    assert math.isclose(pos.avg_entry_price, flip_price, abs_tol=1e-12)


# ------------------------------------------------------------------- account mark


def test_account_marks_at_book_mid() -> None:
    broker, _, _ = make_broker()
    broker.submit(make_order(side=Side.BUY, qty=6.0))
    acct = broker.account()
    # equity = cash + qty * mid, mid = 100.5
    expected = broker.cash + 6.0 * 100.5
    assert math.isclose(acct.equity_quote, expected, abs_tol=1e-9)
    assert acct.cash_quote == broker.cash
    assert len(acct.positions) == 1


def test_account_flat_equity_is_cash() -> None:
    broker, _, _ = make_broker()
    acct = broker.account()
    assert acct.equity_quote == 100_000.0
    assert acct.cash_quote == 100_000.0
    assert acct.positions == ()


def test_initial_cash_must_be_positive() -> None:
    inst = make_instrument()
    src = FakeOrderBookSource()
    src.set_book(make_book())
    with pytest.raises(ValueError, match="initial_cash"):
        PaperBroker(
            {inst.instrument_id: inst}, TransactionCostModel(), book_source=src, initial_cash=0.0
        )


# ------------------------------------------------------------- apply_recorded_fill
#
# Crash recovery (execDesign.md section 9.3 step 4): a store-recorded fill is
# replayed onto a restored broker book, idempotently, so the book catches up to
# the store's durable truth after a mid-batch crash.


def _recorded_fill(
    *,
    client_order_id: str = "af-c1-btc",
    side: Side = Side.BUY,
    qty: float = 6.0,
    price: float = 101.5,
    fee_quote: float = 3.045,
    ts: int = T0,
) -> Fill:
    return Fill(
        client_order_id=client_order_id,
        instrument_id=BTC,
        side=side,
        qty=qty,
        price=price,
        fee_quote=fee_quote,
        liquidity=Liquidity.TAKER,
        ts=ts,
    )


def test_apply_recorded_fill_books_position_and_cash() -> None:
    """A replayed fill moves cash and opens the exact position (verbatim, no re-walk)."""
    broker, _, _ = make_broker()
    cash0 = broker.cash
    applied = broker.apply_recorded_fill(_recorded_fill(side=Side.BUY, qty=6.0, price=101.5))
    assert applied is True
    # cash -= qty*price + fee; a long of 6 @ 101.5 with fee 3.045.
    assert math.isclose(broker.cash, cash0 - 6.0 * 101.5 - 3.045, abs_tol=1e-9)
    pos = {p.instrument_id: p for p in broker.positions()}
    assert pos[BTC].qty == 6.0
    assert pos[BTC].avg_entry_price == 101.5
    # The fill is now part of the broker's fill log + idempotency acks.
    assert [f.client_order_id for f in broker.fills] == ["af-c1-btc"]


def test_apply_recorded_fill_is_idempotent_on_coid() -> None:
    """Replaying the same coid twice books it once (the recovery idempotency guard)."""
    broker, _, _ = make_broker()
    assert broker.apply_recorded_fill(_recorded_fill()) is True
    cash_after_first = broker.cash
    # A second replay of the SAME coid is a no-op (already in acks).
    assert broker.apply_recorded_fill(_recorded_fill()) is False
    assert broker.cash == cash_after_first
    assert len([f for f in broker.fills if f.client_order_id == "af-c1-btc"]) == 1


def test_apply_recorded_fill_skips_id_already_submitted() -> None:
    """A coid the broker already filled via submit is NOT re-applied on replay."""
    broker, _, _ = make_broker()
    broker.submit(make_order(client_order_id="af-c1-btc", side=Side.BUY, qty=6.0))
    cash_after_submit = broker.cash
    fills_after_submit = len(broker.fills)
    # The recovery replay of that same coid (e.g. it was in the restored blob) is a no-op.
    assert broker.apply_recorded_fill(_recorded_fill(client_order_id="af-c1-btc")) is False
    assert broker.cash == cash_after_submit
    assert len(broker.fills) == fills_after_submit
