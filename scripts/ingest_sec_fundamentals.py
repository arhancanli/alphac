#!/usr/bin/env python3
"""INGEST — point-in-time total assets from SEC EDGAR XBRL. 2026-08-04.

WHY THIS EXISTS
---------------
Sleeve #4 (the Fama-French CMA / Cooper-Gulen-Schill investment factor, eq_asset_growth =
assets_t / assets_{t-4q} - 1) needs quarterly total assets. Our Sharadar subscription lapsed and
the on-disk SF1 is frozen at 2026-06-20, so the sleeve had a validated edge and no way to be fed.

SEC EDGAR's XBRL API solves it for free, and solves it BETTER than the paid alternative:

  * Polygon's financials endpoint is entitled on our key but returns filing_date = NULL. Fiscal
    period end is NOT when the number became public, so anything built on it peeks by 25-120 days.
  * EDGAR returns a `filed` date on EVERY fact. It is the authoritative source Sharadar itself
    derives from, and it is point-in-time by construction rather than by our own bookkeeping.

THE POINT-IN-TIME RULE THIS FILE ENFORCES
-----------------------------------------
A single fiscal period is reported MANY times: once in its own 10-Q, then again as a prior-period
comparative in later filings, and again after any restatement. Those later appearances carry
later `filed` dates and sometimes RESTATED values. A backtest that takes the newest row is using
a number nobody had at the time, and one that may have been revised with hindsight.

So for each (ticker, period_end) we keep the row with the EARLIEST `filed` date — the value as
first disclosed, on the date it was first disclosed. That is the only version a trader could have
acted on. The restated value is deliberately discarded.

RATE LIMIT: SEC permits <= 10 requests/second and REQUIRES a descriptive User-Agent with contact
details. Both are honoured below; exceeding either gets the IP blocked, which would be a
self-inflicted outage on a data source we now depend on.

    uv run python scripts/ingest_sec_fundamentals.py            # incremental (resumes)
    uv run python scripts/ingest_sec_fundamentals.py --limit 50 # smoke test
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
import pandas as pd

OUT = Path("data/lake_sec/assets")
ALLOWLIST = Path("data/research/universe_allowlist_20260619.json")
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
TAG = "Assets"
# SEC requires a real contact. This is the fund's own address; do not make one up.
UA = "Canli Capital quantitative research arhancanli@icloud.com"
MIN_INTERVAL = 0.11          # ~9 req/s, under SEC's 10/s ceiling
TIMEOUT = 30.0
MAX_RETRIES = 3


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
                        follow_redirects=True, timeout=TIMEOUT)


def _get(client: httpx.Client, url: str) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = client.get(url)
            if r.status_code == 404:
                return None              # company simply does not report this tag
            if r.status_code in (429, 503):
                time.sleep(2.0 * attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001 — one bad ticker must not kill a long ingest
            if attempt == MAX_RETRIES:
                return None
            time.sleep(1.0 * attempt)
    return None


def ticker_to_cik(client: httpx.Client) -> dict[str, int]:
    d = _get(client, TICKER_MAP_URL) or {}
    return {v["ticker"].upper(): int(v["cik_str"]) for v in d.values()}


def wanted_tickers() -> list[str]:
    """The frozen validated cohort — the same universe the sleeve was measured on."""
    if not ALLOWLIST.exists():
        raise SystemExit(f"missing {ALLOWLIST}; run scripts/freeze_universe_allowlist.py first")
    ids = json.loads(ALLOWLIST.read_text())["instrument_ids"]
    return sorted({i.split(":")[-1].removesuffix("USD").upper() for i in ids})


def facts_to_rows(ticker: str, cik: int, payload: dict) -> list[dict]:
    rows: list[dict] = []
    for unit, facts in (payload.get("units") or {}).items():
        if unit != "USD":
            continue
        for f in facts:
            if not f.get("filed") or not f.get("end") or f.get("val") is None:
                continue
            rows.append({
                "ticker": ticker, "cik": cik, "period_end": f["end"], "filed": f["filed"],
                "form": f.get("form"), "fy": f.get("fy"), "fp": f.get("fp"),
                "assets": float(f["val"]),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only fetch N tickers (smoke test)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    tickers = wanted_tickers()
    if args.limit:
        tickers = tickers[: args.limit]
    done = {p.stem for p in OUT.glob("*.parquet")}
    todo = [t for t in tickers if t not in done]
    print(f"universe {len(tickers):,} tickers | already on disk {len(done):,} | to fetch {len(todo):,}")

    with _client() as client:
        cik = ticker_to_cik(client)
        print(f"SEC ticker->CIK map: {len(cik):,} entries\n", flush=True)
        hit = miss = 0
        last = 0.0
        for i, t in enumerate(todo, 1):
            c = cik.get(t)
            if c is None:
                miss += 1
                continue
            wait = MIN_INTERVAL - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            payload = _get(client, CONCEPT_URL.format(cik=c, tag=TAG))
            if not payload:
                miss += 1
                continue
            rows = facts_to_rows(t, c, payload)
            if not rows:
                miss += 1
                continue
            df = pd.DataFrame(rows)
            # THE POINT-IN-TIME COLLAPSE: value AS FIRST DISCLOSED, never the restatement.
            df = (df.sort_values(["period_end", "filed"])
                    .drop_duplicates(["period_end"], keep="first")
                    .reset_index(drop=True))
            df.to_parquet(OUT / f"{t}.parquet", index=False)
            hit += 1
            if i % 250 == 0:
                print(f"  [{i}/{len(todo)}] {t:<6} hit={hit} miss={miss}", flush=True)

    files = sorted(OUT.glob("*.parquet"))
    print(f"\ndone. {len(files):,} tickers on disk")
    if files:
        s = pd.concat([pd.read_parquet(f) for f in files[:400]])
        lag = (pd.to_datetime(s["filed"]) - pd.to_datetime(s["period_end"])).dt.days
        print(f"  sample: {len(s):,} facts over {s['ticker'].nunique()} tickers")
        print(f"  period range: {s['period_end'].min()} .. {s['period_end'].max()}")
        print(f"  first-disclosure lag: median {lag.median():.0f}d, p05 {lag.quantile(.05):.0f}d, "
              f"p95 {lag.quantile(.95):.0f}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
