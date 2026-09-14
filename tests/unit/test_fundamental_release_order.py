import numpy as np
import pandas as pd
import pytest
from fundamental_release_order import quarterly_ttm_events


def sample():
    return pd.DataFrame({'instrument_id':['A']*5,'period_end':[100,200,300,400,500],
        'available_at':[110,210,450,410,510],'fiscal_year':[2020]*4+[2021],
        'fiscal_period':['Q1','Q2','Q3','Q4','Q1'],'revenue':[10.,20.,30.,40.,50.]})


def test_late_quarter_does_not_leak_and_completes_latest_endpoint():
    events=quarterly_ttm_events(sample(),'revenue').set_index('available_at')
    assert np.isnan(events.loc[410,'ttm'])
    assert events.loc[450,'ttm']==100
    assert events.loc[450,'period_end']==400
    assert events.loc[510,'ttm']==140


def test_every_availability_prefix_is_identical():
    f=sample();full=quarterly_ttm_events(f,'revenue')
    for t in [109,110,210,410,449,450,510]:
        actual=quarterly_ttm_events(f[f.available_at<=t],'revenue')
        expected=full[full.available_at<=t].reset_index(drop=True)
        if actual.empty:assert expected.empty
        else:pd.testing.assert_frame_equal(actual,expected)


def test_simultaneous_release_is_one_complete_batch_and_input_immutable():
    f=sample();f.loc[:3,'available_at']=450;before=f.copy(deep=True)
    a=quarterly_ttm_events(f,'revenue');b=quarterly_ttm_events(f.sample(frac=1,random_state=42),'revenue')
    assert len(a)==2 and a.iloc[0].ttm==100
    pd.testing.assert_frame_equal(a,b);pd.testing.assert_frame_equal(f,before)


def test_gap_is_not_four_quarters_and_latest_missing_value_invalidates():
    f=sample().drop(index=2)
    assert quarterly_ttm_events(f,'revenue').ttm.isna().all()
    f=sample();f.loc[4,'revenue']=np.nan
    events=quarterly_ttm_events(f,'revenue')
    assert events.iloc[-2].ttm==100 and np.isnan(events.iloc[-1].ttm)


def test_other_instrument_cannot_supply_missing_quarters():
    f=sample();other=f.copy();other.instrument_id='B';other.revenue=1
    events=quarterly_ttm_events(pd.concat([f,other.iloc[-1:]],ignore_index=True),'revenue')
    assert events[events.instrument_id=='B'].ttm.isna().all()


@pytest.mark.parametrize('kind',['duplicate','annual','early','fiscal_order'])
def test_ambiguous_source_rejected(kind):
    f=sample()
    if kind=='duplicate':f=pd.concat([f,f.iloc[:1]],ignore_index=True)
    elif kind=='annual':f.loc[0,'fiscal_period']='FY'
    elif kind=='early':f.loc[0,'available_at']=99
    else:f.loc[0,'period_end']=250;f.loc[0,'available_at']=260
    with pytest.raises(ValueError):quarterly_ttm_events(f,'revenue')
