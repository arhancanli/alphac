from dataclasses import replace
from decimal import Decimal as D
import pandas as pd
import pytest
from test_payable_engine import setup, ms, IID
from alphaforge.backtest.engine import ScriptedStrategy
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.backtest.depositary_engine import DepositaryEquityBacktester
from alphaforge.backtest.depositary_dividend_ledger import DepositaryCashTerms
from alphaforge.validation.trend_observation import ObservationError


def terms():
    # Synthetic short contract deliberately differs from the long net receipt.
    return DepositaryCashTerms('div1', ms('2026-01-12'), D('.02'), D('0'), D('2'), D('.01'), 'synthetic-independent-short')


@pytest.mark.parametrize('weight,rate',[(.1,D('1.98')),(-.1,D('2.01'))])
def test_actual_engine_asymmetric_cash_after_sale_weekend_financing(tmp_path,weight,rate):
    args,kwargs,payments,start,end=setup(tmp_path,financing=True)
    result=DepositaryEquityBacktester(*args,payments=payments,depositary_terms=[terms()],**kwargs).run(
        ScriptedStrategy({ms('2026-01-13'):{IID:weight},ms('2026-01-16'):{IID:0.}}),[IID],start=start,end=end)
    record,=result.config['depositary_cash_records']
    qty=D(record['signed_quantity']);net=qty*rate
    assert D(record['net_signed_entitlement'])==net
    assert D(record['gross_per_share'])==2
    assert result.corporate_actions.iloc[0].cashflow_quote==pytest.approx(float(net))
    paid,=result.config['dividend_settlements']
    assert paid['ts']==ms('2026-01-17') and paid['cashflow_quote']==pytest.approx(float(net))
    assert result.config['terminal_pending_dividends']==0
    fin=result.financing_events
    before=fin[fin.end_ts==paid['ts']].iloc[0]
    after=fin[fin.start_ts==paid['ts']].iloc[0]
    assert after.cash_balance==pytest.approx(before.cash_balance+before.payment_quote+float(net))
    assert result.fills.iloc[-1].ts<paid['ts']


def test_empty_terms_preserve_original_engine_exactly(tmp_path):
    args,kwargs,payments,start,end=setup(tmp_path,financing=True)
    script={ms('2026-01-13'):{IID:.1}}
    a=PayableEquityBacktester(*args,payments=payments,**kwargs).run(ScriptedStrategy(script),[IID],start=start,end=end)
    b=DepositaryEquityBacktester(*args,payments=payments,depositary_terms=[],**kwargs).run(ScriptedStrategy(script),[IID],start=start,end=end)
    pd.testing.assert_series_equal(a.equity,b.equity,check_exact=True)
    pd.testing.assert_frame_equal(a.financing_events,b.financing_events,check_exact=True)


@pytest.mark.parametrize('change',[{'observed_ms':ms('2026-01-16')},{'short_payment_per_share':None},{'event_id':'missing'},{'long_fee_per_share':D('NaN')}])
def test_invalid_or_late_terms_rejected_before_trading(tmp_path,change):
    args,kwargs,payments,start,end=setup(tmp_path)
    with pytest.raises(ObservationError):
        DepositaryEquityBacktester(*args,payments=payments,depositary_terms=[replace(terms(),**change)],**kwargs).run(ScriptedStrategy({}),[IID],start=start,end=end)


def test_unpaid_net_entitlement_stays_receivable(tmp_path):
    args,kwargs,payments,start,end=setup(tmp_path,pay=ms('2026-02-01'))
    result=DepositaryEquityBacktester(*args,payments=payments,depositary_terms=[terms()],**kwargs).run(ScriptedStrategy({ms('2026-01-13'):{IID:.1}}),[IID],start=start,end=end)
    rec,=result.config['depositary_cash_records']
    assert result.config['terminal_pending_dividends']==pytest.approx(float(D(rec['net_signed_entitlement'])))
    assert result.config['dividend_settlements']==()
