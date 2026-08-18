"""Point-in-time option surface and lifecycle contract tests."""

from __future__ import annotations

import pytest

from alphaforge.core.errors import CostModelMisuse, LookaheadError, SchemaError
from alphaforge.core.instruments import Instrument
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.types import AssetClass, Liquidity, MarketType
from alphaforge.costs.model import TransactionCostModel
from alphaforge.execution.options import (
    AssignmentNotice,
    ExerciseStyle,
    OptionContract,
    OptionQuote,
    OptionRight,
    OptionSettlement,
    OptionSurfaceIntegrityError,
    OptionSurfaceSnapshot,
    OptionSurfaceViolationType,
    SettlementStyle,
    apply_assignment,
    expiry_delivery,
    intrinsic_value,
)


def _contract(
    *,
    instrument_id: str = "OPRA:OPTION:AAPL20260918C00200000",
    right: OptionRight = OptionRight.CALL,
    strike: float = 200.0,
    exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN,
    settlement_style: SettlementStyle = SettlementStyle.PHYSICAL,
    metadata_available_at: int = 100,
    underlying_instrument_id: str = "XUSE:CASH:AAPLUSD",
    expiration_ts: int = 1_000,
    last_trade_ts: int = 990,
) -> OptionContract:
    return OptionContract(
        instrument_id=instrument_id,
        underlying_instrument_id=underlying_instrument_id,
        right=right,
        strike=strike,
        expiration_ts=expiration_ts,
        last_trade_ts=last_trade_ts,
        listed_ts=10,
        metadata_available_at=metadata_available_at,
        exercise_style=exercise_style,
        settlement_style=settlement_style,
        contract_multiplier=100.0,
    )


def _quote(
    *,
    instrument_id: str,
    observed_ts: int = 190,
    available_at: int = 195,
    bid: float = 4.0,
    ask: float = 4.2,
    bid_size: float = 10.0,
    ask_size: float = 8.0,
    premium_currency: str = "USD",
) -> OptionQuote:
    return OptionQuote(
        instrument_id=instrument_id,
        premium_currency=premium_currency,
        observed_ts=observed_ts,
        available_at=available_at,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
    )


def _settlement(*, price: float, available_at: int = 1_010) -> OptionSettlement:
    return OptionSettlement(
        underlying_instrument_id="XUSE:CASH:AAPLUSD",
        settlement_ts=1_000,
        available_at=available_at,
        price=price,
    )


def test_contract_requires_option_identity_and_valid_lifecycle() -> None:
    with pytest.raises(ValueError, match=r"MarketType\.OPTION"):
        _contract(instrument_id="XUSE:CASH:AAPLUSD")
    with pytest.raises(ValueError, match="last_trade_ts cannot follow"):
        OptionContract(
            instrument_id="OPRA:OPTION:AAPL20260918C00200000",
            underlying_instrument_id="XUSE:CASH:AAPLUSD",
            right=OptionRight.CALL,
            strike=200.0,
            expiration_ts=900,
            last_trade_ts=990,
            listed_ts=10,
            metadata_available_at=100,
            exercise_style=ExerciseStyle.AMERICAN,
            settlement_style=SettlementStyle.PHYSICAL,
            contract_multiplier=100.0,
        )


def test_option_taxonomy_is_canonical_and_costs_fail_closed() -> None:
    iid = SymbolMapper.to_instrument_id(
        "opra", MarketType.OPTION, "AAPL20260918C00200000USD"
    )
    instrument = Instrument(
        instrument_id=iid,
        asset_class=AssetClass.OPTION,
        market_type=MarketType.OPTION,
        base="AAPL20260918C00200000",
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=0.0,
        contract_multiplier=100.0,
        can_short=True,
        maker_fee_bps=0.0,
        taker_fee_bps=0.0,
        funding_interval_hours=None,
        listed_ts=10,
        delisted_ts=1_000,
    )
    with pytest.raises(CostModelMisuse, match="no transaction-fee schedule"):
        TransactionCostModel().fee_frac(instrument, Liquidity.TAKER)
    with pytest.raises(SchemaError, match="only crypto PERP/SPOT"):
        SymbolMapper.to_ccxt(iid)


def test_quote_rejects_crossed_market_and_impossible_availability() -> None:
    iid = _contract().instrument_id
    with pytest.raises(ValueError, match="crossed"):
        OptionQuote(
            instrument_id=iid,
            premium_currency="USD",
            observed_ts=100,
            available_at=100,
            bid=5.0,
            ask=4.0,
            bid_size=1.0,
            ask_size=1.0,
        )
    with pytest.raises(ValueError, match="cannot precede"):
        _quote(instrument_id=iid, observed_ts=200, available_at=199)
    with pytest.raises(ValueError, match="uppercase alphanumerics"):
        _quote(instrument_id=iid, premium_currency="usd")


def test_surface_rejects_future_known_terms_quotes_and_staleness() -> None:
    future_terms = _contract(metadata_available_at=201)
    quote = _quote(instrument_id=future_terms.instrument_id)
    with pytest.raises(LookaheadError, match="terms"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(future_terms,),
            quotes=(quote,),
        )

    contract = _contract()
    future_quote = _quote(instrument_id=contract.instrument_id, available_at=201)
    with pytest.raises(LookaheadError, match="quote"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(contract,),
            quotes=(future_quote,),
        )
    stale = _quote(instrument_id=contract.instrument_id, observed_ts=170, available_at=175)
    with pytest.raises(ValueError, match="stale"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(contract,),
            quotes=(stale,),
        )


def test_surface_never_interpolates_unquoted_contracts() -> None:
    call = _contract()
    put = _contract(
        instrument_id="OPRA:OPTION:AAPL20260918P00200000",
        right=OptionRight.PUT,
    )
    quote = _quote(instrument_id=call.instrument_id)
    snapshot = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(call, put),
        quotes=(quote,),
    )
    assert snapshot.complete_quotes() == ((call, quote),)
    assert snapshot.underlying_instrument_id == "XUSE:CASH:AAPLUSD"
    assert snapshot.static_arbitrage_violations() == ()


def test_surface_requires_one_underlying_unique_terms_and_active_lifecycle() -> None:
    call = _contract()
    with pytest.raises(ValueError, match="at least one"):
        OptionSurfaceSnapshot(decision_ts=200, max_quote_age_ms=20, contracts=(), quotes=())

    other_underlying = _contract(
        instrument_id="OPRA:OPTION:MSFT20260918C00200000",
        underlying_instrument_id="XNAS:CASH:MSFTUSD",
    )
    with pytest.raises(ValueError, match="one underlying"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(call, other_underlying),
            quotes=(),
        )

    duplicate_terms = _contract(instrument_id="OPRA:OPTION:AAPL-DUPLICATE")
    with pytest.raises(ValueError, match="duplicate economic"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(call, duplicate_terms),
            quotes=(),
        )

    expired = _contract(expiration_ts=180, last_trade_ts=180)
    with pytest.raises(ValueError, match="no longer tradable"):
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(expired,),
            quotes=(),
        )


def test_surface_rejects_quote_outside_contract_lifecycle() -> None:
    contract = _contract(metadata_available_at=10)
    prelisting = _quote(
        instrument_id=contract.instrument_id,
        observed_ts=9,
        available_at=10,
    )
    with pytest.raises(ValueError, match="tradable lifecycle"):
        OptionSurfaceSnapshot(
            decision_ts=20,
            max_quote_age_ms=20,
            contracts=(contract,),
            quotes=(prelisting,),
        )


@pytest.mark.parametrize(
    ("right", "low_bid", "low_ask", "high_bid", "high_ask", "violation_type"),
    [
        (OptionRight.CALL, 4.8, 5.0, 6.0, 6.2, OptionSurfaceViolationType.CALL_MONOTONICITY),
        (OptionRight.PUT, 6.0, 6.2, 4.8, 5.0, OptionSurfaceViolationType.PUT_MONOTONICITY),
    ],
)
def test_surface_rejects_guaranteed_executable_monotonicity_violations(
    right: OptionRight,
    low_bid: float,
    low_ask: float,
    high_bid: float,
    high_ask: float,
    violation_type: OptionSurfaceViolationType,
) -> None:
    low = _contract(
        instrument_id=f"OPRA:OPTION:AAPL-190-{right.value.upper()}",
        right=right,
        strike=190.0,
    )
    high = _contract(
        instrument_id=f"OPRA:OPTION:AAPL-200-{right.value.upper()}",
        right=right,
        strike=200.0,
    )
    quotes = (
        _quote(instrument_id=low.instrument_id, bid=low_bid, ask=low_ask),
        _quote(instrument_id=high.instrument_id, bid=high_bid, ask=high_ask),
    )
    with pytest.raises(OptionSurfaceIntegrityError) as exc_info:
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=(low, high),
            quotes=quotes,
        )
    assert exc_info.value.violations[0].violation_type is violation_type
    assert exc_info.value.violations[0].strikes == (190.0, 200.0)


def test_surface_rejects_nonuniform_strike_convexity_violation() -> None:
    contracts = tuple(
        _contract(instrument_id=f"OPRA:OPTION:AAPL-{strike:.0f}-CALL", strike=strike)
        for strike in (190.0, 200.0, 220.0)
    )
    quotes = (
        _quote(instrument_id=contracts[0].instrument_id, bid=11.8, ask=12.0),
        _quote(instrument_id=contracts[1].instrument_id, bid=10.0, ask=10.2),
        _quote(instrument_id=contracts[2].instrument_id, bid=1.8, ask=2.0),
    )
    with pytest.raises(OptionSurfaceIntegrityError) as exc_info:
        OptionSurfaceSnapshot(
            decision_ts=200,
            max_quote_age_ms=20,
            contracts=contracts,
            quotes=quotes,
        )
    assert [item.violation_type for item in exc_info.value.violations] == [
        OptionSurfaceViolationType.STRIKE_CONVEXITY
    ]
    assert exc_info.value.violations[0].strikes == (190.0, 200.0, 220.0)


def test_surface_does_not_invent_arbitrage_from_non_executable_or_wide_quotes() -> None:
    low = _contract(instrument_id="OPRA:OPTION:AAPL-190-CALL", strike=190.0)
    high = _contract(instrument_id="OPRA:OPTION:AAPL-200-CALL", strike=200.0)
    snapshot = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(low, high),
        quotes=(
            _quote(instrument_id=low.instrument_id, bid=4.8, ask=5.0),
            _quote(instrument_id=high.instrument_id, bid=6.0, ask=6.2, bid_size=0.0),
        ),
    )
    assert snapshot.static_arbitrage_violations() == ()


def test_surface_checks_are_series_local_and_ignore_float_roundoff() -> None:
    near = _contract(instrument_id="OPRA:OPTION:AAPL-190-NEAR", strike=190.0)
    far = _contract(
        instrument_id="OPRA:OPTION:AAPL-200-FAR",
        strike=200.0,
        expiration_ts=1_100,
        last_trade_ts=1_090,
    )
    separate_expiries = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(near, far),
        quotes=(
            _quote(instrument_id=near.instrument_id, bid=4.8, ask=5.0),
            _quote(instrument_id=far.instrument_id, bid=6.0, ask=6.2),
        ),
    )
    assert separate_expiries.static_arbitrage_violations() == ()

    high_same_expiry = _contract(
        instrument_id="OPRA:OPTION:AAPL-200-CURRENCY",
        strike=200.0,
    )
    separate_currencies = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(near, high_same_expiry),
        quotes=(
            _quote(instrument_id=near.instrument_id, bid=4.8, ask=5.0),
            _quote(
                instrument_id=high_same_expiry.instrument_id,
                bid=6.0,
                ask=6.2,
                premium_currency="EUR",
            ),
        ),
    )
    assert separate_currencies.static_arbitrage_violations() == ()

    high = _contract(instrument_id="OPRA:OPTION:AAPL-200-NEAR", strike=200.0)
    roundoff = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(near, high),
        quotes=(
            _quote(instrument_id=near.instrument_id, bid=4.8, ask=5.0),
            _quote(instrument_id=high.instrument_id, bid=5.0 + 5e-13, ask=5.2),
        ),
    )
    assert roundoff.static_arbitrage_violations() == ()


def test_intrinsic_value_is_right_specific() -> None:
    assert intrinsic_value(_contract(), 215.0) == 15.0
    assert intrinsic_value(_contract(right=OptionRight.PUT), 185.0) == 15.0


def test_cash_settled_expiry_uses_official_available_price() -> None:
    contract = _contract(
        exercise_style=ExerciseStyle.EUROPEAN,
        settlement_style=SettlementStyle.CASH,
    )
    settlement = _settlement(price=215.0)
    with pytest.raises(LookaheadError, match="official settlement"):
        expiry_delivery(
            contract,
            signed_contracts=2.0,
            settlement=settlement,
            decision_ts=1_005,
        )
    delivery = expiry_delivery(
        contract,
        signed_contracts=2.0,
        settlement=settlement,
        decision_ts=1_010,
    )
    assert delivery.cash_delta == 3_000.0
    assert delivery.underlying_qty_delta == 0.0
    assert delivery.option_contracts_delta == -2.0


def test_expiry_rejects_pre_expiration_settlement_timestamp() -> None:
    settlement = OptionSettlement(
        underlying_instrument_id="XUSE:CASH:AAPLUSD",
        settlement_ts=999,
        available_at=1_010,
        price=215.0,
    )
    with pytest.raises(ValueError, match="cannot precede option expiration"):
        expiry_delivery(
            _contract(),
            signed_contracts=1.0,
            settlement=settlement,
            decision_ts=1_010,
        )


@pytest.mark.parametrize(
    ("right", "signed_contracts", "price", "underlying_delta", "cash_delta"),
    [
        (OptionRight.CALL, 2.0, 215.0, 200.0, -40_000.0),
        (OptionRight.CALL, -2.0, 215.0, -200.0, 40_000.0),
        (OptionRight.PUT, 2.0, 185.0, -200.0, 40_000.0),
        (OptionRight.PUT, -2.0, 185.0, 200.0, -40_000.0),
    ],
)
def test_physical_expiry_delivery_has_signed_stock_and_strike_cash(
    right: OptionRight,
    signed_contracts: float,
    price: float,
    underlying_delta: float,
    cash_delta: float,
) -> None:
    delivery = expiry_delivery(
        _contract(right=right),
        signed_contracts=signed_contracts,
        settlement=_settlement(price=price),
        decision_ts=1_010,
    )
    assert delivery.underlying_qty_delta == underlying_delta
    assert delivery.cash_delta == cash_delta
    assert delivery.option_contracts_delta == -signed_contracts


def test_expiry_lapse_closes_option_without_delivery() -> None:
    delivery = expiry_delivery(
        _contract(),
        signed_contracts=3.0,
        settlement=_settlement(price=200.005),
        decision_ts=1_010,
        auto_exercise_threshold=0.01,
    )
    assert delivery.event_type == "expiry_lapse"
    assert delivery.option_contracts_delta == -3.0
    assert delivery.underlying_qty_delta == 0.0
    assert delivery.cash_delta == 0.0


def test_assignment_notice_is_authoritative_and_point_in_time() -> None:
    contract = _contract()
    notice = AssignmentNotice(
        instrument_id=contract.instrument_id,
        assigned_contracts=2.0,
        event_ts=500,
        available_at=510,
    )
    with pytest.raises(LookaheadError, match="assignment notice"):
        apply_assignment(
            contract,
            short_contracts=3.0,
            notice=notice,
            decision_ts=505,
        )
    delivery = apply_assignment(
        contract,
        short_contracts=3.0,
        notice=notice,
        decision_ts=510,
    )
    assert delivery.option_contracts_delta == 2.0
    assert delivery.underlying_qty_delta == -200.0
    assert delivery.cash_delta == 40_000.0


def test_assignment_fails_closed_for_impossible_terms_or_quantity() -> None:
    contract = _contract(exercise_style=ExerciseStyle.EUROPEAN)
    notice = AssignmentNotice(
        instrument_id=contract.instrument_id,
        assigned_contracts=2.0,
        event_ts=500,
        available_at=510,
    )
    with pytest.raises(ValueError, match="American"):
        apply_assignment(
            contract,
            short_contracts=3.0,
            notice=notice,
            decision_ts=510,
        )
    with pytest.raises(ValueError, match="exceed"):
        apply_assignment(
            _contract(),
            short_contracts=1.0,
            notice=notice,
            decision_ts=510,
        )

    expired_notice = AssignmentNotice(
        instrument_id=_contract().instrument_id,
        assigned_contracts=1.0,
        event_ts=1_000,
        available_at=1_010,
    )
    with pytest.raises(ValueError, match="must precede"):
        apply_assignment(
            _contract(),
            short_contracts=1.0,
            notice=expired_notice,
            decision_ts=1_010,
        )
