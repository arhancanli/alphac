from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.options_margin import (
    OptionMarginAssessment,
    OptionMarginPolicy,
    OptionMarginPosition,
    OptionMarginRequirementType,
    OptionMarginScenario,
    OptionMarginScenarioLoss,
    OptionMarginScenarioPrice,
    OptionMarginSnapshot,
    StaticOptionMarginDataProvider,
    assess_option_scenario_margin,
)

CALL_ID = "OPRA:OPTION:AAPL20260918C00200000"
PUT_ID = "OPRA:OPTION:AAPL20260918P00200000"
MODEL_SHA = "a" * 64
INPUT_SHA = "b" * 64
SOURCE_SHA = "c" * 64


def _positions() -> tuple[OptionMarginPosition, ...]:
    return (
        OptionMarginPosition(
            instrument_id=CALL_ID,
            underlying_group="AAPL",
            premium_currency="USD",
            signed_contracts=2,
            mark_price=Decimal("5"),
            contract_multiplier=Decimal("100"),
        ),
        OptionMarginPosition(
            instrument_id=PUT_ID,
            underlying_group="AAPL",
            premium_currency="USD",
            signed_contracts=-1,
            mark_price=Decimal("3"),
            contract_multiplier=Decimal("100"),
        ),
    )


def _scenario(
    scenario_id: str,
    call_price: str,
    put_price: str,
) -> OptionMarginScenario:
    return OptionMarginScenario(
        scenario_id=scenario_id,
        prices=(
            OptionMarginScenarioPrice(
                instrument_id=CALL_ID,
                stressed_price=Decimal(call_price),
            ),
            OptionMarginScenarioPrice(
                instrument_id=PUT_ID,
                stressed_price=Decimal(put_price),
            ),
        ),
    )


def _snapshot(
    *,
    positions: tuple[OptionMarginPosition, ...] | None = None,
    scenarios: tuple[OptionMarginScenario, ...] | None = None,
    decision_ts: int = 200,
    marks_observed_at: int = 180,
    generated_at: int = 190,
    available_at: int = 195,
    max_mark_age_ms: int = 30,
    premium_currency: str = "USD",
) -> OptionMarginSnapshot:
    return OptionMarginSnapshot(
        decision_ts=decision_ts,
        marks_observed_at=marks_observed_at,
        generated_at=generated_at,
        available_at=available_at,
        max_mark_age_ms=max_mark_age_ms,
        premium_currency=premium_currency,
        scenario_model_id="LOCKED-STRESS-V1",
        scenario_model_sha256=MODEL_SHA,
        input_artifact_sha256=INPUT_SHA,
        positions=positions or _positions(),
        scenarios=scenarios
        or (
            _scenario("DOWN", "1", "8"),
            _scenario("UP", "10", "1"),
        ),
    )


def _policy(
    *,
    revision: int = 1,
    available_at: int = 100,
    effective_from: int = 100,
    effective_until: int = 1_000,
    premium_currency: str = "USD",
    policy_id: str = "INTERNAL-SCENARIO-MARGIN",
) -> OptionMarginPolicy:
    return OptionMarginPolicy(
        policy_id=policy_id,
        revision=revision,
        account_class="INTERNAL",
        risk_method="LOCKED-STRESS-V1",
        premium_currency=premium_currency,
        requirement_type=OptionMarginRequirementType.INITIAL,
        source_published_at=90,
        available_at=available_at,
        effective_from=effective_from,
        effective_until=effective_until,
        source_url="https://example.test/risk/options-margin-policy.pdf",
        source_sha256=SOURCE_SHA,
        scenario_loss_multiplier=Decimal("1.10"),
        short_contract_minimum=Decimal("500"),
        gross_short_mark_addon_rate=Decimal("0.10"),
        concentration_threshold=Decimal("0.50"),
        concentration_addon_rate=Decimal("0.20"),
    )


def test_scenario_margin_nets_legs_then_applies_explicit_floors_and_addons() -> None:
    assessment = assess_option_scenario_margin(
        _policy(),
        _snapshot(),
        decision_ts=200,
    )

    loss_rows = [
        (row.scenario_id, row.portfolio_pnl, row.loss)
        for row in assessment.scenario_losses
    ]
    assert loss_rows == [
        ("DOWN", Decimal("-1300"), Decimal("1300")),
        ("UP", Decimal("1200"), Decimal("0")),
    ]
    assert assessment.worst_scenario_id == "DOWN"
    assert assessment.scenario_loss_multiplier == Decimal("1.10")
    assert assessment.scenario_requirement == Decimal("1430.00")
    assert assessment.short_contracts == 1
    assert assessment.short_contract_minimum == Decimal("500")
    assert assessment.short_contract_floor == Decimal("500")
    assert assessment.gross_short_mark == Decimal("300")
    assert assessment.gross_short_mark_addon_rate == Decimal("0.10")
    assert assessment.gross_short_mark_addon == Decimal("30.00")
    assert assessment.concentration_addon == Decimal("30.0000")
    assert assessment.largest_short_group_share == Decimal("1")
    assert assessment.total_requirement == Decimal("1490.0000")
    assert assessment.scenario_model_sha256 == MODEL_SHA
    assert assessment.input_artifact_sha256 == INPUT_SHA
    assert assessment.source_sha256 == SOURCE_SHA


def test_scenario_order_does_not_change_deterministic_loss_rows() -> None:
    reversed_snapshot = _snapshot(
        scenarios=(
            _scenario("UP", "10", "1"),
            _scenario("DOWN", "1", "8"),
        )
    )
    assessment = assess_option_scenario_margin(
        _policy(), reversed_snapshot, decision_ts=200
    )
    assert [row.scenario_id for row in assessment.scenario_losses] == ["DOWN", "UP"]


def test_long_only_portfolio_has_no_short_floor_or_addons() -> None:
    long_position = (_positions()[0],)
    snapshot = _snapshot(
        positions=long_position,
        scenarios=(
            OptionMarginScenario(
                scenario_id="LOSS",
                prices=(
                    OptionMarginScenarioPrice(
                        instrument_id=CALL_ID,
                        stressed_price=Decimal("2"),
                    ),
                ),
            ),
        ),
    )
    assessment = assess_option_scenario_margin(_policy(), snapshot, decision_ts=200)
    assert assessment.worst_scenario_loss == Decimal("600")
    assert assessment.scenario_requirement == Decimal("660.00")
    assert assessment.short_contracts == 0
    assert assessment.short_contract_floor == Decimal("0")
    assert assessment.gross_short_mark_addon == Decimal("0.00")
    assert assessment.concentration_addon == Decimal("0")
    assert assessment.total_requirement == Decimal("660.00")


def test_complete_matrix_is_mandatory_and_names_missing_and_extra_ids() -> None:
    incomplete = OptionMarginScenario(
        scenario_id="INCOMPLETE",
        prices=(
            OptionMarginScenarioPrice(
                instrument_id=CALL_ID,
                stressed_price=Decimal("1"),
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"missing=.*AAPL20260918P"):
        _snapshot(scenarios=(incomplete,))

    extra_id = "OPRA:OPTION:MSFT20260918C00200000"
    extra = replace(
        incomplete,
        prices=(
            *incomplete.prices,
            OptionMarginScenarioPrice(
                instrument_id=PUT_ID,
                stressed_price=Decimal("1"),
            ),
            OptionMarginScenarioPrice(
                instrument_id=extra_id,
                stressed_price=Decimal("1"),
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"extra=.*MSFT"):
        _snapshot(scenarios=(extra,))


def test_snapshot_rejects_future_stale_or_misordered_scenario_generation() -> None:
    with pytest.raises(LookaheadError, match="exceed decision"):
        _snapshot(available_at=201)
    with pytest.raises(ValueError, match="stale"):
        _snapshot(marks_observed_at=160)
    with pytest.raises(ValueError, match="must be ordered"):
        _snapshot(marks_observed_at=190, generated_at=180)
    with pytest.raises(ValueError, match="nonnegative integer"):
        _snapshot(max_mark_age_ms=True)  # type: ignore[arg-type]


def test_snapshot_rejects_cross_currency_duplicate_or_malformed_inputs() -> None:
    eur_put = replace(_positions()[1], premium_currency="EUR")
    with pytest.raises(ValueError, match="share the snapshot premium currency"):
        _snapshot(positions=(_positions()[0], eur_put))
    with pytest.raises(ValueError, match="position instrument ids must be unique"):
        _snapshot(positions=(_positions()[0], _positions()[0]))
    with pytest.raises(ValueError, match="scenario ids must be unique"):
        down = _scenario("DOWN", "1", "8")
        _snapshot(scenarios=(down, down))
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(_snapshot(), scenario_model_sha256="A" * 64)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"instrument_id": "XUSE:CASH:AAPLUSD"}, r"MarketType\.OPTION"),
        ({"signed_contracts": 0}, "non-zero integer"),
        ({"signed_contracts": True}, "non-zero integer"),
        ({"mark_price": Decimal("-1")}, "must be >= 0"),
        ({"mark_price": 1.0}, "finite Decimal"),
        ({"contract_multiplier": Decimal("0")}, "must be > 0"),
        ({"premium_currency": "usd"}, "uppercase code"),
    ],
)
def test_margin_position_rejects_invalid_evidence(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_positions()[0], **changes)


def test_scenario_price_rejects_negative_inexact_or_nonoption_values() -> None:
    price = _scenario("DOWN", "1", "8").prices[0]
    with pytest.raises(ValueError, match="must be >= 0"):
        replace(price, stressed_price=Decimal("-1"))
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(price, stressed_price=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"MarketType\.OPTION"):
        replace(price, instrument_id="XUSE:CASH:AAPLUSD")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scenario_loss_multiplier": Decimal("0.99")}, "must be >= 1"),
        ({"short_contract_minimum": Decimal("-1")}, "must be >= 0"),
        ({"gross_short_mark_addon_rate": 0.1}, "finite Decimal"),
        ({"concentration_threshold": Decimal("1.1")}, r"in \[0, 1\]"),
        ({"requirement_type": "initial"}, "OptionMarginRequirementType"),
        ({"source_url": "http://example.test/policy"}, "credential-free HTTPS"),
        ({"source_sha256": "C" * 64}, "64 lowercase"),
    ],
)
def test_policy_rejects_invalid_or_inexact_parameters(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_policy(), **changes)


def test_policy_is_point_in_time_and_effective() -> None:
    with pytest.raises(LookaheadError, match="exceeds decision"):
        _policy(available_at=201).require_effective(200)
    with pytest.raises(ValueError, match="not effective"):
        _policy(effective_from=300).require_effective(200)


def test_policy_provider_selects_latest_known_effective_revision() -> None:
    first = _policy(effective_until=1_000)
    second = _policy(
        revision=2,
        available_at=600,
        effective_from=500,
        effective_until=1_200,
    )
    provider = StaticOptionMarginDataProvider(policies=(second, first))
    query = {
        "account_class": "INTERNAL",
        "risk_method": "LOCKED-STRESS-V1",
        "premium_currency": "USD",
        "requirement_type": OptionMarginRequirementType.INITIAL,
    }
    assert provider.policy(**query, as_of=550) == first
    assert provider.policy(**query, as_of=700) == second
    assert provider.policy(**{**query, "account_class": "BROKER"}, as_of=700) is None


def test_policy_provider_rejects_gaps_identity_and_time_regressions() -> None:
    first = _policy()
    with pytest.raises(ValueError, match="contiguous"):
        StaticOptionMarginDataProvider(
            policies=(first, _policy(revision=3, available_at=300))
        )
    with pytest.raises(ValueError, match="one policy_id"):
        StaticOptionMarginDataProvider(
            policies=(
                first,
                _policy(revision=2, available_at=300, policy_id="OTHER-POLICY"),
            )
        )
    with pytest.raises(ValueError, match="strictly increase"):
        StaticOptionMarginDataProvider(
            policies=(first, _policy(revision=2, available_at=100))
        )
    with pytest.raises(ValueError, match="cannot regress"):
        StaticOptionMarginDataProvider(
            policies=(
                first,
                _policy(revision=2, available_at=300, effective_from=99),
            )
        )


def test_assessment_rejects_currency_or_decision_mismatch() -> None:
    with pytest.raises(ValueError, match="premium currencies"):
        assess_option_scenario_margin(
            _policy(premium_currency="EUR"),
            _snapshot(),
            decision_ts=200,
        )
    with pytest.raises(ValueError, match="decision timestamps"):
        assess_option_scenario_margin(_policy(), _snapshot(), decision_ts=201)
    with pytest.raises(ValueError, match="policy risk method"):
        assess_option_scenario_margin(
            _policy(),
            replace(_snapshot(), scenario_model_id="LOCKED-STRESS-V2"),
            decision_ts=200,
        )


def test_assessment_records_reject_tampered_losses_and_totals() -> None:
    assessment = assess_option_scenario_margin(_policy(), _snapshot(), decision_ts=200)
    with pytest.raises(ValueError, match="maximum scenario loss"):
        replace(assessment, worst_scenario_loss=Decimal("1"))
    with pytest.raises(ValueError, match="does not reconcile"):
        replace(assessment, total_requirement=Decimal("1"))
    with pytest.raises(ValueError, match="scenario loss policy"):
        replace(assessment, scenario_requirement=Decimal("1"))
    with pytest.raises(ValueError, match="short minimum policy"):
        replace(assessment, short_contract_floor=Decimal("1"))
    with pytest.raises(ValueError, match="short-mark add-on"):
        replace(assessment, gross_short_mark_addon=Decimal("1"))
    with pytest.raises(ValueError, match="concentration add-on"):
        replace(assessment, concentration_addon=Decimal("1"))
    with pytest.raises(ValueError, match="assessed scenario"):
        replace(assessment, worst_scenario_id="MISSING")
    with pytest.raises(ValueError, match="unique"):
        replace(
            assessment,
            scenario_losses=(assessment.scenario_losses[0],) * 2,
        )

    valid_loss = OptionMarginScenarioLoss(
        scenario_id="ZERO",
        portfolio_pnl=Decimal("1"),
        loss=Decimal("0"),
    )
    with pytest.raises(ValueError, match=r"max\(-portfolio_pnl"):
        replace(valid_loss, loss=Decimal("1"))


def test_assessment_source_and_model_hashes_are_self_validating() -> None:
    assessment = assess_option_scenario_margin(_policy(), _snapshot(), decision_ts=200)
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(assessment, input_artifact_sha256="bad")
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        replace(assessment, source_url="file:///tmp/policy")


def test_assessment_constructor_requires_real_scenario_loss_records() -> None:
    assessment = assess_option_scenario_margin(_policy(), _snapshot(), decision_ts=200)
    with pytest.raises(ValueError, match="OptionMarginScenarioLoss"):
        OptionMarginAssessment(
            **{
                field: getattr(assessment, field)
                for field in assessment.__dataclass_fields__
                if field != "scenario_losses"
            },
            scenario_losses=("not-a-loss",),  # type: ignore[arg-type]
        )
