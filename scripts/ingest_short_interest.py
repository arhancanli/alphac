#!/usr/bin/env python3
"""INGEST — FINRA short interest (via Polygon Stocks Starter) into the research lake.

WHY THIS EXISTS
---------------
The Polygon Starter upgrade authorised an endpoint we did not previously have: bi-monthly FINRA
short interest, 2017-12-29 .. present, for the whole US tape. That is ~8.5 years of a genuinely
MECHANICAL cross-sectional variable (who is short, and how many days of volume it would take them
to cover). Every cheap daily-OHLCV idea this fund has tried has returned a null, so a new
INPUT is worth more than another rearrangement of the inputs we already had.

THE LOOKAHEAD TRAP THIS FILE EXISTS TO CLOSE
--------------------------------------------
`settlement_date` is the date the short position was MEASURED. It is NOT the date anyone could
have known it. FINRA disseminates roughly 8 business days after settlement. A backtest that acts
on settlement_date is trading on information from the future, and it will look wonderful and be
worthless. So this ingest stores an explicit ``available_from_ms`` column computed as

    settlement_date + AVAILABILITY_LAG_BDAYS business days   (conservative: 10, not 8)

and EVERY downstream user must join on ``available_from_ms``, never on ``settlement_date``. Two
extra business days of conservatism costs a sliver of edge and removes any argument about whether
the result is real. That trade is always worth making.

Bulk-by-date (one query per settlement date, paginated) rather than per-ticker: ~200 requests
instead of ~2,000, and it captures the FULL cross-section including names we do not otherwise
track — which matters, because a short-interest signal is only meaningful relative to its peers.

    uv run python scripts/ingest_short_interest.py            # incremental (resumes)
    uv run python scripts/ingest_short_interest.py --full     # re-fetch everything
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import httpx
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

OUT = Path("data/lake_shortint")
BASE = "https://api.polygon.io/stocks/v1/short-interest"
AVAILABILITY_LAG_BDAYS = 10      # FINRA disseminates ~8 bdays after settlement; 10 = conservative
PAGE = 1000
TIMEOUT = 30.0
MAX_RETRIES = 4
MAX_PAGES = 60          # 22k tickers / 1000 per page = ~23; 60 is a runaway-cursor backstop


def _key() -> str:
    k = os.environ.get("POLYGON_API_KEY")
    if not k:
        env = Path.home() / ".config" / "alphaforge" / "polygon.env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("POLYGON_API_KEY="):
                    k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        raise SystemExit("POLYGON_API_KEY not set and ~/.config/alphaforge/polygon.env has none")
    return k


def _get(client: httpx.Client, url: str, params: dict | None) -> dict:
    """GET with bounded retries. Never logs the URL — it carries the key (see the 1.5M-line leak)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = client.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(2 * attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 — one bad page must not kill a long ingest
            if attempt == MAX_RETRIES:
                print(f"    give up after {MAX_RETRIES}: {type(exc).__name__}")
                return {}
            time.sleep(1.5 * attempt)
    return {}


def settlement_dates(client: httpx.Client, key: str) -> list[str]:
    """Discover the real settlement calendar from a liquid, continuously-listed name."""
    seen: set[str] = set()
    for probe in ("AAPL", "MSFT", "SPY"):
        d = _get(client, BASE, {"ticker": probe, "limit": 1000, "apiKey": key})
        seen |= {r["settlement_date"] for r in d.get("results", []) if r.get("settlement_date")}
    return sorted(seen)


def _with_auth(url: str, key: str, limit: int = PAGE) -> str:
    """Add the key to a next_url while PRESERVING its cursor and re-asserting the page size.

    Passing httpx `params=` alongside a URL that already has a query string clobbers `limit`,
    which silently drops the page size from 1000 back to the endpoint default of 10. That is not
    an error anyone sees — it just makes a 23-page fetch into a 2,200-page one, so a full ingest
    goes from ~35 minutes to days and looks like a hang. Found by instrumenting, not by reading.
    """
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    q["apiKey"] = key
    q["limit"] = str(limit)
    return urlunparse(u._replace(query=urlencode(q)))


def fetch_date(client: httpx.Client, key: str, day: str) -> pd.DataFrame:
    rows: list[dict] = []
    data = _get(client, BASE, {"settlement_date": day, "limit": PAGE, "apiKey": key})
    pages = 0
    while True:
        rows.extend(data.get("results", []))
        nxt = data.get("next_url")
        pages += 1
        if not nxt or pages >= MAX_PAGES:
            break
        data = _get(client, _with_auth(nxt, key), None)
        if not data:
            break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("short_interest", "avg_daily_volume", "days_to_cover"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="re-fetch every settlement date")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    key = _key()
    have = {p.stem for p in OUT.glob("settlement_date=*.parquet")}

    with httpx.Client(follow_redirects=True) as client:
        days = settlement_dates(client, key)
        print(f"settlement calendar: {len(days)} dates, {days[0]} .. {days[-1]}")
        todo = days if args.full else [d for d in days if f"settlement_date={d}" not in have]
        print(f"to fetch: {len(todo)} ({len(days) - len(todo)} already on disk)\n", flush=True)

        total = 0
        for i, day in enumerate(todo, 1):
            df = fetch_date(client, key, day)
            if df.empty:
                print(f"  [{i}/{len(todo)}] {day}  EMPTY (skipped)", flush=True)
                continue
            # THE ANTI-LOOKAHEAD COLUMN. Downstream research must join on this, never on settlement.
            avail = np.busday_offset(np.datetime64(day, "D"), AVAILABILITY_LAG_BDAYS, roll="forward")
            df["settlement_ms"] = int(pd.Timestamp(day).timestamp() * 1000)
            df["available_from_ms"] = int(pd.Timestamp(str(avail)).timestamp() * 1000)
            df["availability_lag_bdays"] = AVAILABILITY_LAG_BDAYS
            df.to_parquet(OUT / f"settlement_date={day}.parquet", index=False)
            total += len(df)
            print(f"  [{i}/{len(todo)}] {day}  {len(df):>6,} rows  (available {avail})", flush=True)

    files = sorted(OUT.glob("settlement_date=*.parquet"))
    print(f"\ndone. {len(files)} date files on disk, {total:,} rows written this run")
    if files:
        s = pd.concat([pd.read_parquet(f) for f in files[-3:]])
        print(f"  most recent coverage: {s['ticker'].nunique():,} unique tickers")
        print(f"  columns: {sorted(s.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
