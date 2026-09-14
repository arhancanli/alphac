"""Opt-in ledger with signed dividend receivables and explicit cash settlement.

Caller must schedule ex-date entitlement and payable timestamps in chronological
order and split financing intervals at settlements. The legacy engine does not
yet supply that event schedule; this class is not automatically activated there.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from alphaforge.backtest.ledger import Ledger
from alphaforge.validation.trend_dividend_settlement import DividendSettlementBook
from alphaforge.validation.trend_observation import ObservationError


class PayableDividendLedger(Ledger):
    def __init__(self, initial_cash, instruments, *, payments, retrospective_vintage_ms=None):
        super().__init__(initial_cash, instruments)
        schedule = {}
        ids = set()
        for event in payments:
            key = (event.symbol, event.ex_ms)
            if event.symbol not in instruments or key in schedule or event.event_id in ids:
                raise ObservationError("Unique known-instrument payment schedule required")
            # Reuse the full settlement validation without changing the live book.
            DividendSettlementBook(
                Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms
            ).accrue(event, Decimal(0), as_of_ms=event.ex_ms)
            schedule[key] = event
            ids.add(event.event_id)
        self._payment_schedule = MappingProxyType(schedule)
        self._dividend_book = DividendSettlementBook(
            Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms
        )
        self._entitlements = {}
        self._settlement_records = []
        self._settled_ids = set()

    @property
    def pending_dividends(self):
        return float(self._dividend_book.pending_cash)

    def apply_cash_dividend(self, instrument_id, ts, cash_amount):
        event = self._payment_schedule.get((instrument_id, ts))
        if event is None or Decimal(str(cash_amount)) != event.cash_per_share:
            raise ObservationError("Exact known payment-date event required")
        if event.event_id in self._entitlements:
            return 0.0  # entitlement was fixed once from the original pre-ex position
        position = self.positions().get(instrument_id)
        qty = position.qty if position is not None else 0.0
        staged = deepcopy(self._dividend_book)
        staged.accrue(event, Decimal(str(qty)), as_of_ms=ts)
        if not math.isfinite(float(staged.pending_cash)):
            raise ObservationError("Nonfinite dividend receivable")
        settled_cash = self._cash
        amount = super().apply_cash_dividend(instrument_id, ts, cash_amount)
        self._cash = settled_cash  # preserve cash exactly; ex-date entry is economic income
        self._dividend_book = staged
        self._entitlements[event.event_id] = amount
        return amount

    def settle_dividends(self, *, as_of_ms):
        # A skipped payment timestamp would silently misstate financing. Require
        # the caller to stop at each due instant before advancing past it.
        due = [
            event
            for event in self._payment_schedule.values()
            if event.event_id in self._entitlements
            and event.event_id not in self._settled_ids
            and event.pay_ms <= as_of_ms
        ]
        if any(event.pay_ms != as_of_ms for event in due):
            raise ObservationError("Payment boundary skipped; split financing intervals")
        staged = deepcopy(self._dividend_book)
        amount = float(staged.settle_due(as_of_ms=as_of_ms))
        cash = self._cash + amount
        if not math.isfinite(cash):
            raise ObservationError("Nonfinite settled cash")
        self._cash = cash
        self._dividend_book = staged
        self._settled_ids.update(event.event_id for event in due)
        if due:
            self._settlement_records.append(
                {
                    "ts": as_of_ms,
                    "cashflow_quote": amount,
                    "event_ids": tuple(e.event_id for e in due),
                }
            )
        return amount

    def apply_financing(self, accrual):
        for event in self._payment_schedule.values():
            if event.event_id not in self._entitlements:
                continue
            crosses_payment = accrual.start_ts < event.pay_ms < accrual.end_ts
            unpaid_at_start = (
                event.pay_ms <= accrual.start_ts and event.event_id not in self._settled_ids
            )
            if crosses_payment or unpaid_at_start:
                raise ObservationError("Payment boundary requires split financing intervals")
        return super().apply_financing(accrual)

    def mark(self, closes, ts):
        state = super().mark(closes, ts)
        equity = state.equity_quote + self.pending_dividends
        if not math.isfinite(equity):
            raise ObservationError("Nonfinite economic equity")
        self._equity_values[-1] = equity
        return replace(state, equity_quote=equity)  # cash_quote stays settled cash

    def dividend_settlements(self):
        return tuple(dict(row) for row in self._settlement_records)
