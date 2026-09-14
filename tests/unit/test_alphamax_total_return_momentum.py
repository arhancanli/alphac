import numpy as np
import pandas as pd
import pytest
from alphamax_total_return_momentum import session_wealth_returns,total_return_momentum,DAY


def world():
    grid=np.arange(400,dtype=np.int64)*DAY
    raw=pd.DataFrame({'SYNTH':100.},index=grid)
    event=dict(instrument_id='SYNTH',ex_date=grid[200],available_at=grid[190],action_type='dividend',ratio=np.nan,cash_amount=1.)
    raw.iloc[200:]=99.
    return raw,pd.DataFrame([event])


def test_dividend_price_drop_is_not_economic_loss():
    p,a=world();r=session_wealth_returns(p,a)
    assert r.iloc[200,0]==pytest.approx(0)
    assert total_return_momentum(p,a).iloc[252,0]==pytest.approx(0)
    assert np.log(p.iloc[231,0]/p.iloc[0,0])<0


def test_future_ex_close_does_not_rewrite_prior_features():
    p,a=world();before=session_wealth_returns(p,a)
    p2=p.copy();p2.iloc[200]=50.
    after=session_wealth_returns(p2,a)
    pd.testing.assert_frame_equal(before.iloc[:200],after.iloc[:200])
    prefix=session_wealth_returns(p.iloc[:200],a)
    pd.testing.assert_frame_equal(before.iloc[:200],prefix)


def test_split_conservation_and_no_actions_control():
    p,a=world();p.iloc[:]=100.;p.iloc[200:]=25.
    a.loc[0,['action_type','ratio','cash_amount']]=['split',4.,np.nan]
    assert session_wealth_returns(p,a).iloc[200,0]==pytest.approx(0)
    q=pd.DataFrame({'SYNTH':100*np.exp(np.arange(400)*.001)},index=p.index)
    got=total_return_momentum(q,pd.DataFrame())
    expected=np.log(q.shift(21)/q.shift(252))
    np.testing.assert_allclose(got,expected,atol=1e-12,equal_nan=True)


def test_wealth_identity_with_reinvestment_and_input_immutability():
    p,a=world();p.iloc[200:]=100.;copy=p.copy();actions=a.copy()
    got=session_wealth_returns(p,a).iloc[1:,0]
    # One prior share receives1 and reinvests at100, yielding1.01shares.
    assert np.exp(got.sum())==pytest.approx(1.01)
    pd.testing.assert_frame_equal(p,copy);pd.testing.assert_frame_equal(a,actions)


def test_gaps_and_recent_skip():
    p,a=world();p.iloc[100]=np.nan
    assert np.isnan(total_return_momentum(p,a).iloc[252,0])
    p,a=world();before=total_return_momentum(p,a).iloc[252,0];p.iloc[232:253]=np.nan
    assert total_return_momentum(p,a).iloc[252,0]==before


@pytest.mark.parametrize('kind',['late','duplicate','simultaneous','negative_cash','off_grid'])
def test_invalid_actions_fail(kind):
    p,a=world()
    if kind=='late':a.loc[0,'available_at']=a.loc[0,'ex_date']+2*DAY
    if kind=='duplicate':a=pd.concat([a,a])
    if kind=='simultaneous':b=a.copy();b.loc[0,['action_type','ratio']]=['split',2.];a=pd.concat([a,b])
    if kind=='negative_cash':a.loc[0,'cash_amount']=-1.
    if kind=='off_grid':a.loc[0,'ex_date']+=1
    with pytest.raises(ValueError):session_wealth_returns(p,a)
