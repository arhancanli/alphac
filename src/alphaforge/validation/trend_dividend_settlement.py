"""Isolated simulated dividend accrual/settlement; never a broker cash authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alphaforge.validation.trend_observation import ObservationError


@dataclass(frozen=True)
class DividendPayment:
    event_id: str
    symbol: str
    ex_ms: int
    pay_ms: int
    observed_ms: int
    cash_per_share: Decimal


class DividendSettlementBook:
    """Signed receivables captured from the pre-ex position, payable on known dates.

    This simulation component does not infer payment dates or credit buying power
    at ex-date. Actual paper settlement requires broker reconciliation separately.
    A supplied retrospective_vintage_ms explicitly permits late observations only
    through that capture cutoff; default behavior still requires observation by ex-date.
    The original event and its observed_ms are retained unchanged in the book.
    """

    def __init__(self, settled_cash: Decimal, *, retrospective_vintage_ms: int | None = None):
        if not isinstance(settled_cash, Decimal) or not settled_cash.is_finite():
            raise ObservationError("Finite Decimal settled cash required")
        if retrospective_vintage_ms is not None and (
            type(retrospective_vintage_ms) is not int or retrospective_vintage_ms < 0
        ):
            raise ObservationError("Nonnegative integer retrospective vintage required")
        self._retrospective_vintage_ms = retrospective_vintage_ms
        self._cash = settled_cash
        self._events = {}
        self._paid = set()
        self._last_ms = -1

    @property
    def settled_cash(self):
        return self._cash

    @property
    def pending_cash(self):
        return sum(
            (amount for key, (_, _, amount) in self._events.items() if key not in self._paid),
            Decimal(0),
        )

    def accrue(self, event: DividendPayment, pre_ex_quantity: Decimal, *, as_of_ms: int):
        if (
            not event.event_id
            or not event.symbol
            or any(
                type(t) is not int or t < 0
                for t in [event.ex_ms, event.pay_ms, event.observed_ms, as_of_ms]
            )
            or event.pay_ms < event.ex_ms
            or event.observed_ms
            > (
                event.ex_ms
                if self._retrospective_vintage_ms is None
                else self._retrospective_vintage_ms
            )
            or as_of_ms != event.ex_ms
            or not isinstance(event.cash_per_share, Decimal)
            or not event.cash_per_share.is_finite()
            or event.cash_per_share <= 0
            or not isinstance(pre_ex_quantity, Decimal)
            or not pre_ex_quantity.is_finite()
        ):
            raise ObservationError(
                "Known payment date, timely event and finite signed quantity required"
            )
        record = (event, pre_ex_quantity, pre_ex_quantity * event.cash_per_share)
        old = self._events.get(event.event_id)
        if old is not None:
            if old != record:
                raise ObservationError("Conflicting event replay")
            return Decimal(0)
        if as_of_ms < self._last_ms:
            raise ObservationError("Cannot backfill an accrual behind the settlement clock")
        self._events[event.event_id] = record
        self._last_ms = as_of_ms
        return record[2]

    def settle_due(self, *, as_of_ms: int):
        if type(as_of_ms) is not int or as_of_ms < self._last_ms:
            raise ObservationError("Monotonic integer settlement clock required")
        due = [
            key
            for key, (event, _, _) in self._events.items()
            if key not in self._paid and event.pay_ms <= as_of_ms
        ]
        amount = sum((self._events[key][2] for key in due), Decimal(0))
        self._cash += amount
        self._paid.update(due)
        self._last_ms = as_of_ms
        return amount
