from __future__ import annotations

import math
from dataclasses import replace

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.market_status import (
    MarketStatus,
    MarketStatusEvent,
    StaticMarketStatusProvider,
)
from alphaforge.execution.options import (
    ExerciseStyle,
    OptionContract,
    OptionQuote,
    OptionRight,
    OptionSurfaceSnapshot,
    SettlementStyle,
)
from alphaforge.execution.options_packages import (
    DISPLAYED_ATOMIC_CROSS_ASSUMPTION,
    OptionLegExecution,
    OptionPackageExecution,
    OptionPackageExecutionStatus,
    OptionPackageLeg,
    OptionPackageMarketStatus,
    OptionPackageOrder,
    OptionPackageRejectReason,
    OptionPackageTimeInForce,
    execute_displayed_option_package,
)

CALL_ID = "OPRA:OPTION:AAPL20260918C00200000"
PUT_ID = "OPRA:OPTION:AAPL20260918P00200000"


def _contract(
    instrument_id: str,
    *,
    right: OptionRight,
    multiplier: float = 100.0,
) -> OptionContract:
    return OptionContract(
        instrument_id=instrument_id,
        underlying_instrument_id="XUSE:CASH:AAPLUSD",
        right=right,
        strike=200.0,
        expiration_ts=1_000,
        last_trade_ts=990,
        listed_ts=10,
        metadata_available_at=100,
        exercise_style=ExerciseStyle.AMERICAN,
        settlement_style=SettlementStyle.PHYSICAL,
        contract_multiplier=multiplier,
    )


def _quote(
    instrument_id: str,
    *,
    bid: float,
    ask: float,
    bid_size: float = 8.0,
    ask_size: float = 10.0,
    premium_currency: str = "USD",
) -> OptionQuote:
    return OptionQuote(
        instrument_id=instrument_id,
        premium_currency=premium_currency,
        observed_ts=190,
        available_at=195,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
    )


def _surface(
    *,
    call_quote: OptionQuote | None = None,
    put_quote: OptionQuote | None = None,
) -> OptionSurfaceSnapshot:
    quotes = tuple(
        quote
        for quote in (
            call_quote or _quote(CALL_ID, bid=4.8, ask=5.0),
            put_quote or _quote(PUT_ID, bid=3.0, ask=3.2),
        )
        if quote is not None
    )
    return OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(
            _contract(CALL_ID, right=OptionRight.CALL),
            _contract(PUT_ID, right=OptionRight.PUT),
        ),
        quotes=quotes,
    )


def _order(
    *,
    package_units: int = 3,
    max_net_debit_per_unit: float = 250.0,
    time_in_force: OptionPackageTimeInForce = OptionPackageTimeInForce.IOC,
    legs: tuple[OptionPackageLeg, ...] | None = None,
    submitted_ts: int = 199,
    reduce_only: bool = False,
) -> OptionPackageOrder:
    return OptionPackageOrder(
        order_id="pkg-1",
        submitted_ts=submitted_ts,
        package_units=package_units,
        max_net_debit_per_unit=max_net_debit_per_unit,
        time_in_force=time_in_force,
        reduce_only=reduce_only,
        legs=legs
        or (
            OptionPackageLeg(instrument_id=CALL_ID, ratio=1),
            OptionPackageLeg(instrument_id=PUT_ID, ratio=-1),
        ),
    )


def test_full_package_crosses_buy_ask_sell_bid_and_preserves_cash_sign() -> None:
    execution = execute_displayed_option_package(order=_order(), surface=_surface())

    assert execution.status is OptionPackageExecutionStatus.FILLED
    assert execution.reduce_only is False
    assert execution.executed_package_units == 3
    assert execution.canceled_package_units == 0
    assert execution.displayed_capacity_units == 8
    assert execution.net_debit_per_unit == 200.0
    assert execution.premium_currency == "USD"
    assert [(leg.signed_contracts, leg.price) for leg in execution.leg_executions] == [
        (3, 5.0),
        (-3, 3.0),
    ]
    assert execution.premium_cash_delta == -600.0
    assert execution.reject_reason is None
    assert execution.assumption == DISPLAYED_ATOMIC_CROSS_ASSUMPTION
    assert execution.market_statuses == ()


def _status_event(
    status: MarketStatus,
    *,
    available_at: int = 190,
    instrument_id: str | None = None,
) -> MarketStatusEvent:
    return MarketStatusEvent(
        venue="OPRA",
        instrument_id=instrument_id,
        status=status,
        effective_from=150,
        effective_until=250,
        observed_ts=180,
        available_at=available_at,
        reason="fixture_status",
    )


def _status_provider(status: MarketStatus) -> StaticMarketStatusProvider:
    return StaticMarketStatusProvider(events=(_status_event(status),))


def test_open_status_coverage_is_recorded_for_every_leg() -> None:
    execution = execute_displayed_option_package(
        order=_order(),
        surface=_surface(),
        market_status_provider=_status_provider(MarketStatus.OPEN),
    )
    assert execution.status is OptionPackageExecutionStatus.FILLED
    assert [row.instrument_id for row in execution.market_statuses] == [CALL_ID, PUT_ID]
    assert all(row.status is MarketStatus.OPEN for row in execution.market_statuses)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (MarketStatus.HALTED, OptionPackageRejectReason.MARKET_HALTED),
        (MarketStatus.OUTAGE, OptionPackageRejectReason.VENUE_OUTAGE),
        (MarketStatus.AUCTION_ONLY, OptionPackageRejectReason.AUCTION_ONLY),
        (MarketStatus.CLOSE_ONLY, OptionPackageRejectReason.CLOSE_ONLY_RISK_INCREASE),
    ],
)
def test_noncontinuous_or_close_only_markets_block_risk_increase(
    status: MarketStatus,
    reason: OptionPackageRejectReason,
) -> None:
    execution = execute_displayed_option_package(
        order=_order(),
        surface=_surface(),
        market_status_provider=_status_provider(status),
    )
    assert execution.status is OptionPackageExecutionStatus.REJECTED
    assert execution.reject_reason is reason
    assert execution.market_statuses[0].status is status


def test_missing_status_coverage_fails_closed_when_provider_is_required() -> None:
    execution = execute_displayed_option_package(
        order=_order(),
        surface=_surface(),
        market_status_provider=StaticMarketStatusProvider(events=()),
    )
    assert execution.reject_reason is OptionPackageRejectReason.MISSING_MARKET_STATUS


def test_close_only_allows_only_proven_ratio_preserving_reduction() -> None:
    execution = execute_displayed_option_package(
        order=_order(reduce_only=True),
        surface=_surface(),
        market_status_provider=_status_provider(MarketStatus.CLOSE_ONLY),
        current_positions={CALL_ID: -3, PUT_ID: 3},
    )
    assert execution.status is OptionPackageExecutionStatus.FILLED
    assert execution.reduce_only is True
    assert all(row.status is MarketStatus.CLOSE_ONLY for row in execution.market_statuses)


def test_reduce_only_requires_positions_and_cannot_flip_or_increase() -> None:
    missing = execute_displayed_option_package(
        order=_order(reduce_only=True),
        surface=_surface(),
    )
    assert missing.reject_reason is OptionPackageRejectReason.REDUCE_ONLY_POSITION_MISSING

    increasing = execute_displayed_option_package(
        order=_order(reduce_only=True),
        surface=_surface(),
        current_positions={CALL_ID: 3, PUT_ID: 3},
    )
    assert increasing.reject_reason is OptionPackageRejectReason.REDUCE_ONLY_NOT_REDUCING

    flipping = execute_displayed_option_package(
        order=_order(reduce_only=True),
        surface=_surface(),
        current_positions={CALL_ID: -2, PUT_ID: 3},
    )
    assert flipping.reject_reason is OptionPackageRejectReason.REDUCE_ONLY_NOT_REDUCING


def test_reduce_only_positions_must_be_integer_contracts() -> None:
    with pytest.raises(ValueError, match="integer contracts"):
        execute_displayed_option_package(
            order=_order(reduce_only=True),
            surface=_surface(),
            current_positions={CALL_ID: -3.0, PUT_ID: 3},  # type: ignore[dict-item]
        )


def test_future_known_market_status_fails_lookahead() -> None:
    provider = StaticMarketStatusProvider(
        events=(_status_event(MarketStatus.HALTED, available_at=201),)
    )
    with pytest.raises(LookaheadError, match="market status"):
        execute_displayed_option_package(
            order=_order(),
            surface=_surface(),
            market_status_provider=provider,
        )


def test_instrument_status_overrides_venue_status_for_package() -> None:
    provider = StaticMarketStatusProvider(
        events=(
            _status_event(MarketStatus.OPEN),
            _status_event(MarketStatus.HALTED, instrument_id=CALL_ID),
        )
    )
    execution = execute_displayed_option_package(
        order=_order(),
        surface=_surface(),
        market_status_provider=provider,
    )
    assert execution.reject_reason is OptionPackageRejectReason.MARKET_HALTED
    assert execution.market_statuses[0].instrument_id == CALL_ID


def test_ioc_partial_fill_uses_smallest_whole_ratio_capacity() -> None:
    legs = (
        OptionPackageLeg(instrument_id=CALL_ID, ratio=2),
        OptionPackageLeg(instrument_id=PUT_ID, ratio=-1),
    )
    surface = _surface(
        call_quote=_quote(CALL_ID, bid=4.8, ask=5.0, ask_size=5.9),
        put_quote=_quote(PUT_ID, bid=3.0, ask=3.2, bid_size=20.0),
    )
    execution = execute_displayed_option_package(
        order=_order(package_units=4, max_net_debit_per_unit=800.0, legs=legs),
        surface=surface,
    )

    assert execution.status is OptionPackageExecutionStatus.PARTIALLY_FILLED
    assert execution.displayed_capacity_units == 2
    assert execution.executed_package_units == 2
    assert execution.canceled_package_units == 2
    assert [leg.signed_contracts for leg in execution.leg_executions] == [4, -2]


def test_fok_rejects_entire_package_when_any_leg_is_undersized() -> None:
    execution = execute_displayed_option_package(
        order=_order(package_units=9, time_in_force=OptionPackageTimeInForce.FOK),
        surface=_surface(),
    )

    assert execution.status is OptionPackageExecutionStatus.REJECTED
    assert execution.reject_reason is OptionPackageRejectReason.FOK_INSUFFICIENT_SIZE
    assert execution.displayed_capacity_units == 8
    assert execution.executed_package_units == 0
    assert execution.canceled_package_units == 9
    assert execution.leg_executions == ()


def test_net_debit_limit_rejects_without_partial_or_synthetic_price() -> None:
    execution = execute_displayed_option_package(
        order=_order(max_net_debit_per_unit=199.99),
        surface=_surface(),
    )

    assert execution.status is OptionPackageExecutionStatus.REJECTED
    assert execution.reject_reason is OptionPackageRejectReason.NET_LIMIT
    assert execution.net_debit_per_unit == 200.0
    assert execution.displayed_capacity_units == 8
    assert execution.leg_executions == ()


def test_negative_debit_limit_enforces_minimum_credit() -> None:
    credit_legs = (
        OptionPackageLeg(instrument_id=CALL_ID, ratio=-1),
        OptionPackageLeg(instrument_id=PUT_ID, ratio=1),
    )
    surface = _surface(
        call_quote=_quote(CALL_ID, bid=5.0, ask=5.2),
        put_quote=_quote(PUT_ID, bid=2.8, ask=3.0),
    )
    accepted = execute_displayed_option_package(
        order=_order(max_net_debit_per_unit=-150.0, legs=credit_legs),
        surface=surface,
    )
    rejected = execute_displayed_option_package(
        order=_order(max_net_debit_per_unit=-250.0, legs=credit_legs),
        surface=surface,
    )

    assert accepted.status is OptionPackageExecutionStatus.FILLED
    assert accepted.net_debit_per_unit == -200.0
    assert accepted.premium_cash_delta == 600.0
    assert rejected.reject_reason is OptionPackageRejectReason.NET_LIMIT


def test_limit_comparison_tolerates_only_float_roundoff() -> None:
    execution = execute_displayed_option_package(
        order=_order(max_net_debit_per_unit=200.0 - 5e-11),
        surface=_surface(),
    )
    assert execution.status is OptionPackageExecutionStatus.FILLED


def test_missing_quote_rejects_entire_package() -> None:
    surface = OptionSurfaceSnapshot(
        decision_ts=200,
        max_quote_age_ms=20,
        contracts=(
            _contract(CALL_ID, right=OptionRight.CALL),
            _contract(PUT_ID, right=OptionRight.PUT),
        ),
        quotes=(_quote(CALL_ID, bid=4.8, ask=5.0),),
    )
    execution = execute_displayed_option_package(order=_order(), surface=surface)
    assert execution.reject_reason is OptionPackageRejectReason.MISSING_QUOTE
    assert execution.net_debit_per_unit is None


def test_zero_bid_is_not_treated_as_an_executable_sale() -> None:
    surface = _surface(put_quote=_quote(PUT_ID, bid=0.0, ask=0.1, bid_size=50.0))
    execution = execute_displayed_option_package(order=_order(), surface=surface)
    assert execution.reject_reason is OptionPackageRejectReason.NON_EXECUTABLE_BID


@pytest.mark.parametrize(
    "call_quote",
    [
        _quote(CALL_ID, bid=4.8, ask=5.0, ask_size=0.0),
        _quote(CALL_ID, bid=4.8, ask=5.0, ask_size=0.9),
    ],
)
def test_zero_or_subratio_displayed_size_rejects(call_quote: OptionQuote) -> None:
    legs = (
        OptionPackageLeg(instrument_id=CALL_ID, ratio=1),
        OptionPackageLeg(instrument_id=PUT_ID, ratio=-1),
    )
    execution = execute_displayed_option_package(
        order=_order(legs=legs),
        surface=_surface(call_quote=call_quote),
    )
    assert execution.reject_reason is OptionPackageRejectReason.NO_DISPLAYED_SIZE


def test_side_specific_capacity_ignores_size_on_the_wrong_side() -> None:
    surface = _surface(
        call_quote=_quote(CALL_ID, bid=4.8, ask=5.0, bid_size=0.0, ask_size=4.0),
        put_quote=_quote(PUT_ID, bid=3.0, ask=3.2, bid_size=3.0, ask_size=0.0),
    )
    execution = execute_displayed_option_package(order=_order(), surface=surface)
    assert execution.status is OptionPackageExecutionStatus.FILLED
    assert execution.displayed_capacity_units == 3


def test_leg_absent_from_surface_terms_is_a_configuration_error() -> None:
    absent = OptionPackageLeg(
        instrument_id="OPRA:OPTION:MSFT20260918C00200000",
        ratio=1,
    )
    with pytest.raises(ValueError, match="absent from the surface terms"):
        execute_displayed_option_package(
            order=_order(legs=(absent,)),
            surface=_surface(),
        )


def test_package_rejects_cross_currency_netting() -> None:
    surface = _surface(
        put_quote=_quote(
            PUT_ID,
            bid=3.0,
            ask=3.2,
            premium_currency="EUR",
        )
    )
    with pytest.raises(ValueError, match="share one premium currency"):
        execute_displayed_option_package(order=_order(), surface=surface)


def test_future_submitted_order_fails_lookahead() -> None:
    with pytest.raises(LookaheadError, match="after decision"):
        execute_displayed_option_package(
            order=_order(submitted_ts=201),
            surface=_surface(),
        )


@pytest.mark.parametrize("ratio", [0, True, 1.5])
def test_leg_requires_nonzero_integer_option_ratio(ratio: object) -> None:
    with pytest.raises(ValueError, match="non-zero integer"):
        OptionPackageLeg(instrument_id=CALL_ID, ratio=ratio)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"MarketType\.OPTION"):
        OptionPackageLeg(instrument_id="XUSE:CASH:AAPLUSD", ratio=1)


@pytest.mark.parametrize("package_units", [0, -1, True, 1.5])
def test_order_requires_positive_integer_package_units(package_units: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _order(package_units=package_units)  # type: ignore[arg-type]


def test_order_rejects_blank_id_empty_legs_duplicate_legs_and_nonfinite_limit() -> None:
    base = {
        "submitted_ts": 199,
        "package_units": 1,
        "max_net_debit_per_unit": 1.0,
        "time_in_force": OptionPackageTimeInForce.IOC,
    }
    with pytest.raises(ValueError, match="blank"):
        OptionPackageOrder(
            order_id=" ",
            legs=(OptionPackageLeg(instrument_id=CALL_ID, ratio=1),),
            **base,
        )
    with pytest.raises(ValueError, match="at least one"):
        OptionPackageOrder(order_id="x", legs=(), **base)
    with pytest.raises(ValueError, match="OptionPackageLeg"):
        OptionPackageOrder(order_id="x", legs=("not-a-leg",), **base)  # type: ignore[arg-type]
    duplicate = OptionPackageLeg(instrument_id=CALL_ID, ratio=1)
    with pytest.raises(ValueError, match="unique"):
        OptionPackageOrder(order_id="x", legs=(duplicate, duplicate), **base)
    with pytest.raises(ValueError, match="finite"):
        OptionPackageOrder(
            order_id="x",
            legs=(duplicate,),
            **{**base, "max_net_debit_per_unit": math.inf},
        )
    with pytest.raises(ValueError, match="OptionPackageTimeInForce"):
        OptionPackageOrder(
            order_id="x",
            legs=(duplicate,),
            **{**base, "time_in_force": "ioc"},  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="reduce_only must be boolean"):
        OptionPackageOrder(
            order_id="x",
            legs=(duplicate,),
            **{**base, "reduce_only": 1},  # type: ignore[arg-type]
        )


def test_leg_execution_uses_contract_multiplier_and_signed_cash() -> None:
    bought = OptionLegExecution(
        instrument_id=CALL_ID,
        premium_currency="USD",
        signed_contracts=2,
        price=1.25,
        contract_multiplier=150.0,
    )
    sold = OptionLegExecution(
        instrument_id=PUT_ID,
        premium_currency="USD",
        signed_contracts=-3,
        price=0.5,
        contract_multiplier=100.0,
    )
    assert bought.premium_cash_delta == -375.0
    assert sold.premium_cash_delta == 150.0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"signed_contracts": 0}, "non-zero integer"),
        ({"signed_contracts": True}, "non-zero integer"),
        ({"price": 0.0}, "finite and > 0"),
        ({"contract_multiplier": math.inf}, "finite and > 0"),
        ({"premium_currency": "usd"}, "uppercase alphanumerics"),
        ({"instrument_id": "XUSE:CASH:AAPLUSD"}, r"MarketType\.OPTION"),
    ],
)
def test_leg_execution_rejects_impossible_evidence_records(
    changes: dict[str, object], message: str
) -> None:
    valid = OptionLegExecution(
        instrument_id=CALL_ID,
        premium_currency="USD",
        signed_contracts=1,
        price=1.0,
        contract_multiplier=100.0,
    )
    with pytest.raises(ValueError, match=message):
        replace(valid, **changes)


def test_package_execution_record_rejects_impossible_state_combinations() -> None:
    valid = execute_displayed_option_package(order=_order(), surface=_surface())
    with pytest.raises(ValueError, match="partition"):
        replace(valid, canceled_package_units=1)
    with pytest.raises(ValueError, match="displayed capacity"):
        replace(
            valid,
            displayed_capacity_units=2,
        )
    with pytest.raises(ValueError, match="reject reason"):
        replace(valid, reject_reason=OptionPackageRejectReason.NET_LIMIT)
    with pytest.raises(ValueError, match="premium cash"):
        replace(valid, net_debit_per_unit=199.0)
    with pytest.raises(ValueError, match="ExecutionStatus"):
        replace(valid, status="filled")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="OptionPackageRejectReason"):
        replace(valid, reject_reason="net_limit")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        replace(valid, leg_executions=(valid.leg_executions[0],) * 2)
    with pytest.raises(ValueError, match="share one premium currency"):
        replace(
            valid,
            leg_executions=(
                valid.leg_executions[0],
                replace(valid.leg_executions[1], premium_currency="EUR"),
            ),
        )
    status = OptionPackageMarketStatus(
        instrument_id=CALL_ID,
        venue="OPRA",
        status=MarketStatus.OPEN,
        effective_from=150,
        effective_until=250,
        observed_ts=180,
        available_at=190,
        reason="fixture",
    )
    with pytest.raises(ValueError, match="effective and known"):
        replace(valid, market_statuses=(replace(status, available_at=201),))
    with pytest.raises(ValueError, match="unique"):
        replace(valid, market_statuses=(status, status))
    with pytest.raises(ValueError, match="complete market-status"):
        replace(valid, market_statuses=(status,))
    blocked = replace(status, status=MarketStatus.HALTED)
    with pytest.raises(ValueError, match="blocking market status"):
        replace(
            valid,
            market_statuses=(
                blocked,
                replace(blocked, instrument_id=PUT_ID),
            ),
        )
    close_only = replace(status, status=MarketStatus.CLOSE_ONLY)
    with pytest.raises(ValueError, match="marked reduce_only"):
        replace(
            valid,
            market_statuses=(
                close_only,
                replace(close_only, instrument_id=PUT_ID),
            ),
        )

    rejected = OptionPackageExecution(
        order_id="rejected",
        decision_ts=200,
        status=OptionPackageExecutionStatus.REJECTED,
        requested_package_units=1,
        executed_package_units=0,
        canceled_package_units=1,
        displayed_capacity_units=0,
        net_debit_per_unit=None,
        leg_executions=(),
        reject_reason=OptionPackageRejectReason.MISSING_QUOTE,
    )
    with pytest.raises(ValueError, match="require a reject reason"):
        replace(rejected, reject_reason=None)
    with pytest.raises(ValueError, match="cannot contain executions"):
        replace(
            rejected,
            executed_package_units=1,
            canceled_package_units=0,
            displayed_capacity_units=1,
            leg_executions=valid.leg_executions,
        )
    assert rejected.premium_currency is None
