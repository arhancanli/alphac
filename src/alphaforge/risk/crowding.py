"""Coverage-aware point-in-time crowding and liquidation-risk assessment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from alphaforge.core.errors import LookaheadError
from alphaforge.core.time import Ms

__all__ = [
    "CrowdingAssessment",
    "CrowdingObservation",
    "CrowdingPolicy",
    "CrowdingStatus",
    "assess_crowding",
]


def _fraction(name: str, value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be a finite fraction in [0, 1]")


@dataclass(frozen=True, slots=True, kw_only=True)
class CrowdingObservation:
    instrument_id: str
    observed_ts: Ms
    available_at: Ms
    valid_from: Ms
    valid_until: Ms
    institutional_ownership_frac: float | None
    short_interest_frac_float: float | None
    borrow_utilization: float | None
    absolute_fund_flow_frac_aum: float | None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id cannot be empty")
        if self.available_at < self.observed_ts:
            raise ValueError("available_at cannot precede observed_ts")
        if self.valid_from >= self.valid_until:
            raise ValueError("valid_from must precede valid_until")
        _fraction("institutional_ownership_frac", self.institutional_ownership_frac)
        _fraction("short_interest_frac_float", self.short_interest_frac_float)
        _fraction("borrow_utilization", self.borrow_utilization)
        _fraction("absolute_fund_flow_frac_aum", self.absolute_fund_flow_frac_aum)

    def require_effective(self, decision_ts: Ms) -> None:
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"crowding observation for {self.instrument_id!r} available at "
                f"{self.available_at} exceeds decision {decision_ts}"
            )
        if not self.valid_from <= decision_ts < self.valid_until:
            raise ValueError("crowding observation is not effective at decision time")


@dataclass(frozen=True, slots=True, kw_only=True)
class CrowdingPolicy:
    max_institutional_ownership_frac: float
    max_short_interest_frac_float: float
    max_borrow_utilization: float
    max_absolute_fund_flow_frac_aum: float
    daily_liquidation_participation: float
    stressed_adv_haircut: float
    max_stressed_liquidation_days: float
    require_ownership: bool = True
    require_fund_flows: bool = True
    require_short_metrics_for_shorts: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_institutional_ownership_frac",
            "max_short_interest_frac_float",
            "max_borrow_utilization",
            "max_absolute_fund_flow_frac_aum",
            "daily_liquidation_participation",
            "stressed_adv_haircut",
        ):
            _fraction(name, float(getattr(self, name)))
        if self.daily_liquidation_participation == 0.0 or self.stressed_adv_haircut == 0.0:
            raise ValueError("liquidation participation and ADV haircut must be > 0")
        if not math.isfinite(self.max_stressed_liquidation_days) or (
            self.max_stressed_liquidation_days <= 0.0
        ):
            raise ValueError("max_stressed_liquidation_days must be finite and > 0")


class CrowdingStatus(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    UNASSESSABLE = "unassessable"


@dataclass(frozen=True, slots=True, kw_only=True)
class CrowdingAssessment:
    status: CrowdingStatus
    reasons: tuple[str, ...]
    liquidation_days: float
    stressed_liquidation_days: float


def assess_crowding(
    observation: CrowdingObservation,
    policy: CrowdingPolicy,
    *,
    decision_ts: Ms,
    resulting_signed_notional: float,
    adv_quote: float,
) -> CrowdingAssessment:
    """Assess observable crowding without blending heterogeneous metrics into one score."""
    observation.require_effective(decision_ts)
    if not math.isfinite(resulting_signed_notional):
        raise ValueError("resulting_signed_notional must be finite")
    if not math.isfinite(adv_quote) or adv_quote <= 0.0:
        raise ValueError("adv_quote must be finite and > 0")
    missing: list[str] = []
    if policy.require_ownership and observation.institutional_ownership_frac is None:
        missing.append("institutional_ownership")
    if policy.require_fund_flows and observation.absolute_fund_flow_frac_aum is None:
        missing.append("fund_flows")
    is_short = resulting_signed_notional < 0.0
    if policy.require_short_metrics_for_shorts and is_short:
        if observation.short_interest_frac_float is None:
            missing.append("short_interest")
        if observation.borrow_utilization is None:
            missing.append("borrow_utilization")
    liquidation_days = abs(resulting_signed_notional) / (
        policy.daily_liquidation_participation * adv_quote
    )
    stressed_days = liquidation_days / policy.stressed_adv_haircut
    if missing:
        return CrowdingAssessment(
            status=CrowdingStatus.UNASSESSABLE,
            reasons=("missing required PIT metrics: " + ", ".join(sorted(missing)),),
            liquidation_days=liquidation_days,
            stressed_liquidation_days=stressed_days,
        )
    reasons: list[str] = []
    if (
        observation.institutional_ownership_frac is not None
        and observation.institutional_ownership_frac > policy.max_institutional_ownership_frac
    ):
        reasons.append("institutional_ownership_limit")
    if (
        observation.absolute_fund_flow_frac_aum is not None
        and observation.absolute_fund_flow_frac_aum > policy.max_absolute_fund_flow_frac_aum
    ):
        reasons.append("fund_flow_limit")
    if is_short:
        if (
            observation.short_interest_frac_float is not None
            and observation.short_interest_frac_float > policy.max_short_interest_frac_float
        ):
            reasons.append("short_interest_limit")
        if (
            observation.borrow_utilization is not None
            and observation.borrow_utilization > policy.max_borrow_utilization
        ):
            reasons.append("borrow_utilization_limit")
    if stressed_days > policy.max_stressed_liquidation_days:
        reasons.append("stressed_liquidation_days_limit")
    return CrowdingAssessment(
        status=CrowdingStatus.BLOCK if reasons else CrowdingStatus.PASS,
        reasons=tuple(reasons),
        liquidation_days=liquidation_days,
        stressed_liquidation_days=stressed_days,
    )
