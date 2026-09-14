"""Opt-in USD depositary cash terms known by ex-date; no historical clearance.

Gross actions remain the matching authority. Cash entitlement uses explicit long
net terms or independent short obligations. Later fee revisions are unsupported.
"""
from dataclasses import dataclass, replace, asdict
from decimal import Decimal
from copy import deepcopy
import math
from types import MappingProxyType
from alphaforge.backtest.payable_dividend_ledger import PayableDividendLedger
from alphaforge.backtest.ledger import Ledger
from alphaforge.validation.trend_observation import ObservationError


@dataclass(frozen=True)
class DepositaryCashTerms:
    event_id: str
    observed_ms: int
    long_fee_per_share: Decimal
    long_tax_per_share: Decimal
    short_payment_per_share: Decimal
    short_fee_per_share: Decimal
    policy_id: str


class DepositaryDividendLedger(PayableDividendLedger):
    def __init__(self, *args, depositary_terms, **kwargs):
        super().__init__(*args, **kwargs)
        events = {e.event_id: e for e in self._payment_schedule.values()}
        terms = {}
        for t in depositary_terms:
            if not isinstance(t, DepositaryCashTerms) or t.event_id not in events or t.event_id in terms:
                raise ObservationError('Unique known depositary event terms required')
            e = events[t.event_id]
            values = [t.long_fee_per_share, t.long_tax_per_share,
                      t.short_payment_per_share, t.short_fee_per_share]
            if (not isinstance(t.policy_id, str) or not t.policy_id.strip()
                    or type(t.observed_ms) is not int or not 0 <= t.observed_ms <= e.ex_ms
                    or any(not isinstance(x, Decimal) or not x.is_finite() or x < 0 for x in values)):
                raise ObservationError('Timely explicit long and short depositary terms required')
            if (e.cash_per_share - t.long_fee_per_share - t.long_tax_per_share <= 0
                    or t.short_payment_per_share + t.short_fee_per_share <= 0):
                raise ObservationError('Positive net long and short cash required')
            if self._instruments[e.symbol].quote != 'USD':
                raise ObservationError('USD depositary cash only; FX requires separate accounting')
            terms[t.event_id] = t
        self._depositary_terms = MappingProxyType(terms)
        self._depositary_records = []

    def apply_cash_dividend(self, instrument_id, ts, cash_amount):
        e = self._payment_schedule.get((instrument_id, ts))
        if e is None or Decimal(str(cash_amount)) != e.cash_per_share:
            raise ObservationError('Exact known gross payment event required')
        t = self._depositary_terms.get(e.event_id)
        if t is None:
            return super().apply_cash_dividend(instrument_id, ts, cash_amount)
        if e.event_id in self._entitlements:
            return 0.0
        pos = self.positions().get(instrument_id)
        qty = Decimal(str(pos.qty if pos is not None else 0.0))
        rate = (e.cash_per_share - t.long_fee_per_share - t.long_tax_per_share
                if qty >= 0 else t.short_payment_per_share + t.short_fee_per_share)
        staged = deepcopy(self._dividend_book)
        staged.accrue(replace(e, cash_per_share=rate), qty, as_of_ms=ts)
        amount = float(qty * rate)
        if not math.isfinite(amount) or not math.isfinite(float(staged.pending_cash)):
            raise ObservationError('Nonfinite depositary receivable')
        # Record the economic net flow through the normal accounting accumulator,
        # then restore settled cash: buying power changes only at payable time.
        cash = self._cash
        Ledger.apply_cash_dividend(self, instrument_id, ts, float(rate))
        self._cash = cash
        self._dividend_book = staged
        self._entitlements[e.event_id] = amount
        self._depositary_records.append({
            'event_id': e.event_id, 'ts': ts, 'signed_quantity': str(qty),
            'gross_per_share': str(e.cash_per_share), 'applied_per_share': str(rate),
            'gross_signed_entitlement': str(qty * e.cash_per_share),
            'net_signed_entitlement': str(qty * rate),
            'adjustment_quote': str(qty * (rate - e.cash_per_share)),
            'terms': asdict(t),
        })
        return amount

    def depositary_records(self):
        return deepcopy(tuple(self._depositary_records))
