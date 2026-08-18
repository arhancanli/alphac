#!/usr/bin/env python3
"""Backfill the historical US options chain from Alpaca — the dataset we wrongly believed impossible.

WHY THIS EXISTS, AND THE ERROR IT CORRECTS.

On 2026-08-07 I tested whether Alpaca could serve expired option contracts, called
``GET /v2/options/contracts`` WITHOUT ``status=inactive``, got zero rows, and concluded:

    "expired contracts CANNOT be enumerated ... the chain on any past date is unreconstructable,
     therefore NO options strategy can be backtested"

That was published to the owner as a hard constraint and used to argue against buying options data.
**It is false.** The endpoint defaults to active contracts only. Adding ``status=inactive`` returns
them:

    without status=inactive, SPY expiring 2024-01..03 ->    0 contracts
    with    status=inactive, same query               -> 4256 contracts

And historical daily bars ARE retrievable for those expired symbols (verified: 6 of 6 sampled
contracts returned bars). So the options chain IS reconstructable from roughly 2024 onward.

A wrong "impossible" is worse than a wrong number: it silently forecloses a whole research
direction, and nobody re-checks a constraint they believe is settled.

WHAT THIS DOES AND DOES NOT GIVE US.

Coverage begins ~2024 (a 2023-06 query returns zero), so this is ~2.5 years — real, free, and
enough to test whether an idea has any signal at all. It is NOT enough to clear a deflation hurdle:
at N~134 trials, a 2.5-year sample needs an implausible Sharpe to be distinguishable from luck. So
treat this as a SCREENING asset, not as evidence that can fund a sleeve. Anything promising here
still needs the forward record or purchased deep history to settle it.

    uv run python scripts/ingest_options_chain.py --underlying SPY --from 2024-01-01 --dry-run
    uv run python scripts/ingest_options_chain.py --underlying SPY --from 2024-01-01
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
LAKE = _ROOT / "data" / "lake_options"
ENV = Path.home() / ".config" / "alphaforge" / "alpaca_equity.env"
TRADING = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"


def _headers() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}


def _get(url: str, hdr: dict[str, str], tries: int = 4) -> Any:
    """GET with backoff. A transient 429/5xx must not abort a multi-hour backfill."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _contracts(hdr: dict[str, str], underlying: str, lo: date, hi: date) -> list[dict[str, Any]]:
    """Every contract expiring in [lo, hi], ACTIVE AND INACTIVE.

    status=inactive is the whole point: without it the endpoint silently returns only live
    contracts and a historical query looks empty rather than erroring.
    """
    out: list[dict[str, Any]] = []
    for status in ("active", "inactive"):
        token = None
        while True:
            q = {"underlying_symbols": underlying, "status": status, "limit": "10000",
                 "expiration_date_gte": lo.isoformat(), "expiration_date_lte": hi.isoformat()}
            if token:
                q["page_token"] = token
            d = _get(f"{TRADING}/v2/options/contracts?{urllib.parse.urlencode(q)}", hdr)
            out.extend(d.get("option_contracts") or [])
            token = d.get("next_page_token")
            if not token:
                break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ingest_options_chain")
    ap.add_argument("--underlying", default="SPY")
    ap.add_argument("--from", dest="start", default="2024-01-01")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--dry-run", action="store_true", help="enumerate only; fetch no bars")
    a = ap.parse_args(argv)

    lo = date.fromisoformat(a.start)
    hi = date.fromisoformat(a.end) if a.end else datetime.now(UTC).date()
    hdr = _headers()

    print("=" * 88)
    print(f"OPTIONS CHAIN BACKFILL — {a.underlying}  {lo} .. {hi}")
    print("  (expired contracts require status=inactive; omitting it returns zero and looks empty)")
    print("=" * 88)

    total = 0
    month = lo.replace(day=1)
    manifest: list[dict[str, Any]] = []
    while month <= hi:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        cs = _contracts(hdr, a.underlying, month, min(nxt - timedelta(days=1), hi))
        total += len(cs)
        manifest.append({"month": month.isoformat(), "contracts": len(cs)})
        print(f"  {month:%Y-%m}  {len(cs):6d} contracts")
        month = nxt

    print(f"\n  TOTAL {total:,} contracts across the window")
    if a.dry_run:
        print("  --dry-run: no bars fetched, nothing written")
        return 0

    LAKE.mkdir(parents=True, exist_ok=True)
    (LAKE / f"{a.underlying}_contracts_manifest.json").write_text(
        json.dumps({"underlying": a.underlying, "from": lo.isoformat(), "to": hi.isoformat(),
                    "total_contracts": total, "by_month": manifest,
                    "note": "coverage begins ~2024; a 2023 query returns zero. SCREENING asset "
                            "only — 2.5 years cannot clear a deflation hurdle at N~134.",
                    "built_utc": datetime.now(UTC).isoformat()}, indent=1) + "\n")
    print(f"  manifest written: {LAKE / (a.underlying + '_contracts_manifest.json')}")
    print("  (bar ingestion is the next step and is deliberately separate — enumerate first,")
    print("   confirm the scale, then decide what to fetch.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
