#!/usr/bin/env python3
"""COLLECT — multi-venue perp funding-rate BACKFILL (CANDIDATE 3 support, 2026-07-19).

One-shot HISTORICAL backfill of funding rates for the LIVE crypto-carry sleeve's perp
universe (the 58 instruments that entered the blessed crypto_carry_wk walk-forward,
read from artifacts/walkforward/crypto_carry_wk/walkforward.json) from PUBLIC,
key-free endpoints. Research-side only: writes ONLY under data/research/** — nothing
in src/, configs/, the lake, or launchd is touched. Binance funding is NOT re-fetched
(already owned in data/lake/funding).

Venues + verified endpoint facts (probed 2026-07-19 from this network):
  bybit ........ GET https://api.bytick.com/v5/market/funding/history
                 (api.bybit.com TIMES OUT from this network; bytick is Bybit's own
                 mirror domain). category=linear, limit<=200/page, paginate DESCENDING
                 via endTime. Depth: serves 2021 history, INCLUDING delisted names
                 (LUNAUSDT, TOMOUSDT, MATICUSDT all verified non-empty). 8h intervals
                 (4h/1h on some names — interval inferred downstream from gaps).
  okx .......... GET https://www.okx.com/api/v5/public/funding-rate-history
                 instId={BASE}-USDT-SWAP, limit<=100, paginate via `after`.
                 DEPTH-CAPPED: empty beyond ~90-180 days back (verified: 90d has data,
                 180d empty). => OKX can support only the ~3-month cross-venue SPREAD
                 snapshot, NOT the 2021-2026 signal A/B. Recorded as a data finding.
  hyperliquid .. POST https://api.hyperliquid.xyz/info {"type":"fundingHistory",...}
                 HOURLY funding, <=500 rows/call, paginate ASCENDING via startTime.
                 Earliest BTC row 2023-05-12 => contributes from 2023-05 onward only.

Symbol mapping (Binance key -> venue symbol), applied mechanically:
  bybit: try the identical symbol first, then the swapped 1000-form
         (1000SHIBUSDT -> SHIB1000USDT). First non-empty candidate wins.
  okx:   strip USDT + strip a leading "1000" (unit-level quote; the funding RATE is
         a rate — comparable regardless of contract multiplier) -> {BASE}-USDT-SWAP.
  hyperliquid: strip USDT; "1000X" -> "kX" (HL's kilo-unit convention).
  A venue simply missing a name yields an empty file recorded in the manifest —
  downstream aggregation falls back to the venues that do list it.

Output layout (all NEW paths):
  data/research/multivenue_funding/{venue}/{BINANCE_SYMBOL}.parquet
      columns: instrument_key (BINANCE:PERP:X — the lake join key), venue,
               venue_symbol, ts_funding (int64 ms UTC), rate (float64)
  data/research/multivenue_funding/manifest.json  (per venue/symbol row counts,
      coverage span, misses, and the OKX depth-cap disclosure)

Resume-safe: a symbol whose parquet already exists is skipped (delete the file to
re-fetch). Retries 3x with backoff; persistent failures land in the manifest as
errors, never fabricated rows. Rates are stored EXACTLY as the venue reports them
(per-interval decimal rate, positive = longs pay shorts on all four venues).

Usage:  uv run python scripts/collect_multivenue_funding.py [--start 2021-04-01]
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / "data" / "research" / "multivenue_funding"
WF_JSON = _ROOT / "artifacts" / "walkforward" / "crypto_carry_wk" / "walkforward.json"

BYBIT_URL = "https://api.bytick.com/v5/market/funding/history"
OKX_URL = "https://www.okx.com/api/v5/public/funding-rate-history"
HL_URL = "https://api.hyperliquid.xyz/info"

SLEEP_S = 0.25          # base pacing between requests (public-endpoint politeness)
RETRIES = 3
TIMEOUT_S = 25

session = requests.Session()
session.headers["User-Agent"] = "alphaforge-research/1.0"


def _get(url: str, params: dict) -> dict | list | None:
    for attempt in range(RETRIES):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT_S)
            if r.status_code == 429:
                time.sleep(5.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001
            time.sleep(2.0 * (attempt + 1))
    return None


def _post(url: str, body: dict) -> dict | list | None:
    for attempt in range(RETRIES):
        try:
            r = session.post(url, json=body, timeout=TIMEOUT_S)
            if r.status_code == 429:
                time.sleep(5.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001
            time.sleep(2.0 * (attempt + 1))
    return None


# ---------------------------------------------------------------- symbol mapping
def bybit_candidates(binance_sym: str) -> list[str]:
    cands = [binance_sym]
    if binance_sym.startswith("1000") and binance_sym.endswith("USDT"):
        base = binance_sym[4:-4]
        cands.append(f"{base}1000USDT")
    return cands


def okx_inst_id(binance_sym: str) -> str:
    base = binance_sym[:-4]  # strip USDT
    if base.startswith("1000"):
        base = base[4:]
    return f"{base}-USDT-SWAP"


def hl_coin(binance_sym: str) -> str:
    base = binance_sym[:-4]
    if base.startswith("1000"):
        return "k" + base[4:]
    return base


# ---------------------------------------------------------------- venue fetchers
def fetch_bybit(binance_sym: str, start_ms: int, end_ms: int) -> tuple[pd.DataFrame, str]:
    """Descending endTime pagination, 200/page, stop below start_ms or empty page."""
    for sym in bybit_candidates(binance_sym):
        rows: list[tuple[int, float]] = []
        cursor = end_ms
        while True:
            j = _get(BYBIT_URL, {"category": "linear", "symbol": sym, "limit": 200, "endTime": cursor})
            time.sleep(SLEEP_S)
            if j is None or j.get("retCode") != 0:
                break
            lst = (j.get("result") or {}).get("list") or []
            if not lst:
                break
            page = [(int(x["fundingRateTimestamp"]), float(x["fundingRate"])) for x in lst]
            rows.extend(page)
            oldest = min(t for t, _ in page)
            if oldest <= start_ms or len(lst) < 200:
                break
            cursor = oldest - 1
        if rows:
            df = pd.DataFrame(rows, columns=["ts_funding", "rate"])
            df = df[df["ts_funding"] >= start_ms]
            return df, sym
    return pd.DataFrame(columns=["ts_funding", "rate"]), bybit_candidates(binance_sym)[0]


def fetch_okx(binance_sym: str, start_ms: int) -> tuple[pd.DataFrame, str]:
    """Descending `after` pagination, 100/page, until empty (server depth-caps ~90d)."""
    inst = okx_inst_id(binance_sym)
    rows: list[tuple[int, float]] = []
    after: int | None = None
    while True:
        params = {"instId": inst, "limit": 100}
        if after is not None:
            params["after"] = after
        j = _get(OKX_URL, params)
        time.sleep(SLEEP_S)
        if j is None or j.get("code") != "0":
            break
        lst = j.get("data") or []
        if not lst:
            break
        page = [(int(x["fundingTime"]), float(x.get("realizedRate") or x["fundingRate"])) for x in lst]
        rows.extend(page)
        oldest = min(t for t, _ in page)
        if oldest <= start_ms:
            break
        after = oldest
    df = pd.DataFrame(rows, columns=["ts_funding", "rate"])
    if len(df):
        df = df[df["ts_funding"] >= start_ms]
    return df, inst


def fetch_hyperliquid(binance_sym: str, start_ms: int, end_ms: int) -> tuple[pd.DataFrame, str]:
    """Ascending startTime pagination, 500 hourly rows/call."""
    coin = hl_coin(binance_sym)
    rows: list[tuple[int, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        j = _post(HL_URL, {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms})
        time.sleep(SLEEP_S)
        if not isinstance(j, list) or not j:
            break
        page = [(int(x["time"]), float(x["fundingRate"])) for x in j]
        rows.extend(page)
        newest = max(t for t, _ in page)
        if len(j) < 500 or newest <= cursor:
            break
        cursor = newest + 1
    return pd.DataFrame(rows, columns=["ts_funding", "rate"]), coin


# ---------------------------------------------------------------------- driver
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-04-01", help="backfill start date (UTC)")
    args = ap.parse_args()
    start_ms = int(datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(time.time() * 1000)

    ids = json.loads(WF_JSON.read_text())["config"]["instrument_ids"]
    symbols = [i.split(":")[-1] for i in ids]  # BINANCE:PERP:BTCUSDT -> BTCUSDT
    print(f"universe: {len(symbols)} sleeve perps; backfill {args.start} .. now")

    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "universe_source": str(WF_JSON.relative_to(_ROOT)),
        "notes": {
            "okx_depth_cap": "OKX public funding-rate-history is server-capped at roughly 3 months "
                             "(verified 90d back non-empty, 180d back empty) => OKX supports the "
                             "cross-venue spread SNAPSHOT only, not the 2021-2026 A/B panel.",
            "bybit_domain": "api.bybit.com unreachable from this network; api.bytick.com mirror used.",
            "hyperliquid_depth": "earliest funding row 2023-05-12 (hourly cadence).",
            "rate_convention": "stored raw per-interval decimal rate; positive = longs pay shorts (all venues).",
        },
        "venues": {},
    }

    fetchers = {
        "bybit": lambda s: fetch_bybit(s, start_ms, end_ms),
        "okx": lambda s: fetch_okx(s, start_ms),
        "hyperliquid": lambda s: fetch_hyperliquid(s, max(start_ms, 1682899200000), end_ms),  # 2023-05-01 floor
    }

    for venue, fetch in fetchers.items():
        vdir = OUT / venue
        vdir.mkdir(parents=True, exist_ok=True)
        vman: dict = {}
        for k, sym in enumerate(symbols):
            fp = vdir / f"{sym}.parquet"
            if fp.exists():
                n_prev = len(pd.read_parquet(fp, columns=["ts_funding"]))
                vman[sym] = {"rows": n_prev, "status": "cached"}
                continue
            t0 = time.time()
            df, venue_sym = fetch(sym)
            df = df.drop_duplicates("ts_funding").sort_values("ts_funding").reset_index(drop=True)
            df["instrument_key"] = f"BINANCE:PERP:{sym}"
            df["venue"] = venue
            df["venue_symbol"] = venue_sym
            df = df[["instrument_key", "venue", "venue_symbol", "ts_funding", "rate"]]
            df["ts_funding"] = df["ts_funding"].astype("int64")
            df["rate"] = df["rate"].astype("float64")
            df.to_parquet(fp, index=False)
            span = ""
            if len(df):
                lo = datetime.fromtimestamp(df["ts_funding"].min() / 1000, tz=timezone.utc).date()
                hi = datetime.fromtimestamp(df["ts_funding"].max() / 1000, tz=timezone.utc).date()
                span = f"{lo}..{hi}"
            vman[sym] = {"rows": int(len(df)), "venue_symbol": venue_sym, "span": span,
                         "status": "ok" if len(df) else "empty"}
            print(f"  [{venue:11s}] {k+1:2d}/{len(symbols)} {sym:16s} rows={len(df):6d} {span} ({time.time()-t0:.1f}s)")
        manifest["venues"][venue] = vman
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    n_ok = {v: sum(1 for r in m.values() if r.get("rows", 0) > 0) for v, m in manifest["venues"].items()}
    print(f"done. non-empty coverage per venue: {n_ok}")
    print(f"manifest: {OUT / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
