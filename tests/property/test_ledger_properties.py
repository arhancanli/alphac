"""Hypothesis property tests for the backtest Ledger (execDesign.md §4.3).

The ledger is the accounting truth of the backtester, so its invariants are
checked over random fill/funding sequences rather than by example:

1. equity decomposition: equity == initial + realized + unrealized - fees + funding
   at every step of any fill sequence;
2. funding sign law (qty>0, f>0 => payment<0) and long/short antisymmetry
   (equal-size opposite books net to zero funding);
3. a flip realizes exactly (exit - entry) * qty_closed on the old position;
4. VWAP avg_entry is invariant under permutation of same-direction adds.
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from alphaforge.backtest import Ledger
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, Fill, Liquidity, MarketType, Side

PERP_ID = "BINANCE:PERP:BTCUSDT"
INITIAL_CASH = 1_000_000.0

_INSTRUMENTS = {
    PERP_ID: Instrument(
        instrument_id=PERP_ID,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=4.0,
        funding_interval_hours=8,
        listed_ts=0,
        delisted_ts=None,
    )
}

# Bounded, well-conditioned domains: prices/qtys span 5+ orders of magnitude but
# stay far from float64 cancellation cliffs so 1e-6-absolute assertions are honest.
qtys = st.floats(min_value=1e-3, max_value=50.0, allow_nan=False, allow_infinity=False)
prices = st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)
fees = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)
rates = st.floats(min_value=-0.0075, max_value=0.0075, allow_nan=False, allow_infinity=False)
sides = st.sampled_from([Side.BUY, Side.SELL])

fill_tuples = st.lists(st.tuples(sides, qtys, prices, fees), min_size=1, max_size=30)


def _ledger() -> Ledger:
    return Ledger(initial_cash=INITIAL_CASH, instruments=_INSTRUMENTS)


def _fill(side: Side, qty: float, price: float, fee: float, ts: int) -> Fill:
    return Fill(
        client_order_id=f"o-{ts}",
        instrument_id=PERP_ID,
        side=side,
        qty=qty,
        price=price,
        fee_quote=fee,
        liquidity=Liquidity.TAKER,
        ts=ts,
    )


@given(seq=fill_tuples, mark_price=prices)
def test_equity_decomposition_holds_at_every_step(
    seq: list[tuple[Side, float, float, float]], mark_price: float
) -> None:
    """cash + Σ qty·mark == initial + realized + unrealized - fees (+ funding=0)."""
    ledger = _ledger()
    for i, (side, qty, price, fee) in enumerate(seq):
        ledger.apply_fill(_fill(side, qty, price, fee, ts=1_000 + i))

        positions = ledger.positions()
        position_value = sum(p.qty * mark_price for p in positions.values())
        unrealized = sum(p.qty * (mark_price - p.avg_entry_price) for p in positions.values())
        realized = sum(ledger.realized_pnl().values())

        # The cash + position-mark identity (equity as derived state) ...
        equity = ledger.cash + position_value
        # ... must equal the PnL decomposition, at every step.
        expected = INITIAL_CASH + realized + unrealized - ledger.total_fees
        assert math.isclose(equity, expected, rel_tol=1e-9, abs_tol=1e-5)
        assert math.isfinite(ledger.cash)

    state = ledger.mark({PERP_ID: mark_price} if ledger.positions() else {}, ts=10_000 + len(seq))
    marked = ledger.cash + sum(p.qty * mark_price for p in ledger.positions().values())
    assert math.isclose(state.equity_quote, marked, rel_tol=1e-12, abs_tol=1e-9)


@given(qty=qtys, entry=prices, mark=prices, rate=rates)
def test_funding_sign_law_and_long_short_antisymmetry(
    qty: float, entry: float, mark: float, rate: float
) -> None:
    """qty>0, f>0 => payment<0; equal-size long and short books net to zero funding."""
    long_book = _ledger()
    short_book = _ledger()
    long_book.apply_fill(_fill(Side.BUY, qty, entry, 0.0, ts=1_000))
    short_book.apply_fill(_fill(Side.SELL, qty, entry, 0.0, ts=1_000))

    p_long = long_book.apply_funding(PERP_ID, ts_funding=2_000, rate=rate, mark_price=mark)
    p_short = short_book.apply_funding(PERP_ID, ts_funding=2_000, rate=rate, mark_price=mark)

    if rate > 0.0:
        assert p_long <= 0.0  # longs pay shorts
        assert p_short >= 0.0
    elif rate < 0.0:
        assert p_long >= 0.0
        assert p_short <= 0.0

    # Antisymmetry: what the long pays is exactly what the short receives.
    assert math.isclose(p_long, -p_short, rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(p_long + p_short, 0.0, abs_tol=1e-12)
    assert math.isclose(p_long, -qty * mark * rate, rel_tol=1e-12, abs_tol=1e-12)


@given(open_qty=qtys, extra_qty=qtys, entry=prices, exit_price=prices, long_first=st.booleans())
def test_flip_realizes_exactly_entry_exit_times_qty_closed(
    open_qty: float, extra_qty: float, entry: float, exit_price: float, long_first: bool
) -> None:
    """Crossing zero realizes (exit - entry) * qty_closed * sign and restarts avg_entry."""
    ledger = _ledger()
    open_side, flip_side = (Side.BUY, Side.SELL) if long_first else (Side.SELL, Side.BUY)
    sign = 1.0 if long_first else -1.0

    ledger.apply_fill(_fill(open_side, open_qty, entry, 0.0, ts=1_000))
    ledger.apply_fill(_fill(flip_side, open_qty + extra_qty, exit_price, 0.0, ts=2_000))

    expected_realized = open_qty * (exit_price - entry) * sign
    assert math.isclose(
        ledger.realized_pnl()[PERP_ID], expected_realized, rel_tol=1e-9, abs_tol=1e-6
    )

    pos = ledger.positions()[PERP_ID]
    assert math.isclose(pos.qty, -sign * extra_qty, rel_tol=1e-9, abs_tol=1e-12)
    assert pos.avg_entry_price == exit_price  # avg_entry restarts at the flip fill price
    assert pos.opened_ts == 2_000


@given(
    adds=st.lists(st.tuples(qtys, prices), min_size=2, max_size=8),
    perm_seed=st.randoms(use_true_random=False),
    long_side=st.booleans(),
)
def test_vwap_avg_entry_is_permutation_invariant(
    adds: list[tuple[float, float]],
    perm_seed: object,
    long_side: bool,
) -> None:
    """Same-direction adds give the same VWAP avg_entry in any fill order."""
    import random

    assert isinstance(perm_seed, random.Random)
    side = Side.BUY if long_side else Side.SELL
    shuffled = list(adds)
    perm_seed.shuffle(shuffled)

    book_a = _ledger()
    book_b = _ledger()
    for i, (qty, price) in enumerate(adds):
        book_a.apply_fill(_fill(side, qty, price, 0.0, ts=1_000 + i))
    for i, (qty, price) in enumerate(shuffled):
        book_b.apply_fill(_fill(side, qty, price, 0.0, ts=1_000 + i))

    pos_a = book_a.positions()[PERP_ID]
    pos_b = book_b.positions()[PERP_ID]
    assert math.isclose(pos_a.qty, pos_b.qty, rel_tol=1e-12)
    assert math.isclose(pos_a.avg_entry_price, pos_b.avg_entry_price, rel_tol=1e-9)
    # And the VWAP is the analytic quantity-weighted mean.
    expected_vwap = sum(q * p for q, p in adds) / sum(q for q, _ in adds)
    assert math.isclose(pos_a.avg_entry_price, expected_vwap, rel_tol=1e-9)
