"""Causal matched ridge screen; no data access or historical return computation."""
from dataclasses import dataclass
import numpy as np
import pandas as pd

CONTROLS = ('return_4h', 'return_24h', 'return_7d', 'rv_24h', 'log_volume_4h', 'funding_mean_21d', 'eth_indicator')
EXTRA = 'flow'
SYMBOLS = frozenset(('BTCUSDT', 'ETHUSDT'))

@dataclass(frozen=True)
class Model:
    columns: tuple
    mean: np.ndarray
    scale: np.ndarray
    intercept: float
    coefficient: np.ndarray
    training_rows: int
    last_label_available: pd.Timestamp

    def predict(self, frame):
        x = frame.loc[:, list(self.columns)].to_numpy(dtype=float)
        if not np.isfinite(x).all():
            raise ValueError('Nonfinite prediction input')
        return self.intercept + ((x-self.mean)/self.scale) @ self.coefficient


def _time(series):
    # Do not silently assign a timezone to naive source timestamps.
    if not isinstance(series.dtype, pd.DatetimeTZDtype):
        raise ValueError('Explicit timezone-aware timestamps required')
    return series.dt.tz_convert('UTC')


def fit_pair(frame, cutoff):
    """Fit both arms on identical complete, matured paired rows before annual cutoff."""
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is None:
        raise ValueError('Timezone-aware cutoff required')
    cutoff = cutoff.tz_convert('UTC')
    if cutoff.year not in (2023,2024,2025,2026) or cutoff != pd.Timestamp(year=cutoff.year, month=1, day=1, tz='UTC'):
        raise ValueError('Annual January1 cutoff required')
    required = list(CONTROLS)+( [EXTRA, 'target', 'symbol', 'decision_at', 'input_available_at', 'label_available_at'])
    f = frame.loc[:, required].copy()
    for c in ('decision_at','input_available_at','label_available_at'):
        f[c] = _time(f[c])
    if f.duplicated(['symbol','decision_at']).any() or not set(f.symbol)<=SYMBOLS:
        raise ValueError('Duplicate row or unexpected symbol')
    # Select by timing BEFORE numerical eligibility; evaluation labels cannot influence fit.
    f = f[(f.decision_at >= pd.Timestamp('2022-01-01', tz='UTC')) & (f.decision_at < cutoff) & (f.label_available_at < cutoff-pd.Timedelta(hours=24))].copy()
    if (f.input_available_at > f.decision_at).any() or (f.label_available_at != f.decision_at+pd.Timedelta(hours=4,minutes=10)).any():
        raise ValueError('Noncausal input or label')
    if (f.decision_at != f.decision_at.dt.floor('4h')+pd.Timedelta(minutes=5)).any():
        raise ValueError('Decision must be five minutes after UTC4hour boundary')
    if not np.isfinite(f[list(CONTROLS)+[EXTRA,'target']].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite eligible training input')
    groups=f.groupby('decision_at').symbol.agg(lambda x: frozenset(x))
    days=groups.groupby(groups.index.normalize()).size()
    if int(days.eq(6).sum())<252 or not all(g==SYMBOLS for g in groups):
        raise ValueError('Need >=252 complete paired UTC days')
    if not np.array_equal(f.eth_indicator.to_numpy(), (f.symbol=='ETHUSDT').astype(float).to_numpy()):
        raise ValueError('Symbol indicator mismatch')
    f=f.sort_values(['decision_at','symbol'])
    y=f.target.to_numpy(dtype=float);intercept=float(y.mean());yc=y-intercept
    def fit(columns):
        x=f[list(columns)].to_numpy(dtype=float)
        mean=x.mean(axis=0);scale=x.std(axis=0);scale=np.where(scale>0,scale,1.)
        z=(x-mean)/scale
        coefficient=np.linalg.solve(z.T@z+np.eye(z.shape[1]),z.T@yc)
        if columns[-1]==EXTRA and coefficient[-1]<0:
            coefficient[:-1]=np.linalg.solve(z[:,:-1].T@z[:,:-1]+np.eye(z.shape[1]-1),z[:,:-1].T@yc)
            coefficient[-1]=0.
        return Model(columns,mean,scale,intercept,coefficient,len(f),f.label_available_at.max())
    return fit(CONTROLS),fit(CONTROLS+(EXTRA,))
