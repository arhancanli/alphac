"""Point-in-time option terms, quote-surface, expiry, exercise, and assignment primitives.

The module is intentionally narrower than an option backtester.  It makes the lifecycle
facts that cannot be inferred from an adjusted underlying price explicit: contract terms,
quote availability, official settlement observations, automatic exercise, and delivered
cash/underlying.  It does not synthesize missing strikes, estimate an implied-volatility
surface, predict early assignment, or claim an executable option sleeve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from alphaforge.core.errors import LookaheadError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms
from alphaforge.core.types import MarketType

__all__ = [
    "AssignmentNotice",
    "ExerciseStyle",
    "OptionContract",
    "OptionDelivery",
    "OptionQuote",
    "OptionRight",
    "OptionSettlement",
    "OptionSurfaceIntegrityError",
    "OptionSurfaceSnapshot",
    "OptionSurfaceViolation",
    "OptionSurfaceViolationType",
    "SettlementStyle",
    "apply_assignment",
    "expiry_delivery",
    "intrinsic_value",
]


def _positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _nonnegative_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and >= 0, got {value!r}")


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _currency(value: str) -> str:
    if not value or value != value.upper() or not value.isalnum() or not 3 <= len(value) <= 12:
        raise ValueError(f"currency must be 3-12 uppercase alphanumerics, got {value!r}")
    return value


def _materially_greater(lhs: float, rhs: float) -> bool:
    """Reject real bound violations without turning float round-off into market structure."""
    tolerance = max(1e-12, 1e-12 * max(abs(lhs), abs(rhs)))
    return lhs > rhs + tolerance


class OptionRight(StrEnum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(StrEnum):
    AMERICAN = "american"
    EUROPEAN = "european"


class SettlementStyle(StrEnum):
    CASH = "cash"
    PHYSICAL = "physical"


class OptionSurfaceViolationType(StrEnum):
    """Guaranteed cross-strike failures in displayed, positive-size quote bounds."""

    CALL_MONOTONICITY = "call_monotonicity"
    PUT_MONOTONICITY = "put_monotonicity"
    STRIKE_CONVEXITY = "strike_convexity"


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionSurfaceViolation:
    """One deterministic quote-bound violation in a homogeneous option series."""

    violation_type: OptionSurfaceViolationType
    expiration_ts: Ms
    right: OptionRight
    strikes: tuple[float, ...]
    detail: str


class OptionSurfaceIntegrityError(ValueError):
    """Raised when displayed positive-size quotes guarantee a cross-strike violation."""

    def __init__(self, violations: tuple[OptionSurfaceViolation, ...]) -> None:
        self.violations = violations
        summary = "; ".join(
            f"{item.violation_type.value}@{item.expiration_ts}:{item.strikes}"
            for item in violations
        )
        super().__init__(f"option surface static-arbitrage violation(s): {summary}")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionContract:
    """Immutable option terms with their explicit observation timestamp."""

    instrument_id: str
    underlying_instrument_id: str
    right: OptionRight
    strike: float
    expiration_ts: Ms
    last_trade_ts: Ms
    listed_ts: Ms
    metadata_available_at: Ms
    exercise_style: ExerciseStyle
    settlement_style: SettlementStyle
    contract_multiplier: float

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError(
                f"option contract requires MarketType.OPTION, got {market_type.value!r}"
            )
        SymbolMapper.parse_instrument_id(self.underlying_instrument_id)
        _positive_finite("strike", self.strike)
        _positive_finite("contract_multiplier", self.contract_multiplier)
        if self.listed_ts >= self.last_trade_ts:
            raise ValueError("listed_ts must precede last_trade_ts")
        if self.last_trade_ts > self.expiration_ts:
            raise ValueError("last_trade_ts cannot follow expiration_ts")
        if self.metadata_available_at > self.last_trade_ts:
            raise ValueError("metadata_available_at cannot follow last_trade_ts")

    def known_at(self, decision_ts: Ms) -> bool:
        return self.listed_ts <= decision_ts and self.metadata_available_at <= decision_ts


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionQuote:
    """One non-crossed option quote with observation and availability lineage."""

    instrument_id: str
    premium_currency: str
    observed_ts: Ms
    available_at: Ms
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    def __post_init__(self) -> None:
        _currency(self.premium_currency)
        if self.available_at < self.observed_ts:
            raise ValueError("available_at cannot precede observed_ts")
        _nonnegative_finite("bid", self.bid)
        _positive_finite("ask", self.ask)
        _nonnegative_finite("bid_size", self.bid_size)
        _nonnegative_finite("ask_size", self.ask_size)
        if self.bid > self.ask:
            raise ValueError("option quote cannot be crossed")

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionSurfaceSnapshot:
    """A single-underlying decision-time slice with executable integrity checks.

    Missing quotes remain missing. Cross-strike checks operate only inside homogeneous
    expiry/right/exercise/settlement/multiplier series and reject only violations guaranteed by
    displayed, positive-size bid/ask bounds. This is a quote-integrity gate, not a claim that the
    full package can fill at displayed size. No midpoint smoothing, parity input, or interpolation
    is invented.
    """

    decision_ts: Ms
    max_quote_age_ms: int
    contracts: tuple[OptionContract, ...]
    quotes: tuple[OptionQuote, ...]

    def __post_init__(self) -> None:
        if self.max_quote_age_ms < 0:
            raise ValueError("max_quote_age_ms must be >= 0")
        if not self.contracts:
            raise ValueError("option surface requires at least one contract")
        contract_by_id = {contract.instrument_id: contract for contract in self.contracts}
        if len(contract_by_id) != len(self.contracts):
            raise ValueError("option surface contract ids must be unique")
        underlyings = {contract.underlying_instrument_id for contract in self.contracts}
        if len(underlyings) != 1:
            raise ValueError("option surface contracts must share one underlying")
        economic_terms: set[
            tuple[str, OptionRight, float, Ms, ExerciseStyle, SettlementStyle, float]
        ] = set()
        quote_ids: set[str] = set()
        for contract in self.contracts:
            if not contract.known_at(self.decision_ts):
                raise LookaheadError(
                    f"option terms for {contract.instrument_id!r} were not known at "
                    f"decision {self.decision_ts}"
                )
            if self.decision_ts > contract.last_trade_ts:
                raise ValueError(
                    f"option contract {contract.instrument_id!r} is no longer tradable at "
                    f"decision {self.decision_ts}"
                )
            terms = (
                contract.underlying_instrument_id,
                contract.right,
                contract.strike,
                contract.expiration_ts,
                contract.exercise_style,
                contract.settlement_style,
                contract.contract_multiplier,
            )
            if terms in economic_terms:
                raise ValueError("option surface contains duplicate economic contract terms")
            economic_terms.add(terms)
        for quote in self.quotes:
            if quote.instrument_id in quote_ids:
                raise ValueError(f"duplicate option quote for {quote.instrument_id!r}")
            quote_ids.add(quote.instrument_id)
            if quote.instrument_id not in contract_by_id:
                raise ValueError(f"quote has no contract terms: {quote.instrument_id!r}")
            contract = contract_by_id[quote.instrument_id]
            if not contract.listed_ts <= quote.observed_ts <= contract.last_trade_ts:
                raise ValueError(
                    f"option quote for {quote.instrument_id!r} falls outside its tradable lifecycle"
                )
            if quote.available_at > self.decision_ts:
                raise LookaheadError(
                    f"quote for {quote.instrument_id!r} available at {quote.available_at} "
                    f"exceeds decision {self.decision_ts}"
                )
            if self.decision_ts - quote.observed_ts > self.max_quote_age_ms:
                raise ValueError(f"stale option quote for {quote.instrument_id!r}")
        violations = _static_arbitrage_violations(self.contracts, self.quotes)
        if violations:
            raise OptionSurfaceIntegrityError(violations)

    @property
    def underlying_instrument_id(self) -> str:
        """The one underlying shared by every admitted contract."""
        return self.contracts[0].underlying_instrument_id

    def static_arbitrage_violations(self) -> tuple[OptionSurfaceViolation, ...]:
        """Return guaranteed quote-bound violations; valid snapshots always return empty."""
        return _static_arbitrage_violations(self.contracts, self.quotes)

    def complete_quotes(self) -> tuple[tuple[OptionContract, OptionQuote], ...]:
        """Return only explicitly quoted contracts; never interpolate missing strikes."""
        quote_by_id = {quote.instrument_id: quote for quote in self.quotes}
        return tuple(
            (contract, quote_by_id[contract.instrument_id])
            for contract in self.contracts
            if contract.instrument_id in quote_by_id
        )


def _static_arbitrage_violations(
    contracts: tuple[OptionContract, ...],
    quotes: tuple[OptionQuote, ...],
) -> tuple[OptionSurfaceViolation, ...]:
    """Check monotonicity and strike convexity from positive-size bid/ask bounds only."""
    contract_by_id = {contract.instrument_id: contract for contract in contracts}
    series: dict[
        tuple[Ms, OptionRight, ExerciseStyle, SettlementStyle, float, str],
        list[tuple[OptionContract, OptionQuote]],
    ] = {}
    for quote in quotes:
        contract = contract_by_id[quote.instrument_id]
        key = (
            contract.expiration_ts,
            contract.right,
            contract.exercise_style,
            contract.settlement_style,
            contract.contract_multiplier,
            quote.premium_currency,
        )
        series.setdefault(key, []).append((contract, quote))

    violations: list[OptionSurfaceViolation] = []
    for key, points in sorted(series.items(), key=lambda item: tuple(str(v) for v in item[0])):
        expiration_ts, right, _exercise, _settlement, _multiplier, _premium_currency = key
        ordered = sorted(points, key=lambda point: point[0].strike)
        for lower, higher in pairwise(ordered):
            low_contract, low_quote = lower
            high_contract, high_quote = higher
            if (
                right is OptionRight.CALL
                and low_quote.ask_size > 0.0
                and high_quote.bid_size > 0.0
                and _materially_greater(high_quote.bid, low_quote.ask)
            ):
                violations.append(
                    OptionSurfaceViolation(
                        violation_type=OptionSurfaceViolationType.CALL_MONOTONICITY,
                        expiration_ts=expiration_ts,
                        right=right,
                        strikes=(low_contract.strike, high_contract.strike),
                        detail="higher-strike bid exceeds lower-strike ask",
                    )
                )
            if (
                right is OptionRight.PUT
                and low_quote.bid_size > 0.0
                and high_quote.ask_size > 0.0
                and _materially_greater(low_quote.bid, high_quote.ask)
            ):
                violations.append(
                    OptionSurfaceViolation(
                        violation_type=OptionSurfaceViolationType.PUT_MONOTONICITY,
                        expiration_ts=expiration_ts,
                        right=right,
                        strikes=(low_contract.strike, high_contract.strike),
                        detail="lower-strike bid exceeds higher-strike ask",
                    )
                )

        for index in range(1, len(ordered) - 1):
            low_contract, low_quote = ordered[index - 1]
            mid_contract, mid_quote = ordered[index]
            high_contract, high_quote = ordered[index + 1]
            if not (
                low_quote.ask_size > 0.0
                and mid_quote.bid_size > 0.0
                and high_quote.ask_size > 0.0
            ):
                continue
            width = high_contract.strike - low_contract.strike
            low_weight = (high_contract.strike - mid_contract.strike) / width
            high_weight = (mid_contract.strike - low_contract.strike) / width
            outer_ask_bound = low_weight * low_quote.ask + high_weight * high_quote.ask
            if _materially_greater(mid_quote.bid, outer_ask_bound):
                violations.append(
                    OptionSurfaceViolation(
                        violation_type=OptionSurfaceViolationType.STRIKE_CONVEXITY,
                        expiration_ts=expiration_ts,
                        right=right,
                        strikes=(
                            low_contract.strike,
                            mid_contract.strike,
                            high_contract.strike,
                        ),
                        detail=(
                            "middle-strike bid exceeds the strike-weighted outer asks"
                        ),
                    )
                )
    return tuple(violations)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionSettlement:
    """Official expiry settlement observation, distinct from a last trade or midpoint."""

    underlying_instrument_id: str
    settlement_ts: Ms
    available_at: Ms
    price: float

    def __post_init__(self) -> None:
        SymbolMapper.parse_instrument_id(self.underlying_instrument_id)
        if self.available_at < self.settlement_ts:
            raise ValueError("settlement available_at cannot precede settlement_ts")
        _positive_finite("settlement price", self.price)

    def require_known(self, decision_ts: Ms) -> None:
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"official settlement available at {self.available_at} exceeds decision "
                f"{decision_ts}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignmentNotice:
    """Broker/clearing assignment notice; no probabilistic assignment is invented."""

    instrument_id: str
    assigned_contracts: float
    event_ts: Ms
    available_at: Ms

    def __post_init__(self) -> None:
        _positive_finite("assigned_contracts", self.assigned_contracts)
        if self.available_at < self.event_ts:
            raise ValueError("assignment available_at cannot precede event_ts")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionDelivery:
    """Atomic position/cash effects from expiry exercise or an assignment notice."""

    event_type: str
    instrument_id: str
    option_contracts_delta: float
    underlying_instrument_id: str
    underlying_qty_delta: float
    cash_delta: float


def intrinsic_value(contract: OptionContract, underlying_price: float) -> float:
    _positive_finite("underlying_price", underlying_price)
    if contract.right is OptionRight.CALL:
        return max(underlying_price - contract.strike, 0.0)
    return max(contract.strike - underlying_price, 0.0)


def _delivery(
    contract: OptionContract,
    *,
    signed_contracts: float,
    settlement_price: float,
    event_type: str,
) -> OptionDelivery:
    intrinsic = intrinsic_value(contract, settlement_price)
    if intrinsic == 0.0 or signed_contracts == 0.0:
        return OptionDelivery(
            event_type=event_type,
            instrument_id=contract.instrument_id,
            option_contracts_delta=-signed_contracts,
            underlying_instrument_id=contract.underlying_instrument_id,
            underlying_qty_delta=0.0,
            cash_delta=0.0,
        )
    if contract.settlement_style is SettlementStyle.CASH:
        return OptionDelivery(
            event_type=event_type,
            instrument_id=contract.instrument_id,
            option_contracts_delta=-signed_contracts,
            underlying_instrument_id=contract.underlying_instrument_id,
            underlying_qty_delta=0.0,
            cash_delta=signed_contracts * contract.contract_multiplier * intrinsic,
        )
    direction = 1.0 if contract.right is OptionRight.CALL else -1.0
    underlying_delta = signed_contracts * contract.contract_multiplier * direction
    return OptionDelivery(
        event_type=event_type,
        instrument_id=contract.instrument_id,
        option_contracts_delta=-signed_contracts,
        underlying_instrument_id=contract.underlying_instrument_id,
        underlying_qty_delta=underlying_delta,
        cash_delta=-underlying_delta * contract.strike,
    )


def expiry_delivery(
    contract: OptionContract,
    *,
    signed_contracts: float,
    settlement: OptionSettlement,
    decision_ts: Ms,
    auto_exercise_threshold: float = 0.01,
) -> OptionDelivery:
    """Settle an expired position from the official, already-available settlement price."""
    if decision_ts < contract.expiration_ts:
        raise ValueError("cannot settle an option before expiration")
    if not contract.known_at(decision_ts):
        raise LookaheadError("option terms were not known by the expiry decision")
    if settlement.underlying_instrument_id != contract.underlying_instrument_id:
        raise ValueError("settlement underlying does not match option terms")
    if settlement.settlement_ts < contract.expiration_ts:
        raise ValueError("official settlement cannot precede option expiration")
    settlement.require_known(decision_ts)
    _finite("signed_contracts", signed_contracts)
    _nonnegative_finite("auto_exercise_threshold", auto_exercise_threshold)
    if intrinsic_value(contract, settlement.price) < auto_exercise_threshold:
        return _delivery(
            contract,
            signed_contracts=signed_contracts,
            settlement_price=contract.strike,
            event_type="expiry_lapse",
        )
    return _delivery(
        contract,
        signed_contracts=signed_contracts,
        settlement_price=settlement.price,
        event_type="expiry_exercise_or_assignment",
    )


def apply_assignment(
    contract: OptionContract,
    *,
    short_contracts: float,
    notice: AssignmentNotice,
    decision_ts: Ms,
) -> OptionDelivery:
    """Apply a known early-assignment notice to a short American physical option."""
    if contract.exercise_style is not ExerciseStyle.AMERICAN:
        raise ValueError("early assignment requires an American-style option")
    if contract.settlement_style is not SettlementStyle.PHYSICAL:
        raise ValueError("early assignment requires physical settlement")
    if notice.instrument_id != contract.instrument_id:
        raise ValueError("assignment notice does not match option contract")
    if not contract.known_at(decision_ts):
        raise LookaheadError("option terms were not known by the assignment decision")
    if notice.event_ts >= contract.expiration_ts:
        raise ValueError("early-assignment event must precede option expiration")
    if notice.available_at > decision_ts:
        raise LookaheadError(
            f"assignment notice available at {notice.available_at} exceeds decision {decision_ts}"
        )
    _positive_finite("short_contracts", short_contracts)
    if notice.assigned_contracts > short_contracts:
        raise ValueError("assigned contracts exceed the short option position")
    signed_assigned = -notice.assigned_contracts
    direction = 1.0 if contract.right is OptionRight.CALL else -1.0
    underlying_delta = signed_assigned * contract.contract_multiplier * direction
    return OptionDelivery(
        event_type="early_assignment",
        instrument_id=contract.instrument_id,
        option_contracts_delta=notice.assigned_contracts,
        underlying_instrument_id=contract.underlying_instrument_id,
        underlying_qty_delta=underlying_delta,
        cash_delta=-underlying_delta * contract.strike,
    )
