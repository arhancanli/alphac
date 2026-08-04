#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 1: Databento cost estimate for a 1-min US equity/ETF slice.

Prices (metadata.get_cost — costs $0 to call) the LETF research set:
  TQQQ SQQQ SPXL SPXS UPRO SPXU SOXL SOXS TNA TZA TMF TMV FAS FAZ  (14 LETFs)
+ SPY QQQ IWM SOXX TLT XLF                                          (6 underlyings)
schema=ohlcv-1m over each candidate dataset's full available range (capped at 2016-01-01).

Candidate datasets:
  EQUS.MINI   — Databento US equities mini (consolidated subset), cheapest consolidated-ish
  DBEQ.BASIC  — legacy name of the same family (kept for pricing comparison if listed)
  XNAS.ITCH   — Nasdaq TotalView-ITCH (single venue, deep history 2018+)
  ARCX.PILLAR — NYSE Arca (the ETF listing venue), single venue
  XNYS.PILLAR — NYSE

SAFETY: EXECUTES a download ONLY if the account credit balance can be VERIFIED via the
API and total cost <= balance - $25 buffer. Databento's Historical API has no documented
balance endpoint; we attempt a few candidates and if none exists we PRINT THE PRICE ONLY
and exit — never risking a card charge.

Writes: artifacts/sweep/intraday_feasibility/databento_cost_report.json
        (+ data/research/intraday_probe/lake/databento_1min/ only if the guard passes)

Usage:  uv run python scripts/probe_intraday_databento_cost.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import os
from pathlib import Path

import databento as db
import httpx

_ROOT = Path(__file__).resolve().parent.parent
ART_OUT = _ROOT / "artifacts" / "sweep" / "intraday_feasibility"
LAKE_OUT = _ROOT / "data" / "research" / "intraday_probe" / "lake" / "databento_1min"
ART_OUT.mkdir(parents=True, exist_ok=True)

KEY = next(
    line.split("=", 1)[1].strip()
    for line in open(os.path.expanduser("~/.config/alphaforge/databento.env"))
    if line.startswith("DATABENTO_API_KEY")
)

SYMBOLS = [
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UPRO", "SPXU", "SOXL", "SOXS",
    "TNA", "TZA", "TMF", "TMV", "FAS", "FAZ",
    "SPY", "QQQ", "IWM", "SOXX", "TLT", "XLF",
]
CANDIDATES = ["EQUS.MINI", "DBEQ.BASIC", "XNAS.ITCH", "ARCX.PILLAR", "XNYS.PILLAR"]
FLOOR_START = "2016-01-01"
BUFFER_USD = 25.0


def try_balance() -> tuple[float | None, str]:
    """Best-effort credit-balance check. Databento documents NO balance endpoint on the
    Historical API; we try plausible ones and report honestly."""
    for ep in ("billing.get_balance", "metadata.get_balance", "account.get_balance", "user.get_balance"):
        try:
            r = httpx.get(f"https://hist.databento.com/v0/{ep}", auth=(KEY, ""), timeout=15)
            if r.status_code == 200:
                js = r.json()
                for k in ("balance", "balance_usd", "available", "credit"):
                    if isinstance(js, dict) and k in js:
                        return float(js[k]), f"verified via {ep}"
                return None, f"{ep} returned 200 but unparseable: {str(js)[:120]}"
        except Exception:  # noqa: BLE001
            continue
    return None, "no balance endpoint exists on the Historical API (404 on all candidates) — balance UNVERIFIABLE programmatically"


def main() -> int:
    client = db.Historical(KEY)
    listed = set(client.metadata.list_datasets())
    report: dict = {"probe": "databento_intraday_cost", "schema": "ohlcv-1m", "symbols": SYMBOLS,
                    "n_symbols": len(SYMBOLS), "datasets": {}}

    balance, bal_note = try_balance()
    report["credit_balance_usd"] = balance
    report["balance_note"] = bal_note
    print(f"credit balance: {balance if balance is not None else 'UNVERIFIABLE'} ({bal_note})")

    for ds in CANDIDATES:
        entry: dict = {}
        if ds not in listed:
            entry["status"] = "not listed for this account"
            report["datasets"][ds] = entry
            print(f"{ds:12s}: not listed")
            continue
        try:
            rng = client.metadata.get_dataset_range(dataset=ds)
            start = max(str(rng["start"])[:10], FLOOR_START)
            end = str(rng["end"])[:10]
            cost = client.metadata.get_cost(dataset=ds, symbols=SYMBOLS, schema="ohlcv-1m",
                                            start=start, end=end, stype_in="raw_symbol")
            size = client.metadata.get_billable_size(dataset=ds, symbols=SYMBOLS, schema="ohlcv-1m",
                                                     start=start, end=end, stype_in="raw_symbol")
            entry.update({"status": "ok", "range_start": str(rng["start"]), "range_end": str(rng["end"]),
                          "priced_window": f"{start}..{end}", "cost_usd": round(float(cost), 2),
                          "billable_gb": round(size / 1e9, 3)})
            print(f"{ds:12s}: {start}..{end}  ${cost:,.2f}  ({size/1e9:.2f} GB)")
        except Exception as e:  # noqa: BLE001
            entry["status"] = f"error: {str(e)[:160]}"
            print(f"{ds:12s}: ERROR {str(e)[:120]}")
        report["datasets"][ds] = entry

    # ---- execution guard ----
    ok = [d for d, e in report["datasets"].items() if e.get("status") == "ok"]
    best = min(ok, key=lambda d: report["datasets"][d]["cost_usd"]) if ok else None
    decision = "PRICE-ONLY"
    if best is not None:
        cost = report["datasets"][best]["cost_usd"]
        if balance is None:
            decision = f"PRICE-ONLY: balance unverifiable -> hard rule forbids executing (best={best} ${cost:,.2f})"
        elif cost <= balance - BUFFER_USD:
            decision = f"EXECUTE {best} (${cost:,.2f} <= {balance:.2f} - {BUFFER_USD:.0f})"
        else:
            decision = f"PRICE-ONLY: ${cost:,.2f} exceeds balance {balance:.2f} - {BUFFER_USD:.0f} buffer"
    report["decision"] = decision
    print(f"\nDECISION: {decision}")

    if decision.startswith("EXECUTE"):
        LAKE_OUT.mkdir(parents=True, exist_ok=True)
        ds = best
        e = report["datasets"][ds]
        start, end = e["priced_window"].split("..")
        print(f"pulling {ds} ohlcv-1m {start}..{end} ...")
        data = client.timeseries.get_range(dataset=ds, symbols=SYMBOLS, schema="ohlcv-1m",
                                           start=start, end=end, stype_in="raw_symbol")
        df = data.to_df()
        out = LAKE_OUT / f"{ds.replace('.', '_')}_ohlcv1m.parquet"
        df.to_parquet(out)
        report["pulled"] = {"dataset": ds, "rows": int(len(df)), "path": str(out)}
        print(f"  -> {out} ({len(df):,} rows)")

    (ART_OUT / "databento_cost_report.json").write_text(json.dumps(report, indent=2))
    print(f"report -> {ART_OUT / 'databento_cost_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
