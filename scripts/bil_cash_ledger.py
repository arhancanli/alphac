"""Deterministic cash-only BIL ledger; callers must reserve before historical replay."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

D = Decimal

@dataclass(frozen=True)
class Price:
    day: date
    open: Decimal
    close: Decimal

@dataclass(frozen=True)
class Distribution:
    ex: date
    pay: date
    amount: Decimal


def replay(prices, distributions, sessions, start, end, initial=D('100000'), cost_bps=D('6')):
    """Monthly integer buys; end-pay-date settlement; no borrowing or sales."""
    if start > end or not initial.is_finite() or initial <= 0:
        raise ValueError('invalid interval or initial capital')
    if not cost_bps.is_finite() or cost_bps < 0:
        raise ValueError('invalid costs')
    prices = list(prices)
    distributions = list(distributions)
    sessions = list(sessions)
    if sessions != sorted(set(sessions)) or any(not start <= x <= end for x in sessions):
        raise ValueError('sessions must be ordered unique evaluation dates')
    selected = [p for p in prices if start <= p.day <= end]
    if len({p.day for p in selected}) != len(selected) or {p.day for p in selected} != set(sessions):
        raise ValueError('prices must cover exactly verified sessions')
    if any(not v.is_finite() or v <= 0 for p in selected for v in (p.open, p.close)):
        raise ValueError('nonpositive or nonfinite prices')
    events = [x for x in distributions if start <= x.ex <= end]
    if len({x.ex for x in events}) != len(events):
        raise ValueError('duplicate ex date')
    if any(x.ex not in set(sessions) or x.pay < x.ex or not x.amount.is_finite() or x.amount < 0 for x in events):
        raise ValueError('invalid distribution')
    quotes = {p.day:p for p in selected}
    exdates = {x.ex:x for x in events}
    cash, previous, mark = initial, initial, D(0)
    quantity, last_buy_month = 0, None
    pending = []
    rows = []
    day = start
    rate = cost_bps / D(10000)
    while day <= end:
        carried = quantity
        accrued, paid, fee, notional = D(0), D(0), D(0), D(0)
        bought = 0
        if day in exdates:
            event = exdates[day]
            accrued = carried * event.amount
            pending.append((event.pay, accrued))
        available_at_open = cash
        if day in quotes:
            p = quotes[day]
            month = (day.year, day.month)
            if month != last_buy_month:
                bought = int((cash / (p.open * (1 + rate))).to_integral_value(rounding=ROUND_FLOOR))
                notional = bought * p.open
                fee = notional * rate
                cash -= notional + fee
                quantity += bought
                last_buy_month = month
            mark = p.close
        paid = sum((amount for pay, amount in pending if pay == day), D(0))
        pending = [(pay, amount) for pay, amount in pending if pay > day]
        cash += paid
        receivable = sum((amount for _, amount in pending), D(0))
        nav = quantity * mark + cash + receivable
        assert cash >= 0 and nav > 0
        rows.append(dict(day=day, carried_quantity=carried, bought=bought, quantity=quantity,
                         available_at_open=available_at_open, notional=notional, fee=fee,
                         accrued=accrued, paid=paid, cash=cash, pending=receivable,
                         mark=mark, nav=nav, net_return=nav / previous - 1))
        previous = nav
        day += timedelta(days=1)
    return rows


def combine_row(baseline, cash_return):
    """Keep the original alpha columns and benchmark unchanged."""
    if float(baseline['cash_contribution']) != 0:
        raise ValueError('expected zero-cash reference')
    out = dict(baseline)
    out['cash_contribution'] = .325 * float(cash_return)
    out['total'] = float(baseline['total']) + out['cash_contribution']
    out['excess'] = out['total'] - float(baseline['benchmark'])
    return out
