import numpy as np
import pandas as pd
import pytest
from crypto_oi_incremental_model import fit_pair, CONTROLS, EXTRA


def fixture_frame(sign=1):
    rng=np.random.default_rng(29)
    dates=pd.date_range('2022-01-01', periods=365, tz='UTC').repeat(2)
    f=pd.DataFrame({'decision_at':dates,'symbol':['BTCUSDT','ETHUSDT']*365})
    f['input_available_at']=f.decision_at-pd.Timedelta(hours=1)
    f['label_available_at']=f.decision_at+pd.Timedelta(days=7,hours=1)
    for c in CONTROLS[:-1]:f[c]=rng.normal(size=len(f))
    f['eth_indicator']=(f.symbol=='ETHUSDT').astype(float)
    f[EXTRA]=rng.normal(size=len(f))
    f['target']=sign*2*f[EXTRA]+.3*f.momentum_7d+rng.normal(scale=.01,size=len(f))
    return f


def test_future_labels_and_features_do_not_affect_fit():
    f=fixture_frame();original=fit_pair(f,'2023-01-01T00:00Z')
    excluded=f.label_available_at>=pd.Timestamp('2022-12-25T00:00Z')
    f.loc[excluded,list(CONTROLS)+[EXTRA,'target']]=np.nan
    changed=fit_pair(f,'2023-01-01T00:00Z')
    for a,b in zip(original,changed):
        np.testing.assert_array_equal(a.coefficient,b.coefficient)
        np.testing.assert_array_equal(a.mean,b.mean)
        assert a.last_label_available<pd.Timestamp('2022-12-25T00:00Z')


def test_constraint_reverts_negative_extra_to_matched_control():
    f=fixture_frame(-1);control,candidate=fit_pair(f,'2023-01-01T00:00Z')
    assert candidate.coefficient[-1]==0
    np.testing.assert_allclose(control.predict(f),candidate.predict(f),atol=1e-12)


def test_positive_increment_learned_without_evaluation_fitting():
    f=fixture_frame();control,candidate=fit_pair(f,'2023-01-01T00:00Z')
    assert candidate.coefficient[-1]>1
    # Independent centered ridge closed form for this unconstrained interior solution.
    train=f[f.label_available_at<pd.Timestamp('2022-12-25T00:00Z')]
    x=train[list(CONTROLS)+[EXTRA]].to_numpy();z=(x-x.mean(0))/x.std(0)
    y=train.target.to_numpy();expected=np.linalg.lstsq(np.vstack([z,np.eye(5)]),np.r_[y-y.mean(),np.zeros(5)],rcond=None)[0]
    np.testing.assert_allclose(candidate.coefficient,expected,atol=1e-12)
    assert candidate.training_rows==control.training_rows


def test_shuffle_invariance():
    f=fixture_frame();a=fit_pair(f,'2023-01-01T00:00Z');b=fit_pair(f.sample(frac=1,random_state=4),'2023-01-01T00:00Z')
    for x,y in zip(a,b):np.testing.assert_array_equal(x.coefficient,y.coefficient)


@pytest.mark.parametrize('kind',['late_input','unpaired','nan','duplicate','naive','indicator','short_history','early_label'])
def test_bad_inputs_fail_closed(kind):
    f=fixture_frame()
    if kind=='late_input':f.loc[0,'input_available_at']=f.loc[0,'decision_at']+pd.Timedelta(seconds=1)
    if kind=='unpaired':f=f.iloc[1:]
    if kind=='nan':f.loc[0,EXTRA]=np.nan
    if kind=='duplicate':f=pd.concat([f,f.iloc[:1]])
    if kind=='naive':f['decision_at']=f.decision_at.dt.tz_localize(None)
    if kind=='indicator':f.loc[0,'eth_indicator']=1
    if kind=='short_history':f=f.iloc[:500]
    if kind=='early_label':f.loc[0,'label_available_at']=f.loc[0,'decision_at']+pd.Timedelta(days=1)
    with pytest.raises(ValueError):fit_pair(f,'2023-01-01T00:00Z')


def test_pre2022_rows_are_not_used():
    f=fixture_frame();old=f.copy()
    for c in ('decision_at','input_available_at','label_available_at'):old[c]=old[c]-pd.Timedelta(days=365)
    old.loc[:,list(CONTROLS)+[EXTRA,'target']]=np.nan
    a=fit_pair(f,'2023-01-01T00:00Z');b=fit_pair(pd.concat([old,f]),'2023-01-01T00:00Z')
    for x,y in zip(a,b):np.testing.assert_array_equal(x.coefficient,y.coefficient)
