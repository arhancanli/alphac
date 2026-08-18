#!/usr/bin/env python3
"""Corporate-action-adjusted RETURNS for the raw equity lake. 2026-08-05.

WHY THIS EXISTS (a real defect, found in published output)
----------------------------------------------------------
``data/lake/ohlcv_1d`` stores RAW, AS-TRADED closes. It is not split- or dividend-adjusted, and
nothing in the file name says so. Verified directly:

    AAPL  2020-08-28  500.04  ->  2020-08-31  129.04     (4:1 split, -135% log return)
    NVDA  2024-06-07 1208.88  ->  2024-06-10  121.79     (10:1 split, -229% log return)
    TSLA  2022-08-24  891.29  ->  2022-08-25  296.07     (3:1 split, -110% log return)

Any probe doing ``np.log(px).diff()`` on that panel books a catastrophic fake loss on every
forward split. The production feature engine REFUSES to do this -- equity_price.py raises rather
than accept raw prices -- but standalone probe scripts bypass that guard, and two of them did.

The bias is DIRECTIONAL, not random noise, which is what makes it dangerous: forward splits happen
in high-priced mega-caps, mega-caps have enormous ADV, and any volume-scaled signal therefore
sorts them into a predictable decile. In the short-interest probe, days_to_cover = SI/ADV is tiny
for mega-caps, so every fake -75% landed in the LONG leg.

THE RULE, and the part that is easy to get wrong
------------------------------------------------
Adjust the RETURN SERIES ONLY. Never back-adjust the price LEVEL.

Back-adjusting levels would let a $3 stock that later did a 1:10 reverse split appear as $30 in
2018 and pass a price floor it never actually passed -- a look-ahead that the raw panel does NOT
have and that a careless "fix" would introduce. So price floors, ADV ranks and any other
level-based screen keep using the raw as-traded close and volume. Only the return used for P&L
is adjusted.

    r[t] = log( (close[t] + cash_dividend[t]) * split_ratio[t] ) - log( close[t-1] )

with split_ratio defaulting to 1.0 and cash_dividend to 0.0. On a 4:1 split
(close 500 -> 125, ratio 4): log(125*4) - log(500) = 0. Correct.

Using ``ex_date`` is contemporaneous, not look-ahead: on the ex-date the market has already
repriced, so a trader holding that day knows. ``available_at`` governs FORWARD knowledge of an
upcoming action, which is a different question and not what this function answers.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import numpy as np
import pandas as pd

CA_DIR = "data/lake/corporate_actions"


def load_actions(
    symbols: set[str] | None = None,
    ca_dir: str | Path = CA_DIR,
    *,
    strict: bool = False,
) -> pd.DataFrame:
    """Splits and cash dividends keyed by (symbol, ex_date)."""
    frames = []
    action_root = str(ca_dir)
    for d in os.listdir(action_root):
        if not d.startswith("instrument_id=XUSE"):
            continue
        sym = d.split(":")[-1].removesuffix("USD")
        if symbols is not None and sym not in symbols:
            continue
        for f in glob.glob(glob.escape(os.path.join(action_root, d)) + "/*/*.parquet"):
            try:
                t = pd.read_parquet(f, columns=["action_type", "ex_date", "ratio", "cash_amount"])
            except Exception as error:
                if strict:
                    raise RuntimeError(f"unreadable corporate-action partition: {f}") from error
                continue
            if t.empty:
                continue
            t["symbol"] = sym
            frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["symbol", "ex_date", "ratio", "cash_amount", "action_type"])
    a = pd.concat(frames, ignore_index=True)
    a["ex_date"] = pd.to_datetime(a["ex_date"], utc=True).dt.tz_localize(None).dt.normalize()
    return a


def adjusted_log_returns(
    px: pd.DataFrame,
    ca_dir: str | Path = CA_DIR,
    *,
    strict_actions: bool = False,
    carry_missing: bool = False,
) -> pd.DataFrame:
    """Corporate-action-adjusted log returns for a wide close panel (index=dates, cols=symbols).

    ``px`` MUST be the raw as-traded close panel. The returned frame is returns only -- the caller
    keeps using ``px`` itself for any level-based screen (price floors, ADV ranks). See module
    docstring for why that separation is not optional.
    """
    a = load_actions(set(px.columns), ca_dir=ca_dir, strict=strict_actions)
    working = px.ffill() if carry_missing else px
    ratio = pd.DataFrame(1.0, index=px.index, columns=px.columns)
    divs = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    if not a.empty:
        sp = a[a["action_type"] == "split"].dropna(subset=["ratio"])
        for sym, ex, r in zip(sp["symbol"], sp["ex_date"], sp["ratio"], strict=False):
            if sym not in ratio.columns or ex not in ratio.index or not r or r <= 0:
                continue
            effective = ex
            if carry_missing and not np.isfinite(px.at[ex, sym]):
                observed = px.index[(px.index >= ex) & px[sym].notna()]
                if observed.empty:
                    continue
                effective = observed[0]
            ratio.at[effective, sym] *= float(r)
        dv = a[a["action_type"] == "dividend"].dropna(subset=["cash_amount"])
        for sym, ex, c in zip(dv["symbol"], dv["ex_date"], dv["cash_amount"], strict=False):
            if sym in divs.columns and ex in divs.index and c and c > 0:
                divs.at[ex, sym] += float(c)
    num = (working + divs) * ratio
    return np.log(num) - np.log(working.shift(1))


def adjustment_report(px: pd.DataFrame) -> dict:
    """How much the adjustment actually changed — for disclosure, not decoration."""
    raw = np.log(px).diff()
    adj = adjusted_log_returns(px)
    d = (adj - raw).abs()
    touched = int((d > 1e-9).sum().sum())
    return {
        "cells": int(px.notna().sum().sum()),
        "cells_adjusted": touched,
        "worst_raw_log_return": float(np.nanmin(raw.to_numpy())),
        "worst_adjusted_log_return": float(np.nanmin(adj.to_numpy())),
        "n_split_events": touched,
    }
