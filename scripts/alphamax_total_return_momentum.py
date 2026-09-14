"""Causal ex-date wealth-return momentum; signal index, not spendable cash."""
import numpy as np
import pandas as pd
DAY=86400000


def session_wealth_returns(raw,actions):
    """Return log((q_t*P_t+D_t)/P_previous) on the full supplied session grid.

q is new shares per old; D is cash per prior share. Simultaneous split and
cash distribution is rejected until share units are independently reconciled.
The supplied action snapshot must be complete and historically admissible; this
function checks stored availability but cannot establish publication provenance.
"""
    if not raw.index.is_unique or not raw.index.is_monotonic_increasing or not raw.columns.is_unique:
        raise ValueError('Unique ordered source grid required')
    if len(raw)==0:raise ValueError('Nonempty price grid required')
    p=raw.astype(float).where(lambda x:np.isfinite(x)&x.gt(0))
    ratios=pd.DataFrame(1.,index=p.index,columns=p.columns)
    cash=pd.DataFrame(0.,index=p.index,columns=p.columns)
    if not actions.empty:
        a=actions[actions.instrument_id.isin(p.columns)&(actions.ex_date>p.index.min())&(actions.ex_date<=p.index.max())].copy()
        if a.duplicated(['instrument_id','ex_date']).any():
            raise ValueError('Duplicate or simultaneous action requires share-basis adjudication')
        for r in a.itertuples():
            if r.ex_date not in p.index:raise ValueError('Action is not on the supplied session grid')
            if pd.isna(r.available_at) or r.available_at>r.ex_date+DAY:
                raise ValueError('Late action requires explicit causal revision design')
            if r.action_type=='split':
                if not np.isfinite(r.ratio) or r.ratio<=0:raise ValueError('Invalid new/old share ratio')
                ratios.loc[r.ex_date,r.instrument_id]=r.ratio
            elif r.action_type=='dividend':
                if not np.isfinite(r.cash_amount) or r.cash_amount<0:raise ValueError('Invalid dividend amount')
                cash.loc[r.ex_date,r.instrument_id]=r.cash_amount
            else:raise ValueError('Unsupported action')
    gross=(ratios*p+cash)/p.shift(1)
    return np.log(gross.where(np.isfinite(gross)&gross.gt(0)))


def total_return_momentum(raw,actions):
    """Same252/21endpoints:231completed daily wealth returns ending t-21."""
    return session_wealth_returns(raw,actions).shift(21).rolling(231,min_periods=231).sum()
