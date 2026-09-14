import numpy as np
import pandas as pd
import pytest
from crypto_trade_flow_model import CONTROLS,fit_pair


def sample():
    rng=np.random.default_rng(7)
    times=pd.date_range('2022-01-01 00:05',periods=365*6,freq='4h',tz='UTC').repeat(2)
    f=pd.DataFrame(rng.normal(size=(len(times),len(CONTROLS))),columns=CONTROLS)
    f['symbol']=np.tile(['BTCUSDT','ETHUSDT'],len(times)//2)
    f.eth_indicator=(f.symbol=='ETHUSDT').astype(float)
    f['flow']=rng.normal(size=len(f));f['target']=.01*f.flow+.003*f.return_4h
    f['decision_at']=times;f['input_available_at']=times
    f['label_available_at']=times+pd.Timedelta(hours=4,minutes=10)
    return f


def test_fit_detects_incremental_feature_and_training_only_scaling():
    f=sample();a,b=fit_pair(f,'2023-01-01T00:00Z')
    assert b.coefficient[-1]>0
    assert ((b.predict(f)-f.target)**2).mean()<((a.predict(f)-f.target)**2).mean()
    train=f[f.label_available_at<pd.Timestamp('2022-12-31',tz='UTC')]
    np.testing.assert_allclose(b.mean,train[list(b.columns)].mean())


def test_future_labels_and_extreme_features_cannot_change_training():
    f=sample();_,base=fit_pair(f,'2023-01-01T00:00Z')
    future=f.iloc[:12].copy()
    for c in ['decision_at','input_available_at','label_available_at']:future[c]+=pd.Timedelta(days=365)
    future['flow']=1e9;future['target']=-1e12
    _,changed=fit_pair(pd.concat([f,future],ignore_index=True),'2023-01-01T00:00Z')
    np.testing.assert_array_equal(base.mean,changed.mean)
    np.testing.assert_array_equal(base.coefficient,changed.coefficient)


def test_negative_flow_slope_collapses_to_control_without_sign_flip():
    f=sample();f.target=-f.flow
    a,b=fit_pair(f,'2023-01-01T00:00Z')
    assert b.coefficient[-1]==0
    np.testing.assert_allclose(a.predict(f),b.predict(f),atol=1e-12)


@pytest.mark.parametrize('kind',['late_input','early_label','duplicate','wrong_clock','few_days'])
def test_timing_and_sample_gates(kind):
    f=sample()
    if kind=='late_input':f.loc[0,'input_available_at']+=pd.Timedelta(minutes=1)
    elif kind=='early_label':f.loc[0,'label_available_at']-=pd.Timedelta(minutes=5)
    elif kind=='duplicate':f=pd.concat([f,f.iloc[:1]],ignore_index=True)
    elif kind=='wrong_clock':
        for c in ['decision_at','input_available_at','label_available_at']:f[c]+=pd.Timedelta(minutes=1)
    else:f=f.iloc[:250*12]
    with pytest.raises(ValueError):fit_pair(f,'2023-01-01T00:00Z')
