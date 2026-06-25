#!/usr/bin/env python3
"""Backfill the Deribit DVOL implied-vol index history (BTC + ETH) for Front-A VRP research.

The CORRECT DVOL source is Deribit public/get_volatility_index_data (ccxt:
publicGetGetVolatilityIndexData) — the implied-vol index, NOT fetch_volatility_history
(which is a trailing REALIZED-vol cone). DVOL incepts 2021-03-24 for both currencies and
spans LUNA (2022-05) and FTX (2022-11). The endpoint caps at ~721 rows/call, so we paginate
in ~28-day chunks at 1h resolution. Output: data/deribit/dvol_index/{BTC,ETH}.parquet,
PIT-stamped (available_at = bar-close = ts_open + 1h; DVOL is a close-of-bar index).
Run ONCE (then deribit_capture keeps the live tail fresh daily).
"""
# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import ccxt
import pandas as pd

OUT = Path(os.path.expanduser("~/alphaforge/data/deribit/dvol_index"))
INCEPTION_MS = int(dt.datetime(2021, 3, 24, tzinfo=dt.UTC).timestamp() * 1000)
HOUR_MS = 3_600_000
CHUNK_MS = 28 * 24 * HOUR_MS  # ~672 rows/chunk at 1h, under the ~721 cap


def backfill(cur: str, d: ccxt.deribit) -> pd.DataFrame:
    rows: dict[int, list] = {}
    start = INCEPTION_MS
    now = int(time.time() * 1000)
    while start < now:
        end = min(start + CHUNK_MS, now)
        try:
            r = d.publicGetGetVolatilityIndexData(
                {"currency": cur, "start_timestamp": start, "end_timestamp": end, "resolution": "3600"})
            data = r.get("result", {}).get("data", [])
        except Exception as e:
            print(f"  {cur} chunk {start}: err {str(e)[:80]}; retry once")
            time.sleep(1)
            try:
                data = d.publicGetGetVolatilityIndexData(
                    {"currency": cur, "start_timestamp": start, "end_timestamp": end, "resolution": "3600"}
                ).get("result", {}).get("data", [])
            except Exception:
                data = []
        for row in data:
            ts = int(float(row[0]))
            rows[ts] = [ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])]
        start = (max(rows) + HOUR_MS) if data else end  # advance past last row, else skip the gap
        time.sleep(d.rateLimit / 1000.0)
    df = pd.DataFrame(sorted(rows.values()), columns=["ts_open", "open", "high", "low", "close"])
    df["available_at"] = df["ts_open"] + HOUR_MS
    df["ingested_at"] = int(time.time() * 1000)
    return df


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d = ccxt.deribit({"enableRateLimit": True})
    for cur in ("BTC", "ETH"):
        df = backfill(cur, d)
        df.to_parquet(OUT / f"{cur}.parquet", index=False)
        if len(df):
            f = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")  # noqa: E731
            gaps = int((df["ts_open"].diff() > 2 * HOUR_MS).sum())
            print(f"{cur}: {len(df)} rows  {f(df['ts_open'].iloc[0])}..{f(df['ts_open'].iloc[-1])}  gaps>2h={gaps}  -> {OUT/(cur+'.parquet')}")
        else:
            print(f"{cur}: NO DATA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
