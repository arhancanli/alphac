#!/usr/bin/env python3
"""Collect Binance POSITIONING + ORDER-FLOW history — the only data here that cannot be bought back.

WHY THIS EXISTS. Every sleeve candidate this book has tested was derived from PRICE or FUNDING, and
19 consecutive honest nulls say that space is mined out. These five endpoints are a different
information class: who is positioned how, and which side is lifting the offer. Nothing in the lake
carries that today.

*** THE REASON IT IS A COLLECTOR AND NOT A RESEARCH SCRIPT ***
Measured 2026-08-11: every one of these endpoints serves ~21 DAYS of history and returns EMPTY at
200 days back. Twenty-one days cannot support a walk-forward, and a t-statistic computed on it
would be exactly the kind of number that has been anti-predictive three times for three here. So
this deliberately makes NO claim and runs NO test. It accumulates.

What makes that worth doing anyway: this history is UNBUYABLE RETROACTIVELY. Binance does not sell
it and no vendor here carries it. A year from now the book either has twelve months of
exchange-published positioning data or it has twenty-one days, and the only thing separating those
two outcomes is whether this job was started today. That asymmetry — near-zero cost now, an asset
that cannot be reconstructed later — is the entire argument.

POINT-IN-TIME. Every row carries `available_at` = the instant we fetched it. The venue's own
`timestamp` is the observation time. Any future research MUST condition on available_at, never on
timestamp alone, or it will be reading the future exactly as this repo's own DATA_CONTRACT warns.

RUNS ON THE VPS because Frankfurt is the only location that can reach Binance (the Mac is
network-blocked; the US droplet is geo-blocked 451). It writes append-only parquet and never edits
a prior row.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

OUT = Path("/opt/alphaforge/data/lake_positioning")
FAPI = "https://fapi.binance.com"
# period=1h is the finest granularity that carries the full ~21-day window on every endpoint.
PERIOD = "1h"
# 500 is the venue maximum per call and covers ~21 days at 1h, so one call per symbol per endpoint
# fully refreshes the available window. Overlap is intentional: the writer dedupes.
LIMIT = 500
DATASETS = {
    "open_interest": "/futures/data/openInterestHist",
    "top_trader_account_ratio": "/futures/data/topLongShortAccountRatio",
    "top_trader_position_ratio": "/futures/data/topLongShortPositionRatio",
    "global_account_ratio": "/futures/data/globalLongShortAccountRatio",
    "taker_buy_sell_ratio": "/futures/data/takerlongshortRatio",
}
TOP_N = 120          # top symbols by 24h quote volume — where the positioning data is meaningful
SLEEP_S = 0.12       # ~8 req/s, far under the venue's weight limits


def _get(url: str, tries: int = 4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:                      # rate limited: back off, do not hammer
                time.sleep(2 ** i)
                continue
            return None
        except Exception:
            time.sleep(1 + i)
    return None


def universe() -> list[str]:
    """Top USDT perps by 24h quote volume. Recomputed each run so new listings enter naturally."""
    data = _get(f"{FAPI}/fapi/v1/ticker/24hr")
    if not data:
        return []
    rows = [d for d in data if d.get("symbol", "").endswith("USDT")]
    rows.sort(key=lambda d: float(d.get("quoteVolume", 0) or 0), reverse=True)
    return [d["symbol"] for d in rows[:TOP_N]]


def main() -> int:
    fetched_at = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    syms = universe()
    if not syms:
        print("  FAILED: could not fetch the 24h ticker — venue unreachable?")
        return 1
    print(f"  universe: {len(syms)} symbols  (top by 24h quote volume)")

    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    grand = 0
    for name, path in DATASETS.items():
        rows = []
        for s in syms:
            r = _get(f"{FAPI}{path}?symbol={s}&period={PERIOD}&limit={LIMIT}")
            time.sleep(SLEEP_S)
            if not isinstance(r, list):
                continue
            for x in r:
                x["symbol"] = x.get("symbol", s)
                x["available_at"] = fetched_at   # PIT: when WE could first have seen it
                rows.append(x)
        if not rows:
            print(f"  {name:26s} 0 rows (endpoint returned nothing)")
            continue
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
        # APPEND-ONLY WITH DEDUPE. Re-fetching the same 21-day window every hour is deliberate: it
        # repairs any gap left by an outage. (symbol, timestamp) is the natural key; keep the FIRST
        # available_at seen for a row, because the earliest time we could have known it is the
        # honest one and a later refetch must never make data look fresher than it was.
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        # PARTITION BY OBSERVATION DATE, not fetch date.
        # Each pull returns the venue's full ~21-day window, so naming the file after the FETCH
        # date put ~21 days of observations in every file and made consecutive files overlap almost
        # entirely: measured 2026-08-12 with only two files on disk, 128,914 rows stored 70,249
        # unique (symbol, timestamp) pairs — 1.84x, growing to ~21x by day 21. Partitioning on the
        # observation's own date puts each row in exactly one file however often it is re-fetched,
        # keeps the hourly gap-repair pull idempotent, and leaves the archive readable as a plain
        # date-partitioned dataset instead of something a reader must dedupe tree-wide first.
        obs_day = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
        span = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        written = 0
        for day_key, part in df.groupby(obs_day):
            f = d / f"{day_key}.parquet"
            if f.exists():
                part = pd.concat([pd.read_parquet(f), part], ignore_index=True)
            # keep="first" preserves the EARLIEST available_at for a row: the earliest moment we
            # could have known it is the honest one, and a later re-fetch must never make data look
            # fresher than it was.
            part = part.drop_duplicates(subset=["symbol", "timestamp"], keep="first").sort_values(
                ["symbol", "timestamp"]
            )
            part.to_parquet(f, index=False)
            written += len(part)
        print(f"  {name:26s} {written:7d} rows  {span.min():%Y-%m-%d} .. {span.max():%Y-%m-%d %H:%M}")
        grand += written
    print(f"  TOTAL rows on disk today: {grand}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
