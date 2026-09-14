"""Frozen-calendar eligibility and funding-slot adapter; no forecasts or targets."""
import numpy as np
import pandas as pd

SYMBOLS=('BTCUSDT','ETHUSDT')
DAYS=pd.date_range('2022-01-01','2026-06-01',tz='UTC')
DECISIONS=pd.date_range('2023-01-01','2026-05-25',tz='UTC')


def normalize_funding_slots(frame):
    """Preserve observations; map only within 1s AFTER modeled 00/08/16UTC slots."""
    f=frame.copy()
    for c in ('settled_at','available_at'):
        if not isinstance(f[c].dtype,pd.DatetimeTZDtype) or f[c].isna().any():
            raise ValueError('Timezone-aware funding times required')
        f[c]=f[c].dt.tz_convert('UTC')
    if not set(f.symbol)<=set(SYMBOLS):
        raise ValueError('Unexpected symbol')
    if not np.isfinite(f.rate.to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite funding rate')
    if (f.available_at<f.settled_at).any():
        raise ValueError('Availability before actual settlement')
    f['actual_settled_at']=f.settled_at
    f['settled_at']=f.actual_settled_at.dt.floor('8h')
    f['slot_offset_seconds']=(f.actual_settled_at-f.settled_at).dt.total_seconds()
    if not f.slot_offset_seconds.between(0,1,inclusive='both').all():
        raise ValueError('Settlement outside fixed slot tolerance')
    if f.duplicated(['symbol','settled_at']).any():
        raise ValueError('Duplicate normalized funding slot')
    return f.sort_values(['symbol','settled_at']).reset_index(drop=True)


def calendar_eligibility(coverage):
    """Exact common29day source-window mask; omitted dates stay false.

Coverage has explicit Boolean oi_complete, price_complete, funding_complete.
The label-endpoint coverage check is separate; this never reads any price value.
"""
    f=coverage.copy()
    if not isinstance(f.day.dtype,pd.DatetimeTZDtype) or f.day.isna().any():
        raise ValueError('Timezone-aware source dates required')
    f['day']=f.day.dt.tz_convert('UTC')
    if not set(f.symbol)<=set(SYMBOLS) or f.duplicated(['symbol','day']).any():
        raise ValueError('Unexpected or duplicate identity')
    if (f.day!=f.day.dt.normalize()).any() or not f.day.isin(DAYS).all():
        raise ValueError('Source day outside frozen calendar')
    columns=['oi_complete','price_complete','funding_complete']
    if any(f[c].dtype!=bool for c in columns):
        raise ValueError('Explicit nonmissing Boolean coverage required')
    all_masks={};summaries=[]
    for symbol in SYMBOLS:
        g=f[f.symbol==symbol].set_index('day').reindex(DAYS)
        complete=g[columns].eq(True).all(axis=1)
        mask=complete.rolling(29,min_periods=29).sum().eq(29)
        mask.index=mask.index+pd.Timedelta(days=3)
        all_masks[symbol]=mask
        evaluation=mask.reindex(DECISIONS,fill_value=False)
        fraction=float(evaluation.mean())
        summaries.append({'symbol':symbol,'expected_decision_dates':len(DECISIONS),'eligible_decision_dates':int(evaluation.sum()),'coverage_fraction':fraction,'coverage_pass':fraction>=.95})
    masks=pd.DataFrame(all_masks).fillna(False)
    masks['paired_eligible']=masks[list(SYMBOLS)].all(axis=1)
    training=[]
    for year in range(2023,2027):
        cutoff=pd.Timestamp(year=year,month=1,day=1,tz='UTC')
        # Endpoint hourly bar completes seven days plus one hour after decision.
        eligible=masks.paired_eligible & (masks.index>=pd.Timestamp('2022-01-01',tz='UTC')) & (masks.index<cutoff) & (masks.index+pd.Timedelta(days=7,hours=1)<cutoff-pd.Timedelta(days=7))
        training.append({'year':year,'paired_source_eligible_training_dates':int(eligible.sum()),'minimum_training_pass':int(eligible.sum())>=252})
    return masks,{'symbols':summaries,'training':training,'source_coverage_pass':all(r['coverage_pass'] for r in summaries) and all(r['minimum_training_pass'] for r in training),'limitation':'Source mask only. Independently verify actual input availability and matured hourly label endpoints before fitting.'}
