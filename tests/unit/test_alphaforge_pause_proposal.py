from copy import deepcopy
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from prepare_alphaforge_pause import proposal
from paper_trading_state import _weights_on,combined_live


def curves():
    return {k:[dict(date='2026-08-07',equity=100.),dict(date='2026-09-11',equity=90. if k=='crypto' else 102.)]
            for k in ('crypto','equity','mf','vintage')}


@pytest.mark.parametrize('allocation',['cash','redistribute'])
def test_pause_future_crypto_loss_is_excluded_but_history_preserved(allocation):
    current=curves(); original=deepcopy(current)
    result=proposal(current,'2026-09-12',allocation)
    assert current==original and result['historical_marks_unchanged']
    assert result['state']=='PREPARED_NOT_ACTIVE'
    schedule=result['schedule']
    prior=combined_live(current,schedule=schedule)
    for k,curve in current.items():
        curve.append(dict(date='2026-09-12',equity=curve[-1]['equity']*(.5 if k=='crypto' else 1.04)))
    after=combined_live(current,schedule=schedule)
    assert after[:-1]==prior
    expected=.03 if allocation=='cash' else .04
    assert after[-1]['equity']==round(prior[-1]['equity']*(1+expected),2)


def test_cash_is_not_renormalized_away():
    result=proposal(curves(),'2026-09-12','cash')
    assert _weights_on('2026-09-12',result['schedule'])==dict(crypto=0.,equity=.25,mf=.25,vintage=.25,cash=.25)


@pytest.mark.parametrize('cutover',['2026-09-11','2026-09-10','invalid'])
def test_retrospective_cutover_refused(cutover):
    with pytest.raises(ValueError): proposal(curves(),cutover,'cash')


def test_overlay_remains_separately_explicit():
    data=curves(); result=proposal(data,'2026-09-12','cash')
    for k,curve in data.items(): curve.append(dict(date='2026-09-12',equity=curve[-1]['equity']))
    a=combined_live(data,schedule=result['schedule'])
    b=combined_live(data,market={'2026-09-12':.1},tilt=.1,schedule=result['schedule'])
    assert b[-1]['equity']==round(a[-2]['equity']*1.01,2)
