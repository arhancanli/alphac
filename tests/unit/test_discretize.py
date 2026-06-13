"""Unit tests for alphaforge.portfolio.discretize (weights -> orders, execDesign §6.4).

Every expected quantity/notional is hand-computed in a comment next to its
assertion. Equity defaults to 100_000 so the 10 bps no-trade band is exactly
$100 — fixtures sit just above/below it deliberately.
"""

from __future__ import annotations

import math

import pytest

from alphaforge.backtest import Ledger
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, Fill, Liquidity, MarketType, OrderType, Side
from alphaforge.portfolio import weights_to_orders

LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"
DOGE = "BINANCE:PERP:DOGEUSDT"


def make_perp(
    symbol: str,
    base: str,
    lot_size: float,
    min_qty: float,
    min_notional: float,
) -> Instrument:
    return Instrument(
        instrument_id=symbol,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=lot_size,
        min_qty=min_qty,
        min_notional=min_notional,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


INSTRUMENTS: dict[str, Instrument] = {
    BTC: make_perp(BTC, "BTC", lot_size=0.001, min_qty=0.001, min_notional=100.0),
    ETH: make_perp(ETH, "ETH", lot_size=0.01, min_qty=0.01, min_notional=500.0),
    DOGE: make_perp(DOGE, "DOGE", lot_size=1.0, min_qty=100.0, min_notional=10.0),
}


def make_ledger(initial_cash: float = 100_000.0) -> Ledger:
    return Ledger(initial_cash=initial_cash, instruments=INSTRUMENTS)


def buy(ledger: Ledger, iid: str, qty: float, price: float) -> None:
    ledger.apply_fill(
        Fill(
            client_order_id="setup",
            instrument_id=iid,
            side=Side.BUY,
            qty=qty,
            price=price,
            fee_quote=0.0,
            liquidity=Liquidity.TAKER,
            ts=1,
        )
    )


class TestNoTradeBand:
    def test_delta_below_band_is_skipped(self) -> None:
        # E = 100_000, band = 0.0010 * E = $100; |delta| = 0.0005 * E = $50 < $100.
        orders = weights_to_orders({BTC: 0.0005}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS)
        assert orders == []

    def test_delta_above_band_trades(self) -> None:
        # |delta| = 0.0020 * E = $200 >= $100 -> trade 200/50_000 = 0.004 BTC.
        orders = weights_to_orders({BTC: 0.0020}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].qty == pytest.approx(0.004, abs=1e-15)


class TestSimpleOpen:
    def test_full_order_fields(self) -> None:
        # delta = 0.10 * 100_000 = $10_000 -> 10_000/50_000 = 0.2 BTC, exact lot multiple.
        orders = weights_to_orders(
            {BTC: 0.10}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS, cycle_ts=777
        )
        assert len(orders) == 1
        o = orders[0]
        assert o.client_order_id == f"rb-777-{BTC}"
        assert o.instrument_id == BTC
        assert o.side is Side.BUY
        assert o.qty == pytest.approx(0.2, abs=1e-15)
        assert o.order_type is OrderType.MARKET
        assert o.reduce_only is False
        assert o.decision_ts == 777
        assert o.decision_price == 50_000.0
        assert o.reason == "rebalance"

    def test_short_target_sells(self) -> None:
        orders = weights_to_orders({BTC: -0.10}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].side is Side.SELL
        assert orders[0].qty == pytest.approx(0.2, abs=1e-15)
        assert orders[0].reduce_only is False


class TestExchangeFilters:
    def test_lot_floor(self) -> None:
        # delta = $10_000 at close 2997: raw qty = 3.33667000... -> ETH lot 0.01 -> 3.33.
        orders = weights_to_orders({ETH: 0.10}, make_ledger(), {ETH: 2_997.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].qty == pytest.approx(3.33, abs=1e-12)
        assert math.isclose(orders[0].qty % 0.01, 0.0, abs_tol=1e-9) or math.isclose(
            orders[0].qty % 0.01, 0.01, abs_tol=1e-9
        )

    def test_exact_lot_multiple_not_floored_down(self) -> None:
        # 0.2 / 0.001 = 200.00000000000003 in float64; the epsilon guard must
        # keep it at 0.2, not floor to 0.199.
        orders = weights_to_orders({BTC: 0.10}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS)
        assert orders[0].qty == pytest.approx(0.2, abs=1e-15)

    def test_min_qty_skip(self) -> None:
        # delta = 0.0015 * E = $150 >= band; qty = 150/2 = 75 < min_qty 100 -> skip.
        orders = weights_to_orders({DOGE: 0.0015}, make_ledger(), {DOGE: 2.0}, INSTRUMENTS)
        assert orders == []

    def test_min_notional_skip(self) -> None:
        # delta = 0.004 * E = $400 >= band; ETH min_notional 500 -> threshold
        # 1.05 * 500 = $525 > $400 -> skip (5% buffer against a price tick).
        orders = weights_to_orders({ETH: 0.004}, make_ledger(), {ETH: 200.0}, INSTRUMENTS)
        assert orders == []

    def test_min_notional_buffer_is_5_percent(self) -> None:
        # $520 >= 500 but < 525: still skipped — the buffer is part of the contract.
        orders = weights_to_orders({ETH: 0.0052}, make_ledger(), {ETH: 200.0}, INSTRUMENTS)
        assert orders == []
        # $530 >= 525: trades.
        orders = weights_to_orders({ETH: 0.0053}, make_ledger(), {ETH: 200.0}, INSTRUMENTS)
        assert len(orders) == 1


class TestFlip:
    def test_flip_emits_two_orders_close_then_open(self) -> None:
        # Book: +1 BTC @ 50_000 (cash 50_000, E = 100_000 at close 50_000).
        # Target -0.10: target qty = -0.2; sign crosses zero -> TWO orders:
        # reduce_only SELL 1.0 to flat, then SELL 0.2 to open the short.
        ledger = make_ledger()
        buy(ledger, BTC, 1.0, 50_000.0)
        orders = weights_to_orders({BTC: -0.10}, ledger, {BTC: 50_000.0}, INSTRUMENTS, cycle_ts=42)
        assert len(orders) == 2
        close_leg, open_leg = orders
        assert close_leg.client_order_id == f"rb-42-{BTC}-close"
        assert close_leg.side is Side.SELL
        assert close_leg.qty == pytest.approx(1.0, abs=1e-15)
        assert close_leg.reduce_only is True
        assert open_leg.client_order_id == f"rb-42-{BTC}-open"
        assert open_leg.side is Side.SELL
        assert open_leg.qty == pytest.approx(0.2, abs=1e-15)
        assert open_leg.reduce_only is False
        for o in orders:
            assert o.decision_price == 50_000.0
            assert o.reason == "rebalance"

    def test_flip_open_leg_respects_min_filters(self) -> None:
        # Short -1 ETH @ 200 -> flip to a tiny long whose open notional $400
        # < 1.05 * 500: only the reduce_only close survives.
        ledger = make_ledger()
        ledger.apply_fill(
            Fill(
                client_order_id="setup",
                instrument_id=ETH,
                side=Side.SELL,
                qty=1.0,
                price=200.0,
                fee_quote=0.0,
                liquidity=Liquidity.TAKER,
                ts=1,
            )
        )
        # E = cash 100_200 - 1*200 = 100_000. Target +0.004 -> $400 open.
        orders = weights_to_orders({ETH: 0.004}, ledger, {ETH: 200.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].reduce_only is True
        assert orders[0].side is Side.BUY  # closing a short
        assert orders[0].qty == pytest.approx(1.0, abs=1e-15)


class TestReduceAndClose:
    def test_partial_reduce_is_reduce_only(self) -> None:
        # +1 BTC, target 0.20: delta = 20_000 - 50_000 = -30_000 -> SELL 0.6,
        # same-sign book afterwards -> single reduce_only order.
        ledger = make_ledger()
        buy(ledger, BTC, 1.0, 50_000.0)
        orders = weights_to_orders({BTC: 0.20}, ledger, {BTC: 50_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].side is Side.SELL
        assert orders[0].qty == pytest.approx(0.6, abs=1e-12)
        assert orders[0].reduce_only is True

    def test_full_close_on_zero_target(self) -> None:
        ledger = make_ledger()
        buy(ledger, BTC, 1.0, 50_000.0)
        orders = weights_to_orders({BTC: 0.0}, ledger, {BTC: 50_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].side is Side.SELL
        assert orders[0].qty == pytest.approx(1.0, abs=1e-15)
        assert orders[0].reduce_only is True

    def test_reduce_bypasses_min_notional(self) -> None:
        # Position 0.00205 BTC = $102.50 (above the $100 band). Closing it
        # floors to 0.002 BTC = $100 < 1.05*100 = $105 — a risk-INCREASING
        # order would be skipped, but de-risking must always be possible.
        ledger = make_ledger()
        buy(ledger, BTC, 0.00205, 50_000.0)
        orders = weights_to_orders({BTC: 0.0}, ledger, {BTC: 50_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].qty == pytest.approx(0.002, abs=1e-15)
        assert orders[0].reduce_only is True

    def test_equity_is_marked_from_closes(self) -> None:
        # +1 BTC @ 50_000, close now 60_000: E = 50_000 + 60_000 = 110_000.
        # Target 0.5 -> 55_000 vs current 60_000 -> SELL 5_000/60_000
        # = 0.08333... -> lot 0.001 -> 0.083.
        ledger = make_ledger()
        buy(ledger, BTC, 1.0, 50_000.0)
        orders = weights_to_orders({BTC: 0.5}, ledger, {BTC: 60_000.0}, INSTRUMENTS)
        assert len(orders) == 1
        assert orders[0].side is Side.SELL
        assert orders[0].qty == pytest.approx(0.083, abs=1e-15)


class TestDeterminismAndOrdering:
    def test_orders_sorted_by_instrument_id(self) -> None:
        closes = {BTC: 50_000.0, ETH: 3_000.0, DOGE: 0.5}
        targets = {ETH: 0.10, BTC: 0.10, DOGE: 0.05}
        orders = weights_to_orders(targets, make_ledger(), closes, INSTRUMENTS)
        assert [o.instrument_id for o in orders] == sorted(o.instrument_id for o in orders)

    def test_idempotent_client_order_ids(self) -> None:
        a = weights_to_orders({BTC: 0.10}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS, cycle_ts=99)
        b = weights_to_orders({BTC: 0.10}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS, cycle_ts=99)
        assert [o.client_order_id for o in a] == [o.client_order_id for o in b]
        assert a[0].client_order_id == f"rb-99-{BTC}"


class TestValidation:
    def test_unknown_instrument_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown instrument"):
            weights_to_orders({"BINANCE:PERP:XRPUSDT": 0.1}, make_ledger(), {}, INSTRUMENTS)

    def test_missing_close_for_target_raises(self) -> None:
        with pytest.raises(ValueError, match="close"):
            weights_to_orders({BTC: 0.1}, make_ledger(), {}, INSTRUMENTS)

    def test_missing_close_for_open_position_raises(self) -> None:
        ledger = make_ledger()
        buy(ledger, BTC, 1.0, 50_000.0)
        with pytest.raises(ValueError, match="open position"):
            weights_to_orders({ETH: 0.1}, ledger, {ETH: 3_000.0}, INSTRUMENTS)

    def test_non_finite_target_raises(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            weights_to_orders({BTC: float("nan")}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS)

    def test_negative_band_raises(self) -> None:
        with pytest.raises(ValueError, match="no_trade_band"):
            weights_to_orders(
                {BTC: 0.1}, make_ledger(), {BTC: 50_000.0}, INSTRUMENTS, no_trade_band=-0.1
            )
