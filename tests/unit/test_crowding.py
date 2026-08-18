"""Coverage-aware crowding-risk tests."""

from __future__ import annotations

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.risk.crowding import (
    CrowdingObservation,
    CrowdingPolicy,
    CrowdingStatus,
    assess_crowding,
)


def _policy() -> CrowdingPolicy:
    return CrowdingPolicy(
        max_institutional_ownership_frac=0.85,
        max_short_interest_frac_float=0.25,
        max_borrow_utilization=0.90,
        max_absolute_fund_flow_frac_aum=0.10,
        daily_liquidation_participation=0.10,
        stressed_adv_haircut=0.50,
        max_stressed_liquidation_days=5.0,
    )


def _observation(**changes: float | None) -> CrowdingObservation:
    values: dict[str, float | None] = {
        "institutional_ownership_frac": 0.50,
        "short_interest_frac_float": 0.10,
        "borrow_utilization": 0.50,
        "absolute_fund_flow_frac_aum": 0.02,
    }
    values.update(changes)
    return CrowdingObservation(
        instrument_id="XUSE:CASH:XYZUSD",
        observed_ts=90,
        available_at=100,
        valid_from=100,
        valid_until=200,
        **values,  # type: ignore[arg-type]
    )


def test_future_known_observation_fails_closed() -> None:
    row = _observation()
    with pytest.raises(LookaheadError, match="crowding observation"):
        assess_crowding(
            row,
            _policy(),
            decision_ts=99,
            resulting_signed_notional=10_000.0,
            adv_quote=1_000_000.0,
        )


def test_missing_required_short_metrics_is_unassessable() -> None:
    result = assess_crowding(
        _observation(short_interest_frac_float=None, borrow_utilization=None),
        _policy(),
        decision_ts=100,
        resulting_signed_notional=-10_000.0,
        adv_quote=1_000_000.0,
    )
    assert result.status is CrowdingStatus.UNASSESSABLE
    assert "borrow_utilization" in result.reasons[0]
    assert "short_interest" in result.reasons[0]


def test_metrics_remain_separate_and_each_can_block() -> None:
    result = assess_crowding(
        _observation(
            institutional_ownership_frac=0.90,
            short_interest_frac_float=0.30,
            borrow_utilization=0.95,
            absolute_fund_flow_frac_aum=0.20,
        ),
        _policy(),
        decision_ts=100,
        resulting_signed_notional=-300_000.0,
        adv_quote=1_000_000.0,
    )
    assert result.status is CrowdingStatus.BLOCK
    assert set(result.reasons) == {
        "institutional_ownership_limit",
        "fund_flow_limit",
        "short_interest_limit",
        "borrow_utilization_limit",
        "stressed_liquidation_days_limit",
    }
    assert result.liquidation_days == 3.0
    assert result.stressed_liquidation_days == 6.0


def test_long_does_not_require_short_specific_metrics() -> None:
    result = assess_crowding(
        _observation(short_interest_frac_float=None, borrow_utilization=None),
        _policy(),
        decision_ts=100,
        resulting_signed_notional=10_000.0,
        adv_quote=1_000_000.0,
    )
    assert result.status is CrowdingStatus.PASS
