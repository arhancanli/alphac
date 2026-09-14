"""Research-only carry annualization from published settlement intervals."""
import numpy as np


def observed_carry(settlements_ms, published_ms, rates, *, decision_ms, k=21):
    """Use last k payments and their k elapsed intervals; never infer publication."""
    ts=np.asarray(settlements_ms,dtype=np.int64)
    pub=np.asarray(published_ms,dtype=np.int64)
    rate=np.asarray(rates,dtype=float)
    if ts.ndim!=1 or ts.shape!=pub.shape or ts.shape!=rate.shape or k<1:
        raise ValueError('Invalid shapes or window')
    if np.any(pub<ts) or not np.isfinite(rate).all():
        raise ValueError('Invalid publication order or funding rate')
    known=(pub<=decision_ms)&(ts<=decision_ms)
    ts,rate=ts[known],rate[known]
    order=np.argsort(ts,kind='stable');ts,rate=ts[order],rate[order]
    if len(ts)<k+1:return float('nan')
    ts,rate=ts[-k-1:],rate[-k-1:]
    gaps=np.diff(ts)/3600000
    if np.any(gaps<1-1/3600) or np.any(gaps>8+1/3600):
        return float('nan')
    return float(-rate[1:].sum()*8760/gaps.sum())
