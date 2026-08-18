"""Internal point-in-time scenario margin for option portfolios.

This is a deterministic internal risk requirement, not a broker, OCC, exchange,
Reg-T, TIMS, STANS, or portfolio-margin replica.  An upstream locked model must
provide a complete matrix of stressed option prices.  The engine nets cross-leg
P&L within each scenario, then applies source-bound policy floors and add-ons.
It does not generate volatility surfaces, infer stress prices, or include premium
cash needed to open a position.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Protocol
from urllib.parse import urlparse

from alphaforge.core.errors import LookaheadError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms
from alphaforge.core.types import MarketType

__all__ = [
    "OptionMarginAssessment",
    "OptionMarginDataProvider",
    "OptionMarginPolicy",
    "OptionMarginPosition",
    "OptionMarginRequirementType",
    "OptionMarginScenario",
    "OptionMarginScenarioLoss",
    "OptionMarginScenarioPrice",
    "OptionMarginSnapshot",
    "StaticOptionMarginDataProvider",
    "assess_option_scenario_margin",
]

ZERO = Decimal("0")
ONE = Decimal("1")


class OptionMarginRequirementType(StrEnum):
    INITIAL = "initial"
    MAINTENANCE = "maintenance"


def _decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {value!r}")


def _positive_decimal(name: str, value: Decimal) -> None:
    _decimal(name, value)
    if value <= ZERO:
        raise ValueError(f"{name} must be > 0")


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def _nonzero_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0:
        raise ValueError(f"{name} must be a non-zero integer, got {value!r}")


def _nonnegative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer, got {value!r}")


def _code(name: str, value: str) -> None:
    if (
        not value
        or value != value.upper()
        or len(value) > 64
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in value)
    ):
        raise ValueError(f"{name} must be 1-64 uppercase code characters, got {value!r}")


def _sha256(name: str, value: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be exactly 64 lowercase hexadecimal characters")


def _source_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("source_url must be an absolute credential-free HTTPS URL")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginPosition:
    instrument_id: str
    underlying_group: str
    premium_currency: str
    signed_contracts: int
    mark_price: Decimal
    contract_multiplier: Decimal

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("option margin positions require MarketType.OPTION identities")
        _code("underlying_group", self.underlying_group)
        _code("premium_currency", self.premium_currency)
        _nonzero_int("signed_contracts", self.signed_contracts)
        _decimal("mark_price", self.mark_price)
        if self.mark_price < ZERO:
            raise ValueError("mark_price must be >= 0")
        _positive_decimal("contract_multiplier", self.contract_multiplier)

    @property
    def signed_mark_value(self) -> Decimal:
        return self.signed_contracts * self.mark_price * self.contract_multiplier


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginScenarioPrice:
    instrument_id: str
    stressed_price: Decimal

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("scenario prices require MarketType.OPTION identities")
        _decimal("stressed_price", self.stressed_price)
        if self.stressed_price < ZERO:
            raise ValueError("stressed_price must be >= 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginScenario:
    scenario_id: str
    prices: tuple[OptionMarginScenarioPrice, ...]

    def __post_init__(self) -> None:
        _code("scenario_id", self.scenario_id)
        if not self.prices:
            raise ValueError("margin scenario requires at least one price")
        if any(not isinstance(price, OptionMarginScenarioPrice) for price in self.prices):
            raise ValueError("scenario prices must contain OptionMarginScenarioPrice records")
        instrument_ids = [price.instrument_id for price in self.prices]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("scenario price instrument ids must be unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginSnapshot:
    decision_ts: Ms
    marks_observed_at: Ms
    generated_at: Ms
    available_at: Ms
    max_mark_age_ms: int
    premium_currency: str
    scenario_model_id: str
    scenario_model_sha256: str
    input_artifact_sha256: str
    positions: tuple[OptionMarginPosition, ...]
    scenarios: tuple[OptionMarginScenario, ...]

    def __post_init__(self) -> None:
        if min(self.decision_ts, self.marks_observed_at, self.generated_at, self.available_at) < 0:
            raise ValueError("margin snapshot timestamps must be >= 0")
        _nonnegative_int("max_mark_age_ms", self.max_mark_age_ms)
        if not self.marks_observed_at <= self.generated_at <= self.available_at:
            raise ValueError("marks, generation, and availability timestamps must be ordered")
        if self.available_at > self.decision_ts:
            raise LookaheadError(
                f"margin scenarios available at {self.available_at} exceed decision "
                f"{self.decision_ts}"
            )
        if self.decision_ts - self.marks_observed_at > self.max_mark_age_ms:
            raise ValueError("option margin marks are stale at the decision timestamp")
        _code("premium_currency", self.premium_currency)
        _code("scenario_model_id", self.scenario_model_id)
        _sha256("scenario_model_sha256", self.scenario_model_sha256)
        _sha256("input_artifact_sha256", self.input_artifact_sha256)
        if not self.positions:
            raise ValueError("margin snapshot requires at least one position")
        if any(not isinstance(position, OptionMarginPosition) for position in self.positions):
            raise ValueError("positions must contain OptionMarginPosition records")
        position_ids = [position.instrument_id for position in self.positions]
        if len(position_ids) != len(set(position_ids)):
            raise ValueError("margin position instrument ids must be unique")
        if {position.premium_currency for position in self.positions} != {
            self.premium_currency
        }:
            raise ValueError("all margin positions must share the snapshot premium currency")
        if not self.scenarios:
            raise ValueError("margin snapshot requires at least one scenario")
        if any(not isinstance(scenario, OptionMarginScenario) for scenario in self.scenarios):
            raise ValueError("scenarios must contain OptionMarginScenario records")
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("margin scenario ids must be unique")
        expected = set(position_ids)
        for scenario in self.scenarios:
            observed = {price.instrument_id for price in scenario.prices}
            if observed != expected:
                missing = sorted(expected - observed)
                extra = sorted(observed - expected)
                raise ValueError(
                    f"margin scenario {scenario.scenario_id!r} matrix mismatch: "
                    f"missing={missing}, extra={extra}"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginPolicy:
    policy_id: str
    revision: int
    account_class: str
    risk_method: str
    premium_currency: str
    requirement_type: OptionMarginRequirementType
    source_published_at: Ms
    available_at: Ms
    effective_from: Ms
    effective_until: Ms
    source_url: str
    source_sha256: str
    scenario_loss_multiplier: Decimal
    short_contract_minimum: Decimal
    gross_short_mark_addon_rate: Decimal
    concentration_threshold: Decimal
    concentration_addon_rate: Decimal

    def __post_init__(self) -> None:
        _code("policy_id", self.policy_id)
        _positive_int("revision", self.revision)
        _code("account_class", self.account_class)
        _code("risk_method", self.risk_method)
        _code("premium_currency", self.premium_currency)
        if not isinstance(self.requirement_type, OptionMarginRequirementType):
            raise ValueError("requirement_type must be an OptionMarginRequirementType")
        if min(
            self.source_published_at,
            self.available_at,
            self.effective_from,
            self.effective_until,
        ) < 0:
            raise ValueError("margin policy timestamps must be >= 0")
        if self.available_at < self.source_published_at:
            raise ValueError("available_at cannot precede source publication")
        if self.effective_from >= self.effective_until:
            raise ValueError("effective_from must precede effective_until")
        _source_url(self.source_url)
        _sha256("source_sha256", self.source_sha256)
        _decimal("scenario_loss_multiplier", self.scenario_loss_multiplier)
        if self.scenario_loss_multiplier < ONE:
            raise ValueError("scenario_loss_multiplier must be >= 1")
        for name, value in (
            ("short_contract_minimum", self.short_contract_minimum),
            ("gross_short_mark_addon_rate", self.gross_short_mark_addon_rate),
            ("concentration_addon_rate", self.concentration_addon_rate),
        ):
            _decimal(name, value)
            if value < ZERO:
                raise ValueError(f"{name} must be >= 0")
        _decimal("concentration_threshold", self.concentration_threshold)
        if not ZERO <= self.concentration_threshold <= ONE:
            raise ValueError("concentration_threshold must be in [0, 1]")

    @property
    def key(self) -> tuple[str, str, str, OptionMarginRequirementType]:
        return (
            self.account_class,
            self.risk_method,
            self.premium_currency,
            self.requirement_type,
        )

    def require_effective(self, decision_ts: Ms) -> None:
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"margin policy {self.policy_id!r} revision {self.revision} available at "
                f"{self.available_at} exceeds decision {decision_ts}"
            )
        if not self.effective_from <= decision_ts < self.effective_until:
            raise ValueError("margin policy is not effective at the decision timestamp")


class OptionMarginDataProvider(Protocol):
    def policy(
        self,
        *,
        account_class: str,
        risk_method: str,
        premium_currency: str,
        requirement_type: OptionMarginRequirementType,
        as_of: Ms,
    ) -> OptionMarginPolicy | None:
        """Latest policy revision both known and effective at ``as_of``."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticOptionMarginDataProvider:
    policies: tuple[OptionMarginPolicy, ...]

    def __post_init__(self) -> None:
        groups: dict[
            tuple[str, str, str, OptionMarginRequirementType], list[OptionMarginPolicy]
        ] = {}
        for policy in self.policies:
            groups.setdefault(policy.key, []).append(policy)
        for key, revisions in groups.items():
            ordered = sorted(revisions, key=lambda item: item.revision)
            if {item.policy_id for item in ordered} != {ordered[0].policy_id}:
                raise ValueError(f"margin policy key {key!r} must retain one policy_id")
            if [item.revision for item in ordered] != list(range(1, len(ordered) + 1)):
                raise ValueError(f"margin policy key {key!r} revisions must be contiguous from 1")
            for prior, current in pairwise(ordered):
                if current.available_at <= prior.available_at:
                    raise ValueError("margin policy revision availability must strictly increase")
                if current.effective_from < prior.effective_from:
                    raise ValueError("margin policy effective_from cannot regress")

    def policy(
        self,
        *,
        account_class: str,
        risk_method: str,
        premium_currency: str,
        requirement_type: OptionMarginRequirementType,
        as_of: Ms,
    ) -> OptionMarginPolicy | None:
        key = (account_class, risk_method, premium_currency, requirement_type)
        candidates = [
            policy
            for policy in self.policies
            if policy.key == key
            and policy.available_at <= as_of
            and policy.effective_from <= as_of < policy.effective_until
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginScenarioLoss:
    scenario_id: str
    portfolio_pnl: Decimal
    loss: Decimal

    def __post_init__(self) -> None:
        _code("scenario_id", self.scenario_id)
        _decimal("portfolio_pnl", self.portfolio_pnl)
        _decimal("loss", self.loss)
        if self.loss != max(-self.portfolio_pnl, ZERO):
            raise ValueError("scenario loss must equal max(-portfolio_pnl, 0)")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionMarginAssessment:
    policy_id: str
    policy_revision: int
    requirement_type: OptionMarginRequirementType
    decision_ts: Ms
    premium_currency: str
    scenario_model_id: str
    scenario_model_sha256: str
    input_artifact_sha256: str
    scenario_losses: tuple[OptionMarginScenarioLoss, ...]
    worst_scenario_id: str
    worst_scenario_loss: Decimal
    scenario_loss_multiplier: Decimal
    scenario_requirement: Decimal
    short_contracts: int
    short_contract_minimum: Decimal
    short_contract_floor: Decimal
    gross_short_mark: Decimal
    gross_short_mark_addon_rate: Decimal
    gross_short_mark_addon: Decimal
    largest_short_group_share: Decimal
    concentration_threshold: Decimal
    concentration_addon_rate: Decimal
    concentration_addon: Decimal
    total_requirement: Decimal
    source_url: str
    source_sha256: str

    def __post_init__(self) -> None:
        _code("policy_id", self.policy_id)
        _positive_int("policy_revision", self.policy_revision)
        if not isinstance(self.requirement_type, OptionMarginRequirementType):
            raise ValueError("requirement_type must be an OptionMarginRequirementType")
        if self.decision_ts < 0:
            raise ValueError("decision_ts must be >= 0")
        _code("premium_currency", self.premium_currency)
        _code("scenario_model_id", self.scenario_model_id)
        _sha256("scenario_model_sha256", self.scenario_model_sha256)
        _sha256("input_artifact_sha256", self.input_artifact_sha256)
        if not self.scenario_losses:
            raise ValueError("assessment requires scenario losses")
        if any(not isinstance(row, OptionMarginScenarioLoss) for row in self.scenario_losses):
            raise ValueError("scenario_losses must contain OptionMarginScenarioLoss records")
        loss_by_id = {row.scenario_id: row.loss for row in self.scenario_losses}
        if len(loss_by_id) != len(self.scenario_losses):
            raise ValueError("assessment scenario ids must be unique")
        if self.worst_scenario_id not in loss_by_id:
            raise ValueError("worst_scenario_id must identify an assessed scenario")
        if self.worst_scenario_loss != max(loss_by_id.values()):
            raise ValueError("worst_scenario_loss must equal the maximum scenario loss")
        _nonnegative_int("short_contracts", self.short_contracts)
        for name, value in (
            ("worst_scenario_loss", self.worst_scenario_loss),
            ("scenario_loss_multiplier", self.scenario_loss_multiplier),
            ("scenario_requirement", self.scenario_requirement),
            ("short_contract_minimum", self.short_contract_minimum),
            ("short_contract_floor", self.short_contract_floor),
            ("gross_short_mark", self.gross_short_mark),
            ("gross_short_mark_addon_rate", self.gross_short_mark_addon_rate),
            ("gross_short_mark_addon", self.gross_short_mark_addon),
            ("largest_short_group_share", self.largest_short_group_share),
            ("concentration_threshold", self.concentration_threshold),
            ("concentration_addon_rate", self.concentration_addon_rate),
            ("concentration_addon", self.concentration_addon),
            ("total_requirement", self.total_requirement),
        ):
            _decimal(name, value)
            if value < ZERO:
                raise ValueError(f"{name} must be >= 0")
        if self.scenario_loss_multiplier < ONE:
            raise ValueError("scenario_loss_multiplier must be >= 1")
        if not ZERO <= self.largest_short_group_share <= ONE:
            raise ValueError("largest_short_group_share must be in [0, 1]")
        if not ZERO <= self.concentration_threshold <= ONE:
            raise ValueError("concentration_threshold must be in [0, 1]")
        if self.gross_short_mark == ZERO and self.largest_short_group_share != ZERO:
            raise ValueError("largest short-group share must be zero without short mark")
        if self.scenario_requirement != self.worst_scenario_loss * self.scenario_loss_multiplier:
            raise ValueError("scenario_requirement does not reconcile to scenario loss policy")
        if self.short_contract_floor != self.short_contracts * self.short_contract_minimum:
            raise ValueError("short_contract_floor does not reconcile to short minimum policy")
        if self.gross_short_mark_addon != (
            self.gross_short_mark * self.gross_short_mark_addon_rate
        ):
            raise ValueError("gross short-mark add-on does not reconcile to policy rate")
        expected_concentration = (
            self.gross_short_mark
            * max(self.largest_short_group_share - self.concentration_threshold, ZERO)
            * self.concentration_addon_rate
        )
        if self.concentration_addon != expected_concentration:
            raise ValueError("concentration add-on does not reconcile to policy rate")
        expected = (
            max(self.scenario_requirement, self.short_contract_floor)
            + self.gross_short_mark_addon
            + self.concentration_addon
        )
        if self.total_requirement != expected:
            raise ValueError("total_requirement does not reconcile to margin components")
        _source_url(self.source_url)
        _sha256("source_sha256", self.source_sha256)


def assess_option_scenario_margin(
    policy: OptionMarginPolicy,
    snapshot: OptionMarginSnapshot,
    *,
    decision_ts: Ms,
) -> OptionMarginAssessment:
    """Net each complete stress scenario, then apply explicit conservative add-ons."""
    policy.require_effective(decision_ts)
    if snapshot.decision_ts != decision_ts:
        raise ValueError("snapshot and assessment decision timestamps must match")
    if snapshot.premium_currency != policy.premium_currency:
        raise ValueError("snapshot and margin policy premium currencies must match")
    if snapshot.scenario_model_id != policy.risk_method:
        raise ValueError("snapshot scenario model does not match the margin policy risk method")

    positions = {position.instrument_id: position for position in snapshot.positions}
    scenario_losses: list[OptionMarginScenarioLoss] = []
    for scenario in sorted(snapshot.scenarios, key=lambda item: item.scenario_id):
        stressed = {price.instrument_id: price.stressed_price for price in scenario.prices}
        pnl = sum(
            (
                position.signed_contracts
                * (stressed[instrument_id] - position.mark_price)
                * position.contract_multiplier
                for instrument_id, position in positions.items()
            ),
            start=ZERO,
        )
        scenario_losses.append(
            OptionMarginScenarioLoss(
                scenario_id=scenario.scenario_id,
                portfolio_pnl=pnl,
                loss=max(-pnl, ZERO),
            )
        )

    worst = max(scenario_losses, key=lambda row: row.loss)
    scenario_requirement = worst.loss * policy.scenario_loss_multiplier
    shorts = [position for position in snapshot.positions if position.signed_contracts < 0]
    short_contracts = sum(abs(position.signed_contracts) for position in shorts)
    short_floor = policy.short_contract_minimum * short_contracts
    gross_by_group: dict[str, Decimal] = {}
    for position in shorts:
        mark = abs(position.signed_mark_value)
        gross_by_group[position.underlying_group] = (
            gross_by_group.get(position.underlying_group, ZERO) + mark
        )
    gross_short_mark = sum(gross_by_group.values(), start=ZERO)
    gross_addon = gross_short_mark * policy.gross_short_mark_addon_rate
    if gross_short_mark == ZERO:
        largest_share = ZERO
        concentration_addon = ZERO
    else:
        largest_share = max(gross_by_group.values()) / gross_short_mark
        excess_share = max(largest_share - policy.concentration_threshold, ZERO)
        concentration_addon = (
            gross_short_mark * excess_share * policy.concentration_addon_rate
        )
    total = max(scenario_requirement, short_floor) + gross_addon + concentration_addon
    return OptionMarginAssessment(
        policy_id=policy.policy_id,
        policy_revision=policy.revision,
        requirement_type=policy.requirement_type,
        decision_ts=decision_ts,
        premium_currency=policy.premium_currency,
        scenario_model_id=snapshot.scenario_model_id,
        scenario_model_sha256=snapshot.scenario_model_sha256,
        input_artifact_sha256=snapshot.input_artifact_sha256,
        scenario_losses=tuple(scenario_losses),
        worst_scenario_id=worst.scenario_id,
        worst_scenario_loss=worst.loss,
        scenario_loss_multiplier=policy.scenario_loss_multiplier,
        scenario_requirement=scenario_requirement,
        short_contracts=short_contracts,
        short_contract_minimum=policy.short_contract_minimum,
        short_contract_floor=short_floor,
        gross_short_mark=gross_short_mark,
        gross_short_mark_addon_rate=policy.gross_short_mark_addon_rate,
        gross_short_mark_addon=gross_addon,
        largest_short_group_share=largest_share,
        concentration_threshold=policy.concentration_threshold,
        concentration_addon_rate=policy.concentration_addon_rate,
        concentration_addon=concentration_addon,
        total_requirement=total,
        source_url=policy.source_url,
        source_sha256=policy.source_sha256,
    )
