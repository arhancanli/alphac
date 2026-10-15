"""Breadth lab engine: many signals, each run inside every industry as its own dollar-neutral sleeve,
net of costs, beta-hedged and scaled to the same risk; then the correlation structure and the book.

A sleeve's weights are decided at a rebalance close and earn returns from the second close after it
(one day to trade). Every rolling estimate uses data up to the day before it is applied.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.lab --mode search
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from research.breadth_lab.panel import CACHE, Panel

TARGET_VOL = 0.10
MIN_NAMES = 10
MAX_LEVERAGE = 5.0
BORROW = 0.005


@dataclass
class Ctx:
    """Shared daily inputs, computed once per panel."""

    p: Panel
    r: pd.DataFrame          # total return, NaN when not trading
    r0: pd.DataFrame         # total return with NaN as 0, for holding
    ltri: pd.DataFrame       # log total-return index
    adv: pd.DataFrame        # 63-day median dollar volume
    eligible: pd.DataFrame   # price >= 5 and adv >= 5m
    market: pd.Series        # equal-weighted return of yesterday's eligible names
    cost: pd.DataFrame       # one-way cost per name
    bucket: pd.Series        # industry per name
    month_ends: pd.DatetimeIndex
    week_ends: pd.DatetimeIndex


def context(p: Panel) -> Ctx:
    r = p.total.astype("float64")
    r0 = r.fillna(0.0)
    ltri = np.log1p(r0.clip(lower=-0.99)).cumsum()
    adv = p.dollar_volume.rolling(63, min_periods=40).median()
    eligible = (p.close >= 5.0) & (adv >= 5e6)
    market = r.where(eligible.shift(1, fill_value=False)).mean(axis=1).fillna(0.0)
    cost = pd.DataFrame(np.where(adv >= 5e7, 0.0010, np.where(adv >= 1e7, 0.0020, 0.0040)), index=r.index, columns=r.columns)
    s = pd.Series(r.index, index=r.index)
    naive = r.index.tz_localize(None)
    month_ends = pd.DatetimeIndex(s.groupby(naive.to_period("M")).last().to_numpy())
    week_ends = pd.DatetimeIndex(s.groupby(naive.to_period("W-FRI")).last().to_numpy())
    return Ctx(p, r, r0, ltri, adv, eligible, market, cost, p.meta["famaindustry"], month_ends, week_ends)


# ---- signals: a DataFrame on the daily grid, higher = long; sampled at the rebalance dates ----------

def _ret(c: Ctx, a: int, b: int) -> pd.DataFrame:
    """Return from the close a days ago to the close b days ago (a > b)."""
    return np.expm1(c.ltri.shift(b) - c.ltri.shift(a))


def _beta(c: Ctx, window: int) -> pd.DataFrame:
    m = c.market
    mr = c.r0.mul(m, axis=0).rolling(window, min_periods=window // 2).mean()
    rm = c.r0.rolling(window, min_periods=window // 2).mean()
    mm = m.rolling(window, min_periods=window // 2).mean()
    var = (m * m).rolling(window, min_periods=window // 2).mean() - mm * mm
    return (mr - rm.mul(mm, axis=0)).div(var, axis=0)


def _season(c: Ctx) -> pd.DataFrame:
    """Heston-Sadka: mean return in the coming calendar month over the previous five years."""
    monthly = (1.0 + c.r0.clip(lower=-0.99)).groupby(c.r.index.tz_localize(None).to_period("M")).prod() - 1.0
    lagged = sum(monthly.shift(12 * k - 1) for k in range(1, 6)) / 5.0  # at month M: months M+1-12k
    lagged.index = lagged.index.to_timestamp(how="end").normalize().tz_localize("UTC")
    return lagged.reindex(c.r.index, method="ffill")


SIGNALS: dict[str, tuple[Callable[[Ctx], pd.DataFrame], str]] = {
    "mom_12_1": (lambda c: _ret(c, 252, 21), "M"),
    "mom_6_1": (lambda c: _ret(c, 126, 21), "M"),
    "rev_36_12": (lambda c: -_ret(c, 756, 252), "M"),
    "rev_1m": (lambda c: -_ret(c, 21, 0), "M"),
    "rev_1w": (lambda c: -_ret(c, 5, 0), "W"),
    "hi52": (lambda c: c.ltri - c.ltri.rolling(252, min_periods=200).max(), "M"),
    "lowvol_63": (lambda c: -c.r.rolling(63, min_periods=40).std(), "M"),
    "lowbeta_252": (lambda c: -_beta(c, 252), "M"),
    "ivol_63": (lambda c: -(c.r0 - _beta(c, 252).mul(c.market, axis=0)).rolling(63, min_periods=40).std(), "M"),
    "max_21": (lambda c: -c.r.rolling(21, min_periods=15).max(), "M"),
    "skew_252": (lambda c: -c.r.rolling(252, min_periods=200).skew(), "M"),
    "vol_shock": (lambda c: np.log(c.p.dollar_volume.rolling(21, min_periods=15).mean() / c.p.dollar_volume.rolling(252, min_periods=200).mean()), "M"),
    "amihud_63": (lambda c: (c.r.abs() / c.p.dollar_volume).rolling(63, min_periods=40).mean(), "M"),
    "small_63": (lambda c: -np.log(c.adv), "M"),
    "season": (_season, "M"),
    "overnight_252": (lambda c: c.p.overnight.astype("float64").rolling(252, min_periods=200).sum(), "M"),
    "intraday_252": (lambda c: c.p.intraday.astype("float64").rolling(252, min_periods=200).sum(), "M"),
}


FUNDAMENTAL = ["gp_assets", "op_equity", "roa", "cfo_assets", "accruals", "asset_growth", "net_issuance", "book_to_market",
               "earnings_yield", "fcf_yield", "sales_yield", "capex_assets", "sue", "revenue_surprise"]
_fundamental_cache: dict[int, dict[str, pd.DataFrame]] = {}


def fundamental(name: str) -> Callable[[Ctx], pd.DataFrame]:
    def fn(c: Ctx) -> pd.DataFrame:
        if id(c) not in _fundamental_cache:
            from research.breadth_lab.fundamentals import signals
            _fundamental_cache[id(c)] = signals(c.ltri, c.p.close, c.month_ends)
        return _fundamental_cache[id(c)][name]
    return fn


SIGNALS.update({n: (fundamental(n), "M") for n in FUNDAMENTAL})
BASE = list(SIGNALS)
SMOOTH: dict[str, int] = {}
for _n in BASE:
    SIGNALS[f"{_n}_s"] = SIGNALS[_n]
    SMOOTH[f"{_n}_s"] = 4 if SIGNALS[_n][1] == "W" else 3


# ---- sleeves --------------------------------------------------------------------------------------

def smoothed(c: Ctx, w: pd.DataFrame, k: int) -> pd.DataFrame:
    """Overlapping portfolios: hold the mean of the last k rebalances' weights, back to gross 1 per industry."""
    if k <= 1:
        return w
    m = w.rolling(k, min_periods=1).mean()
    g = c.bucket.reindex(m.columns)
    gross = m.abs().T.groupby(g).transform("sum").T
    return (m / gross.where(gross > 0)).fillna(0.0)


def weights(c: Ctx, signal: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Rank-demeaned, gross-1 weights inside each industry at each rebalance date."""
    rows = []
    for d in dates:
        s = signal.loc[d].where(c.eligible.loc[d]).dropna()
        s = s[c.bucket.reindex(s.index).notna()]
        g = c.bucket.reindex(s.index)
        n = g.map(g.value_counts())
        s, g = s[n >= MIN_NAMES], g[n >= MIN_NAMES]
        if s.empty:
            rows.append(pd.Series(dtype="float64", name=d))
            continue
        x = s.groupby(g).rank(pct=True)
        x = x - x.groupby(g).transform("mean")
        x = x / x.abs().groupby(g).transform("sum")
        rows.append(x.rename(d))
    return pd.DataFrame(rows).reindex(columns=c.r.columns).fillna(0.0)


def sleeve_returns(c: Ctx, w_rebal: pd.DataFrame, before_costs: bool = False) -> pd.DataFrame:
    """Net daily return of every industry sleeve of one signal, before hedging and scaling."""
    held = w_rebal.reindex(c.r.index).ffill().fillna(0.0)
    traded = held.shift(1).fillna(0.0)     # trade at the close after the decision
    live = held.shift(2).fillna(0.0)       # earn from the next close on
    turnover = (traded - traded.shift(1).fillna(0.0)).abs()
    groups = c.bucket.reindex(c.r.columns)
    names = groups.dropna().index
    onehot = pd.get_dummies(groups.loc[names]).astype("float64")
    gross = (live[names].to_numpy() * c.r0[names].to_numpy()) @ onehot.to_numpy()
    costs = (turnover[names].to_numpy() * c.cost[names].to_numpy()) @ onehot.to_numpy()
    short = (live[names].clip(upper=0.0).abs().to_numpy()) @ onehot.to_numpy()
    charges = np.vstack([np.zeros((1, onehot.shape[1])), costs[:-1]]) + short * BORROW / 252.0
    active = (np.abs(live[names].to_numpy()) @ onehot.to_numpy()) > 0
    net = pd.DataFrame(np.where(active, gross - charges, np.nan), index=c.r.index, columns=onehot.columns)
    keep = net.columns[net.notna().any()]
    if before_costs:
        return pd.DataFrame(np.where(active, gross, np.nan), index=c.r.index, columns=onehot.columns)[keep]
    return net[keep]


def hedge_and_scale(c: Ctx, raw: pd.DataFrame, parts: bool = False):
    """Market-hedged with a trailing beta and scaled to TARGET_VOL with a trailing vol, both lagged a day."""
    m = c.market
    mm = m.rolling(252, min_periods=126).mean()
    var = (m * m).rolling(252, min_periods=126).mean() - mm * mm
    beta = (raw.mul(m, axis=0).rolling(252, min_periods=126).mean() - raw.rolling(252, min_periods=126).mean().mul(mm, axis=0)).div(var, axis=0)
    hedged = raw - beta.shift(1).mul(m, axis=0)
    vol = hedged.rolling(126, min_periods=63).std() * np.sqrt(252)
    lev = (TARGET_VOL / vol.shift(1)).clip(upper=MAX_LEVERAGE)
    if parts:
        return hedged * lev, lev, beta.shift(1)
    return hedged * lev


def stats(x: pd.Series, periods: int = 252) -> dict:
    x = x.dropna()
    if len(x) < 60 or x.std() == 0:
        return {"days": int(len(x))}
    sr = x.mean() / x.std() * np.sqrt(periods)
    eq = (1.0 + x).cumprod()
    return {"days": int(len(x)), "sharpe": round(float(sr), 3), "t": round(float(sr * np.sqrt(len(x) / periods)), 2),
            "ann_return": round(float(x.mean() * periods), 4), "ann_vol": round(float(x.std() * np.sqrt(periods)), 4),
            "max_dd": round(float((eq / eq.cummax() - 1.0).min()), 4)}


def correlation(sleeves: pd.DataFrame) -> dict:
    weekly = sleeves.resample("W-FRI").sum(min_count=3)
    cm = weekly.corr(min_periods=104).to_numpy()
    n = cm.shape[0]
    off = cm[~np.eye(n, dtype=bool)]
    rho = float(np.nanmean(off))
    filled = np.nan_to_num(cm, nan=0.0)
    np.fill_diagonal(filled, 1.0)
    eig = np.clip(np.linalg.eigvalsh(filled), 0, None)
    return {"sleeves": n, "avg_pairwise_corr": round(rho, 4), "p95_pairwise_corr": round(float(np.nanpercentile(off, 95)), 3),
            "n_eff_from_avg": round(float(n / (1 + (n - 1) * rho)), 1) if rho > -1 / max(n - 1, 1) else None,
            "n_eff_participation": round(float(eig.sum() ** 2 / (eig ** 2).sum()), 1)}


def book(sleeves: pd.DataFrame) -> pd.Series:
    raw = sleeves.mean(axis=1, skipna=True)
    vol = raw.rolling(126, min_periods=63).std() * np.sqrt(252)
    return raw * (TARGET_VOL / vol.shift(1))


def run(mode: str, only: list[str] | None = None) -> dict:
    t0 = time.time()
    c = context(Panel(mode))
    print(f"context {time.time() - t0:.0f}s: {c.r.shape[0]:,} days x {c.r.shape[1]:,} names", flush=True)
    out_dir = CACHE / mode
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, (fn, freq) in SIGNALS.items():
        if only and name not in only:
            continue
        t1 = time.time()
        sig = fn(c)
        dates = c.month_ends if freq == "M" else c.week_ends
        w = smoothed(c, weights(c, sig, dates[dates.isin(c.r.index)]), SMOOTH.get(name, 1))
        raw = sleeve_returns(c, w)
        gross_raw = sleeve_returns(c, w, before_costs=True)
        pre, lev, beta = hedge_and_scale(c, gross_raw, parts=True)
        # Net of this sleeve's own costs, at the leverage and hedge its before-cost record sets.
        scaled = (raw - beta.mul(c.market, axis=0)) * lev
        for frame, tag in ((scaled, "net"), (pre, "gross"), (lev, "lev"), (beta, "beta")):
            f = frame.copy()
            f.columns = [f"{name}|{b}" for b in f.columns]
            f.astype("float32").to_parquet(out_dir / f"{name}.{tag}.parquet")
        w.astype("float32").to_parquet(out_dir / f"{name}.weights.parquet")
        scaled.columns = [f"{name}|{b}" for b in scaled.columns]
        per = {k: v for k in scaled.columns if (v := stats(scaled[k]).get("sharpe")) is not None}
        corr = correlation(scaled)
        results[name] = {"sleeves": scaled.shape[1], "book": stats(book(scaled)), "book_before_costs": stats(book(pre)).get("sharpe"),
                         "avg_corr": corr["avg_pairwise_corr"], "n_eff": corr["n_eff_participation"], "mean_sleeve_sharpe": round(float(np.nanmean(list(per.values()))), 3),
                         "share_positive": round(float(np.mean([v > 0 for v in per.values()])), 3),
                         "turnover_per_year": round(float(w.diff().abs().sum(axis=1).mean() * (12 if freq == "M" else 52) / max(w.abs().sum(axis=1).mean(), 1e-9)), 2),
                         "seconds": round(time.time() - t1)}
        print(name, json.dumps(results[name]), flush=True)
    path = out_dir / "signals.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(results)
    path.write_text(json.dumps(merged, indent=1))
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="search", choices=["search"])
    ap.add_argument("--only", default=None, help="comma list, or 'smoothed' for every *_s variant")
    a = ap.parse_args()
    only = [n for n in SIGNALS if n.endswith("_s")] if a.only == "smoothed" else (a.only.split(",") if a.only else None)
    run(a.mode, only)
