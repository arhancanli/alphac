#!/usr/bin/env python3
"""Collect CROSS-VENUE perpetual funding + positioning — data this book has never held.

WHY THIS EXISTS. Every sleeve candidate tested here has been derived from Binance alone, because
Binance was the only venue any of our machines could reach. From Frankfurt, four more answer:
Bybit, OKX, Gate and Kraken (verified 2026-08-12, all HTTP 200). We store none of them.

`multivenue_funding` is already a recorded KILL in scripts/glassbox_export.py — but it was killed
on COST ARITHMETIC (a four-legged trade whose ~30bp round trip swallowed the spread), not on the
data being unavailable or the phenomenon being absent. Holding the data does not resurrect that
idea and must not be used to argue it back; it makes a different class of question askable at all,
and it is worth exactly nothing until there is enough history to ask one honestly.

SO THIS MAKES NO CLAIM AND RUNS NO TEST. It accumulates. The whole argument is asymmetry: venues
serve only a trailing window (Bybit ~200 rows, OKX ~100, Gate ~100 per call), so history not
captured is history that cannot be bought back later. A year from now this either holds a year of
five-venue funding or it holds a trailing week.

DESIGN, inherited wholesale from collect_positioning.py because those choices were each paid for:
  * `available_at` stamped on every row — the instant WE could first have seen it. Any future
    research must condition on it, never on the venue's own timestamp, or it reads the future.
  * partitioned by OBSERVATION date, not fetch date. Naming files after the fetch date put ~21 days
    of observations in every file and produced 1.84x duplication after two days, heading to ~21x.
  * idempotent re-fetch with dedupe on (venue, symbol, ts), keep='first' so the EARLIEST
    available_at survives — a later refetch must never make data look fresher than it was.
  * fails closed and logs loudly; a venue erroring must not take the others down.

    ./.venv/bin/python collect_venues.py
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

OUT = Path("/opt/alphaforge/data/lake_venues")
UA = {"User-Agent": "alphaforge-research/1.0"}
SLEEP_S = 0.15
TOP_N = 60  # per venue, by the venue's own liquidity ordering where available


def _get(url: str, tries: int = 3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2**i)
                continue
            return None
        except Exception:
            time.sleep(1 + i)
    return None


# ---------------------------------------------------------------- per-venue adapters
def bybit_symbols() -> list[str]:
    d = _get("https://api.bybit.com/v5/market/tickers?category=linear")
    rows = ((d or {}).get("result") or {}).get("list") or []
    rows = [r for r in rows if str(r.get("symbol", "")).endswith("USDT")]
    rows.sort(key=lambda r: float(r.get("turnover24h") or 0), reverse=True)
    return [r["symbol"] for r in rows[:TOP_N]]


def bybit_funding(sym: str) -> list[dict]:
    d = _get(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&limit=200")
    rows = ((d or {}).get("result") or {}).get("list") or []
    return [{"venue": "bybit", "symbol": sym, "ts": int(r["fundingRateTimestamp"]),
             "rate": float(r["fundingRate"])} for r in rows if r.get("fundingRateTimestamp")]


def okx_symbols() -> list[str]:
    d = _get("https://www.okx.com/api/v5/market/tickers?instType=SWAP")
    rows = [r for r in (d or {}).get("data") or [] if str(r.get("instId", "")).endswith("-USDT-SWAP")]
    rows.sort(key=lambda r: float(r.get("volCcy24h") or 0), reverse=True)
    return [r["instId"] for r in rows[:TOP_N]]


def okx_funding(sym: str) -> list[dict]:
    d = _get(f"https://www.okx.com/api/v5/public/funding-rate-history?instId={sym}&limit=100")
    return [{"venue": "okx", "symbol": sym, "ts": int(r["fundingTime"]),
             "rate": float(r["fundingRate"])} for r in (d or {}).get("data") or []]


def gate_symbols() -> list[str]:
    d = _get("https://api.gateio.ws/api/v4/futures/usdt/contracts")
    rows = [r for r in (d or []) if isinstance(r, dict)]
    rows.sort(key=lambda r: float(r.get("trade_size") or 0), reverse=True)
    return [r["name"] for r in rows[:TOP_N] if r.get("name")]


def gate_funding(sym: str) -> list[dict]:
    d = _get(f"https://api.gateio.ws/api/v4/futures/usdt/funding_rate?contract={sym}&limit=100")
    return [{"venue": "gate", "symbol": sym, "ts": int(r["t"]) * 1000, "rate": float(r["r"])}
            for r in (d or []) if isinstance(r, dict) and r.get("t") is not None]


def kraken_all_funding() -> list[dict]:
    """Kraken serves a very deep single-call history (~1MB), so it needs no per-symbol loop."""
    out: list[dict] = []
    ins = _get("https://futures.kraken.com/derivatives/api/v3/instruments")
    syms = [i["symbol"] for i in (ins or {}).get("instruments", [])
            if i.get("tradeable") and str(i.get("symbol", "")).startswith("PF_")][:TOP_N]
    for s in syms:
        d = _get(f"https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol={s}")
        for r in (d or {}).get("rates", []):
            ts = r.get("timestamp")
            rate = r.get("relativeFundingRate")
            if ts is None or rate is None:
                continue
            out.append({"venue": "kraken", "symbol": s,
                        "ts": int(pd.Timestamp(ts).timestamp() * 1000), "rate": float(rate)})
        time.sleep(SLEEP_S)
    return out


def okx_long_short() -> list[dict]:
    """OKX publishes a long/short ACCOUNT ratio — positioning, not price. Same class as the
    Binance top-trader spread, and a second venue's view of the same behaviour."""
    out: list[dict] = []
    for ccy in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        d = _get(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=1H")
        for row in (d or {}).get("data") or []:
            if len(row) >= 2:
                out.append({"venue": "okx", "symbol": ccy, "ts": int(row[0]),
                            "long_short_ratio": float(row[1])})
        time.sleep(SLEEP_S)
    return out


def write_partitioned(name: str, rows: list[dict], keys: list[str], fetched_at: int) -> int:
    """Append rows into OBSERVATION-date partitions, deduped, earliest available_at winning."""
    if not rows:
        print(f"  {name:22s} 0 rows")
        return 0
    df = pd.DataFrame(rows)
    df["available_at"] = fetched_at
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("int64")
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    obs = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    written = 0
    for day, part in df.groupby(obs):
        f = d / f"{day}.parquet"
        if f.exists():
            part = pd.concat([pd.read_parquet(f), part], ignore_index=True)
        part = part.drop_duplicates(subset=keys, keep="first").sort_values(keys)
        part.to_parquet(f, index=False)
        written += len(part)
    span = pd.to_datetime(df["ts"], unit="ms", utc=True)
    print(f"  {name:22s} {written:7d} rows on disk  fetched {len(df):6d}  "
          f"{span.min():%Y-%m-%d} .. {span.max():%Y-%m-%d}")
    return written


def main() -> int:
    fetched_at = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    print(f"=== cross-venue collect {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} ===")
    total = 0

    for venue, syms_fn, fund_fn in (
        ("bybit", bybit_symbols, bybit_funding),
        ("okx", okx_symbols, okx_funding),
        ("gate", gate_symbols, gate_funding),
    ):
        try:
            syms = syms_fn()
            rows: list[dict] = []
            for s in syms:
                rows.extend(fund_fn(s))
                time.sleep(SLEEP_S)
            total += write_partitioned(f"funding_{venue}", rows, ["venue", "symbol", "ts"], fetched_at)
        except Exception as e:  # one venue failing must never take the others down
            print(f"  funding_{venue:15s} FAILED: {type(e).__name__}: {str(e)[:70]}")

    try:
        total += write_partitioned("funding_kraken", kraken_all_funding(),
                                   ["venue", "symbol", "ts"], fetched_at)
    except Exception as e:
        print(f"  funding_kraken         FAILED: {type(e).__name__}: {str(e)[:70]}")

    try:
        total += write_partitioned("positioning_okx", okx_long_short(),
                                   ["venue", "symbol", "ts"], fetched_at)
    except Exception as e:
        print(f"  positioning_okx        FAILED: {type(e).__name__}: {str(e)[:70]}")

    print(f"  TOTAL rows on disk: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
