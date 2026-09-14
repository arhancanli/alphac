from datetime import datetime, timezone
import pytest
from earnings_filing_inputs import prepare, seasonal_pair


def row(**kw):
    r=dict(ticker='NA',dimension='ARQ',datekey='2024-07-31',reportperiod='2024-06-29',fiscalperiod='2024-Q3',netinccmn='50',assets='1000')
    return r|kw


def test_fiscal_ticker_and_delay():
    f=prepare(row(),{'NA':'stable:1'})
    assert (f.ticker,f.fiscal_quarter)==('NA',3)
    assert f.available_at==datetime(2024,8,2,4,tzinfo=timezone.utc)
    winter=prepare(row(datekey='2024-01-31',reportperiod='2023-12-30',fiscalperiod='2024-Q1'),{'NA':'stable:1'})
    assert winter.available_at==datetime(2024,2,2,5,tzinfo=timezone.utc)


def test_no_future_filing_or_revision_leak():
    p=prepare(row(datekey='2023-07-31',reportperiod='2023-07-01',fiscalperiod='2023-Q3'),{'NA':'s'})
    c=prepare(row(),{'NA':'s'})
    future=prepare(row(datekey='2024-08-05',netinccmn='999'),{'NA':'s'})
    before=datetime(2024,8,2,3,59,tzinfo=timezone.utc)
    at=c.available_at
    assert seasonal_pair([p,c,future],'s',before) is None
    assert seasonal_pair([p,c],'s',at)==seasonal_pair([future,c,p],'s',at)==(c,p)
    assert seasonal_pair([c,p,future],'s',future.available_at)==(future,p)


def test_ambiguous_or_missing_quarter_not_shifted():
    p=prepare(row(datekey='2023-07-31',reportperiod='2023-07-01',fiscalperiod='2023-Q3'),{'NA':'s'})
    c=prepare(row(),{'NA':'s'})
    bad=prepare(row(reportperiod='2024-06-30'),{'NA':'s'})
    assert seasonal_pair([p,c,bad],'s',c.available_at) is None
    assert seasonal_pair([c],'s',c.available_at) is None
    assert seasonal_pair([c,p,p],'s',c.available_at)==(c,p)


@pytest.mark.parametrize('change',[{'dimension':'MRQ'},{'reportperiod':'2025-01-01'},{'fiscalperiod':'2024Q3'},{'assets':'0'},{'netinccmn':'NaN'},{'ticker':'N.A'}])
def test_invalid_inputs_fail_closed(change):
    with pytest.raises(ValueError): prepare(row(**change),{'NA':'s'})


def test_cross_security_and_naive_time_rejected():
    f=prepare(row(),{'NA':'s'})
    assert seasonal_pair([f],'other',f.available_at) is None
    with pytest.raises(ValueError): seasonal_pair([f],'s',datetime(2024,8,2))
