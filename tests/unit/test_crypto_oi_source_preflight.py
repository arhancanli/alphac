import pandas as pd
import pytest
from crypto_oi_source_preflight import normalize_funding_slots,calendar_eligibility,DAYS,DECISIONS


def funding():
    t=pd.date_range('2022-01-01',periods=3,freq='8h',tz='UTC')+pd.Timedelta(milliseconds=31)
    return pd.DataFrame({'symbol':'BTCUSDT','settled_at':t,'available_at':t+pd.Timedelta(minutes=5),'rate':[.001,.002,.003]})


def test_slot_mapping_preserves_actual_times_and_availability():
    f=funding();g=normalize_funding_slots(f)
    pd.testing.assert_series_equal(g.actual_settled_at,f.settled_at,check_names=False)
    pd.testing.assert_series_equal(g.available_at,f.available_at)
    assert g.settled_at.iloc[0]==pd.Timestamp('2022-01-01T00:00Z')
    assert g.slot_offset_seconds.eq(.031).all()


@pytest.mark.parametrize('kind',['late','before','duplicate','early_available','nan'])
def test_invalid_settlements_rejected(kind):
    f=funding()
    if kind=='late':f.loc[0,'settled_at']+=pd.Timedelta(seconds=1)
    if kind=='before':f.loc[0,'settled_at']-=pd.Timedelta(seconds=1)
    if kind=='duplicate':f=pd.concat([f,f.iloc[:1]])
    if kind=='early_available':f.loc[0,'available_at']=f.loc[0,'settled_at']-pd.Timedelta(milliseconds=1)
    if kind=='nan':f.loc[0,'rate']=float('nan')
    with pytest.raises(ValueError):normalize_funding_slots(f)


def coverage():
    return pd.concat([pd.DataFrame({'symbol':symbol,'day':DAYS,'oi_complete':True,'price_complete':True,'funding_complete':True}) for symbol in ['BTCUSDT','ETHUSDT']],ignore_index=True)


def test_complete_frozen_calendar_passes_and_purge_exact():
    masks,result=calendar_eligibility(coverage())
    assert result['source_coverage_pass']
    assert all(r['eligible_decision_dates']==len(DECISIONS) for r in result['symbols'])
    expected=len(pd.date_range('2022-02-01','2022-12-17',tz='UTC'))
    assert result['training'][0]['paired_source_eligible_training_dates']==expected


def test_missing_day_invalidates29_calendar_windows():
    f=coverage();gap=pd.Timestamp('2024-04-01',tz='UTC')
    f=f[~((f.symbol=='BTCUSDT') & (f.day==gap))]
    mask,r=calendar_eligibility(f)
    affected=mask.reindex(DECISIONS)
    assert (~affected.BTCUSDT).sum()==29 and affected.ETHUSDT.all()
    assert (~affected.paired_eligible).sum()==29
    assert not mask.loc[gap+pd.Timedelta(days=3),'BTCUSDT']
    assert mask.loc[gap+pd.Timedelta(days=32),'BTCUSDT']


def test_high_raw_coverage_can_fail_feature_coverage():
    f=coverage()
    gaps=pd.to_datetime(['2024-02-01','2024-05-01','2024-08-01'],utc=True)
    f.loc[(f.symbol=='BTCUSDT') & f.day.isin(gaps),'oi_complete']=False
    assert f.oi_complete.mean()>.99
    _,r=calendar_eligibility(f)
    assert not r['source_coverage_pass'] and not r['symbols'][0]['coverage_pass']


def test_duplicate_coverage_rejected():
    f=coverage()
    with pytest.raises(ValueError):calendar_eligibility(pd.concat([f,f.iloc[:1]]))
