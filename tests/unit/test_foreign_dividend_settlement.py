from dataclasses import replace
from decimal import Decimal as D
import pytest
from alphaforge.validation.foreign_dividend_settlement import (
    ForeignDividendBook, ForeignEntitlement, FxObservation, SettlementTerms,
)


def event(key='a'):
    return ForeignEntitlement(key, 'EUR', 100, 300, 90, D('1.6'))


def terms():
    return SettlementTerms(150, 200, D('1.1915'), D('.28596'), D('0'), D('1.9064'), D('.01'))


def start(quantity='10'):
    b = ForeignDividendBook()
    b.accrue(event(), D(quantity), as_of_ms=100)
    b.observe_fx(FxObservation('EUR', 90, 95, D('1.1')), as_of_ms=100)
    return b


def test_foreign_revaluation_withholding_and_settlement_conserve_nav():
    b = start()
    assert b.pending_usd(as_of_ms=100, max_fx_age_ms=20) == D('17.60')
    assert b.settled_cash_delta == 0
    b.observe_fx(FxObservation('EUR', 140, 145, D('1.2')), as_of_ms=150)
    assert b.pending_usd(as_of_ms=150, max_fx_age_ms=20) == D('19.20')
    b.fix('a', terms(), as_of_ms=200)
    assert b.pending_usd(as_of_ms=200, max_fx_age_ms=0) == D('16.2044')
    assert b.settle_due(as_of_ms=299) == 0
    assert b.settle_due(as_of_ms=300) == D('16.2044')
    assert b.pending_usd(as_of_ms=300, max_fx_age_ms=0) == 0
    assert b.settle_due(as_of_ms=300) == 0
    assert b.settled_cash_delta == D('16.2044')


def test_short_obligation_does_not_inherit_long_withholding():
    b = start('-10')
    b.fix('a', terms(), as_of_ms=200)
    assert b.pending_usd(as_of_ms=200, max_fx_age_ms=0) == D('-19.1640')
    assert b.settle_due(as_of_ms=300) == D('-19.1640')


def test_future_terms_cannot_change_earlier_nav():
    b = start()
    for future in (terms(), replace(terms(), usd_per_foreign=D('2'))):
        with pytest.raises(ValueError, match='unavailable'):
            b.fix('a', future, as_of_ms=100)
        assert b.pending_usd(as_of_ms=100, max_fx_age_ms=20) == D('17.60')
    with pytest.raises(ValueError, match='available'):
        b.observe_fx(FxObservation('EUR', 101, 102, D('2')), as_of_ms=100)
    assert b.settled_cash_delta == 0


def test_missing_late_and_stale_observations_fail_closed():
    b = ForeignDividendBook()
    with pytest.raises(ValueError, match='Timely'):
        b.accrue(replace(event(), available_ms=101), D(10), as_of_ms=100)
    b.accrue(event(), D(10), as_of_ms=100)
    with pytest.raises(ValueError, match='Missing'):
        b.pending_usd(as_of_ms=100, max_fx_age_ms=20)
    b.observe_fx(FxObservation('EUR', 90, 95, D('1.1')), as_of_ms=100)
    with pytest.raises(ValueError, match='stale'):
        b.pending_usd(as_of_ms=120, max_fx_age_ms=20)
    with pytest.raises(ValueError, match='No settlement'):
        b.settle_due(as_of_ms=300)
    assert b.settled_cash_delta == 0


def test_failed_batch_does_not_partially_settle():
    b = start()
    b.accrue(event('b'), D(5), as_of_ms=100)
    b.fix('a', terms(), as_of_ms=200)
    with pytest.raises(ValueError, match='No settlement'):
        b.settle_due(as_of_ms=300)
    assert b.settled_cash_delta == 0
    b.fix('b', terms(), as_of_ms=200)
    assert b.settle_due(as_of_ms=300) == D('24.3066')
    with pytest.raises(ValueError, match='backwards'):
        b.pending_usd(as_of_ms=299, max_fx_age_ms=0)
