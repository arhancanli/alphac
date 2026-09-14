from dataclasses import replace
from decimal import Decimal as D

import pytest

from alphaforge.validation.trend_dividend_settlement import DividendPayment, DividendSettlementBook
from alphaforge.validation.trend_observation import ObservationError

EVENT = DividendPayment("div1", "SPY", 100, 200, 90, D("1.25"))


def test_accrual_preserves_settled_cash_until_payment():
    b = DividendSettlementBook(D("1000"))
    assert b.accrue(EVENT, D(10), as_of_ms=100) == D("12.5")
    assert b.settled_cash == D(1000)
    assert b.pending_cash == D("12.5")
    assert b.settle_due(as_of_ms=199) == 0
    assert b.settle_due(as_of_ms=200) == D("12.5")
    assert b.settled_cash == D("1012.5") and b.pending_cash == 0
    assert b.settle_due(as_of_ms=201) == 0


def test_short_payment_obligation():
    b = DividendSettlementBook(D(1000))
    b.accrue(EVENT, D(-10), as_of_ms=100)
    assert b.pending_cash == D("-12.5")
    b.settle_due(as_of_ms=200)
    assert b.settled_cash == D("987.5")


def test_retries_and_conflicts():
    b = DividendSettlementBook(D(1000))
    b.accrue(EVENT, D(10), as_of_ms=100)
    assert b.accrue(EVENT, D(10), as_of_ms=100) == 0
    with pytest.raises(ObservationError):
        b.accrue(EVENT, D(20), as_of_ms=100)
    assert b.pending_cash == D("12.5")


def test_zero_preex_holding_has_no_entitlement():
    b = DividendSettlementBook(D(1000))
    assert b.accrue(EVENT, D(0), as_of_ms=100) == 0
    assert b.settle_due(as_of_ms=200) == 0


@pytest.mark.parametrize(
    "event",
    [
        replace(EVENT, pay_ms=99),
        replace(EVENT, observed_ms=101),
        replace(EVENT, cash_per_share=D("NaN")),
    ],
)
def test_invalid_events(event):
    with pytest.raises(ObservationError):
        DividendSettlementBook(D(1000)).accrue(event, D(1), as_of_ms=100)


def test_out_of_order_accrual_rejected():
    b = DividendSettlementBook(D(1000))
    b.settle_due(as_of_ms=150)
    with pytest.raises(ObservationError):
        b.accrue(EVENT, D(1), as_of_ms=100)
