"""Daily OI diagnostic adapter; callers retain source provenance and gap receipts.

Funding schedules must come from an independently checked source, never inferred
from the rows under test. This module does not fetch data or run experiments.
"""
import numpy as np
import pandas as pd

SYMBOLS = {'BTCUSDT', 'ETHUSDT'}
DAY = pd.Timedelta(days=1)


def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None or pd.isna(t):
        raise ValueError('Explicit timezone required')
    return t.tz_convert('UTC')


def times(series):
    if not isinstance(series.dtype, pd.DatetimeTZDtype) or series.isna().any():
        raise ValueError('Explicit nonmissing timezone-aware timestamps required')
    return series.dt.tz_convert('UTC')


def _rows(frame, symbol, stamp, expected, numeric):
    f = frame.copy()
    if not f.symbol.eq(symbol).all():
        raise ValueError('Wrong symbol')
    f[stamp] = times(f[stamp])
    if f[stamp].duplicated().any() or set(f[stamp]) != set(expected):
        raise ValueError('Incomplete, duplicate or extra source timestamps')
    if not np.isfinite(f[numeric].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite source values')
    return f.sort_values(stamp)


def daily_record(day, symbol, oi, prices, funding, expected_settlements):
    """Validate one full source day. Invalid days raise; never repair their data."""
    d = utc(day)
    if d != d.normalize() or symbol not in SYMBOLS:
        raise ValueError('Invalid day or symbol')
    grid = pd.date_range(d, periods=288, freq='5min')
    o = _rows(oi, symbol, 'observed_at', grid, ['quantity'])
    p = _rows(prices, symbol, 'open_at', grid, ['close'])
    if (o.quantity <= 0).any() or (p.close <= 0).any():
        raise ValueError('Nonpositive source values')
    expected = [utc(t) for t in expected_settlements]
    if not expected or len(set(expected)) != len(expected) or any(not d <= t < d+DAY for t in expected):
        raise ValueError('Invalid independently supplied funding schedule')
    f = _rows(funding, symbol, 'settled_at', expected, ['rate'])
    f['available_at'] = times(f.available_at)
    p['available_at'] = times(p.available_at)
    if (f.available_at < f.settled_at).any() or (p.available_at < p.open_at+pd.Timedelta(minutes=5)).any():
        raise ValueError('Source available before event completion')
    return dict(day=d, symbol=symbol, close=float(p.close.iloc[-1]),
                oi=float(o.quantity.iloc[-1]), funding_sum=float(f.rate.sum()),
                funding_count=len(f),
                input_available_at=max(d+3*DAY, f.available_at.max(), p.available_at.max()))


def build_features(daily, symbol, first_day, last_day):
    """Preserve every calendar anchor, with NaN features for invalid windows."""
    start,end=utc(first_day),utc(last_day)
    if symbol not in SYMBOLS or start != start.normalize() or end != end.normalize() or end < start:
        raise ValueError('Invalid calendar or symbol')
    f=daily.copy()
    f['day']=times(f.day); f['input_available_at']=times(f.input_available_at)
    if not f.symbol.eq(symbol).all() or f.day.duplicated().any() or (f.day != f.day.dt.normalize()).any():
        raise ValueError('Mixed symbols or invalid daily identity')
    if (f.input_available_at < f.day+3*DAY).any():
        raise ValueError('Daily source bypasses frozen lag')
    numeric=f[['close','oi','funding_sum','funding_count']].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (f[['close','oi','funding_count']]<=0).any().any():
        raise ValueError('Invalid daily aggregate')
    if (f.funding_count % 1 != 0).any():
        raise ValueError('Funding count must be integer')
    indexed=f.set_index('day').sort_index()
    output=[]
    for d in pd.date_range(start,end,freq='D'):
        decision=d+3*DAY
        window=indexed.reindex(pd.date_range(d-28*DAY,d,freq='D'))
        rec=dict(source_day=d,symbol=symbol,decision_at=decision,
                 input_available_at=decision,eth_indicator=float(symbol=='ETHUSDT'),
                 funding_mean_21d=np.nan,momentum_7d=np.nan,momentum_28d=np.nan,
                 oi_crowding=np.nan,eligible=False,reason='missing_calendar_day')
        if window[['close','oi','funding_sum','funding_count']].isna().any().any():
            output.append(rec);continue
        latest=window.input_available_at.max()
        rec['input_available_at']=latest
        if latest>decision:
            rec['reason']='late_source';output.append(rec);continue
        funding_window=window.iloc[-21:]
        mean=float(funding_window.funding_sum.sum()/funding_window.funding_count.sum())
        growth=float(np.log(window.oi.iloc[-1]/window.oi.iloc[-8]))
        rec.update(funding_mean_21d=mean,
                   momentum_7d=float(np.log(window.close.iloc[-1]/window.close.iloc[-8])),
                   momentum_28d=float(np.log(window.close.iloc[-1]/window.close.iloc[0])),
                   oi_crowding=-float(np.sign(mean))*max(growth,0.),eligible=True,reason='eligible')
        output.append(rec)
    return pd.DataFrame(output)


def attach_mature_labels(features, hourly, as_of):
    """Explicit separate label step; never call on real data before trial reservation.

Only endpoint prices whose one-hour bars have completed by as_of are accessed.
Unavailable targets stay NaN on the original calendar.
"""
    at=utc(as_of);f=features.copy();h=hourly.copy()
    h['open_at']=times(h.open_at);h['available_at']=times(h.available_at)
    if h.duplicated(['symbol','open_at']).any() or not set(h.symbol)<=SYMBOLS:
        raise ValueError('Invalid hourly identities')
    if (h.available_at<h.open_at+pd.Timedelta(hours=1)).any():
        raise ValueError('Hourly availability before bar close')
    h=h.set_index(['symbol','open_at'])
    f['target']=np.nan
    f['label_available_at']=f.decision_at+7*DAY+pd.Timedelta(hours=1)
    for idx,row in f.iterrows():
        if not row.eligible or row.label_available_at>at:
            continue
        keys=[(row.symbol,row.decision_at),(row.symbol,row.decision_at+7*DAY)]
        if not all(key in h.index for key in keys):
            continue
        endpoints=h.loc[keys]
        maturity=endpoints.available_at.max()
        f.loc[idx,'label_available_at']=max(row.label_available_at,maturity)
        if maturity>at:
            continue
        prices=endpoints.open.to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices<=0).any():
            raise ValueError('Invalid mature label price')
        f.loc[idx,'target']=prices[1]/prices[0]-1
    return f
