"""Unit tests for alphaforge.costs — fee schedules and the TransactionCostModel.

Every numeric assertion is hand-computed in a comment next to it and checked
to 1e-12 absolute. Impact fixtures use ADV ratios that are exact powers of two
(e.g. 15_625 / 1_000_000 = 2**-6, sqrt = 0.125 exactly) so the expected values
are bit-clean, not just close.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pytest

from alphaforge.config.settings import load_settings
from alphaforge.core.errors import CostModelMisuse
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, Liquidity, MarketType, Side
from alphaforge.costs import (
    BINANCE_VIP0_PERP,
    BINANCE_VIP0_SPOT,
    MAX_ADV_PARTICIPATION,
    FeeSchedule,
    TransactionCostModel,
)

LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

# Exact-power-of-two impact fixture: 15_625 / 1_000_000 = 0.015625 = 2**-6,
# sqrt(2**-6) = 2**-3 = 0.125 exactly in float64.
NOTIONAL = 15_625.0
ADV = 1_000_000.0
SIGMA = 0.04


def make_perp(**overrides: object) -> Instrument:
    kwargs: dict[str, object] = {
        "instrument_id": "BINANCE:PERP:BTCUSDT",
        "asset_class": AssetClass.CRYPTO_PERP,
        "market_type": MarketType.PERP,
        "base": "BTC",
        "quote": "USDT",
        "tick_size": 0.1,
        "lot_size": 0.001,
        "min_qty": 0.001,
        "min_notional": 100.0,
        "contract_multiplier": 1.0,
        "can_short": True,
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 5.0,
        "funding_interval_hours": 8,
        "listed_ts": LISTED,
        "delisted_ts": None,
    }
    kwargs.update(overrides)
    return Instrument(**kwargs)  # type: ignore[arg-type]


def make_spot(**overrides: object) -> Instrument:
    kwargs: dict[str, object] = {
        "instrument_id": "BINANCE:SPOT:ETHUSDT",
        "asset_class": AssetClass.CRYPTO_SPOT,
        "market_type": MarketType.SPOT,
        "base": "ETH",
        "quote": "USDT",
        "tick_size": 0.01,
        "lot_size": 0.0001,
        "min_qty": 0.0001,
        "min_notional": 5.0,
        "can_short": False,
        "maker_fee_bps": 10.0,
        "taker_fee_bps": 10.0,
        "funding_interval_hours": None,
        "listed_ts": LISTED,
        "delisted_ts": None,
    }
    kwargs.update(overrides)
    return Instrument(**kwargs)  # type: ignore[arg-type]


PERP = make_perp()
SPOT = make_spot()


def approx(x: float) -> object:
    return pytest.approx(x, rel=0, abs=1e-12)


class TestFeeSchedule:
    def test_vip0_constants(self) -> None:
        assert FeeSchedule(maker_bps=10.0, taker_bps=10.0) == BINANCE_VIP0_SPOT
        assert FeeSchedule(maker_bps=2.0, taker_bps=5.0) == BINANCE_VIP0_PERP

    def test_fee_frac(self) -> None:
        # perp taker: 5.0 bps * 1e-4 = 5.0e-4; maker: 2.0 bps * 1e-4 = 2.0e-4
        assert BINANCE_VIP0_PERP.fee_frac(Liquidity.TAKER) == approx(5.0e-4)
        assert BINANCE_VIP0_PERP.fee_frac(Liquidity.MAKER) == approx(2.0e-4)
        # spot: 10 bps both sides => 1.0e-3
        assert BINANCE_VIP0_SPOT.fee_frac(Liquidity.TAKER) == approx(1.0e-3)
        assert BINANCE_VIP0_SPOT.fee_frac(Liquidity.MAKER) == approx(1.0e-3)

    def test_fee_quote_taker(self) -> None:
        # fee = |qty| * price * bps * 1e-4 = 2.0 * 50_000 * 5 * 1e-4 = 50.0
        assert BINANCE_VIP0_PERP.fee_quote(2.0, 50_000.0, Liquidity.TAKER) == approx(50.0)

    def test_fee_quote_sign_ignored(self) -> None:
        # |-2.0| * 50_000 * 2e-4 = 20.0 — fees are paid on sells too
        assert BINANCE_VIP0_PERP.fee_quote(-2.0, 50_000.0, Liquidity.MAKER) == approx(20.0)

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            BINANCE_VIP0_PERP.maker_bps = 0.0  # type: ignore[misc]

    @pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
    def test_invalid_rates_rejected(self, bad: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            FeeSchedule(maker_bps=bad, taker_bps=5.0)

    def test_fee_quote_invalid_price(self) -> None:
        with pytest.raises(ValueError, match="price"):
            BINANCE_VIP0_PERP.fee_quote(1.0, 0.0, Liquidity.TAKER)


class TestFeeRouting:
    def test_perp_routes_to_perp_schedule(self) -> None:
        model = TransactionCostModel()
        assert model.fee_frac(PERP, Liquidity.TAKER) == approx(5.0e-4)  # 5 bps
        assert model.fee_frac(PERP, Liquidity.MAKER) == approx(2.0e-4)  # 2 bps

    def test_spot_routes_to_spot_schedule(self) -> None:
        model = TransactionCostModel()
        assert model.fee_frac(SPOT, Liquidity.TAKER) == approx(1.0e-3)  # 10 bps
        assert model.fee_frac(SPOT, Liquidity.MAKER) == approx(1.0e-3)  # 10 bps


class TestHalfSpread:
    def test_default(self) -> None:
        # default 2.5 bps * 1e-4 = 2.5e-4
        assert TransactionCostModel().half_spread_frac(PERP) == approx(2.5e-4)

    def test_override_wins_only_for_named_instrument(self) -> None:
        model = TransactionCostModel(
            half_spread_overrides={"BINANCE:PERP:BTCUSDT": 1.0}  # 1 bp observed
        )
        assert model.half_spread_frac(PERP) == approx(1.0e-4)  # 1.0 * 1e-4
        assert model.half_spread_frac(SPOT) == approx(2.5e-4)  # falls back to default

    def test_overrides_copied_at_construction(self) -> None:
        table = {"BINANCE:PERP:BTCUSDT": 1.0}
        model = TransactionCostModel(half_spread_overrides=table)
        table["BINANCE:PERP:BTCUSDT"] = 99.0  # mutate the caller's dict afterwards
        assert model.half_spread_frac(PERP) == approx(1.0e-4)

    def test_negative_override_rejected(self) -> None:
        with pytest.raises(ValueError, match="half_spread_overrides"):
            TransactionCostModel(half_spread_overrides={"BINANCE:PERP:BTCUSDT": -1.0})


class TestImpact:
    def test_sqrt_law_exact(self) -> None:
        # impact = Y * sigma * sqrt(Q/ADV) = 1.0 * 0.04 * sqrt(2**-6)
        #        = 0.04 * 0.125 = 0.005   (sqrt and *0.125 are exact in float64)
        model = TransactionCostModel()
        assert model.impact_frac(NOTIONAL, ADV, SIGMA) == approx(0.005)

    def test_impact_coef_scales_linearly(self) -> None:
        # Y=2.0: 2.0 * 0.04 * 0.125 = 0.01
        model = TransactionCostModel(impact_coef=2.0)
        assert model.impact_frac(NOTIONAL, ADV, SIGMA) == approx(0.01)

    def test_misuse_guard_allows_exact_5pct_boundary(self) -> None:
        # notional == 0.05 * ADV is the last admissible point (guard is strict >)
        model = TransactionCostModel()
        boundary = MAX_ADV_PARTICIPATION * ADV
        # impact = 1.0 * 0.04 * sqrt(0.05 * ADV / ADV) = 0.04 * sqrt(0.05)
        expected = 0.04 * math.sqrt(boundary / ADV)
        assert model.impact_frac(boundary, ADV, SIGMA) == approx(expected)

    def test_misuse_guard_raises_just_above_5pct(self) -> None:
        model = TransactionCostModel()
        just_above = math.nextafter(MAX_ADV_PARTICIPATION * ADV, math.inf)
        with pytest.raises(CostModelMisuse, match="sqrt impact law invalid"):
            model.impact_frac(just_above, ADV, SIGMA)

    @pytest.mark.parametrize(
        ("notional", "adv", "sigma"),
        [
            (0.0, ADV, SIGMA),  # non-positive notional
            (-1.0, ADV, SIGMA),
            (NOTIONAL, 0.0, SIGMA),  # non-positive ADV
            (NOTIONAL, ADV, 0.0),  # non-positive vol
            (math.nan, ADV, SIGMA),  # non-finite inputs
            (NOTIONAL, math.inf, SIGMA),
            (NOTIONAL, ADV, math.nan),
        ],
    )
    def test_invalid_inputs_raise(self, notional: float, adv: float, sigma: float) -> None:
        with pytest.raises(CostModelMisuse, match="finite"):
            TransactionCostModel().impact_frac(notional, adv, sigma)


class TestLatency:
    def test_flat_placeholder(self) -> None:
        # 2.0 bps * 1e-4 = 2.0e-4, same for every instrument until Phase 12
        model = TransactionCostModel()
        assert model.latency_frac(PERP) == approx(2.0e-4)
        assert model.latency_frac(SPOT) == approx(2.0e-4)


class TestOnewayCost:
    def test_taker_total(self) -> None:
        # fee + hs + impact = 5.0e-4 + 2.5e-4 + 0.005 = 0.00575  (NO latency term)
        model = TransactionCostModel()
        assert model.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA) == approx(0.00575)

    def test_taker_is_default_liquidity(self) -> None:
        model = TransactionCostModel()
        explicit = model.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA, liquidity=Liquidity.TAKER)
        assert model.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA) == explicit

    def test_maker_total(self) -> None:
        # 2.0e-4 + 2.5e-4 + 0.005 = 0.00545
        model = TransactionCostModel()
        got = model.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA, liquidity=Liquidity.MAKER)
        assert got == approx(0.00545)

    def test_spot_schedule_in_total(self) -> None:
        # spot taker: 1.0e-3 + 2.5e-4 + 0.005 = 0.00625
        model = TransactionCostModel()
        assert model.oneway_cost_frac(SPOT, NOTIONAL, ADV, SIGMA) == approx(0.00625)

    def test_latency_excluded(self) -> None:
        # Cranking latency 2 bps -> 200 bps must not move the optimizer penalty:
        # latency is a fill-price phenomenon, not a cost-hurdle term.
        base = TransactionCostModel(latency_bps=2.0)
        loud = TransactionCostModel(latency_bps=200.0)
        assert base.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA) == approx(
            loud.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA)
        )

    def test_misuse_propagates(self) -> None:
        with pytest.raises(CostModelMisuse):
            TransactionCostModel().oneway_cost_frac(PERP, 0.06 * ADV, ADV, SIGMA)


class TestFillPrice:
    def test_buy_marked_up(self) -> None:
        # slip = hs + impact + latency = 2.5e-4 + 0.005 + 2.0e-4 = 0.00545
        # P = 100 * (1 + 0.00545) = 100.545
        model = TransactionCostModel()
        got = model.fill_price(PERP, Side.BUY, 100.0, NOTIONAL, ADV, SIGMA)
        assert got == approx(100.545)

    def test_sell_marked_down(self) -> None:
        # P = 100 * (1 - 0.00545) = 99.455
        model = TransactionCostModel()
        got = model.fill_price(PERP, Side.SELL, 100.0, NOTIONAL, ADV, SIGMA)
        assert got == approx(99.455)

    def test_latency_included(self) -> None:
        # Same model with latency zeroed: slip = 2.5e-4 + 0.005 = 0.00525,
        # P = 100.525; the 2 bps latency add-on is worth exactly 0.02 on a 100 ref.
        no_latency = TransactionCostModel(latency_bps=0.0)
        got = no_latency.fill_price(PERP, Side.BUY, 100.0, NOTIONAL, ADV, SIGMA)
        assert got == approx(100.525)

    def test_fee_not_in_price(self) -> None:
        # Maker vs taker fee never changes the fill price: the ledger charges
        # commission as a separate cash debit. Equal slippage either way.
        model = TransactionCostModel()
        price = model.fill_price(PERP, Side.BUY, 100.0, NOTIONAL, ADV, SIGMA)
        # reconstruct without any fee term: 100 * (1 + 2.5e-4 + 0.005 + 2.0e-4)
        assert price == approx(100.0 * (1.0 + 2.5e-4 + 0.005 + 2.0e-4))

    def test_override_flows_into_price(self) -> None:
        # hs override 1 bp: slip = 1.0e-4 + 0.005 + 2.0e-4 = 0.0053 -> P = 100.53
        model = TransactionCostModel(half_spread_overrides={"BINANCE:PERP:BTCUSDT": 1.0})
        got = model.fill_price(PERP, Side.BUY, 100.0, NOTIONAL, ADV, SIGMA)
        assert got == approx(100.53)

    @pytest.mark.parametrize("bad", [0.0, -100.0, math.nan, math.inf])
    def test_invalid_ref_price(self, bad: float) -> None:
        with pytest.raises(CostModelMisuse, match="ref_price"):
            TransactionCostModel().fill_price(PERP, Side.BUY, bad, NOTIONAL, ADV, SIGMA)

    def test_misuse_guard_applies(self) -> None:
        with pytest.raises(CostModelMisuse):
            TransactionCostModel().fill_price(PERP, Side.BUY, 100.0, 0.06 * ADV, ADV, SIGMA)


class TestConstructorValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"impact_coef": -0.1},
            {"impact_coef": math.nan},
            {"default_half_spread_bps": -1.0},
            {"latency_bps": math.inf},
        ],
    )
    def test_bad_params_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="finite"):
            TransactionCostModel(**kwargs)  # type: ignore[arg-type]


class TestFromSettings:
    @staticmethod
    def _write(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")

    def test_round_trip_with_custom_overlay(self, tmp_path: Path) -> None:
        self._write(
            tmp_path / "configs" / "base.yaml",
            """\
            costs:
              perp_maker_bps: 1.5
              perp_taker_bps: 4.0
              default_half_spread_bps: 3.0
              impact_coef: 0.8
              latency_addon_bps: 1.0
            """,
        )
        self._write(
            tmp_path / "configs" / "lab.yaml",
            """\
            costs:
              perp_taker_bps: 3.5
            """,
        )
        settings = load_settings(profile="lab", root=tmp_path)
        model = TransactionCostModel.from_settings(settings)

        # overlay wins for taker: 3.5 bps -> 3.5e-4; base survives for maker: 1.5e-4
        assert model.fee_frac(PERP, Liquidity.TAKER) == approx(3.5e-4)
        assert model.fee_frac(PERP, Liquidity.MAKER) == approx(1.5e-4)
        # spot fees pinned to the VIP0 constant (not configurable): 10 bps
        assert model.fee_frac(SPOT, Liquidity.TAKER) == approx(1.0e-3)
        # default half-spread 3.0 bps -> 3.0e-4
        assert model.half_spread_frac(PERP) == approx(3.0e-4)
        # impact_coef 0.8: 0.8 * 0.04 * 0.125 = 0.004
        assert model.impact_frac(NOTIONAL, ADV, SIGMA) == approx(0.8 * 0.04 * 0.125)
        # latency 1.0 bp -> 1.0e-4, present in fill price...
        # slip = 3.0e-4 + 0.004 + 1.0e-4 = 0.0044 -> P = 200 * 1.0044 = 200.88
        got = model.fill_price(PERP, Side.BUY, 200.0, NOTIONAL, ADV, SIGMA)
        assert got == approx(200.0 * (1.0 + 3.0e-4 + 0.8 * 0.04 * 0.125 + 1.0e-4))
        # ...but absent from the one-way cost: 3.5e-4 + 3.0e-4 + 0.004 = 0.00465
        oneway = model.oneway_cost_frac(PERP, NOTIONAL, ADV, SIGMA)
        assert oneway == approx(3.5e-4 + 3.0e-4 + 0.8 * 0.04 * 0.125)

    def test_repo_defaults_match_spec(self, tmp_path: Path) -> None:
        # An empty costs section yields the execDesign §3 defaults end to end.
        self._write(tmp_path / "configs" / "base.yaml", "costs: {}\n")
        model = TransactionCostModel.from_settings(load_settings(root=tmp_path))
        assert model.fee_frac(PERP, Liquidity.MAKER) == approx(2.0e-4)
        assert model.fee_frac(PERP, Liquidity.TAKER) == approx(5.0e-4)
        assert model.half_spread_frac(PERP) == approx(2.5e-4)
        assert model.latency_frac(PERP) == approx(2.0e-4)
        assert model.impact_frac(NOTIONAL, ADV, SIGMA) == approx(0.005)
