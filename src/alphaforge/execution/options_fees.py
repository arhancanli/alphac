"""Point-in-time, source-bound option fee schedules with exact money arithmetic.

No venue rate is embedded here.  Adapters must supply immutable schedule revisions
from archived source material.  Components can represent per-contract commissions,
premium-based regulatory charges, explicit minima/caps, or rebates.  Trade assessment
uses actual option package leg executions; exercise and assignment are separate events.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Protocol
from urllib.parse import urlparse

from alphaforge.core.errors import LookaheadError
from alphaforge.core.time import Ms
from alphaforge.execution.options_packages import (
    OptionPackageExecution,
    OptionPackageExecutionStatus,
)

__all__ = [
    "OptionFeeAssessment",
    "OptionFeeComponent",
    "OptionFeeDataProvider",
    "OptionFeeEvent",
    "OptionFeeLine",
    "OptionFeeLiquidity",
    "OptionFeeRounding",
    "OptionFeeSchedule",
    "OptionFeeSide",
    "StaticOptionFeeDataProvider",
    "assess_option_lifecycle_fees",
    "assess_option_trade_fees",
]

ZERO = Decimal("0")


class OptionFeeEvent(StrEnum):
    TRADE = "trade"
    EXERCISE = "exercise"
    ASSIGNMENT = "assignment"


class OptionFeeSide(StrEnum):
    ALL = "all"
    BUY = "buy"
    SELL = "sell"


class OptionFeeLiquidity(StrEnum):
    ALL = "all"
    MAKER = "maker"
    TAKER = "taker"
    AUCTION = "auction"


class OptionFeeRounding(StrEnum):
    NONE = "none"
    HALF_UP = "half_up"
    CEILING = "ceiling"


def _decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {value!r}")


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def _code(name: str, value: str) -> None:
    if (
        not value
        or value != value.upper()
        or len(value) > 40
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in value)
    ):
        raise ValueError(f"{name} must be 1-40 uppercase code characters, got {value!r}")


def _source_sha256(value: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("source_sha256 must be exactly 64 lowercase hexadecimal characters")


def _source_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("source_url must be an absolute credential-free HTTPS URL")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionFeeComponent:
    """One independently scoped exact fee or rebate component.

    Rates are signed.  Nonnegative components may have a per-order minimum or cap.
    Rebate components must be nonpositive and cannot use minima or caps.
    ``premium_rate`` is a quote-currency fraction, not basis points.
    """

    name: str
    event: OptionFeeEvent
    side: OptionFeeSide = OptionFeeSide.ALL
    liquidity: OptionFeeLiquidity = OptionFeeLiquidity.ALL
    per_contract: Decimal = ZERO
    premium_rate: Decimal = ZERO
    rounding_increment: Decimal | None = None
    rounding: OptionFeeRounding = OptionFeeRounding.NONE
    minimum_per_order: Decimal | None = None
    maximum_per_order: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("fee component name must not be blank")
        if not isinstance(self.event, OptionFeeEvent):
            raise ValueError("event must be an OptionFeeEvent")
        if not isinstance(self.side, OptionFeeSide):
            raise ValueError("side must be an OptionFeeSide")
        if not isinstance(self.liquidity, OptionFeeLiquidity):
            raise ValueError("liquidity must be an OptionFeeLiquidity")
        if not isinstance(self.rounding, OptionFeeRounding):
            raise ValueError("rounding must be an OptionFeeRounding")
        _decimal("per_contract", self.per_contract)
        _decimal("premium_rate", self.premium_rate)
        if self.per_contract == ZERO and self.premium_rate == ZERO:
            raise ValueError("fee component must have a non-zero rate")
        if self.per_contract * self.premium_rate < ZERO:
            raise ValueError("per-contract and premium rates cannot mix fee and rebate signs")
        if self.rounding_increment is None:
            if self.rounding is not OptionFeeRounding.NONE:
                raise ValueError("rounding mode requires a rounding_increment")
        else:
            _decimal("rounding_increment", self.rounding_increment)
            if self.rounding_increment <= ZERO:
                raise ValueError("rounding_increment must be > 0")
            if self.rounding is OptionFeeRounding.NONE:
                raise ValueError("rounding_increment requires an explicit rounding mode")
        if self.event is not OptionFeeEvent.TRADE:
            if self.side is not OptionFeeSide.ALL:
                raise ValueError("exercise and assignment components cannot be side-scoped")
            if self.liquidity is not OptionFeeLiquidity.ALL:
                raise ValueError("exercise and assignment components cannot be liquidity-scoped")
            if self.premium_rate != ZERO:
                raise ValueError("exercise and assignment components cannot use premium_rate")
        for name, value in (
            ("minimum_per_order", self.minimum_per_order),
            ("maximum_per_order", self.maximum_per_order),
        ):
            if value is not None:
                _decimal(name, value)
                if value < ZERO:
                    raise ValueError(f"{name} must be >= 0")
        is_rebate = self.per_contract < ZERO or self.premium_rate < ZERO
        if is_rebate and (self.minimum_per_order is not None or self.maximum_per_order is not None):
            raise ValueError("rebate components cannot use minima or caps")
        if (
            self.minimum_per_order is not None
            and self.maximum_per_order is not None
            and self.minimum_per_order > self.maximum_per_order
        ):
            raise ValueError("minimum_per_order cannot exceed maximum_per_order")

    def assess(self, *, contracts: int, premium_notional: Decimal) -> Decimal:
        _positive_int("contracts", contracts)
        _decimal("premium_notional", premium_notional)
        if premium_notional < ZERO:
            raise ValueError("premium_notional must be >= 0")
        amount = self.per_contract * contracts + self.premium_rate * premium_notional
        if self.rounding_increment is not None:
            decimal_rounding = (
                ROUND_HALF_UP
                if self.rounding is OptionFeeRounding.HALF_UP
                else ROUND_CEILING
            )
            amount = (
                amount / self.rounding_increment
            ).to_integral_value(rounding=decimal_rounding) * self.rounding_increment
        if self.minimum_per_order is not None:
            amount = max(amount, self.minimum_per_order)
        if self.maximum_per_order is not None:
            amount = min(amount, self.maximum_per_order)
        return amount


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionFeeSchedule:
    """One immutable schedule revision with effective and availability lineage."""

    schedule_id: str
    revision: int
    venue: str
    account_class: str
    product_group: str
    premium_currency: str
    source_published_at: Ms
    available_at: Ms
    effective_from: Ms
    effective_until: Ms
    source_url: str
    source_sha256: str
    components: tuple[OptionFeeComponent, ...]

    def __post_init__(self) -> None:
        _code("schedule_id", self.schedule_id)
        _positive_int("revision", self.revision)
        _code("venue", self.venue)
        _code("account_class", self.account_class)
        _code("product_group", self.product_group)
        _code("premium_currency", self.premium_currency)
        if min(
            self.source_published_at,
            self.available_at,
            self.effective_from,
            self.effective_until,
        ) < 0:
            raise ValueError("fee schedule timestamps must be >= 0")
        if self.available_at < self.source_published_at:
            raise ValueError("available_at cannot precede source publication")
        if self.effective_from >= self.effective_until:
            raise ValueError("effective_from must precede effective_until")
        _source_url(self.source_url)
        _source_sha256(self.source_sha256)
        if not self.components:
            raise ValueError("fee schedule requires at least one component")
        identities = [
            (component.name, component.event, component.side, component.liquidity)
            for component in self.components
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("fee component scope identities must be unique")

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.venue, self.account_class, self.product_group, self.premium_currency)

    def require_effective(self, decision_ts: Ms) -> None:
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"fee schedule {self.schedule_id!r} revision {self.revision} available at "
                f"{self.available_at} exceeds decision {decision_ts}"
            )
        if not self.effective_from <= decision_ts < self.effective_until:
            raise ValueError("fee schedule is not effective at the decision timestamp")


class OptionFeeDataProvider(Protocol):
    def schedule(
        self,
        *,
        venue: str,
        account_class: str,
        product_group: str,
        premium_currency: str,
        as_of: Ms,
    ) -> OptionFeeSchedule | None:
        """Latest schedule revision both known and effective at ``as_of``."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticOptionFeeDataProvider:
    schedules: tuple[OptionFeeSchedule, ...]

    def __post_init__(self) -> None:
        groups: dict[tuple[str, str, str, str], list[OptionFeeSchedule]] = {}
        for schedule in self.schedules:
            groups.setdefault(schedule.key, []).append(schedule)
        for key, revisions in groups.items():
            ordered = sorted(revisions, key=lambda item: item.revision)
            if {item.schedule_id for item in ordered} != {ordered[0].schedule_id}:
                raise ValueError(f"fee schedule key {key!r} must retain one schedule_id")
            if [item.revision for item in ordered] != list(range(1, len(ordered) + 1)):
                raise ValueError(f"fee schedule key {key!r} revisions must be contiguous from 1")
            for prior, current in pairwise(ordered):
                if current.available_at <= prior.available_at:
                    raise ValueError("fee schedule revision availability must strictly increase")
                if current.effective_from < prior.effective_from:
                    raise ValueError("fee schedule effective_from cannot regress across revisions")

    def schedule(
        self,
        *,
        venue: str,
        account_class: str,
        product_group: str,
        premium_currency: str,
        as_of: Ms,
    ) -> OptionFeeSchedule | None:
        key = (venue, account_class, product_group, premium_currency)
        candidates = [
            schedule
            for schedule in self.schedules
            if schedule.key == key
            and schedule.available_at <= as_of
            and schedule.effective_from <= as_of < schedule.effective_until
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionFeeLine:
    component_name: str
    event: OptionFeeEvent
    contracts: int
    premium_notional: Decimal
    amount: Decimal

    def __post_init__(self) -> None:
        if not self.component_name.strip():
            raise ValueError("component_name must not be blank")
        if not isinstance(self.event, OptionFeeEvent):
            raise ValueError("fee line event must be an OptionFeeEvent")
        _positive_int("contracts", self.contracts)
        _decimal("premium_notional", self.premium_notional)
        _decimal("amount", self.amount)
        if self.premium_notional < ZERO:
            raise ValueError("premium_notional must be >= 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionFeeAssessment:
    schedule_id: str
    schedule_revision: int
    event: OptionFeeEvent
    assessment_ts: Ms
    premium_currency: str
    lines: tuple[OptionFeeLine, ...]
    total_amount: Decimal
    source_url: str
    source_sha256: str

    def __post_init__(self) -> None:
        _code("schedule_id", self.schedule_id)
        _positive_int("schedule_revision", self.schedule_revision)
        if not isinstance(self.event, OptionFeeEvent):
            raise ValueError("assessment event must be an OptionFeeEvent")
        if self.assessment_ts < 0:
            raise ValueError("assessment_ts must be >= 0")
        _code("premium_currency", self.premium_currency)
        if any(not isinstance(line, OptionFeeLine) for line in self.lines):
            raise ValueError("lines must contain only OptionFeeLine records")
        if any(line.event is not self.event for line in self.lines):
            raise ValueError("fee line events must match the assessment event")
        _decimal("total_amount", self.total_amount)
        if self.total_amount != sum((line.amount for line in self.lines), start=ZERO):
            raise ValueError("total_amount must equal the exact sum of fee lines")
        _source_url(self.source_url)
        _source_sha256(self.source_sha256)


def _assessment(
    *,
    schedule: OptionFeeSchedule,
    event: OptionFeeEvent,
    decision_ts: Ms,
    lines: tuple[OptionFeeLine, ...],
) -> OptionFeeAssessment:
    return OptionFeeAssessment(
        schedule_id=schedule.schedule_id,
        schedule_revision=schedule.revision,
        event=event,
        assessment_ts=decision_ts,
        premium_currency=schedule.premium_currency,
        lines=lines,
        total_amount=sum((line.amount for line in lines), start=ZERO),
        source_url=schedule.source_url,
        source_sha256=schedule.source_sha256,
    )


def assess_option_trade_fees(
    schedule: OptionFeeSchedule,
    execution: OptionPackageExecution,
    *,
    liquidity: OptionFeeLiquidity,
    decision_ts: Ms,
) -> OptionFeeAssessment:
    """Assess one accepted package execution at exact schedule rates."""
    schedule.require_effective(decision_ts)
    if not isinstance(liquidity, OptionFeeLiquidity) or liquidity is OptionFeeLiquidity.ALL:
        raise ValueError("trade assessment requires MAKER, TAKER, or AUCTION liquidity")
    if execution.status is OptionPackageExecutionStatus.REJECTED:
        raise ValueError("cannot assess trade fees on a rejected package")
    if execution.decision_ts != decision_ts:
        raise ValueError("execution and fee assessment timestamps must match")
    if execution.premium_currency != schedule.premium_currency:
        raise ValueError("execution and fee schedule premium currencies must match")

    lines: list[OptionFeeLine] = []
    for component in schedule.components:
        if component.event is not OptionFeeEvent.TRADE:
            continue
        if component.liquidity not in (OptionFeeLiquidity.ALL, liquidity):
            continue
        selected = [
            leg
            for leg in execution.leg_executions
            if component.side is OptionFeeSide.ALL
            or (component.side is OptionFeeSide.BUY and leg.signed_contracts > 0)
            or (component.side is OptionFeeSide.SELL and leg.signed_contracts < 0)
        ]
        if not selected:
            continue
        contracts = sum(abs(leg.signed_contracts) for leg in selected)
        premium_notional = sum(
            (
                Decimal(abs(leg.signed_contracts))
                * Decimal(str(leg.price))
                * Decimal(str(leg.contract_multiplier))
                for leg in selected
            ),
            start=ZERO,
        )
        lines.append(
            OptionFeeLine(
                component_name=component.name,
                event=OptionFeeEvent.TRADE,
                contracts=contracts,
                premium_notional=premium_notional,
                amount=component.assess(
                    contracts=contracts,
                    premium_notional=premium_notional,
                ),
            )
        )
    return _assessment(
        schedule=schedule,
        event=OptionFeeEvent.TRADE,
        decision_ts=decision_ts,
        lines=tuple(lines),
    )


def assess_option_lifecycle_fees(
    schedule: OptionFeeSchedule,
    *,
    event: OptionFeeEvent,
    contracts: int,
    decision_ts: Ms,
) -> OptionFeeAssessment:
    """Assess exact per-contract exercise or assignment fees."""
    schedule.require_effective(decision_ts)
    if event not in (OptionFeeEvent.EXERCISE, OptionFeeEvent.ASSIGNMENT):
        raise ValueError("lifecycle assessment requires EXERCISE or ASSIGNMENT event")
    _positive_int("contracts", contracts)
    lines = tuple(
        OptionFeeLine(
            component_name=component.name,
            event=event,
            contracts=contracts,
            premium_notional=ZERO,
            amount=component.assess(contracts=contracts, premium_notional=ZERO),
        )
        for component in schedule.components
        if component.event is event
    )
    return _assessment(
        schedule=schedule,
        event=event,
        decision_ts=decision_ts,
        lines=lines,
    )
