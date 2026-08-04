#!/usr/bin/env python3
"""Brutal trend-strategy search for AlphaTrend — hundreds of configs, deflated honestly.

The point is NOT to find the best of N backtests (that is how you fool yourself: the luckiest of 300
tries looks great in-sample by chance alone). The point is to test hundreds and then DEFLATE by the
full N, judge everything OUT-OF-SAMPLE, and report how few survive. Three brutal gates:

  1. WALK-FORWARD: every config is fit on TRAIN (2003..2015) and scored on TEST (2015..now) it never
     saw. The honest number is the OOS Sharpe, never the in-sample one.
  2. SELECTION DEFLATION: the best in-sample Sharpe is compared to E[max of N null Sharpes] (the
     Sharpe you'd expect from pure luck after N tries). If it does not clear that bar, it is noise.
  3. PBO (probability of backtest overfitting): does the in-sample winner land below the OOS median?

Run on the clean 17-ETF lake (data/lake_mf). No look-ahead: positions on day t use signals through
t-1; costs charged on turnover.
"""
# ruff: noqa: E501, E702
from __future__ import annotations

import glob
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

LAKE = Path(os.environ.get("MF_SEARCH_LAKE", "data/lake_mf") + "/ohlcv_1d")
COST_BPS = 5.0          # per-unit-turnover cost (fee + half-spread; conservative for liquid ETFs)
TARGET_VOL = 0.10       # annualized portfolio vol target
SPLIT = "2015-01-01"    # train < SPLIT <= test
EULER = 0.5772156649


def load_closes() -> pd.DataFrame:
    """Daily adjusted closes for every instrument in the MF lake, aligned on common dates."""
    series = {}
    for d in sorted(glob.glob(str(LAKE / "instrument_id=*"))):
        sym = d.split("instrument_id=")[-1].split(":")[-1].replace("USD", "")
        files = glob.glob(d + "/**/*.parquet", recursive=True)
        if not files:
            continue
        t = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in files])
        t = t.drop_duplicates("ts_open").sort_values("ts_open")
        t["date"] = pd.to_datetime(t["ts_open"], unit="ms")
        series[sym] = t.set_index("date")["close"]
    px = pd.DataFrame(series).sort_index()
    return px.ffill().dropna(how="all")


# ---- signal families (each returns a per-market position in {-1..+1}, shifted so day t uses t-1) ----
def sig_tsmom(px, L):
    return np.sign(np.log(px / px.shift(L)))

def sig_volmom(px, L, volw):
    r = np.log(px / px.shift(1))
    return (np.log(px / px.shift(L)) / (r.rolling(volw).std() * math.sqrt(L))).clip(-2, 2)

def sig_macross(px, fast, slow):
    return np.sign(px.rolling(fast).mean() - px.rolling(slow).mean())

def sig_breakout(px, N):
    hi = px.rolling(N).max(); lo = px.rolling(N).min()
    s = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    s[px >= hi] = 1.0; s[px <= lo] = -1.0
    return s.replace(0.0, np.nan).ffill().fillna(0.0)

def sig_reversal(px, L):  # short-horizon MEAN REVERSION (the choppy-regime hypothesis)
    return -np.sign(np.log(px / px.shift(L)))

def sig_accel(px, L):  # acceleration: momentum is speeding up (2nd derivative of trend)
    m = np.log(px / px.shift(L))
    return np.sign(m - m.shift(L))

def sig_xsmom(px, L):  # CROSS-SECTIONAL relative momentum: long the strongest markets, short the weakest
    m = np.log(px / px.shift(L))
    r = m.rank(axis=1)
    n = r.max(axis=1)
    return (r.sub(n / 2.0 + 0.5, axis=0)).div(n / 2.0, axis=0)  # ~ -1..+1, cross-sectional

def sig_xsrev(px, L):  # CROSS-SECTIONAL reversal: long the laggards, short the leaders
    return -sig_xsmom(px, L)


def configs():
    out = []
    for L in (20, 40, 63, 90, 126, 189, 252, 378, 504):
        out.append((f"tsmom_{L}", lambda px, L=L: sig_tsmom(px, L)))
    for L in (63, 90, 126, 189, 252, 378):
        for vw in (20, 40, 60, 100):
            out.append((f"volmom_{L}_{vw}", lambda px, L=L, vw=vw: sig_volmom(px, L, vw)))
    for fast, slow in ((10, 50), (20, 100), (20, 200), (50, 200), (10, 100), (30, 150), (40, 200), (15, 90)):
        out.append((f"macross_{fast}_{slow}", lambda px, f=fast, s=slow: sig_macross(px, f, s)))
    for N in (20, 40, 63, 90, 126, 189, 252):
        out.append((f"breakout_{N}", lambda px, N=N: sig_breakout(px, N)))
    for L in (1, 2, 3, 5, 10, 21, 42, 63):                       # short-horizon mean reversion
        out.append((f"reversal_{L}", lambda px, L=L: sig_reversal(px, L)))
    for L in (63, 126, 252):                                     # acceleration
        out.append((f"accel_{L}", lambda px, L=L: sig_accel(px, L)))
    for L in (21, 63, 126, 252):                                 # cross-sectional relative momentum
        out.append((f"xsmom_{L}", lambda px, L=L: sig_xsmom(px, L)))
    for L in (5, 21, 63):                                        # cross-sectional reversal
        out.append((f"xsrev_{L}", lambda px, L=L: sig_xsrev(px, L)))
    return out


def backtest(px, sigfn, volw=60, rebal=5):
    """Vectorized inverse-vol, vol-targeted trend backtest. Returns daily net returns (no look-ahead)."""
    r = np.log(px / px.shift(1))
    iv = 1.0 / r.rolling(volw).std().replace(0, np.nan)         # inverse-vol weight
    sig = sigfn(px).shift(1)                                    # decide on t-1, hold on t
    raw = (sig * iv)
    gross = raw.abs().sum(axis=1).replace(0, np.nan)
    w = raw.div(gross, axis=0).fillna(0.0)                      # normalize to unit gross
    # rebalance every `rebal` days (hold weights between)
    if rebal > 1:
        keep = (np.arange(len(w)) % rebal) == 0
        w = w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)
    port = (w * r).sum(axis=1)
    # vol-target the whole series to TARGET_VOL (ex-ante on trailing 60d)
    scale = (TARGET_VOL / math.sqrt(252)) / port.rolling(60).std().replace(0, np.nan)
    scale = scale.clip(upper=3.0).shift(1).fillna(0.0)
    pnl = port * scale
    turn = (w.diff().abs().sum(axis=1) * scale).fillna(0.0)
    return (pnl - turn * COST_BPS * 1e-4).dropna()


def sharpe(x):
    x = x[x.index >= "2003-01-01"]
    return float(x.mean() / x.std() * math.sqrt(252)) if len(x) > 50 and x.std() > 0 else float("nan")


def main() -> int:
    px = load_closes()
    print(f"loaded {px.shape[1]} markets, {px.index[0].date()}..{px.index[-1].date()}\n")
    cfgs = configs()
    rows = []
    for name, fn in cfgs:
        for rebal in (1, 5, 21):
            pnl = backtest(px, fn, rebal=rebal)
            tr = pnl[pnl.index < SPLIT]; te = pnl[pnl.index >= SPLIT]
            rows.append({"cfg": f"{name}_rb{rebal}", "full": sharpe(pnl),
                         "train": sharpe(tr), "test": sharpe(te)})
    df = pd.DataFrame(rows).dropna(subset=["full"])
    N = len(df)
    print(f"=== tested {N} strategy configs (brutal walk-forward + deflation) ===\n")

    # current live config baseline: tsmom 63/126/252 blend, rb10 ~ approximate with tsmom_126 rb21
    base = df[df.cfg == "tsmom_126_rb21"]
    base_full = float(base["full"].iloc[0]) if len(base) else float("nan")
    base_test = float(base["test"].iloc[0]) if len(base) else float("nan")

    # 1) in-sample best vs selection-deflation bar
    best_is = df.loc[df["train"].idxmax()]
    sd = df["train"].std()
    emax_null = sd * ((1 - EULER) * _z(1 - 1.0 / N) + EULER * _z(1 - 1.0 / (N * math.e)))  # E[max of N nulls]
    print(f"best IN-SAMPLE (train): {best_is.cfg}  train SR {best_is['train']:.2f}  -> its OOS test SR {best_is['test']:.2f}")
    print(f"selection-deflation bar E[max of {N} null tries] = {emax_null:.2f}  (best-train must clear THIS to be skill)")
    print(f"  verdict: best train {best_is['train']:.2f} {'CLEARS' if best_is['train'] > emax_null else 'FAILS — within luck'} the deflation bar\n")

    # 2) the only honest ranking: OUT-OF-SAMPLE (test) Sharpe
    best_oos = df.loc[df["test"].idxmax()]
    beat = df[df["test"] > (base_test if not math.isnan(base_test) else 0)]
    print(f"current-config baseline (tsmom_126_rb21): full SR {base_full:.2f}, OOS test SR {base_test:.2f}")
    print(f"best OUT-OF-SAMPLE: {best_oos.cfg}  test SR {best_oos['test']:.2f}  (full {best_oos['full']:.2f})")
    print(f"configs beating the baseline OUT-OF-SAMPLE: {len(beat)}/{N}\n")

    # 3) PBO: is the in-sample winner below the OOS median? (per-config: rank correlation train vs test)
    rho = df["train"].corr(df["test"])
    is_winner_oos_rank = (df["test"] < best_is["test"]).mean()  # fraction of configs the IS-winner beats OOS
    print(f"train->test Sharpe rank correlation: {rho:+.2f}  (near 0 or negative = in-sample rankings DON'T persist)")
    print(f"PBO check: the in-sample winner sits at the {is_winner_oos_rank*100:.0f}th percentile out-of-sample "
          f"({'OVERFIT' if is_winner_oos_rank < 0.5 else 'holds up'})\n")

    print("=== distribution of OUT-OF-SAMPLE Sharpes across all configs ===")
    q = df["test"].quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    print(f"  p5 {q[0.05]:.2f} | p25 {q[0.25]:.2f} | median {q[0.5]:.2f} | p75 {q[0.75]:.2f} | p95 {q[0.95]:.2f}")
    print(f"  mean OOS Sharpe across all {N} configs: {df['test'].mean():.2f}")
    return 0


def _z(p):  # inverse standard normal CDF (Acklam approx, good to ~1e-9)
    from statistics import NormalDist
    return NormalDist().inv_cdf(min(max(p, 1e-12), 1 - 1e-12))


if __name__ == "__main__":
    raise SystemExit(main())
