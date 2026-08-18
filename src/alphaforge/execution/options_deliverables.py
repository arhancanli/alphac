"""Point-in-time adjusted option deliverables and signed basket delivery.

Adjusted contracts cannot safely reuse the standard ``multiplier x one underlying`` shortcut.
Splits, mergers, spin-offs, and cash consideration can change what one exercised contract
delivers while leaving the option identifier alive. This module preserves every revision's
effective and availability timestamps and turns an already-authorized exercise or assignment
into an explicit asset/cash basket. It does not infer adjustments from prices or corporate-action
headlines and does not model exercise probability, margin, or package fillability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from alphaforge.core.errors import LookaheadError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms
from alphaforge.core.types import MarketType
from alphaforge.execution.options import (
    AssignmentNotice,
    ExerciseStyle,
    OptionContract,
    OptionRight,
    OptionSettlement,
    SettlementStyle,
    intrinsic_value,
)

__all__ = [
    "OptionAssetDelta",
    "OptionBasketDelivery",
    "OptionCashAmount",
    "OptionCashDelta",
    "OptionDeliverableAsset",
    "OptionDeliverableDataProvider",
    "OptionDeliverableTerms",
    "StaticOptionDeliverableDataProvider",
    "apply_adjusted_assignment",
    "apply_physical_deliverable",
    "expiry_adjusted_delivery",
]


def _positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _currency(value: str) -> str:
    if not value or value != value.upper() or not value.isalnum() or not 3 <= len(value) <= 12:
        raise ValueError(f"currency must be 3-12 uppercase alphanumerics, got {value!r}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionDeliverableAsset:
    """One asset received per long-call package (and delivered by a long put)."""

    instrument_id: str
    quantity_per_contract: float

    def __post_init__(self) -> None:
        SymbolMapper.parse_instrument_id(self.instrument_id)
        _positive_finite("quantity_per_contract", self.quantity_per_contract)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionCashAmount:
    """One positive currency amount per contract."""

    currency: str
    amount_per_contract: float

    def __post_init__(self) -> None:
        _currency(self.currency)
        _positive_finite("amount_per_contract", self.amount_per_contract)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionDeliverableTerms:
    """One source-bound revision of an option contract's physical package.

    ``assets`` and ``cash`` describe the package a long call receives or a long put delivers.
    ``exercise_cash`` is the strike consideration paid by a long call or received by a long put.
    Revisions are selected only after both ``effective_ts`` and ``available_at``.
    """

    instrument_id: str
    revision: int
    effective_ts: Ms
    source_observed_ts: Ms
    available_at: Ms
    assets: tuple[OptionDeliverableAsset, ...]
    cash: tuple[OptionCashAmount, ...]
    exercise_cash: OptionCashAmount
    source_ref: str

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("adjusted deliverable requires an OPTION instrument")
        if self.revision < 1:
            raise ValueError("deliverable revision must be >= 1")
        if min(self.effective_ts, self.source_observed_ts, self.available_at) < 0:
            raise ValueError("deliverable timestamps must be nonnegative")
        if self.available_at < self.source_observed_ts:
            raise ValueError("deliverable available_at cannot precede source_observed_ts")
        if not self.source_ref.strip():
            raise ValueError("deliverable source_ref cannot be empty")
        if not self.assets and not self.cash:
            raise ValueError("deliverable package must contain at least one asset or cash amount")
        asset_ids = [item.instrument_id for item in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("deliverable asset ids must be unique")
        cash_currencies = [item.currency for item in self.cash]
        if len(cash_currencies) != len(set(cash_currencies)):
            raise ValueError("deliverable cash currencies must be unique")

    def require_known(self, decision_ts: Ms) -> None:
        if self.available_at > decision_ts:
            raise LookaheadError(
                f"deliverable revision {self.revision} for {self.instrument_id!r} available at "
                f"{self.available_at} exceeds decision {decision_ts}"
            )
        if self.effective_ts > decision_ts:
            raise ValueError(
                f"deliverable revision {self.revision} for {self.instrument_id!r} is not "
                f"effective until {self.effective_ts}"
            )


class OptionDeliverableDataProvider(Protocol):
    """Point-in-time adjusted-deliverable lookup boundary."""

    def terms(self, instrument_id: str, *, as_of: Ms) -> OptionDeliverableTerms | None:
        """Latest revision both effective and available by ``as_of``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticOptionDeliverableDataProvider:
    """Deterministic in-memory revision store used by replay and tests."""

    revisions: tuple[OptionDeliverableTerms, ...]

    def __post_init__(self) -> None:
        by_contract: dict[str, list[OptionDeliverableTerms]] = {}
        for terms in self.revisions:
            by_contract.setdefault(terms.instrument_id, []).append(terms)
        for instrument_id, chain in by_contract.items():
            ordered = sorted(chain, key=lambda item: item.revision)
            expected = list(range(1, len(ordered) + 1))
            observed = [item.revision for item in ordered]
            if observed != expected:
                raise ValueError(
                    f"deliverable revisions for {instrument_id!r} must be contiguous from 1; "
                    f"got {observed}"
                )
            for prior, current in pairwise(ordered):
                if current.effective_ts < prior.effective_ts:
                    raise ValueError("deliverable effective timestamps must be nondecreasing")
                if current.available_at < prior.available_at:
                    raise ValueError("deliverable availability timestamps must be nondecreasing")

    def terms(self, instrument_id: str, *, as_of: Ms) -> OptionDeliverableTerms | None:
        eligible = (
            terms
            for terms in self.revisions
            if terms.instrument_id == instrument_id
            and terms.effective_ts <= as_of
            and terms.available_at <= as_of
        )
        return max(eligible, key=lambda item: item.revision, default=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionAssetDelta:
    instrument_id: str
    quantity_delta: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionCashDelta:
    currency: str
    amount_delta: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionBasketDelivery:
    """Atomic option close plus deterministic multi-asset and multi-currency effects."""

    event_type: str
    instrument_id: str
    deliverable_revision: int
    option_contracts_delta: float
    asset_deltas: tuple[OptionAssetDelta, ...]
    cash_deltas: tuple[OptionCashDelta, ...]


def _validate_physical_terms(
    contract: OptionContract,
    deliverable: OptionDeliverableTerms,
    *,
    decision_ts: Ms,
) -> None:
    if contract.settlement_style is not SettlementStyle.PHYSICAL:
        raise ValueError("adjusted deliverable requires physical settlement")
    if deliverable.instrument_id != contract.instrument_id:
        raise ValueError("deliverable terms do not match option contract")
    if not contract.known_at(decision_ts):
        raise LookaheadError("option terms were not known by the delivery decision")
    deliverable.require_known(decision_ts)


def apply_physical_deliverable(
    contract: OptionContract,
    *,
    signed_contracts: float,
    deliverable: OptionDeliverableTerms,
    decision_ts: Ms,
    event_type: str,
) -> OptionBasketDelivery:
    """Close signed contracts and apply the exact effective adjusted package."""
    _finite("signed_contracts", signed_contracts)
    if not event_type:
        raise ValueError("event_type cannot be empty")
    _validate_physical_terms(contract, deliverable, decision_ts=decision_ts)

    package_direction = 1.0 if contract.right is OptionRight.CALL else -1.0
    package_units = signed_contracts * package_direction
    assets = tuple(
        OptionAssetDelta(
            instrument_id=item.instrument_id,
            quantity_delta=package_units * item.quantity_per_contract,
        )
        for item in sorted(deliverable.assets, key=lambda value: value.instrument_id)
        if package_units != 0.0
    )
    cash_by_currency: dict[str, float] = {}
    for item in deliverable.cash:
        cash_by_currency[item.currency] = (
            cash_by_currency.get(item.currency, 0.0) + package_units * item.amount_per_contract
        )
    exercise = deliverable.exercise_cash
    cash_by_currency[exercise.currency] = (
        cash_by_currency.get(exercise.currency, 0.0)
        - package_units * exercise.amount_per_contract
    )
    cash = tuple(
        OptionCashDelta(currency=currency, amount_delta=amount)
        for currency, amount in sorted(cash_by_currency.items())
        if amount != 0.0
    )
    return OptionBasketDelivery(
        event_type=event_type,
        instrument_id=contract.instrument_id,
        deliverable_revision=deliverable.revision,
        option_contracts_delta=-signed_contracts,
        asset_deltas=assets,
        cash_deltas=cash,
    )


def expiry_adjusted_delivery(
    contract: OptionContract,
    *,
    signed_contracts: float,
    settlement: OptionSettlement,
    deliverable: OptionDeliverableTerms,
    decision_ts: Ms,
    auto_exercise_threshold: float = 0.01,
) -> OptionBasketDelivery:
    """Apply an effective adjusted package after official expiry settlement is known."""
    if decision_ts < contract.expiration_ts:
        raise ValueError("cannot settle an option before expiration")
    if settlement.underlying_instrument_id != contract.underlying_instrument_id:
        raise ValueError("settlement underlying does not match option terms")
    if settlement.settlement_ts < contract.expiration_ts:
        raise ValueError("official settlement cannot precede option expiration")
    settlement.require_known(decision_ts)
    _finite("signed_contracts", signed_contracts)
    if not math.isfinite(auto_exercise_threshold) or auto_exercise_threshold < 0.0:
        raise ValueError("auto_exercise_threshold must be finite and >= 0")
    _validate_physical_terms(contract, deliverable, decision_ts=decision_ts)
    if intrinsic_value(contract, settlement.price) < auto_exercise_threshold:
        return OptionBasketDelivery(
            event_type="expiry_lapse",
            instrument_id=contract.instrument_id,
            deliverable_revision=deliverable.revision,
            option_contracts_delta=-signed_contracts,
            asset_deltas=(),
            cash_deltas=(),
        )
    return apply_physical_deliverable(
        contract,
        signed_contracts=signed_contracts,
        deliverable=deliverable,
        decision_ts=decision_ts,
        event_type="expiry_adjusted_exercise_or_assignment",
    )


def apply_adjusted_assignment(
    contract: OptionContract,
    *,
    short_contracts: float,
    notice: AssignmentNotice,
    deliverable: OptionDeliverableTerms,
    decision_ts: Ms,
) -> OptionBasketDelivery:
    """Apply an observed early-assignment notice through the effective adjusted package."""
    if contract.exercise_style is not ExerciseStyle.AMERICAN:
        raise ValueError("early assignment requires an American-style option")
    if contract.settlement_style is not SettlementStyle.PHYSICAL:
        raise ValueError("early assignment requires physical settlement")
    if notice.instrument_id != contract.instrument_id:
        raise ValueError("assignment notice does not match option contract")
    if notice.event_ts >= contract.expiration_ts:
        raise ValueError("early-assignment event must precede option expiration")
    if notice.available_at > decision_ts:
        raise LookaheadError(
            f"assignment notice available at {notice.available_at} exceeds decision {decision_ts}"
        )
    _positive_finite("short_contracts", short_contracts)
    if notice.assigned_contracts > short_contracts:
        raise ValueError("assigned contracts exceed the short option position")
    return apply_physical_deliverable(
        contract,
        signed_contracts=-notice.assigned_contracts,
        deliverable=deliverable,
        decision_ts=decision_ts,
        event_type="early_adjusted_assignment",
    )
