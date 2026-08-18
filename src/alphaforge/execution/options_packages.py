"""Deterministic displayed-quote execution for ratio-defined option packages.

This module makes one conservative replay assumption explicit: every leg crosses its
displayed bid or ask atomically at one decision timestamp, with package units capped by
the smallest displayed leg capacity.  It preserves package ratios under IOC partial
execution and rejects undersized FOK orders.  It does not model a complex-order book,
queue position, hidden liquidity, price improvement, market impact beyond displayed
size, or the probability that separately displayed legs are simultaneously fillable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from alphaforge.core.errors import LookaheadError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms
from alphaforge.core.types import MarketType
from alphaforge.execution.market_status import (
    MarketStatus,
    MarketStatusEvent,
    MarketStatusProvider,
)
from alphaforge.execution.options import OptionSurfaceSnapshot

__all__ = [
    "DISPLAYED_ATOMIC_CROSS_ASSUMPTION",
    "OptionLegExecution",
    "OptionPackageExecution",
    "OptionPackageExecutionStatus",
    "OptionPackageLeg",
    "OptionPackageMarketStatus",
    "OptionPackageOrder",
    "OptionPackageRejectReason",
    "OptionPackageTimeInForce",
    "execute_displayed_option_package",
]


DISPLAYED_ATOMIC_CROSS_ASSUMPTION = (
    "atomic_cross_of_independently_displayed_bid_ask_without_fill_probability"
)


class OptionPackageTimeInForce(StrEnum):
    """Single-snapshot package handling supported by the deterministic replay."""

    IOC = "ioc"
    FOK = "fok"


class OptionPackageExecutionStatus(StrEnum):
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"


class OptionPackageRejectReason(StrEnum):
    MISSING_QUOTE = "missing_quote"
    NON_EXECUTABLE_BID = "non_executable_bid"
    NO_DISPLAYED_SIZE = "no_displayed_size"
    NET_LIMIT = "net_limit"
    FOK_INSUFFICIENT_SIZE = "fok_insufficient_size"
    MISSING_MARKET_STATUS = "missing_market_status"
    MARKET_HALTED = "market_halted"
    VENUE_OUTAGE = "venue_outage"
    AUCTION_ONLY = "auction_only_no_continuous_fill"
    CLOSE_ONLY_RISK_INCREASE = "close_only_blocks_risk_increase"
    REDUCE_ONLY_POSITION_MISSING = "reduce_only_position_missing"
    REDUCE_ONLY_NOT_REDUCING = "reduce_only_not_reducing"


def _nonzero_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0:
        raise ValueError(f"{name} must be a non-zero integer, got {value!r}")


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def _nonnegative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer, got {value!r}")


def _positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _currency(value: str) -> str:
    if not value or value != value.upper() or not value.isalnum() or not 3 <= len(value) <= 12:
        raise ValueError(f"currency must be 3-12 uppercase alphanumerics, got {value!r}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionPackageLeg:
    """One signed integer contract ratio; positive buys and negative sells."""

    instrument_id: str
    ratio: int

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("option package legs require MarketType.OPTION identities")
        _nonzero_int("ratio", self.ratio)


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionPackageOrder:
    """A ratio-defined package with one net debit ceiling per package unit.

    ``max_net_debit_per_unit`` may be negative.  For example, ``-2.0`` requires
    at least a 2-unit net credit because an observed debit of ``-2.5`` passes while
    ``-1.5`` does not.
    """

    order_id: str
    submitted_ts: Ms
    package_units: int
    max_net_debit_per_unit: float
    time_in_force: OptionPackageTimeInForce
    legs: tuple[OptionPackageLeg, ...]
    reduce_only: bool = False

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("order_id must not be blank")
        _positive_int("package_units", self.package_units)
        if not math.isfinite(self.max_net_debit_per_unit):
            raise ValueError("max_net_debit_per_unit must be finite")
        if not isinstance(self.time_in_force, OptionPackageTimeInForce):
            raise ValueError("time_in_force must be an OptionPackageTimeInForce")
        if not isinstance(self.reduce_only, bool):
            raise ValueError("reduce_only must be boolean")
        if not self.legs:
            raise ValueError("option package requires at least one leg")
        if any(not isinstance(leg, OptionPackageLeg) for leg in self.legs):
            raise ValueError("legs must contain only OptionPackageLeg records")
        instrument_ids = [leg.instrument_id for leg in self.legs]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("option package instrument ids must be unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionLegExecution:
    """One package leg crossed at its displayed side."""

    instrument_id: str
    premium_currency: str
    signed_contracts: int
    price: float
    contract_multiplier: float

    def __post_init__(self) -> None:
        _, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("option leg executions require MarketType.OPTION identities")
        _currency(self.premium_currency)
        _nonzero_int("signed_contracts", self.signed_contracts)
        _positive_finite("price", self.price)
        _positive_finite("contract_multiplier", self.contract_multiplier)

    @property
    def premium_cash_delta(self) -> float:
        """Cash sign from the position holder's perspective; buys consume cash."""
        return -self.signed_contracts * self.price * self.contract_multiplier


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionPackageMarketStatus:
    """The effective PIT status returned for one queried package leg."""

    instrument_id: str
    venue: str
    status: MarketStatus
    effective_from: Ms
    effective_until: Ms
    observed_ts: Ms
    available_at: Ms
    reason: str

    def __post_init__(self) -> None:
        venue, market_type, _ = SymbolMapper.parse_instrument_id(self.instrument_id)
        if market_type is not MarketType.OPTION:
            raise ValueError("package market status requires MarketType.OPTION identities")
        if self.venue != venue:
            raise ValueError("package market-status venue does not match instrument venue")
        if not isinstance(self.status, MarketStatus):
            raise ValueError("status must be a MarketStatus")
        if self.effective_from >= self.effective_until:
            raise ValueError("market-status effective_from must precede effective_until")
        if self.available_at < self.observed_ts:
            raise ValueError("market-status availability cannot precede observation")
        if not self.reason:
            raise ValueError("market-status reason must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class OptionPackageExecution:
    order_id: str
    decision_ts: Ms
    status: OptionPackageExecutionStatus
    requested_package_units: int
    executed_package_units: int
    canceled_package_units: int
    displayed_capacity_units: int
    net_debit_per_unit: float | None
    leg_executions: tuple[OptionLegExecution, ...]
    reject_reason: OptionPackageRejectReason | None
    reduce_only: bool = False
    market_statuses: tuple[OptionPackageMarketStatus, ...] = ()
    assumption: str = DISPLAYED_ATOMIC_CROSS_ASSUMPTION

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("order_id must not be blank")
        if not isinstance(self.status, OptionPackageExecutionStatus):
            raise ValueError("status must be an OptionPackageExecutionStatus")
        if self.reject_reason is not None and not isinstance(
            self.reject_reason, OptionPackageRejectReason
        ):
            raise ValueError("reject_reason must be an OptionPackageRejectReason when present")
        if not isinstance(self.reduce_only, bool):
            raise ValueError("reduce_only must be boolean")
        if any(not isinstance(leg, OptionLegExecution) for leg in self.leg_executions):
            raise ValueError("leg_executions must contain only OptionLegExecution records")
        execution_ids = [leg.instrument_id for leg in self.leg_executions]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("leg execution instrument ids must be unique")
        if any(
            not isinstance(status, OptionPackageMarketStatus)
            for status in self.market_statuses
        ):
            raise ValueError("market_statuses must contain OptionPackageMarketStatus records")
        status_ids = [status.instrument_id for status in self.market_statuses]
        if len(status_ids) != len(set(status_ids)):
            raise ValueError("package market-status instrument ids must be unique")
        if any(
            not status.effective_from <= self.decision_ts < status.effective_until
            or status.available_at > self.decision_ts
            for status in self.market_statuses
        ):
            raise ValueError("package market status must be effective and known at decision")
        execution_currencies = {leg.premium_currency for leg in self.leg_executions}
        if len(execution_currencies) > 1:
            raise ValueError("package leg executions must share one premium currency")
        _positive_int("requested_package_units", self.requested_package_units)
        _nonnegative_int("executed_package_units", self.executed_package_units)
        _nonnegative_int("canceled_package_units", self.canceled_package_units)
        _nonnegative_int("displayed_capacity_units", self.displayed_capacity_units)
        if (
            self.executed_package_units + self.canceled_package_units
            != self.requested_package_units
        ):
            raise ValueError("executed and canceled units must partition requested units")
        if self.executed_package_units > self.displayed_capacity_units:
            raise ValueError("executed units cannot exceed displayed capacity")
        if self.net_debit_per_unit is not None and not math.isfinite(self.net_debit_per_unit):
            raise ValueError("net_debit_per_unit must be finite when present")
        if not self.assumption.strip():
            raise ValueError("assumption must not be blank")

        rejected = self.status is OptionPackageExecutionStatus.REJECTED
        if rejected:
            if self.executed_package_units != 0 or self.leg_executions:
                raise ValueError("rejected packages cannot contain executions")
            if self.reject_reason is None:
                raise ValueError("rejected packages require a reject reason")
            return
        if self.reject_reason is not None:
            raise ValueError("executed packages cannot contain a reject reason")
        if self.executed_package_units <= 0 or not self.leg_executions:
            raise ValueError("executed packages require positive units and leg executions")
        if self.net_debit_per_unit is None:
            raise ValueError("executed packages require a net debit")
        if self.market_statuses and set(status_ids) != set(execution_ids):
            raise ValueError("executed packages require complete market-status leg coverage")
        blocked_statuses = {
            MarketStatus.HALTED,
            MarketStatus.OUTAGE,
            MarketStatus.AUCTION_ONLY,
        }
        if any(status.status in blocked_statuses for status in self.market_statuses):
            raise ValueError("executed packages cannot contain a blocking market status")
        if any(
            status.status is MarketStatus.CLOSE_ONLY for status in self.market_statuses
        ) and not self.reduce_only:
            raise ValueError("close-only execution must be marked reduce_only")
        if self.status is OptionPackageExecutionStatus.FILLED and self.canceled_package_units != 0:
            raise ValueError("filled packages cannot contain canceled units")
        if (
            self.status is OptionPackageExecutionStatus.PARTIALLY_FILLED
            and self.canceled_package_units <= 0
        ):
            raise ValueError("partially filled packages require canceled units")
        expected_cash = -self.net_debit_per_unit * self.executed_package_units
        actual_cash = sum(leg.premium_cash_delta for leg in self.leg_executions)
        tolerance = max(1e-10, 1e-12 * max(abs(expected_cash), abs(actual_cash)))
        if abs(expected_cash - actual_cash) > tolerance:
            raise ValueError("leg premium cash does not reconcile to package net debit")

    @property
    def premium_cash_delta(self) -> float:
        return sum(leg.premium_cash_delta for leg in self.leg_executions)

    @property
    def premium_currency(self) -> str | None:
        """The common premium currency, absent only when no leg executed."""
        if not self.leg_executions:
            return None
        return self.leg_executions[0].premium_currency


def _rejected(
    *,
    order: OptionPackageOrder,
    decision_ts: Ms,
    reason: OptionPackageRejectReason,
    capacity: int = 0,
    net_debit: float | None = None,
    market_statuses: tuple[OptionPackageMarketStatus, ...] = (),
) -> OptionPackageExecution:
    return OptionPackageExecution(
        order_id=order.order_id,
        decision_ts=decision_ts,
        status=OptionPackageExecutionStatus.REJECTED,
        requested_package_units=order.package_units,
        executed_package_units=0,
        canceled_package_units=order.package_units,
        displayed_capacity_units=capacity,
        net_debit_per_unit=net_debit,
        leg_executions=(),
        reject_reason=reason,
        reduce_only=order.reduce_only,
        market_statuses=market_statuses,
    )


def _market_status_evidence(
    *, instrument_id: str, event: MarketStatusEvent, decision_ts: Ms
) -> OptionPackageMarketStatus:
    venue, _, _ = SymbolMapper.parse_instrument_id(instrument_id)
    if event.venue != venue or event.instrument_id not in (None, instrument_id):
        raise ValueError("market-status provider returned an event for the wrong scope")
    if not event.effective_from <= decision_ts < event.effective_until:
        raise ValueError("market-status provider returned an ineffective event")
    if event.available_at > decision_ts:
        raise LookaheadError(
            f"market status for {instrument_id!r} available at {event.available_at} "
            f"exceeds decision {decision_ts}"
        )
    return OptionPackageMarketStatus(
        instrument_id=instrument_id,
        venue=event.venue,
        status=event.status,
        effective_from=event.effective_from,
        effective_until=event.effective_until,
        observed_ts=event.observed_ts,
        available_at=event.available_at,
        reason=event.reason,
    )


def _reduce_only_reject_reason(
    order: OptionPackageOrder,
    current_positions: Mapping[str, int] | None,
) -> OptionPackageRejectReason | None:
    if not order.reduce_only:
        return None
    if current_positions is None:
        return OptionPackageRejectReason.REDUCE_ONLY_POSITION_MISSING
    for leg in order.legs:
        current = current_positions.get(leg.instrument_id)
        if current is None:
            return OptionPackageRejectReason.REDUCE_ONLY_POSITION_MISSING
        if isinstance(current, bool) or not isinstance(current, int):
            raise ValueError("current option positions must be integer contracts")
        delta = leg.ratio * order.package_units
        resulting = current + delta
        if (
            current == 0
            or delta * current >= 0
            or abs(resulting) > abs(current)
            or resulting * current < 0
        ):
            return OptionPackageRejectReason.REDUCE_ONLY_NOT_REDUCING
    return None


def execute_displayed_option_package(
    *,
    order: OptionPackageOrder,
    surface: OptionSurfaceSnapshot,
    market_status_provider: MarketStatusProvider | None = None,
    current_positions: Mapping[str, int] | None = None,
) -> OptionPackageExecution:
    """Cross every leg at displayed bid/ask while preserving package ratios.

    A positive ratio buys at the ask and consumes ask size.  A negative ratio sells
    at a strictly positive bid and consumes bid size.  The smallest whole-number leg
    capacity controls the package; fractional package units are never invented.
    """
    if order.submitted_ts > surface.decision_ts:
        raise LookaheadError(
            f"option package {order.order_id!r} submitted at {order.submitted_ts} "
            f"after decision {surface.decision_ts}"
        )

    contract_by_id = {contract.instrument_id: contract for contract in surface.contracts}
    for leg in order.legs:
        if leg.instrument_id not in contract_by_id:
            raise ValueError(
                f"option package leg {leg.instrument_id!r} is absent from the surface terms"
            )

    reduce_only_reject = _reduce_only_reject_reason(order, current_positions)
    if reduce_only_reject is not None:
        return _rejected(
            order=order,
            decision_ts=surface.decision_ts,
            reason=reduce_only_reject,
        )

    market_statuses: list[OptionPackageMarketStatus] = []
    if market_status_provider is not None:
        for leg in order.legs:
            event = market_status_provider.status(
                leg.instrument_id,
                as_of=surface.decision_ts,
            )
            if event is None:
                return _rejected(
                    order=order,
                    decision_ts=surface.decision_ts,
                    reason=OptionPackageRejectReason.MISSING_MARKET_STATUS,
                    market_statuses=tuple(market_statuses),
                )
            evidence = _market_status_evidence(
                instrument_id=leg.instrument_id,
                event=event,
                decision_ts=surface.decision_ts,
            )
            market_statuses.append(evidence)
            reason = {
                MarketStatus.HALTED: OptionPackageRejectReason.MARKET_HALTED,
                MarketStatus.OUTAGE: OptionPackageRejectReason.VENUE_OUTAGE,
                MarketStatus.AUCTION_ONLY: OptionPackageRejectReason.AUCTION_ONLY,
                MarketStatus.CLOSE_ONLY: OptionPackageRejectReason.CLOSE_ONLY_RISK_INCREASE,
                MarketStatus.OPEN: None,
            }[event.status]
            if event.status is MarketStatus.CLOSE_ONLY and order.reduce_only:
                reason = None
            if reason is not None:
                return _rejected(
                    order=order,
                    decision_ts=surface.decision_ts,
                    reason=reason,
                    market_statuses=tuple(market_statuses),
                )

    quote_by_id = {quote.instrument_id: quote for quote in surface.quotes}
    priced_legs: list[tuple[OptionPackageLeg, float, float, str]] = []
    capacities: list[int] = []

    for leg in order.legs:
        contract = contract_by_id[leg.instrument_id]
        quote = quote_by_id.get(leg.instrument_id)
        if quote is None:
            return _rejected(
                order=order,
                decision_ts=surface.decision_ts,
                reason=OptionPackageRejectReason.MISSING_QUOTE,
                market_statuses=tuple(market_statuses),
            )
        if leg.ratio > 0:
            price = quote.ask
            displayed_size = quote.ask_size
        else:
            price = quote.bid
            displayed_size = quote.bid_size
            if price <= 0.0:
                return _rejected(
                    order=order,
                    decision_ts=surface.decision_ts,
                    reason=OptionPackageRejectReason.NON_EXECUTABLE_BID,
                    market_statuses=tuple(market_statuses),
                )
        capacity = math.floor(displayed_size / abs(leg.ratio))
        if capacity <= 0:
            return _rejected(
                order=order,
                decision_ts=surface.decision_ts,
                reason=OptionPackageRejectReason.NO_DISPLAYED_SIZE,
                market_statuses=tuple(market_statuses),
            )
        capacities.append(capacity)
        priced_legs.append(
            (leg, price, contract.contract_multiplier, quote.premium_currency)
        )

    premium_currencies = {currency for _leg, _price, _multiplier, currency in priced_legs}
    if len(premium_currencies) != 1:
        raise ValueError("option package quotes must share one premium currency")

    displayed_capacity = min(capacities)
    net_debit = sum(
        leg.ratio * price * multiplier
        for leg, price, multiplier, _currency_code in priced_legs
    )
    tolerance = max(
        1e-12,
        1e-12 * max(abs(net_debit), abs(order.max_net_debit_per_unit)),
    )
    if net_debit > order.max_net_debit_per_unit + tolerance:
        return _rejected(
            order=order,
            decision_ts=surface.decision_ts,
            reason=OptionPackageRejectReason.NET_LIMIT,
            capacity=displayed_capacity,
            net_debit=net_debit,
            market_statuses=tuple(market_statuses),
        )
    if (
        order.time_in_force is OptionPackageTimeInForce.FOK
        and displayed_capacity < order.package_units
    ):
        return _rejected(
            order=order,
            decision_ts=surface.decision_ts,
            reason=OptionPackageRejectReason.FOK_INSUFFICIENT_SIZE,
            capacity=displayed_capacity,
            net_debit=net_debit,
            market_statuses=tuple(market_statuses),
        )

    executed_units = min(order.package_units, displayed_capacity)
    canceled_units = order.package_units - executed_units
    status = (
        OptionPackageExecutionStatus.FILLED
        if canceled_units == 0
        else OptionPackageExecutionStatus.PARTIALLY_FILLED
    )
    executions = tuple(
        OptionLegExecution(
            instrument_id=leg.instrument_id,
            premium_currency=premium_currency,
            signed_contracts=leg.ratio * executed_units,
            price=price,
            contract_multiplier=multiplier,
        )
        for leg, price, multiplier, premium_currency in priced_legs
    )
    return OptionPackageExecution(
        order_id=order.order_id,
        decision_ts=surface.decision_ts,
        status=status,
        requested_package_units=order.package_units,
        executed_package_units=executed_units,
        canceled_package_units=canceled_units,
        displayed_capacity_units=displayed_capacity,
        net_debit_per_unit=net_debit,
        leg_executions=executions,
        reject_reason=None,
        reduce_only=order.reduce_only,
        market_statuses=tuple(market_statuses),
    )
