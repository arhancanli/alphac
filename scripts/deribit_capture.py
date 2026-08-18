#!/usr/bin/env python3
"""Deribit options-surface + DVOL daily capture — build the VRP lake forward from today.

We have NO historical Deribit options surface (the lake is Binance-only), and a deployable
crypto-VRP backtest needs one. This snapshots, each day at zero cash, the ATM cohort + the
DVOL index for BTC + ETH so the surface ACCRUES from go-live. For Front-A (crypto VRP)
research once enough sample exists.

Per currency: the nearest expiry > 14 days out (the ~30d cohort), strikes within +-20% of
the index (the ATM cohort), each with mark_iv + greeks + bid/ask (the options spread that
dominates the VRP thesis) + mark_price; plus the DVOL index. PIT-stamped: every row carries
its capture ts and available_at = ts. Append-only JSONL, one snapshot file per UTC day.
"""
# ruff: noqa: E501  (long option-dict literals)
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import ccxt

# Resolve from the deployed script, not $HOME.  The VPS runs this service as root from
# /opt/alphaforge; the old HOME-derived path reported success while writing into
# /root/alphaforge, outside the lake that sync/monitoring consume.
_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "deribit"
ROOT = Path(os.environ.get("ALPHAFORGE_DERIBIT_ROOT", str(_DEFAULT_ROOT))).expanduser()
SNAP = ROOT / "snapshots"
DVOL = ROOT / "dvol"
LOAD_ATTEMPTS = 3
LOAD_BACKOFF_SECONDS = (2.0, 5.0)


def _load_markets_with_retry(exchange, *, sleep=time.sleep) -> bool:
    """Bound retries for the non-critical public metadata call; never raise into cron.

    Deribit's public endpoint has intermittently timed out before any snapshot work starts.  A
    research collector should retry transiently, then fail loudly and quickly; it must never sit
    on an execution/risk critical path or leave a traceback as its only machine-readable result.
    """
    for attempt in range(1, LOAD_ATTEMPTS + 1):
        try:
            exchange.load_markets()
            return True
        except Exception as exc:  # venue/network exceptions vary by ccxt version
            print(f"deribit load_markets attempt {attempt}/{LOAD_ATTEMPTS} failed: {exc}")
            if attempt < LOAD_ATTEMPTS:
                sleep(LOAD_BACKOFF_SECONDS[attempt - 1])
    return False


def capture() -> int:
    SNAP.mkdir(parents=True, exist_ok=True)
    DVOL.mkdir(parents=True, exist_ok=True)
    d = ccxt.deribit({"enableRateLimit": True, "timeout": 10_000})
    if not _load_markets_with_retry(d):
        print("deribit_capture: FAILED before snapshot; no file written")
        return 1
    now = int(time.time() * 1000)
    day = datetime.fromtimestamp(now / 1000, UTC).strftime("%Y-%m-%d")
    rows: list[dict] = []

    def fl(v):
        return float(v) if v not in (None, "") else None
    for cur in ("BTC", "ETH"):
        try:
            # the IMPLIED-vol DVOL index (get_volatility_index_data), NOT the realized-vol cone
            r = d.publicGetGetVolatilityIndexData({"currency": cur, "start_timestamp": now - 6 * 3_600_000,
                                                   "end_timestamp": now, "resolution": "3600"})
            data = r.get("result", {}).get("data", [])
            if data:
                row = data[-1]  # [ts, o, h, l, close]
                with (DVOL / f"{cur}.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": now, "currency": cur,
                                        "dvol": float(row[4]), "dvol_ts": int(float(row[0]))}) + "\n")
        except Exception as e:
            print(f"DVOL {cur} err: {e}")
        try:
            idx = float(d.fetch_ticker(f"{cur}/USD:{cur}")["last"])
        except Exception:
            idx = None
        opts = [m for m in d.markets.values() if m.get("base") == cur and m.get("option")]
        exps = sorted({m["expiry"] for m in opts if m.get("expiry") and m["expiry"] > now + 14 * 864e5})
        if not exps or idx is None:
            continue
        exp = exps[0]
        cohort = [m for m in opts if m["expiry"] == exp and m.get("strike") is not None
                  and abs(m["strike"] - idx) <= 0.20 * idx]
        for m in cohort:
            try:
                t = d.fetch_ticker(m["symbol"])
                info = t.get("info", {})
                g = info.get("greeks", {}) or {}
                rows.append({
                    "ts": now, "available_at": now, "currency": cur, "expiry": int(exp),
                    "strike": m["strike"], "type": "C" if m["symbol"].endswith("-C") else "P",
                    "mark_iv": fl(info.get("mark_iv")), "delta": fl(g.get("delta")),
                    "gamma": fl(g.get("gamma")), "vega": fl(g.get("vega")), "theta": fl(g.get("theta")),
                    "mark_price": t.get("markPrice"), "bid": t.get("bid"), "ask": t.get("ask"),
                    "index_price": idx,
                })
            except Exception as e:
                print(f"ticker {m['symbol']} err: {e}")
    if rows:
        with (SNAP / f"snap_{day}.jsonl").open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(f"deribit_capture: {len(rows)} option rows + DVOL for {day} -> {SNAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(capture())
