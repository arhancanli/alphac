"""Opt-in momentum path-quality hypothesis; no source acquisition or runner."""
import numpy as np
import pandas as pd


def path_momentum(close, sessions):
    """Use exactly the existing252/21session formation endpoints.

The caller supplies the full exchange-session grid and the same corrected
split-price basis as the retained AlphaMax control. Missing sessions stay NaN.
No current holdings, labels, return performance or fitted coefficients enter.
"""
    grid=pd.Index(sessions)
    if not grid.is_unique or not grid.is_monotonic_increasing:
        raise ValueError('Unique ordered full session grid required')
    if not close.index.is_unique or not close.columns.is_unique:
        raise ValueError('Duplicate price identity')
    if not close.index.isin(grid).all():
        raise ValueError('Price row outside supplied session grid')
    p=close.reindex(grid).astype(float)
    p=p.where(np.isfinite(p)&p.gt(0))
    daily=np.log(p/p.shift(1)).shift(21)
    count=daily.rolling(231,min_periods=231).count()
    positive=daily.gt(0).astype(float).where(daily.notna()).rolling(231,min_periods=231).sum()
    negative=daily.lt(0).astype(float).where(daily.notna()).rolling(231,min_periods=231).sum()
    momentum=np.log(p.shift(21)/p.shift(252)).where(count.eq(231))
    discreteness=np.sign(momentum)*(negative-positive)/231.
    candidate=momentum*(1-discreteness)/2.
    return {'control':momentum,'discreteness':discreteness,'candidate':candidate}
