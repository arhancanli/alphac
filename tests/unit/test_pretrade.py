"""Unit tests for alphaforge.risk.limits and alphaforge.risk.pretrade.

Boundary discipline: every cap is tested AT the limit (passes) and a hair
over (fails). Limit values in fixtures are exact binary fractions (0.25, 0.5,
0.125, 0.03125 = 2**-5) and marks/quantities are chosen so the at-limit
notional is bit-exact — "at-limit passes" is then a true equality test, not a
tolerance artifact.
"""

from __future__ import annotations

import math

import pytest

from alphaforge.config.settings import RiskCfg
from alphaforge.core.errors import RiskLimitError
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, MarketType, OrderRequest, OrderType, Side
from alphaforge.costs import TransactionCostModel
from alphaforge.risk import CheckReport, PreTradeChecker, RiskLimits

LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z
DECISION_TS = 1_700_000_000_000

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"

EQUITY = 100_000.0
CLOSE = 100.0
ADV = 1_000_000.0
SIGMA = 0.04


def make_perp(instrument_id: str = BTC, base: str = "BTC") -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=100.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


INSTRUMENTS = {BTC: make_perp(), ETH: make_perp(ETH, "ETH")}


def make_order(
    iid: str = BTC,
    side: Side = Side.BUY,
    qty: float = 10.0,
    *,
    decision_price: float = CLOSE,
    reduce_only: bool = False,
    coid: str = "o1",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        instrument_id=iid,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=reduce_only,
        decision_ts=DECISION_TS,
        decision_price=decision_price,
        reason="rebalance",
    )


def make_limits(**overrides: float | int) -> RiskLimits:
    """Loose exact-binary defaults so each test isolates one cap."""
    kwargs: dict[str, float | int] = {
        "max_position_frac": 1.0,
        "max_gross": 1.0,
        "max_net": 1.0,
        "max_order_adv_frac": 0.03125,  # 2**-5, exact in float64
        "price_collar_frac": 0.0625,  # 2**-4, exact
    }
    kwargs.update(overrides)
    return RiskLimits(**kwargs)  # type: ignore[arg-type]


def run_check(
    orders: list[OrderRequest],
    limits: RiskLimits,
    *,
    equity: float = EQUITY,
    positions: dict[str, float] | None = None,
    closes: dict[str, float] | None = None,
    adv: float = ADV,
) -> CheckReport:
    checker = PreTradeChecker(limits, TransactionCostModel())
    return checker.check(
        orders,
        equity=equity,
        positions=positions or {},
        closes=closes or {BTC: CLOSE, ETH: CLOSE},
        adv_quote={BTC: adv, ETH: adv},
        sigma_daily={BTC: SIGMA, ETH: SIGMA},
        instruments=INSTRUMENTS,
    )


def reasons_text(report: CheckReport, i: int) -> str:
    return " ".join(report.verdicts[i].reasons)


# ----------------------------------------------------------------- RiskLimits


class TestRiskLimits:
    def test_defaults_valid(self) -> None:
        lim = RiskLimits()
        assert lim.max_position_frac == 0.15
        assert lim.max_gross == 1.0
        assert lim.max_net == 0.5
        assert lim.max_order_adv_frac == 0.01
        assert lim.price_collar_frac == 0.05
        assert lim.dd_half_frac == 0.10
        assert lim.dd_flat_frac == 0.15
        assert lim.var_confidence == 0.99
        assert lim.var_window_days == 365
        assert lim.staleness_max_bars == 2

    def test_from_cfg_flips_drawdown_sign(self) -> None:
        cfg = RiskCfg()  # dd_halve_gross=-0.10, dd_flat_halt=-0.15
        lim = RiskLimits.from_cfg(cfg)
        assert lim.dd_half_frac == 0.10
        assert lim.dd_flat_frac == 0.15
        assert lim.max_position_frac == cfg.max_position_frac
        assert lim.max_order_adv_frac == cfg.max_order_adv_frac
        assert lim.var_window_days == cfg.var_window_days
        assert lim.staleness_max_bars == cfg.staleness_max_bars

    def test_adv_cap_must_stay_inside_sqrt_law_tripwire(self) -> None:
        with pytest.raises(ValueError, match="max_order_adv_frac"):
            RiskLimits(max_order_adv_frac=0.06)  # > cost model's 5% tripwire

    def test_orderings_enforced(self) -> None:
        with pytest.raises(ValueError, match="max_net"):
            RiskLimits(max_net=1.5, max_gross=1.0)
        with pytest.raises(ValueError, match="max_position_frac"):
            RiskLimits(max_position_frac=0.5, max_gross=0.4, max_net=0.4)
        with pytest.raises(ValueError, match="dd_half_frac"):
            RiskLimits(dd_half_frac=0.15, dd_flat_frac=0.10)
        with pytest.raises(ValueError, match="finite"):
            RiskLimits(max_gross=math.inf)

    def test_frozen(self) -> None:
        lim = RiskLimits()
        with pytest.raises(AttributeError):
            lim.max_gross = 2.0  # type: ignore[misc]


# ----------------------------------------------------------- per-check matrix


class TestPositionCap:
    LIMITS = make_limits(max_position_frac=0.25)  # cap = 25_000.0 exactly

    def test_at_limit_passes(self) -> None:
        report = run_check([make_order(qty=250.0)], self.LIMITS)
        assert report.verdicts[0].accepted

    def test_hair_over_fails(self) -> None:
        report = run_check([make_order(qty=250.0 + 1e-9)], self.LIMITS)
        assert not report.verdicts[0].accepted
        assert "position_cap" in reasons_text(report, 0)

    def test_existing_position_counts(self) -> None:
        # 200 held + 51 ordered = 251 -> 25_100 > 25_000.
        report = run_check([make_order(qty=51.0)], self.LIMITS, positions={BTC: 200.0})
        assert "position_cap" in reasons_text(report, 0)

    def test_short_side_symmetric(self) -> None:
        ok = run_check([make_order(side=Side.SELL, qty=250.0)], self.LIMITS)
        assert ok.verdicts[0].accepted
        bad = run_check([make_order(side=Side.SELL, qty=250.0 + 1e-9)], self.LIMITS)
        assert "position_cap" in reasons_text(bad, 0)


class TestGrossCap:
    # Short BTC offsets long ETH so net stays 0 and ONLY gross is exercised.
    LIMITS = make_limits(max_position_frac=0.5, max_gross=0.5, max_net=0.5)

    def test_at_limit_passes(self) -> None:
        report = run_check(
            [make_order(ETH, qty=250.0)], self.LIMITS, positions={BTC: -250.0}
        )  # gross = 25_000 + 25_000 = 50_000 = 0.5 * equity exactly
        assert report.verdicts[0].accepted

    def test_hair_over_fails(self) -> None:
        report = run_check(
            [make_order(ETH, qty=250.0 + 1e-9)], self.LIMITS, positions={BTC: -250.0}
        )
        assert not report.verdicts[0].accepted
        assert "gross_cap" in reasons_text(report, 0)
        assert "net_cap" not in reasons_text(report, 0)

    def test_sequential_book_application(self) -> None:
        # Each order alone is fine; the second breaches gross only because the
        # first was applied to the working book (deterministic batch order).
        o1 = make_order(qty=300.0, coid="o1")
        o2 = make_order(qty=300.0, coid="o2")
        limits = make_limits(max_position_frac=0.5, max_gross=0.5, max_net=0.5)
        report = run_check([o1, o2], limits)
        assert report.verdicts[0].accepted
        assert not report.verdicts[1].accepted
        assert "gross_cap" in reasons_text(report, 1)
        assert report.accepted == (o1,)


class TestNetCap:
    LIMITS = make_limits(max_net=0.5)
    BIG_ADV = 16_000_000.0  # ADV cap = 0.03125 * 16e6 = 500_000: never interferes

    def test_at_limit_passes(self) -> None:
        # net = 50_000 = 0.5 * equity exactly
        report = run_check([make_order(qty=500.0)], self.LIMITS, adv=self.BIG_ADV)
        assert report.verdicts[0].accepted

    def test_hair_over_fails(self) -> None:
        report = run_check([make_order(qty=500.0 + 1e-9)], self.LIMITS, adv=self.BIG_ADV)
        assert "net_cap" in reasons_text(report, 0)

    def test_absolute_value_short(self) -> None:
        report = run_check(
            [make_order(side=Side.SELL, qty=500.0 + 1e-9)], self.LIMITS, adv=self.BIG_ADV
        )
        assert "net_cap" in reasons_text(report, 0)

    def test_offsetting_short_relieves_net(self) -> None:
        # Long 500 ETH against short 250 BTC: net = 25_000 < 50_000 cap.
        report = run_check(
            [make_order(ETH, qty=500.0 + 1e-9)],
            self.LIMITS,
            positions={BTC: -250.0},
            adv=self.BIG_ADV,
        )
        assert "net_cap" not in reasons_text(report, 0)


class TestAdvParticipation:
    LIMITS = make_limits()  # max_order_adv_frac = 0.03125 -> cap 31_250.0 exactly

    def test_at_limit_passes(self) -> None:
        report = run_check([make_order(qty=312.5)], self.LIMITS)
        assert report.verdicts[0].accepted

    def test_hair_over_fails(self) -> None:
        report = run_check([make_order(qty=312.5 + 1e-9)], self.LIMITS)
        assert "adv_participation" in reasons_text(report, 0)

    def test_cap_keeps_cost_model_in_valid_regime(self) -> None:
        # The 1%-class pre-trade cap sits below the cost model's 5%
        # CostModelMisuse tripwire, so accepted orders can ALWAYS be priced.
        report = run_check([make_order(qty=312.5)], self.LIMITS)
        assert math.isfinite(report.verdicts[0].est_cost_frac)


class TestPriceCollar:
    LIMITS = make_limits()  # price_collar_frac = 0.0625 -> band = 6.25 exactly

    def test_at_limit_passes_both_sides(self) -> None:
        up = run_check([make_order(qty=10.0, decision_price=106.25)], self.LIMITS)
        down = run_check([make_order(qty=10.0, decision_price=93.75)], self.LIMITS)
        assert up.verdicts[0].accepted
        assert down.verdicts[0].accepted

    def test_hair_over_fails(self) -> None:
        report = run_check([make_order(qty=10.0, decision_price=106.25 + 1e-6)], self.LIMITS)
        assert "price_collar" in reasons_text(report, 0)

    def test_default_collar_five_percent(self) -> None:
        lim = make_limits(price_collar_frac=0.05)
        ok = run_check([make_order(qty=10.0, decision_price=105.0)], lim)
        bad = run_check([make_order(qty=10.0, decision_price=105.000001)], lim)
        assert ok.verdicts[0].accepted
        assert "price_collar" in reasons_text(bad, 0)


# ------------------------------------------------------- reduce-only handling


class TestReduceOnly:
    # Book ALREADY violates position (12_500) and gross (25_000) caps.
    LIMITS = make_limits(max_position_frac=0.125, max_gross=0.25, max_net=0.25)

    def test_exempt_from_opening_caps(self) -> None:
        order = make_order(side=Side.SELL, qty=150.0, reduce_only=True)
        report = run_check([order], self.LIMITS, positions={BTC: 400.0})
        assert report.verdicts[0].accepted
        assert report.accepted == (order,)

    def test_never_exempt_from_collar(self) -> None:
        order = make_order(side=Side.SELL, qty=50.0, reduce_only=True, decision_price=120.0)
        report = run_check([order], self.LIMITS, positions={BTC: 100.0})
        assert "price_collar" in reasons_text(report, 0)

    def test_must_actually_reduce(self) -> None:
        flip = make_order(side=Side.SELL, qty=150.0, reduce_only=True)
        grow = make_order(side=Side.BUY, qty=10.0, reduce_only=True)
        flat = make_order(side=Side.SELL, qty=10.0, reduce_only=True)
        for order, positions in ((flip, {BTC: 100.0}), (grow, {BTC: 100.0}), (flat, {})):
            report = run_check([order], make_limits(), positions=positions)
            assert "reduce_only_not_reducing" in reasons_text(report, 0)


# --------------------------------------------- rejection + systemic semantics


class TestRejectionSemantics:
    def test_rejected_orders_dropped_never_resized(self) -> None:
        order = make_order(qty=250.0 + 1e-9)
        report = run_check([order], make_limits(max_position_frac=0.25))
        assert report.accepted == ()
        assert report.rejected[0].order is order
        assert report.rejected[0].order.qty == 250.0 + 1e-9
        assert math.isnan(report.rejected[0].est_cost_frac)
        assert report.n_accepted == 0
        assert report.n_rejected == 1

    def test_missing_inputs_reject_with_reasons(self) -> None:
        order = make_order("BINANCE:PERP:DOGEUSDT", qty=10.0)
        report = run_check([order], make_limits())
        text = reasons_text(report, 0)
        for tag in ("unknown_instrument", "missing_close", "missing_adv", "missing_sigma"):
            assert tag in text

    def test_accepted_cost_annotation_matches_model(self) -> None:
        model = TransactionCostModel()
        order = make_order(qty=100.0)
        checker = PreTradeChecker(make_limits(), model)
        report = checker.check(
            [order],
            equity=EQUITY,
            positions={},
            closes={BTC: CLOSE},
            adv_quote={BTC: ADV},
            sigma_daily={BTC: SIGMA},
            instruments=INSTRUMENTS,
        )
        expected = model.oneway_cost_frac(INSTRUMENTS[BTC], 100.0 * CLOSE, ADV, SIGMA)
        assert report.verdicts[0].est_cost_frac == expected

    def test_invalid_equity_raises(self) -> None:
        for equity in (0.0, -1.0, math.nan, math.inf):
            with pytest.raises(RiskLimitError, match="equity"):
                run_check([make_order()], make_limits(), equity=equity)


class TestSystemicBreach:
    # max_gross = 0.25 -> cap 25_000.0 exactly; book gross = 40_000.
    LIMITS = make_limits(max_position_frac=0.25, max_gross=0.25, max_net=0.25)

    def test_book_over_gross_with_no_orders_raises(self) -> None:
        with pytest.raises(RiskLimitError, match="systemic"):
            run_check([], self.LIMITS, positions={BTC: 400.0})

    def test_reduce_only_to_exactly_cap_does_not_raise(self) -> None:
        order = make_order(side=Side.SELL, qty=150.0, reduce_only=True)
        report = run_check([order], self.LIMITS, positions={BTC: 400.0})  # 250 -> 25_000
        assert report.verdicts[0].accepted

    def test_insufficient_reduction_still_raises(self) -> None:
        order = make_order(side=Side.SELL, qty=149.0, reduce_only=True)  # 251 -> 25_100
        with pytest.raises(RiskLimitError, match="systemic"):
            run_check([order], self.LIMITS, positions={BTC: 400.0})

    def test_opens_never_relieve_the_systemic_check(self) -> None:
        # An opening SELL would reduce gross arithmetically, but opens are
        # exactly what gets dropped in the systemic scenario — still raises.
        order = make_order(side=Side.SELL, qty=150.0, reduce_only=False)
        with pytest.raises(RiskLimitError, match="systemic"):
            run_check([order], self.LIMITS, positions={BTC: 400.0})
