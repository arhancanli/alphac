"""Isolated published-payment cadence feature; no default-registry mutation."""
import numpy as np
import pandas as pd
from alphaforge.features.spec import Family, FeatureSpec
from crypto_observed_carry import observed_carry


def payment_values(f,k):
    """Values at publication events; direct finite windows for monotone settlements."""
    ts=f.ts_funding.to_numpy(dtype=np.int64);pub=f.available_at.to_numpy(dtype=np.int64)
    rates=f.rate.to_numpy(dtype=float);out=np.full(len(f),np.nan)
    if np.any(pub<ts) or not np.isfinite(rates).all():raise ValueError('Invalid funding publication/rate')
    if np.any(np.diff(ts)<=0):
        return np.array([observed_carry(ts,pub,rates,decision_ms=int(t),k=k) for t in pub])
    if len(f)>=k+1:
        windows=np.lib.stride_tricks.sliding_window_view(ts,k+1)
        gaps=np.diff(windows,axis=1)/3600000
        payments=np.lib.stride_tricks.sliding_window_view(rates,k+1)[:,1:]
        valid=((gaps>=1-1/3600)&(gaps<=8+1/3600)).all(axis=1)
        values=-payments.sum(axis=1)*8760/gaps.sum(axis=1)
        out[k:]=np.where(valid,values,np.nan)
    return out


def feature_fn(ctx,spec):
    grid=np.asarray(ctx.panel('close').index,dtype=np.int64);ids=list(ctx.instrument_ids)
    target=pd.MultiIndex.from_product([grid,ids],names=['ts_open','instrument_id'])
    out=pd.Series(np.nan,index=target,name=spec.name,dtype=float)
    funding=ctx.funding()
    for iid in ids:
        if ctx.instrument(iid).funding_interval_hours is None:continue
        f=funding[funding.instrument_id==iid].sort_values('available_at',kind='stable').copy()
        if f.empty:continue
        f['value']=payment_values(f,int(spec.params['n_settlements']))
        merged=pd.merge_asof(pd.DataFrame({'decision_ts':grid+3600000}),f[['available_at','value']],left_on='decision_ts',right_on='available_at',direction='backward',allow_exact_matches=True)
        out.loc[(slice(None),iid)]=merged.value.to_numpy()
    return out


def carry_observed_21():
    return FeatureSpec(name='carry_observed_21',family=Family.CARRY,direction=1,cross_sectional=True,
                       lookback_bars=(21+2)*8+1,params={'n_settlements':21,'max_gap_hours':8,'min_gap_hours':1},fn=feature_fn)
