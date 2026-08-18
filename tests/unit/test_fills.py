"""Unit tests for alphaforge.backtest.fills (BarView / NextOpenFill).

The load-bearing assertions: NextOpenFill prices exactly per the shared
TransactionCostModel (open * (1 +/- (hs + impact + latency)), taker fee on the
executed notional), stamps the fill at the next bar's OPEN, and raises
LookaheadError on any attempt to fill on (or before) the decision bar — the
no-lookahead contract of execDesign.md §4.1 / leakageCritique.md findings 4/5.
"""

from __future__ import annotations

import math

import pytest

from alphaforge.backtest.fills import (
    BarView,
    FillModel,
    MakerFill,
    NextOpenFill,
    ParticipationCappedFill,
)
from alphaforge.core.errors import FillUnavailableError, LookaheadError
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import (
    AssetClass,
    Liquidity,
    MarketType,
    OrderRequest,
    OrderType,
    Side,
)
from alphaforge.costs import TransactionCostModel

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z (1h-aligned)
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

BTC = "BINANCE:PERP:BTCUSDT"

# Cost-model constants under test (defaults): hs 2.5 bps, latency 2 bps,
# perp taker 5 bps, impact Y = 1.0.
HS = 2.5e-4
LATENCY = 2e-4
TAKER_PERP = 5e-4
ADV = 1e8
SIGMA = 0.02


def make_instrument(
    *,
    instrument_id: str = BTC,
    asset_class: AssetClass = AssetClass.CRYPTO_PERP,
    market_type: MarketType = MarketType.PERP,
    funding_interval_hours: int | None = 8,
) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=asset_class,
        market_type=market_type,
        base=symbol.removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=funding_interval_hours,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def perp(instrument_id: str = BTC) -> Instrument:
    return make_instrument(instrument_id=instrument_id)


def make_order(
    *,
    side: Side = Side.BUY,
    qty: float = 100.0,
    decision_ts: int = T0 + HOUR,
    instrument_id: str = BTC,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=f"bt-{decision_ts}-{instrument_id}",
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        decision_ts=decision_ts,
        decision_price=100.0,
        reason="test",
    )


def make_bar(ts_open: int = T0 + HOUR, *, open_: float = 100.0) -> BarView:
    return BarView(
        ts_open=ts_open,
        open=open_,
        high=open_ * 1.01,
        low=open_ * 0.99,
        close=open_,
        volume=10.0,
        quote_volume=1_000.0,
    )


# --------------------------------------------------------------------- BarView


class TestBarView:
    def test_frozen(self) -> None:
        bar = make_bar()
        with pytest.raises(AttributeError):
            bar.open = 1.0  # type: ignore[misc]

    @pytest.mark.parametrize("field", ["open", "high", "low", "close"])
    def test_rejects_non_positive_prices(self, field: str) -> None:
        kwargs: dict[str, object] = {
            "ts_open": T0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
            "quote_volume": 100.0,
        }
        kwargs[field] = 0.0
        with pytest.raises(ValueError, match=field):
            BarView(**kwargs)  # type: ignore[arg-type]

    def test_rejects_negative_volume(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            BarView(
                ts_open=T0,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=-1.0,
                quote_volume=100.0,
            )

    def test_nan_quote_volume_allowed(self) -> None:
        bar = BarView(
            ts_open=T0,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
            quote_volume=math.nan,
        )
        assert math.isnan(bar.quote_volume)


# ----------------------------------------------------------------- NextOpenFill


class TestNextOpenFill:
    def test_satisfies_fill_model_protocol(self) -> None:
        # FillModel is a structural (non-runtime-checkable) Protocol: this
        # annotated assignment is the conformance test — mypy --strict fails
        # the suite if NextOpenFill drifts off the protocol.
        model: FillModel = NextOpenFill(TransactionCostModel())
        assert model is not None

    def test_buy_price_fee_and_timestamp_exact(self) -> None:
        # qty=100 at open 100: notional 10_000, Q/ADV = 1e-4, sqrt = 0.01
        # impact = 1.0 * 0.02 * 0.01 = 2e-4
        # slip   = hs + impact + latency = 2.5e-4 + 2e-4 + 2e-4 = 6.5e-4
        # price  = 100 * (1 + 6.5e-4) = 100.065
        # fee    = 5e-4 * 100 * 100.065 = 5.00325
        model = NextOpenFill(TransactionCostModel())
        order = make_order(side=Side.BUY, qty=100.0, decision_ts=T0 + HOUR)
        bar = make_bar(ts_open=T0 + HOUR, open_=100.0)
        fill = model.fill(order, perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.price == pytest.approx(100.065, abs=1e-12)
        assert fill.fee_quote == pytest.approx(5.00325, abs=1e-12)
        assert fill.ts == T0 + HOUR  # the NEXT bar's open, never the decision bar
        assert fill.liquidity is Liquidity.TAKER
        assert fill.side is Side.BUY
        assert fill.qty == 100.0
        assert fill.client_order_id == order.client_order_id

    def test_sell_price_mirrors_buy(self) -> None:
        # SELL: price = 100 * (1 - 6.5e-4) = 99.935; fee = 5e-4*100*99.935 = 4.99675
        model = NextOpenFill(TransactionCostModel())
        order = make_order(side=Side.SELL, qty=100.0)
        fill = model.fill(order, perp(), make_bar(), adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.price == pytest.approx(99.935, abs=1e-12)
        assert fill.fee_quote == pytest.approx(4.99675, abs=1e-12)

    def test_same_bar_fill_raises_lookahead(self) -> None:
        # Decision at close T0+1h; the DECISION bar opened at T0 — filling on it
        # would reference the decision bar: hard LookaheadError.
        model = NextOpenFill(TransactionCostModel())
        order = make_order(decision_ts=T0 + HOUR)
        decision_bar = make_bar(ts_open=T0)
        with pytest.raises(LookaheadError, match="never the same bar"):
            model.fill(order, perp(), decision_bar, adv_quote=ADV, sigma_daily=SIGMA)

    def test_next_bar_opening_at_decision_close_is_legal(self) -> None:
        # ts_open == decision_ts is exactly the contiguous t+1 bar: legal.
        model = NextOpenFill(TransactionCostModel())
        order = make_order(decision_ts=T0 + HOUR)
        fill = model.fill(
            order, perp(), make_bar(ts_open=T0 + HOUR), adv_quote=ADV, sigma_daily=SIGMA
        )
        assert fill.ts == order.decision_ts

    def test_instrument_mismatch_raises(self) -> None:
        model = NextOpenFill(TransactionCostModel())
        order = make_order(instrument_id=BTC)
        eth = make_instrument(instrument_id="BINANCE:PERP:ETHUSDT")
        with pytest.raises(ValueError, match="instrument mismatch"):
            model.fill(order, eth, make_bar(), adv_quote=ADV, sigma_daily=SIGMA)

    def test_spot_instrument_routes_spot_fee(self) -> None:
        # Spot VIP0 taker = 10 bps (vs 5 bps perp): fee doubles, price slip identical.
        spot = make_instrument(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            asset_class=AssetClass.CRYPTO_SPOT,
            market_type=MarketType.SPOT,
            funding_interval_hours=None,
        )
        model = NextOpenFill(TransactionCostModel())
        order = make_order(instrument_id="BINANCE:SPOT:BTCUSDT", qty=100.0)
        fill = model.fill(order, spot, make_bar(), adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.price == pytest.approx(100.065, abs=1e-12)
        assert fill.fee_quote == pytest.approx(10e-4 * 100.0 * 100.065, abs=1e-12)

    def test_fee_charged_on_executed_notional_not_reference(self) -> None:
        # fee = fee_frac * qty * P_fill (slipped), not qty * open.
        model = NextOpenFill(TransactionCostModel())
        order = make_order(side=Side.BUY, qty=100.0)
        fill = model.fill(order, perp(), make_bar(), adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.fee_quote == pytest.approx(TAKER_PERP * 100.0 * fill.price, abs=1e-15)
        assert fill.fee_quote > TAKER_PERP * 100.0 * 100.0  # strictly above ref-fee for a buy

    def test_cost_model_misuse_propagates(self) -> None:
        from alphaforge.core.errors import CostModelMisuse

        model = NextOpenFill(TransactionCostModel())
        order = make_order(qty=100.0)
        with pytest.raises(CostModelMisuse):
            # notional 10_000 > 5% of ADV 1_000 -> the tripwire must escape, never
            # be swallowed into a "cheap" fill.
            model.fill(order, perp(), make_bar(), adv_quote=1_000.0, sigma_daily=SIGMA)

    def test_cost_model_property_is_shared_instance(self) -> None:
        cost_model = TransactionCostModel()
        model = NextOpenFill(cost_model)
        assert model.cost_model is cost_model


# ------------------------------------------------------ ParticipationCappedFill


class TestParticipationCappedFill:
    def test_satisfies_fill_model_protocol(self) -> None:
        model: FillModel = ParticipationCappedFill(TransactionCostModel())
        assert isinstance(model, ParticipationCappedFill)

    def test_partial_fill_is_lot_floored_from_observed_quote_volume(self) -> None:
        model = ParticipationCappedFill(TransactionCostModel(), max_bar_participation=0.10)
        order = make_order(qty=100.0)
        # 10% * $1,000 / $100 = 1 base unit, exactly one lot.
        fill = model.fill(order, perp(), make_bar(), adv_quote=ADV, sigma_daily=SIGMA)

        assert fill.qty == 1.0
        assert fill.client_order_id == order.client_order_id
        assert fill.liquidity is Liquidity.TAKER
        expected = NextOpenFill(model.cost_model).fill(
            make_order(qty=1.0), perp(), make_bar(), adv_quote=ADV, sigma_daily=SIGMA
        )
        assert fill.price == expected.price
        assert fill.fee_quote == expected.fee_quote

    def test_order_below_cap_fills_in_full(self) -> None:
        model = ParticipationCappedFill(TransactionCostModel(), max_bar_participation=0.50)
        fill = model.fill(
            make_order(qty=2.0), perp(), make_bar(), adv_quote=ADV, sigma_daily=SIGMA
        )
        assert fill.qty == 2.0

    @pytest.mark.parametrize("quote_volume", [0.0, math.nan])
    def test_missing_or_zero_quote_volume_fails_closed(self, quote_volume: float) -> None:
        model = ParticipationCappedFill(TransactionCostModel())
        bar = BarView(
            ts_open=T0 + HOUR,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
            quote_volume=quote_volume,
        )
        with pytest.raises(FillUnavailableError, match="quote volume"):
            model.fill(make_order(), perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)

    def test_sub_lot_liquidity_fails_closed(self) -> None:
        model = ParticipationCappedFill(TransactionCostModel(), max_bar_participation=0.10)
        bar = BarView(
            ts_open=T0 + HOUR,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=0.5,
            quote_volume=50.0,
        )
        with pytest.raises(FillUnavailableError, match="below min_qty/min_notional"):
            model.fill(make_order(), perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)

    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.1, math.nan, math.inf])
    def test_rejects_invalid_participation(self, bad: float) -> None:
        with pytest.raises(ValueError, match="max_bar_participation"):
            ParticipationCappedFill(TransactionCostModel(), max_bar_participation=bad)


# -------------------------------------------------------------------- MakerFill

MAKER_PERP = 2e-4  # perp maker 2 bps (the maker-vs-taker delta is the whole edge)


def up_close_bar(ts_open: int = T0 + HOUR, *, open_: float = 100.0) -> BarView:
    """close > open -> a resting SELL ask fills passively; a resting BUY bid misses + chases."""
    return BarView(
        ts_open=ts_open, open=open_, high=open_ * 1.02, low=open_ * 0.995,
        close=open_ * 1.015, volume=10.0, quote_volume=1_000.0,
    )


def down_close_bar(ts_open: int = T0 + HOUR, *, open_: float = 100.0) -> BarView:
    """close < open -> a resting BUY bid fills passively; a resting SELL ask misses + chases."""
    return BarView(
        ts_open=ts_open, open=open_, high=open_ * 1.005, low=open_ * 0.98,
        close=open_ * 0.985, volume=10.0, quote_volume=1_000.0,
    )


class TestMakerFill:
    def test_satisfies_fill_model_protocol(self) -> None:
        model: FillModel = MakerFill(TransactionCostModel())
        assert isinstance(model, MakerFill)

    def test_passive_buy_fills_at_open_with_maker_fee(self) -> None:
        # down-close bar -> the resting BUY bid fills passively at the open
        model = MakerFill(TransactionCostModel())
        order = make_order(side=Side.BUY, qty=100.0)
        fill = model.fill(order, perp(), down_close_bar(), adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.liquidity is Liquidity.MAKER
        assert fill.price == 100.0  # filled AT the open, no half-spread crossed
        assert fill.fee_quote == pytest.approx(MAKER_PERP * 100.0 * 100.0)
        assert fill.ts == T0 + HOUR

    def test_passive_sell_fills_at_open_with_maker_fee(self) -> None:
        # up-close bar -> the resting SELL ask fills passively at the open
        model = MakerFill(TransactionCostModel())
        order = make_order(side=Side.SELL, qty=100.0)
        fill = model.fill(order, perp(), up_close_bar(), adv_quote=ADV, sigma_daily=SIGMA)
        assert fill.liquidity is Liquidity.MAKER
        assert fill.price == 100.0
        assert fill.fee_quote == pytest.approx(MAKER_PERP * 100.0 * 100.0)

    def test_buy_nonfill_chases_taker_with_adverse_selection(self) -> None:
        cost_model = TransactionCostModel()
        adv_bps = 5.0
        model = MakerFill(cost_model, adverse_selection_bps=adv_bps)
        order = make_order(side=Side.BUY, qty=100.0)
        bar = up_close_bar()  # bar rallied away from the resting bid -> miss + chase
        fill = model.fill(order, perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)
        # chased: TAKER, and strictly worse than both the open and the pure-taker price
        base = cost_model.fill_price(perp(), Side.BUY, bar.open, 100.0 * bar.open, ADV, SIGMA)
        expected = base + bar.open * adv_bps * 1e-4  # buy -> penalty pushes price UP
        assert fill.liquidity is Liquidity.TAKER
        assert fill.price == pytest.approx(expected)
        assert fill.price > base > bar.open
        assert fill.fee_quote == pytest.approx(TAKER_PERP * 100.0 * fill.price)

    def test_sell_nonfill_chases_taker_with_adverse_selection(self) -> None:
        cost_model = TransactionCostModel()
        adv_bps = 5.0
        model = MakerFill(cost_model, adverse_selection_bps=adv_bps)
        order = make_order(side=Side.SELL, qty=100.0)
        bar = down_close_bar()  # bar fell away from the resting ask -> miss + chase
        fill = model.fill(order, perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)
        base = cost_model.fill_price(perp(), Side.SELL, bar.open, 100.0 * bar.open, ADV, SIGMA)
        expected = base + (-1) * bar.open * adv_bps * 1e-4  # sell -> penalty pushes price DOWN
        assert fill.liquidity is Liquidity.TAKER
        assert fill.price == pytest.approx(expected)
        assert fill.price < base < bar.open
        assert fill.fee_quote == pytest.approx(TAKER_PERP * 100.0 * fill.price)

    def test_zero_adverse_selection_chase_equals_pure_taker_price(self) -> None:
        # with no adverse-selection penalty, a chased fill prices exactly like NextOpenFill
        cost_model = TransactionCostModel()
        order = make_order(side=Side.BUY, qty=100.0)
        bar = up_close_bar()  # BUY misses on an up-close bar -> chase
        maker = MakerFill(cost_model, adverse_selection_bps=0.0).fill(
            order, perp(), bar, adv_quote=ADV, sigma_daily=SIGMA
        )
        taker = NextOpenFill(cost_model).fill(order, perp(), bar, adv_quote=ADV, sigma_daily=SIGMA)
        assert maker.liquidity is Liquidity.TAKER
        assert maker.price == pytest.approx(taker.price)

    def test_lookahead_guard(self) -> None:
        model = MakerFill(TransactionCostModel())
        order = make_order(decision_ts=T0 + 2 * HOUR)
        with pytest.raises(LookaheadError):
            model.fill(order, perp(), make_bar(ts_open=T0 + HOUR), adv_quote=ADV, sigma_daily=SIGMA)

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_rejects_bad_adverse_selection(self, bad: float) -> None:
        with pytest.raises(ValueError, match="adverse_selection_bps"):
            MakerFill(TransactionCostModel(), adverse_selection_bps=bad)

    def test_cost_model_property_is_shared_instance(self) -> None:
        cost_model = TransactionCostModel()
        assert MakerFill(cost_model).cost_model is cost_model
