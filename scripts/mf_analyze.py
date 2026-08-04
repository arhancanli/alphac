#!/usr/bin/env python3
"""Honest stat line + crash-protection evidence for a managed-futures gauntlet equity curve.

Reads artifacts/<run>/equity.parquet (ts ms + equity) and the SPY lake bars, and reports the full
profile: Sharpe / vol / maxDD / skew, correlation to SPY, sub-period stability (two halves), and the
crash-protection check — the sleeve's average return on SPY's worst 5% of days (a real diversifier
makes money, or at least doesn't bleed, when equities crash). Usage:

    mf_analyze.py artifacts/sweep/mf_rb10
"""
# ruff: noqa: E501
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ANN = np.sqrt(252)


def _stats(ret: pd.Series) -> dict:
    sd = ret.std(ddof=1)
    cum = ret.cumsum()
    return {
        "sharpe": float(ret.mean() / sd * ANN) if sd > 0 else float("nan"),
        "vol": float(sd * ANN),
        "maxdd": float((cum.cummax() - cum).max()),
        "skew": float(((ret - ret.mean()) ** 3).mean() / ret.std(ddof=0) ** 3),
    }


def main(run: str) -> int:
    out = Path(run)
    eq = pd.read_parquet(out / "equity.parquet")
    eq["date"] = pd.to_datetime(eq["ts"], unit="ms").dt.normalize()
    eqs = eq.set_index("date")["equity"].astype(float)
    ret = np.log(eqs).diff().dropna()

    spy_files = sorted((Path("data/lake_mf/ohlcv_1d/instrument_id=XUSE:CASH:SPYUSD")).glob("**/*.parquet"))
    spy = pd.concat([pd.read_parquet(f) for f in spy_files], ignore_index=True)
    spy["date"] = pd.to_datetime(spy["ts_open"], utc=True).dt.tz_localize(None).dt.normalize()
    spy_ret = np.log(spy.sort_values("date").set_index("date")["close"].astype(float)).diff()

    j = pd.concat([ret.rename("mf"), spy_ret.rename("spy")], axis=1).dropna()
    corr = float(np.corrcoef(j["mf"], j["spy"])[0, 1])
    st = _stats(ret)

    # sub-period stability
    mid = ret.index[len(ret) // 2]
    h1, h2 = ret[ret.index < mid], ret[ret.index >= mid]
    # crash-protection: MF's mean daily return on SPY's worst-5% days
    thr = j["spy"].quantile(0.05)
    crash = j[j["spy"] <= thr]
    calm = j[j["spy"] > thr]

    print(f"\n=== {run} — HONEST PROFILE ({ret.index[0].date()}..{ret.index[-1].date()}) ===")
    print(f"  net Sharpe   : {st['sharpe']:.3f}")
    print(f"  ann vol      : {st['vol']:.3f}")
    print(f"  max DD       : {st['maxdd']:.3f}")
    print(f"  skew         : {st['skew']:+.2f}")
    print(f"  corr to SPY  : {corr:+.2f}")
    print(f"  sub-period   : H1 Sharpe {_stats(h1)['sharpe']:+.2f} ({h1.index[0].date()}..{h1.index[-1].date()})  |  "
          f"H2 Sharpe {_stats(h2)['sharpe']:+.2f} ({h2.index[0].date()}..{h2.index[-1].date()})")
    print("  --- CRASH PROTECTION (the reason to hold a trend sleeve) ---")
    print(f"  mean MF return on SPY's worst-5% days : {crash['mf'].mean()*1e4:+.1f} bp/day  (n={len(crash)})")
    print(f"  mean MF return on all other days      : {calm['mf'].mean()*1e4:+.1f} bp/day")
    print(f"  => {'POSITIVE in equity crashes (true diversifier)' if crash['mf'].mean() > 0 else 'still bleeds in crashes'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/sweep/mf_rb10"))
