import numpy as np
import pandas as pd
import pytest
from crypto_oi_daily_features import daily_record, build_features, attach_mature_labels


def source_day():
    d=pd.Timestamp('2022-01-01',tz='UTC');g=pd.date_range(d,periods=288,freq='5min')
    oi=pd.DataFrame({'symbol':'BTCUSDT','observed_at':g,'quantity':np.arange(288)+100.})
    p=pd.DataFrame({'symbol':'BTCUSDT','open_at':g,'close':np.arange(288)+1000.,'available_at':g+pd.Timedelta(minutes=5)})
    t=pd.date_range(d,periods=3,freq='8h')
    f=pd.DataFrame({'symbol':'BTCUSDT','settled_at':t,'rate':[.001,.002,.003],'available_at':t+pd.Timedelta(minutes=5)})
    return d,oi,p,f,t


def daily():
    d=pd.date_range('2022-01-01',periods=70,tz='UTC')
    return pd.DataFrame({'day':d,'symbol':'BTCUSDT','close':np.exp(np.arange(70)*.01),
                         'oi':np.exp(np.arange(70)*.02),'funding_sum':.006,'funding_count':3,
                         'input_available_at':d+pd.Timedelta(days=3)})


def test_sorted_final_snapshot_and_exact_lag():
    d,o,p,f,t=source_day()
    r=daily_record(d,'BTCUSDT',o.sample(frac=1,random_state=3),p.sample(frac=1,random_state=2),f,t)
    assert r['oi']==387 and r['close']==1287
    assert r['funding_sum']==.006 and r['funding_count']==3
    assert r['input_available_at']==pd.Timestamp('2022-01-04',tz='UTC')


@pytest.mark.parametrize('kind',['missing_oi','duplicate_oi','missing_price','missing_funding','wrong_symbol','early_price','nonfinite','naive'])
def test_invalid_source_days_rejected(kind):
    d,o,p,f,t=source_day()
    if kind=='missing_oi':o=o.iloc[1:]
    if kind=='duplicate_oi':o=pd.concat([o,o.iloc[:1]])
    if kind=='missing_price':p=p.iloc[1:]
    if kind=='missing_funding':f=f.iloc[1:]
    if kind=='wrong_symbol':o.loc[0,'symbol']='ETHUSDT'
    if kind=='early_price':p.loc[0,'available_at']=d
    if kind=='nonfinite':o.loc[0,'quantity']=np.inf
    if kind=='naive':o['observed_at']=o.observed_at.dt.tz_localize(None)
    with pytest.raises(ValueError):daily_record(d,'BTCUSDT',o,p,f,t)


def test_calendar_windows_formula_and_48hour_after_day_end():
    f=daily();r=build_features(f,'BTCUSDT',f.day.iloc[28],f.day.iloc[28]).iloc[0]
    assert r.eligible and r.decision_at==f.day.iloc[28]+pd.Timedelta(days=3)
    assert r.momentum_7d==pytest.approx(.07)
    assert r.momentum_28d==pytest.approx(.28)
    assert r.funding_mean_21d==pytest.approx(.002)
    assert r.oi_crowding==pytest.approx(-.14)


def test_no_gap_compression_or_forward_fill():
    f=daily().drop(index=20)
    r=build_features(f,'BTCUSDT','2022-01-29T00:00Z','2022-02-20T00:00Z')
    assert len(r)==23
    assert not r.iloc[0].eligible and np.isnan(r.iloc[0].momentum_28d)
    assert r.iloc[-1].eligible


def test_prefix_invariance_and_future_values_excluded():
    f=daily();end=f.day.iloc[35]
    a=build_features(f,'BTCUSDT',f.day.iloc[28],end)
    b=build_features(f[f.day<=end],'BTCUSDT',f.day.iloc[28],end)
    f.loc[f.day>end,['close','oi','funding_sum']]=1e10
    c=build_features(f,'BTCUSDT',f.day.iloc[28],end)
    pd.testing.assert_frame_equal(a,b);pd.testing.assert_frame_equal(a,c)


def test_late_funding_invalidates_decision_instead_of_rescheduling():
    f=daily();f.loc[28,'input_available_at']+=pd.Timedelta(hours=1)
    r=build_features(f,'BTCUSDT',f.day.iloc[28],f.day.iloc[28]).iloc[0]
    assert not r.eligible and r.reason=='late_source'
    assert r.decision_at==pd.Timestamp('2022-02-01T00:00Z')


def test_funding_mean_is_settlement_weighted_and_oi_contraction_zero():
    f=daily();f.loc[28,'funding_count']=6;f.loc[28,'funding_sum']=.06
    f.loc[28,'oi']=.1
    r=build_features(f,'BTCUSDT',f.day.iloc[28],f.day.iloc[28]).iloc[0]
    assert r.funding_mean_21d==pytest.approx((20*.006+.06)/(20*3+6))
    assert r.oi_crowding==0


def test_labels_stay_unavailable_until_end_bar_completes():
    f=daily();r=build_features(f,'BTCUSDT',f.day.iloc[28],f.day.iloc[28]);d=r.decision_at.iloc[0]
    opens=pd.DatetimeIndex([d,d+pd.Timedelta(days=7)])
    h=pd.DataFrame({'symbol':'BTCUSDT','open_at':opens,'available_at':opens+pd.Timedelta(hours=1),'open':[100.,110.]})
    early=attach_mature_labels(r,h,d+pd.Timedelta(days=7))
    assert np.isnan(early.target.iloc[0])
    mature=attach_mature_labels(r,h,d+pd.Timedelta(days=7,hours=1))
    assert mature.target.iloc[0]==pytest.approx(.1)
    h.loc[1,'open']=np.nan
    # Future target values are not read before maturity.
    assert np.isnan(attach_mature_labels(r,h,d+pd.Timedelta(days=7)).target.iloc[0])
    with pytest.raises(ValueError):attach_mature_labels(r,h,d+pd.Timedelta(days=7,hours=1))


def test_delayed_label_receipt_and_missing_endpoint():
    f=daily();r=build_features(f,'BTCUSDT',f.day.iloc[28],f.day.iloc[28]);d=r.decision_at.iloc[0]
    opens=pd.DatetimeIndex([d,d+pd.Timedelta(days=7)])
    h=pd.DataFrame({'symbol':'BTCUSDT','open_at':opens,'available_at':opens+pd.Timedelta(hours=2),'open':[100.,110.]})
    q=attach_mature_labels(r,h,d+pd.Timedelta(days=7,hours=1))
    assert np.isnan(q.target.iloc[0]) and q.label_available_at.iloc[0]==d+pd.Timedelta(days=7,hours=2)
    assert np.isnan(attach_mature_labels(r,h.iloc[:1],d+pd.Timedelta(days=8)).target.iloc[0])


def test_adapter_to_annual_model_end_to_end():
    from crypto_oi_incremental_model import fit_pair
    dates=pd.date_range('2022-01-01',periods=390,tz='UTC')
    panels=[]
    for symbol,offset in [('BTCUSDT',0.),('ETHUSDT',.2)]:
        x=np.arange(len(dates),dtype=float)
        records=pd.DataFrame({'day':dates,'symbol':symbol,'close':100*np.exp(.001*x+.02*np.sin(x/13+offset)),
                              'oi':1000*np.exp(.002*x+.01*np.cos(x/7+offset)),
                              'funding_sum':.0003*np.sin(x/11+offset),'funding_count':3,
                              'input_available_at':dates+pd.Timedelta(days=3)})
        features=build_features(records,symbol,dates[0],dates[-1])
        opens=pd.date_range(dates[0],periods=405,tz='UTC')
        hourly=pd.DataFrame({'symbol':symbol,'open_at':opens,'available_at':opens+pd.Timedelta(hours=1),
                             'open':100*np.exp(.001*np.arange(405)+.01*np.sin(np.arange(405)/17+offset))})
        panels.append(attach_mature_labels(features,hourly,pd.Timestamp('2023-02-10T00:00Z')))
    panel=pd.concat(panels,ignore_index=True)
    eligible=panel[panel.eligible & panel.target.notna()]
    control,candidate=fit_pair(eligible,'2023-01-01T00:00Z')
    assert control.training_rows==candidate.training_rows>=504
    assert candidate.last_label_available<pd.Timestamp('2022-12-25T00:00Z')
    evaluation=eligible[eligible.decision_at>=pd.Timestamp('2023-01-01T00:00Z')]
    assert len(evaluation)>0 and np.isfinite(candidate.predict(evaluation)).all()
