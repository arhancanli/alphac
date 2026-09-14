"""Availability-ordered quarterly flow reduction for isolated research.

Input is one first-disclosure row per fiscal quarter. This reducer cannot certify
source publication dates or convert annual/YTD amounts into quarterly flows.
It rejects revisions/ambiguous quarters rather than choosing a hindsight value.
"""
import numpy as np
import pandas as pd


def quarterly_ttm_events(frame, column):
    """Emit latest-period TTM at each release time, after applying its entire batch.

    Four consecutive fiscal quarters must all be available and finite. An older
    late filing can complete the latest TTM but cannot move the endpoint backward.
    Null events are intentional: as-of users must preserve them, not drop/ffill.
    Timestamps are integer milliseconds. No price or execution data are used.
    """
    required=['instrument_id','period_end','available_at','fiscal_year','fiscal_period',column]
    if not set(required).issubset(frame.columns):raise ValueError('Missing quarterly fields')
    f=frame[required].copy(deep=True)
    if f.empty:return pd.DataFrame(columns=['instrument_id','available_at','period_end','ttm'])
    if f[['instrument_id','period_end','available_at','fiscal_year','fiscal_period']].isna().any().any():
        raise ValueError('Missing identity, timestamp or fiscal quarter')
    for name in ['period_end','available_at','fiscal_year']:
        if not pd.api.types.is_integer_dtype(f[name]):raise ValueError('Integer timestamps/year required')
    if not f.fiscal_period.isin(['Q1','Q2','Q3','Q4']).all():raise ValueError('Quarterly flows required')
    if (f.available_at<f.period_end).any():raise ValueError('Release precedes period end')
    f['quarter']=f.fiscal_year*4+f.fiscal_period.str[-1].astype(int)-1
    if f.duplicated(['instrument_id','quarter']).any() or f.duplicated(['instrument_id','period_end']).any():
        raise ValueError('Duplicate/revised fiscal quarter requires vintage adjudication')
    for _,g in f.groupby('instrument_id'):
        if not g.sort_values('quarter').period_end.is_monotonic_increasing:
            raise ValueError('Fiscal quarter and period ordering disagree')
    events=[]
    for iid,g in f.groupby('instrument_id',sort=True):
        known={}
        for available,batch in g.groupby('available_at',sort=True):
            for row in batch.to_dict('records'):known[row['quarter']]=row
            latest=max(known);endpoint=known[latest]['period_end']
            values=[known[q][column] if q in known else np.nan for q in range(latest-3,latest+1)]
            values=np.asarray(values,dtype=float)
            ttm=float(values.sum()) if np.isfinite(values).all() else np.nan
            events.append({'instrument_id':iid,'available_at':int(available),'period_end':int(endpoint),'ttm':ttm})
    return pd.DataFrame(events).sort_values(['available_at','instrument_id']).reset_index(drop=True)
