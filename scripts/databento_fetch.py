#!/usr/bin/env python3
"""Fetch the CME futures lake from Databento (daily) for the trend + carry sleeves.

Pulls, for ~38 liquid CME futures roots over the full GLBX history (2010-06-06 onward):
  - continuous series c.0/c.1/c.2 (front 3 months) -> trend signal + carry slope, AND
  - every individual contract (parent symbology) -> clean back-adjustment + full term structure.

SAFETY: re-prices via metadata.get_cost and HARD-ABORTS if the total exceeds $100 (it should be ~$50),
so this can never quietly spend real money — the cost is covered by the $125 new-account free credit.
Raw individual contracts are the building blocks; the back-adjusted continuous + carry term structure
are built from them downstream. Key from ~/.config/alphaforge/databento.env (chmod 600).
"""
# ruff: noqa: E501
from __future__ import annotations

import os
from pathlib import Path

import databento as db

KEY = next(l.split("=", 1)[1].strip() for l in open(os.path.expanduser("~/.config/alphaforge/databento.env")) if l.startswith("DATABENTO_API_KEY"))
DS, START, END = "GLBX.MDP3", "2010-06-06", "2026-06-28"
OUT = Path("data/lake_fut_db")

ROOTS_FULL = [
    "ES", "NQ", "YM", "RTY", "EMD", "NKD",                  # equity index
    "ZT", "ZF", "ZN", "TN", "ZB", "UB", "ZQ",              # rates
    "CL", "NG", "HO", "RB",                                 # energy
    "GC", "SI", "HG", "PL", "PA",                           # metals
    "ZC", "ZS", "ZW", "ZL", "ZM", "ZO",                    # grains
    "LE", "HE", "GF",                                       # livestock
    "6E", "6J", "6B", "6A", "6C", "6S", "6N",              # FX
]
ROOTS_SAFE = [r for r in ROOTS_FULL if r not in ("EMD", "NKD", "TN", "UB", "ZQ", "ZO", "6N")]  # the 31 pre-validated


def main() -> int:
    client = db.Historical(KEY)

    def price(roots):
        cont = [f"{r}.c.{k}" for r in roots for k in (0, 1, 2)]
        par = [f"{r}.FUT" for r in roots]
        c1 = client.metadata.get_cost(dataset=DS, symbols=cont, schema="ohlcv-1d", start=START, end=END, stype_in="continuous")
        c2 = client.metadata.get_cost(dataset=DS, symbols=par, schema="ohlcv-1d", start=START, end=END, stype_in="parent")
        return c1, c2, cont, par

    try:
        c1, c2, cont, par = price(ROOTS_FULL)
        roots = ROOTS_FULL
    except Exception as e:  # an unsupported root -> fall back to the pre-validated 31
        print(f"expanded set rejected ({str(e)[:70]}); using the 31 pre-validated roots")
        c1, c2, cont, par = price(ROOTS_SAFE)
        roots = ROOTS_SAFE

    total = c1 + c2
    print(f"COST CHECK ({len(roots)} roots): continuous(c0-c2) ${c1:.2f} + all contracts ${c2:.2f} = ${total:.2f}")
    if total >= 100:
        print(f"ABORT: ${total:.2f} exceeds the $100 safety guard — nothing downloaded.")
        return 1
    print(f"under the $100 guard and the $125 free credit -> downloading (this draws from credit, $0 out of pocket)\n")

    import time

    import pandas as pd

    def fetch(symbols, stype, label, chunk):
        """Chunked + retried streaming — small batches dodge the gateway timeout; a timed-out chunk
        delivers no data so it is not billed, and retries re-pull only the missing chunk."""
        frames = []
        for i in range(0, len(symbols), chunk):
            sub = symbols[i:i + chunk]
            for att in range(4):
                try:
                    d = client.timeseries.get_range(dataset=DS, symbols=sub, schema="ohlcv-1d", start=START, end=END, stype_in=stype)
                    frames.append(d.to_df())
                    break
                except Exception as e:  # noqa: BLE001
                    if att == 3:
                        print(f"  {label}: chunk {sub[0]}..{sub[-1]} failed after retries ({str(e)[:45]})")
                    else:
                        time.sleep((att + 1) * 4)
        return pd.concat(frames) if frames else None

    OUT.mkdir(parents=True, exist_ok=True)
    print("downloading every individual contract (the core data; chunked)...")
    df2 = fetch(par, "parent", "contracts", chunk=6)
    if df2 is not None:
        df2.to_parquet(OUT / "contracts.parquet")
        print(f"  contracts: {len(df2):,} daily rows across {df2['symbol'].nunique()} contracts")

    print("downloading continuous series (convenience; chunked, best-effort)...")
    df1 = fetch(cont, "continuous", "continuous", chunk=4)
    if df1 is not None:
        df1.to_parquet(OUT / "continuous.parquet")
        print(f"  continuous: {len(df1):,} daily rows across {df1['symbol'].nunique()} series")

    print(f"\nDONE. ~${total:.2f} drawn from your free credit (guard {'PASSED' if total < 100 else 'FAILED'}). Raw lake -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
