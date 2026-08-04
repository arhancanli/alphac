#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 1: build the free IEX 1-min lake for the 6 LETF underlyings.

Pulls Alpaca (basic plan, feed=iex, $0) 1-minute bars for SPY QQQ IWM SOXX TLT XLF over the
FULL available history (empirically 2020-07-27 -> today) into per-symbol-year parquets:

    data/research/intraday_probe/lake/alpaca_1min_full/{SYM}_{YYYY}.parquet

Idempotent/resumable: existing year files are skipped (current year always refreshed).
Prints per-year session/coverage stats so lake quality is measured, not assumed.
This lake makes the JFE first->last-half-hour study and the 2020+ era of the LETF-flow
study runnable LOCALLY; pre-2020 eras still need QC cloud (see qc_bundle/).

Usage:  uv run python scripts/probe_intraday_pull_underlyings.py [SYMBOL ...]
"""
# ruff: noqa: E501
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
from probe_intraday_alpaca import get_bars  # noqa: E402  (reuses the tested paginated puller)

OUT = _ROOT / "data" / "research" / "intraday_probe" / "lake" / "alpaca_1min_full"
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["SPY", "QQQ", "IWM", "SOXX", "TLT", "XLF"]
Y0, Y1 = 2020, 2026


def year_stats(df: pd.DataFrame) -> str:
    et = df["t"].dt.tz_convert("America/New_York")
    d = df.assign(day=et.dt.date, hm=et.dt.hour * 60 + et.dt.minute)
    reg = d[(d["hm"] >= 570) & (d["hm"] < 960)]
    if reg.empty:
        return "no regular-session bars"
    per = reg.groupby("day").size()
    l30 = reg[reg["hm"] >= 930].groupby("day").size().reindex(per.index).fillna(0) / 30.0
    return (f"sessions={len(per)} bars/sess(med)={per.median():.0f} "
            f"cov(med)={per.median()/390:.0%} last30cov(med)={np.median(l30):.0%}")


def main() -> int:
    symbols = sys.argv[1:] or SYMBOLS
    for s in symbols:
        for y in range(Y0, Y1 + 1):
            f = OUT / f"{s}_{y}.parquet"
            if f.exists() and y < Y1:
                print(f"{s} {y}: exists, skip")
                continue
            df = get_bars(s, f"{y}-01-01", f"{y}-12-31T23:59:59Z")
            if df.empty:
                print(f"{s} {y}: no bars")
                continue
            df.to_parquet(f, index=False)
            print(f"{s} {y}: {len(df):6d} bars  {year_stats(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
