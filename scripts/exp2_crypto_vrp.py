#!/usr/bin/env python3
"""Experiment #2 — crypto VRP (variance-risk-premium) signal-validity SCREEN.

SIGNAL VALIDITY ONLY. We have no historical Deribit options SURFACE, so this is a
DVOL-vs-realized PROXY, NOT a deployable straddle P&L (the proxy understates gap losses;
deribit_capture.py is accruing the real surface forward). The screen separates the boring
true fact "implied > realized on average" (a calm-regime artifact paid back in crashes)
from the only thing that earns a sleeve: "VRP timing adds a deflation-surviving,
decorrelated net return."

Pre-registered, NO knob search. Per currency BTC/ETH, daily:
  DVOL_d    = Deribit DVOL implied-vol index close / 100  (decimal annual sigma_iv)  [PIT t+1h]
  RV_fcst_d = yang_zhang(window=168, annualize) on the perp  (the registered vol_yz_168 7d RV)
  VRP_d     = DVOL_d - RV_fcst_d
  g_{d+1}   = DVOL_d^2/365 - r_{d+1}^2      (variance-swap P&L per unit vega-notional)
  s_d       = max(0, VRP_d - K_COST)        (long-only short-vol; NEVER inverted; K_COST=0.02)
  ret_{d+1} = s_d * g_{d+1}, PIT vol-normalized; cost = COST_BPS on |Δs_d| turnover
Equal-weight BTC+ETH. Expanding-window OOS after a 365d warmup (the signal has NO fit
parameters; the only PIT-fit object is the expanding vol-normalizer). Deflated Sharpe vs the
GLOBAL trial budget. The headline honesty number is SKEW/KURTOSIS: short-vol MUST be left-
skewed + fat-tailed, exactly what the DSR rightly punishes. Own ledger (measurement).
"""
# ruff: noqa: E402, E501  (sys.path bootstrap before numpy/pandas; long metric-dict literals)
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import pandas as pd

K_COST = 0.02       # VRP entry hurdle: 2 vol points annualized (pre-registered, not tuned)
COST_BPS = 10.0     # per-turn cost on |Δs| vega-notional (pre-registered)
WARMUP_DAYS = 365   # expanding-OOS warmup; nothing before this is in the OOS metrics
DVOL_DIR = Path(__file__).resolve().parent.parent / "data" / "deribit" / "dvol_index"
PERP = {"BTC": "BINANCE:PERP:BTCUSDT", "ETH": "BINANCE:PERP:ETHUSDT"}


def _perp_daily_ohlc(reader, iid, start, end, now):
    """Daily OHLC for one perp from the H1 lake (last-of-day close, day high/low)."""
    from alphaforge.core.time import Timeframe
    tbl = reader.ohlcv([iid], start=start, end=end, as_of=now, tf=Timeframe.H1).to_pydict()
    df = pd.DataFrame({"ts": tbl["ts_open"], "open": tbl["open"], "high": tbl["high"],
                       "low": tbl["low"], "close": tbl["close"]})
    df["day"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.floor("D")
    g = df.groupby("day")
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                         "low": g["low"].min(), "close": g["close"].last()})


def _dvol_daily(cur):
    df = pd.read_parquet(DVOL_DIR / f"{cur}.parquet")
    # PIT: the DVOL close of bar ts_open is known at ts_open+1h => stamp by available_at day
    df["day"] = pd.to_datetime(df["available_at"], unit="ms", utc=True).dt.floor("D")
    return df.groupby("day")["close"].last() / 100.0  # decimal annual sigma_iv


def _vrp_returns(cur, reader, start, end, now):
    """One currency's daily VRP-proxy gross return series (pre-cost, pre-sizing scale)."""
    from alphaforge.features.library.vol import yang_zhang
    ohlc = _perp_daily_ohlc(reader, PERP[cur], start, end, now)
    if ohlc.empty:
        return None
    def _col(k):
        return ohlc[[k]].rename(columns={k: "px"})
    o, h, lo, c = _col("open"), _col("high"), _col("low"), _col("close")
    # vol_yz_168 is an HOURLY estimator; on the daily grid use window 7 (7 sessions ~ 7d) annualized to daily
    rv = yang_zhang(o, h, lo, c, window=7, annualize=False).iloc[:, 0] * np.sqrt(365.0)
    dvol = _dvol_daily(cur)
    df = pd.DataFrame({"dvol": dvol, "rv": rv, "close": c.iloc[:, 0]}).dropna()
    df["r"] = np.log(df["close"]).diff()
    df["vrp"] = df["dvol"] - df["rv"]
    df["s"] = (df["vrp"] - K_COST).clip(lower=0.0)            # long-only short-vol
    df["g_next"] = df["dvol"] ** 2 / 365.0 - df["r"].shift(-1) ** 2   # variance-swap P&L for d->d+1
    df["turn"] = df["s"].diff().abs().fillna(df["s"])
    df["gross"] = df["s"] * df["g_next"] - COST_BPS * 1e-4 * df["turn"]
    # diagnostics — the BORING TRUE FACT layer (is there a premium at all? is naive-always-short awful?)
    naive = df["g_next"].dropna()  # sell 1 unit of variance every day, ignore VRP timing
    diag = {
        "mean_vrp_volpts": float(df["vrp"].mean()),                 # avg DVOL - RV (should be > 0: the premium exists)
        "frac_days_vrp_positive": float((df["vrp"] > 0).mean()),
        "naive_always_short_sharpe": float(naive.mean() / naive.std(ddof=1) * np.sqrt(365)) if naive.std(ddof=1) > 0 else float("nan"),
        "naive_always_short_skew": float(((naive - naive.mean()) ** 3).mean() / naive.std(ddof=0) ** 3),
    }
    return df["gross"].dropna(), diag


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="exp2_crypto_vrp")
    ap.add_argument("--start", default="2021-03-24")
    ap.add_argument("--end", default="2026-06-01")
    a = ap.parse_args(argv)

    from alphaforge.config.settings import load_settings
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentLog

    now = now_ms()
    run_ts = datetime.fromtimestamp(now / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path("artifacts/exp2") / run_ts
    out.mkdir(parents=True, exist_ok=True)
    settings = load_settings(None)
    reader = PITDataReader(LakePaths(settings.paths.lake_dir))
    start, end = parse_utc(f"{a.start}T00:00:00Z"), parse_utc(f"{a.end}T00:00:00Z")

    raw = {cur: _vrp_returns(cur, reader, start, end, now) for cur in ("BTC", "ETH")}
    per = {k: v[0] for k, v in raw.items() if v is not None and len(v[0]) > WARMUP_DAYS}
    diag = {k: v[1] for k, v in raw.items() if v is not None and len(v[0]) > WARMUP_DAYS}
    if not per:
        print("no VRP data")
        return 1
    # equal-weight combine on the union daily index
    combo = pd.concat(per.values(), axis=1).mean(axis=1).dropna()
    # PIT vol-normalize by the EXPANDING std (only past data), then take OOS after warmup
    exp_std = combo.expanding(min_periods=30).std().shift(1)
    norm = (combo / exp_std).replace([np.inf, -np.inf], np.nan).dropna()
    oos = norm.iloc[WARMUP_DAYS:]

    sr = float(oos.mean() / oos.std(ddof=1) * np.sqrt(365)) if oos.std(ddof=1) > 0 else float("nan")
    skew = float(((oos - oos.mean()) ** 3).mean() / oos.std(ddof=0) ** 3)
    kurt = float(((oos - oos.mean()) ** 4).mean() / oos.std(ddof=0) ** 4)  # raw (normal=3)
    led = ExperimentLog(settings.paths.var_dir / "experiments.jsonl")
    n_trials = led.n_trials() + 1
    sr_var = led.trial_sharpe_variance()
    rep = dsr_from_returns(oos, n_trials=n_trials, sr_trials_variance=sr_var, periods_per_year=365.0)

    metrics = {
        "run_ts": run_ts, "label": "SIGNAL VALIDITY ONLY — DVOL proxy understates gap losses; not a deployable P&L curve",
        "window": {"start": a.start, "end": a.end}, "currencies": list(per.keys()),
        "oos_days": len(oos),
        "standalone": {
            "net_sharpe_oos": round(sr, 3),
            "deflated_sharpe": round(float(rep.dsr), 4),
            "psr": round(float(rep.psr), 4) if hasattr(rep, "psr") else None,
            "n_trials_global": n_trials,
            "skew": round(skew, 3),
            "kurtosis_raw": round(kurt, 2),
        },
        "boring_true_fact_diagnostics": {
            cur: {k: round(v, 4) for k, v in d.items()} for cur, d in diag.items()
        },
        "decorrelation_vs_live_sleeves": "PENDING — read from exp1 carry/momentum OOS curves once exp1 finishes",
        "decision_rule": "deploy slot ONLY if deflated Sharpe clears ~0.95 AND skew is not deeply negative AND it decorrelates (calm+stress) from carry/momentum. Prior: positive raw, fails DSR, left-skewed -> publish the null.",
    }
    (out / "exp2_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics["standalone"], indent=2))
    print(f"-> {out}/exp2_metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
