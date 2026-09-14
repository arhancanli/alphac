"""Causal foreign-dividend simulation primitive; not integrated into replay.

Times are explicit UTC milliseconds, not inferred from a notice's printed date.
Long withholding and short payment-in-lieu terms are supplied independently.
No reclaim asset is inferred. Gross receivables are pretax until settlement terms
become available; callers must retain that convention in reported NAV.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

D = Decimal


def _time(value):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative integer timestamp required')


def _decimal(value, *, positive=False):
    if not isinstance(value, D) or not value.is_finite() or (positive and value <= 0):
        raise ValueError('Finite Decimal required; rates and entitlements must be positive')


@dataclass(frozen=True)
class ForeignEntitlement:
    event_id: str
    currency: str
    ex_ms: int
    pay_ms: int
    available_ms: int
    foreign_per_share: D


@dataclass(frozen=True)
class FxObservation:
    currency: str
    effective_ms: int
    available_ms: int
    usd_per_foreign: D


@dataclass(frozen=True)
class SettlementTerms:
    # These are independently evidenced cash terms, not a universal tax rule.
    fixed_ms: int
    available_ms: int
    usd_per_foreign: D
    long_withholding_per_share: D
    long_fee_per_share: D
    short_payment_per_share: D
    short_fee_per_share: D


class ForeignDividendBook:
    def __init__(self):
        self._clock = -1
        self._events = {}
        self._marks = {}
        self._terms = {}
        self._paid = set()
        self._cash = D(0)
        self._journal = []

    def _check_clock(self, as_of_ms):
        _time(as_of_ms)
        if as_of_ms < self._clock:
            raise ValueError('Cannot move dividend clock backwards')

    def accrue(self, event, quantity, *, as_of_ms):
        self._check_clock(as_of_ms)
        if not isinstance(event, ForeignEntitlement):
            raise ValueError('Typed foreign entitlement required')
        for t in (event.ex_ms, event.pay_ms, event.available_ms):
            _time(t)
        _decimal(event.foreign_per_share, positive=True)
        _decimal(quantity)
        if (not event.event_id or not event.currency or event.currency == 'USD'
                or event.pay_ms < event.ex_ms or event.available_ms > event.ex_ms
                or as_of_ms != event.ex_ms):
            raise ValueError('Timely foreign entitlement and ex-date snapshot required')
        record = (event, quantity)
        if event.event_id in self._events:
            if self._events[event.event_id] != record:
                raise ValueError('Conflicting entitlement replay')
            return
        self._events[event.event_id] = record
        self._clock = as_of_ms
        self._journal.append(('accrue', as_of_ms, event.event_id, quantity))

    def observe_fx(self, observation, *, as_of_ms):
        self._check_clock(as_of_ms)
        if not isinstance(observation, FxObservation):
            raise ValueError('Typed FX observation required')
        for t in (observation.effective_ms, observation.available_ms):
            _time(t)
        _decimal(observation.usd_per_foreign, positive=True)
        if (not observation.currency or observation.currency == 'USD'
                or observation.effective_ms > observation.available_ms
                or observation.available_ms > as_of_ms):
            raise ValueError('FX observation not yet effective and available')
        old = self._marks.get(observation.currency)
        if old is not None:
            if observation.effective_ms < old.effective_ms:
                raise ValueError('Cannot replace FX mark with older observation')
            if observation.effective_ms == old.effective_ms and observation != old:
                raise ValueError('Conflicting FX observation')
        self._marks[observation.currency] = observation
        self._clock = as_of_ms
        self._journal.append(('fx', as_of_ms, observation))

    def fix(self, event_id, terms, *, as_of_ms):
        self._check_clock(as_of_ms)
        event, _ = self._events[event_id]
        if not isinstance(terms, SettlementTerms):
            raise ValueError('Typed independently evidenced settlement terms required')
        for t in (terms.fixed_ms, terms.available_ms):
            _time(t)
        _decimal(terms.usd_per_foreign, positive=True)
        for amount in (terms.long_withholding_per_share, terms.long_fee_per_share,
                       terms.short_payment_per_share, terms.short_fee_per_share):
            _decimal(amount)
            if amount < 0:
                raise ValueError('Negative settlement deduction/payment')
        gross = event.foreign_per_share * terms.usd_per_foreign
        if (terms.fixed_ms > terms.available_ms or terms.available_ms > as_of_ms
                or terms.fixed_ms > event.pay_ms
                or terms.long_withholding_per_share + terms.long_fee_per_share > gross):
            raise ValueError('Invalid or unavailable settlement terms')
        old = self._terms.get(event_id)
        if event_id in self._paid or (old is not None and old != terms):
            raise ValueError('Paid or conflicting fixation; amendments require separate handling')
        self._terms[event_id] = terms
        self._clock = as_of_ms
        self._journal.append(('fix', as_of_ms, event_id, terms))

    def _value(self, event_id, as_of_ms, max_fx_age_ms):
        event, quantity = self._events[event_id]
        terms = self._terms.get(event_id)
        if terms is not None:
            if quantity >= 0:
                per_share = (event.foreign_per_share * terms.usd_per_foreign
                             - terms.long_withholding_per_share - terms.long_fee_per_share)
            else:
                per_share = terms.short_payment_per_share + terms.short_fee_per_share
            return quantity * per_share
        mark = self._marks.get(event.currency)
        if mark is None or as_of_ms - mark.effective_ms > max_fx_age_ms:
            raise ValueError('Missing or stale causal FX mark')
        return quantity * event.foreign_per_share * mark.usd_per_foreign

    def pending_usd(self, *, as_of_ms, max_fx_age_ms):
        self._check_clock(as_of_ms)
        _time(max_fx_age_ms)
        value = sum((self._value(k, as_of_ms, max_fx_age_ms)
                     for k in self._events if k not in self._paid), D(0))
        self._clock = as_of_ms
        return value

    def settle_due(self, *, as_of_ms):
        self._check_clock(as_of_ms)
        due = [k for k, (e, _) in self._events.items()
               if k not in self._paid and e.pay_ms <= as_of_ms]
        if any(k not in self._terms for k in due):
            raise ValueError('No settlement without available fixed cash terms')
        # Validate the entire batch before mutating cash or paid flags.
        amounts = {k: self._value(k, as_of_ms, 0) for k in due}
        total = sum(amounts.values(), D(0))
        self._cash += total
        self._paid.update(due)
        self._clock = as_of_ms
        self._journal.append(('settle', as_of_ms, amounts))
        return total

    @property
    def settled_cash_delta(self):
        return self._cash

    @property
    def journal(self):
        return deepcopy(tuple(self._journal))
