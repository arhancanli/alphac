from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.options_fees import (
    OptionFeeComponent,
    OptionFeeEvent,
    OptionFeeLine,
    OptionFeeLiquidity,
    OptionFeeRounding,
    OptionFeeSchedule,
    OptionFeeSide,
    StaticOptionFeeDataProvider,
    assess_option_lifecycle_fees,
    assess_option_trade_fees,
)
from alphaforge.execution.options_packages import (
    OptionLegExecution,
    OptionPackageExecution,
    OptionPackageExecutionStatus,
    OptionPackageRejectReason,
)

SOURCE_SHA = "a" * 64
CALL_ID = "OPRA:OPTION:AAPL20260918C00200000"
PUT_ID = "OPRA:OPTION:AAPL20260918P00200000"


def _components() -> tuple[OptionFeeComponent, ...]:
    return (
        OptionFeeComponent(
            name="broker_commission",
            event=OptionFeeEvent.TRADE,
            per_contract=Decimal("0.65"),
        ),
        OptionFeeComponent(
            name="taker_exchange",
            event=OptionFeeEvent.TRADE,
            liquidity=OptionFeeLiquidity.TAKER,
            per_contract=Decimal("0.20"),
        ),
        OptionFeeComponent(
            name="sell_regulatory",
            event=OptionFeeEvent.TRADE,
            side=OptionFeeSide.SELL,
            premium_rate=Decimal("0.0001"),
        ),
        OptionFeeComponent(
            name="maker_rebate",
            event=OptionFeeEvent.TRADE,
            liquidity=OptionFeeLiquidity.MAKER,
            per_contract=Decimal("-0.10"),
        ),
        OptionFeeComponent(
            name="exercise_fee",
            event=OptionFeeEvent.EXERCISE,
            per_contract=Decimal("1.50"),
        ),
        OptionFeeComponent(
            name="assignment_fee",
            event=OptionFeeEvent.ASSIGNMENT,
            per_contract=Decimal("2.00"),
        ),
    )


def _schedule(
    *,
    revision: int = 1,
    available_at: int = 100,
    effective_from: int = 100,
    effective_until: int = 1_000,
    premium_currency: str = "USD",
    schedule_id: str = "OPRA-PRO-AAPL",
    components: tuple[OptionFeeComponent, ...] | None = None,
) -> OptionFeeSchedule:
    return OptionFeeSchedule(
        schedule_id=schedule_id,
        revision=revision,
        venue="OPRA",
        account_class="PROFESSIONAL",
        product_group="AAPL",
        premium_currency=premium_currency,
        source_published_at=90,
        available_at=available_at,
        effective_from=effective_from,
        effective_until=effective_until,
        source_url="https://example.test/fees/aapl.pdf",
        source_sha256=SOURCE_SHA,
        components=components or _components(),
    )


def _execution() -> OptionPackageExecution:
    return OptionPackageExecution(
        order_id="pkg-1",
        decision_ts=200,
        status=OptionPackageExecutionStatus.FILLED,
        requested_package_units=3,
        executed_package_units=3,
        canceled_package_units=0,
        displayed_capacity_units=8,
        net_debit_per_unit=200.0,
        leg_executions=(
            OptionLegExecution(
                instrument_id=CALL_ID,
                premium_currency="USD",
                signed_contracts=3,
                price=5.0,
                contract_multiplier=100.0,
            ),
            OptionLegExecution(
                instrument_id=PUT_ID,
                premium_currency="USD",
                signed_contracts=-3,
                price=3.0,
                contract_multiplier=100.0,
            ),
        ),
        reject_reason=None,
    )


def test_taker_trade_assessment_is_exact_side_and_liquidity_scoped() -> None:
    assessment = assess_option_trade_fees(
        _schedule(),
        _execution(),
        liquidity=OptionFeeLiquidity.TAKER,
        decision_ts=200,
    )

    assert [(line.component_name, line.amount) for line in assessment.lines] == [
        ("broker_commission", Decimal("3.90")),
        ("taker_exchange", Decimal("1.20")),
        ("sell_regulatory", Decimal("0.09000")),
    ]
    assert assessment.lines[0].contracts == 6
    assert assessment.lines[0].premium_notional == Decimal("2400.00")
    assert assessment.lines[2].contracts == 3
    assert assessment.lines[2].premium_notional == Decimal("900.00")
    assert assessment.total_amount == Decimal("5.19000")
    assert assessment.premium_currency == "USD"
    assert assessment.source_sha256 == SOURCE_SHA


def test_maker_rebate_is_explicit_and_taker_component_is_excluded() -> None:
    assessment = assess_option_trade_fees(
        _schedule(),
        _execution(),
        liquidity=OptionFeeLiquidity.MAKER,
        decision_ts=200,
    )
    assert [(line.component_name, line.amount) for line in assessment.lines] == [
        ("broker_commission", Decimal("3.90")),
        ("sell_regulatory", Decimal("0.09000")),
        ("maker_rebate", Decimal("-0.60")),
    ]
    assert assessment.total_amount == Decimal("3.39000")


def test_component_minimum_and_cap_apply_after_order_aggregation() -> None:
    minimum = OptionFeeComponent(
        name="minimum",
        event=OptionFeeEvent.TRADE,
        premium_rate=Decimal("0.00001"),
        minimum_per_order=Decimal("1.00"),
    )
    capped = OptionFeeComponent(
        name="capped",
        event=OptionFeeEvent.TRADE,
        per_contract=Decimal("1.00"),
        maximum_per_order=Decimal("2.50"),
    )
    assert minimum.assess(contracts=2, premium_notional=Decimal("100")) == Decimal("1.00")
    assert capped.assess(contracts=3, premium_notional=Decimal("0")) == Decimal("2.50")


def test_component_rounding_is_explicit_and_precedes_minimum_and_cap() -> None:
    ceiling = OptionFeeComponent(
        name="rounded_regulatory",
        event=OptionFeeEvent.TRADE,
        premium_rate=Decimal("0.00001"),
        rounding_increment=Decimal("0.01"),
        rounding=OptionFeeRounding.CEILING,
    )
    half_up = replace(ceiling, name="half_up", rounding=OptionFeeRounding.HALF_UP)
    capped = replace(ceiling, name="capped", maximum_per_order=Decimal("0.005"))
    assert ceiling.assess(contracts=1, premium_notional=Decimal("123")) == Decimal("0.01")
    assert half_up.assess(contracts=1, premium_notional=Decimal("123")) == Decimal("0.00")
    assert capped.assess(contracts=1, premium_notional=Decimal("123")) == Decimal("0.005")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"per_contract": 0.1}, "finite Decimal"),
        ({"premium_rate": Decimal("NaN")}, "finite Decimal"),
        ({"per_contract": Decimal("0")}, "non-zero rate"),
        (
            {"per_contract": Decimal("1"), "premium_rate": Decimal("-0.1")},
            "cannot mix",
        ),
        (
            {"per_contract": Decimal("-1"), "minimum_per_order": Decimal("0")},
            "rebate components",
        ),
        (
            {
                "per_contract": Decimal("1"),
                "minimum_per_order": Decimal("2"),
                "maximum_per_order": Decimal("1"),
            },
            "cannot exceed",
        ),
        (
            {"rounding": OptionFeeRounding.CEILING},
            "requires a rounding_increment",
        ),
        (
            {"rounding_increment": Decimal("0.01")},
            "explicit rounding mode",
        ),
        (
            {
                "rounding_increment": Decimal("0"),
                "rounding": OptionFeeRounding.HALF_UP,
            },
            "must be > 0",
        ),
    ],
)
def test_component_rejects_inexact_or_incoherent_rates(
    changes: dict[str, object], message: str
) -> None:
    base: dict[str, object] = {
        "name": "component",
        "event": OptionFeeEvent.TRADE,
        "per_contract": Decimal("0.1"),
    }
    with pytest.raises(ValueError, match=message):
        OptionFeeComponent(**{**base, **changes})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"side": OptionFeeSide.BUY}, "side-scoped"),
        ({"liquidity": OptionFeeLiquidity.TAKER}, "liquidity-scoped"),
        ({"premium_rate": Decimal("0.1")}, "premium_rate"),
    ],
)
def test_lifecycle_components_are_per_contract_and_unscoped(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        OptionFeeComponent(
            name="exercise",
            event=OptionFeeEvent.EXERCISE,
            per_contract=Decimal("1"),
            **changes,  # type: ignore[arg-type]
        )


def test_component_assessment_requires_positive_contracts_and_nonnegative_notional() -> None:
    component = _components()[0]
    with pytest.raises(ValueError, match="positive integer"):
        component.assess(contracts=0, premium_notional=Decimal("1"))
    with pytest.raises(ValueError, match=">= 0"):
        component.assess(contracts=1, premium_notional=Decimal("-1"))


def test_schedule_requires_strict_lineage_and_unique_component_scopes() -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        replace(_schedule(), source_url="http://example.test/fees.pdf")
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(_schedule(), source_sha256="A" * 64)
    with pytest.raises(ValueError, match="source publication"):
        replace(_schedule(), source_published_at=101, available_at=100)
    with pytest.raises(ValueError, match="must precede"):
        replace(_schedule(), effective_from=200, effective_until=200)
    with pytest.raises(ValueError, match="unique"):
        duplicate = _components()[0]
        replace(_schedule(), components=(duplicate, duplicate))
    with pytest.raises(ValueError, match="uppercase code"):
        replace(_schedule(), account_class="professional")


def test_provider_selects_only_latest_known_effective_revision() -> None:
    first = _schedule(effective_until=1_000)
    second = _schedule(
        revision=2,
        available_at=600,
        effective_from=500,
        effective_until=1_200,
    )
    provider = StaticOptionFeeDataProvider(schedules=(second, first))

    assert provider.schedule(
        venue="OPRA",
        account_class="PROFESSIONAL",
        product_group="AAPL",
        premium_currency="USD",
        as_of=550,
    ) == first
    assert provider.schedule(
        venue="OPRA",
        account_class="PROFESSIONAL",
        product_group="AAPL",
        premium_currency="USD",
        as_of=700,
    ) == second
    assert (
        provider.schedule(
            venue="OPRA",
            account_class="RETAIL",
            product_group="AAPL",
            premium_currency="USD",
            as_of=700,
        )
        is None
    )


def test_provider_rejects_revision_gaps_identity_changes_and_time_regression() -> None:
    first = _schedule()
    with pytest.raises(ValueError, match="contiguous"):
        StaticOptionFeeDataProvider(schedules=(first, _schedule(revision=3, available_at=300)))
    with pytest.raises(ValueError, match="one schedule_id"):
        StaticOptionFeeDataProvider(
            schedules=(
                first,
                _schedule(revision=2, available_at=300, schedule_id="OTHER-SCHEDULE"),
            )
        )
    with pytest.raises(ValueError, match="strictly increase"):
        StaticOptionFeeDataProvider(
            schedules=(first, _schedule(revision=2, available_at=100))
        )
    with pytest.raises(ValueError, match="cannot regress"):
        StaticOptionFeeDataProvider(
            schedules=(
                first,
                _schedule(revision=2, available_at=300, effective_from=99),
            )
        )


def test_schedule_effectiveness_is_fail_closed() -> None:
    with pytest.raises(LookaheadError, match="exceeds decision"):
        _schedule(available_at=201).require_effective(200)
    with pytest.raises(ValueError, match="not effective"):
        _schedule(effective_from=300).require_effective(200)


def test_trade_assessment_rejects_wrong_currency_time_liquidity_and_rejected_fill() -> None:
    execution = _execution()
    with pytest.raises(ValueError, match="premium currencies"):
        assess_option_trade_fees(
            _schedule(premium_currency="EUR"),
            execution,
            liquidity=OptionFeeLiquidity.TAKER,
            decision_ts=200,
        )
    with pytest.raises(ValueError, match="timestamps"):
        assess_option_trade_fees(
            _schedule(),
            execution,
            liquidity=OptionFeeLiquidity.TAKER,
            decision_ts=201,
        )
    with pytest.raises(ValueError, match="requires MAKER"):
        assess_option_trade_fees(
            _schedule(),
            execution,
            liquidity=OptionFeeLiquidity.ALL,
            decision_ts=200,
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
    with pytest.raises(ValueError, match="rejected package"):
        assess_option_trade_fees(
            _schedule(),
            rejected,
            liquidity=OptionFeeLiquidity.TAKER,
            decision_ts=200,
        )


def test_exercise_and_assignment_are_separate_exact_events() -> None:
    exercise = assess_option_lifecycle_fees(
        _schedule(),
        event=OptionFeeEvent.EXERCISE,
        contracts=2,
        decision_ts=200,
    )
    assignment = assess_option_lifecycle_fees(
        _schedule(),
        event=OptionFeeEvent.ASSIGNMENT,
        contracts=3,
        decision_ts=200,
    )
    assert [(line.component_name, line.amount) for line in exercise.lines] == [
        ("exercise_fee", Decimal("3.00"))
    ]
    assert exercise.total_amount == Decimal("3.00")
    assert assignment.total_amount == Decimal("6.00")


def test_lifecycle_assessment_rejects_trade_event_and_invalid_contract_count() -> None:
    with pytest.raises(ValueError, match="EXERCISE or ASSIGNMENT"):
        assess_option_lifecycle_fees(
            _schedule(),
            event=OptionFeeEvent.TRADE,
            contracts=1,
            decision_ts=200,
        )
    with pytest.raises(ValueError, match="positive integer"):
        assess_option_lifecycle_fees(
            _schedule(),
            event=OptionFeeEvent.EXERCISE,
            contracts=0,
            decision_ts=200,
        )


def test_fee_lines_and_assessments_reject_impossible_evidence_records() -> None:
    assessment = assess_option_trade_fees(
        _schedule(),
        _execution(),
        liquidity=OptionFeeLiquidity.TAKER,
        decision_ts=200,
    )
    line = assessment.lines[0]
    with pytest.raises(ValueError, match="premium_notional must be >= 0"):
        replace(line, premium_notional=Decimal("-1"))
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(line, amount=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact sum"):
        replace(assessment, total_amount=Decimal("0"))
    with pytest.raises(ValueError, match="must match"):
        replace(
            assessment,
            lines=(replace(line, event=OptionFeeEvent.ASSIGNMENT),),
            total_amount=line.amount,
        )
    with pytest.raises(ValueError, match="OptionFeeLine"):
        replace(assessment, lines=("not-a-line",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(assessment, source_sha256="b")

    zero_line = OptionFeeLine(
        component_name="zero_reconciled_component",
        event=OptionFeeEvent.TRADE,
        contracts=1,
        premium_notional=Decimal("0"),
        amount=Decimal("0"),
    )
    assert zero_line.amount == Decimal("0")
