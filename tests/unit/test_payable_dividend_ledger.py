from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_ledger import PERP_ID, _fill, _perp

from alphaforge.backtest.payable_dividend_ledger import PayableDividendLedger
from alphaforge.core.types import Side
from alphaforge.validation.trend_dividend_settlement import DividendPayment
from alphaforge.validation.trend_observation import ObservationError


def event():
    return DividendPayment("div1", PERP_ID, 2000, 5000, 1000, Decimal("2"))


def book(side=Side.BUY):
    ledger = PayableDividendLedger(10000.0, {PERP_ID: _perp()}, payments=[event()])
    ledger.apply_fill(_fill(side, 10.0, 100.0, 0.0, 1500))
    return ledger


@pytest.mark.parametrize("side,sign", [(Side.BUY, 1), (Side.SELL, -1)])
def test_cash_equity_and_settlement_identity(side, sign):
    ledger = book(side)
    before_cash = ledger.cash
    assert ledger.apply_cash_dividend(PERP_ID, 2000, 2.0) == sign * 20
    assert ledger.cash == before_cash
    assert ledger.pending_dividends == sign * 20
    state = ledger.mark({PERP_ID: 98.0}, 2000)
    assert state.equity_quote == 10000
    assert state.cash_quote == before_cash
    assert ledger.settle_dividends(as_of_ms=4999) == 0
    assert ledger.settle_dividends(as_of_ms=5000) == sign * 20
    assert ledger.cash == before_cash + sign * 20
    assert ledger.pending_dividends == 0
    assert ledger.mark({PERP_ID: 98.0}, 5000).equity_quote == 10000
    assert ledger.settle_dividends(as_of_ms=5000) == 0
    assert len(ledger.dividend_settlements()) == 1


def test_sale_before_payment_keeps_original_entitlement_and_retry_is_noop():
    ledger = book()
    ledger.apply_cash_dividend(PERP_ID, 2000, 2.0)
    ledger.apply_fill(_fill(Side.SELL, 10.0, 98.0, 0.0, 3000))
    assert ledger.cash == 9980
    assert ledger.apply_cash_dividend(PERP_ID, 2000, 2.0) == 0
    assert ledger.mark({}, 3000).equity_quote == 10000
    ledger.settle_dividends(as_of_ms=5000)
    assert ledger.cash == 10000
    assert ledger.total_corporate_actions == 20


def test_split_after_entitlement_does_not_rescale_cash_receivable():
    ledger = book()
    ledger.apply_cash_dividend(PERP_ID, 2000, 2.0)
    ledger.apply_split(PERP_ID, 3000, 2.0)
    assert ledger.pending_dividends == 20
    assert ledger.mark({PERP_ID: 49.0}, 3000).equity_quote == 10000


def test_payment_boundary_cannot_be_skipped_or_financed_across():
    ledger = book()
    ledger.apply_cash_dividend(PERP_ID, 2000, 2.0)
    with pytest.raises(ObservationError, match="boundary"):
        ledger.settle_dividends(as_of_ms=5001)
    assert ledger.cash == 9000 and ledger.pending_dividends == 20
    with pytest.raises(ObservationError, match="boundary"):
        ledger.apply_financing(SimpleNamespace(start_ts=2000, end_ts=5001))
    ledger.settle_dividends(as_of_ms=5000)
    assert ledger.cash == 9020


def test_missing_or_mismatched_payment_event_fails_atomically():
    ledger = book()
    for ts, value in [(2001, 2.0), (2000, 3.0)]:
        with pytest.raises(ObservationError, match="Exact"):
            ledger.apply_cash_dividend(PERP_ID, ts, value)
    assert ledger.pending_dividends == 0 and ledger.cash == 9000
    assert ledger.total_corporate_actions == 0


@pytest.mark.parametrize(
    "payments",
    [
        [event(), event()],
        [replace(event(), pay_ms=1999)],
        [replace(event(), observed_ms=2001)],
    ],
)
def test_bad_schedule(payments):
    with pytest.raises(ObservationError):
        PayableDividendLedger(10000.0, {PERP_ID: _perp()}, payments=payments)


def test_real_financing_uses_settled_cash_before_and_after_payment():
    from alphaforge.execution.financing import FinancingQuote, accrue_financing

    ledger = book()
    ledger.apply_cash_dividend(PERP_ID, 2000, 2.0)
    quote = FinancingQuote(
        currency="USDT",
        observed_ts=0,
        available_at=0,
        valid_from=0,
        valid_until=10000,
        credit_rate_bps=400.0,
        debit_rate_bps=700.0,
        short_proceeds_rate_bps=0.0,
        source="test",
    )
    first = accrue_financing(
        quote,
        cash_balance=ledger.cash,
        short_market_value=0.0,
        start_ts=2000,
        end_ts=5000,
        decision_ts=2000,
    )
    assert first.cash_balance == 9000
    ledger.apply_financing(first)
    ledger.settle_dividends(as_of_ms=5000)
    second = accrue_financing(
        quote,
        cash_balance=ledger.cash,
        short_market_value=0.0,
        start_ts=5000,
        end_ts=6000,
        decision_ts=5000,
    )
    assert second.cash_balance == pytest.approx(9020 + first.payment_quote)
    ledger.apply_financing(second)
    with pytest.raises(ObservationError, match="boundary"):
        ledger.apply_financing(replace(second, start_ts=4000))
