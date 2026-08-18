#!/usr/bin/env python3
"""CAPTURE — append-only EIA-930 demand/forecast vintages with receipt timestamps.

WHY THIS EXISTS. `docs/design/FEASIBILITY_ELECTRICITY_LOAD_WEATHER.md` establishes that EIA
publishes Form EIA-930 hourly actual demand (`D`) and next-day demand forecast (`DF`) free and
without a key, **but that the published archive is a mutable latest-state file, not an append-only
release-vintage archive**. EIA states plainly that balancing authorities may revise historical
submissions and that corrected values REPLACE the historical record.

The consequence is the whole point of this file: *a backtest downloaded today cannot prove what
forecast value was visible at the original decision time.* No amount of money fixes that
retroactively — the vintages were never published. Either you hold a licensed archive that
retained every original vintage, or you start capturing and wait. This is the capturing.

THE ONE DISTINCTION THIS FILE EXISTS TO ENFORCE:

    --mode backfill   Latest-state snapshot of history. Already revised, unknown vintage.
                      Written to a SEPARATE file, labelled `latest_state`, and it is NOT
                      point-in-time evidence and may never be used as a forecast vintage.
    --mode sweep      Forward vintage capture. Each observation carries the wall-clock instant we
                      received it. THIS is the point-in-time record, and it only ever grows.

Conflating those two is precisely the defect the feasibility document warns about, so they never
share a file and the mode is stamped into every row.

REVISIONS ARE THE SIGNAL, NOT NOISE. A sweep appends a row when a key is seen for the first time
OR when its value differs from the last value we recorded for that key. An unchanged value does
not append a row — instead every run writes a SWEEP RECEIPT recording what was covered, so
"we looked and nothing moved" stays provable without inflating the log.

NO DEMO_KEY FALLBACK. The prior audit run silently fell back to the public `DEMO_KEY`, was
rate-limited, and produced `source_collection_complete=false`. A missing key is a hard failure
here: a capture that quietly degrades is worse than one that stops, because the gap is invisible
later and the days cannot be recovered.

    export EIA_API_KEY=...          # free: https://www.eia.gov/opendata/register.php
    uv run python scripts/capture_eia930_vintages.py --mode sweep --days 14
    uv run python scripts/capture_eia930_vintages.py --mode backfill --start 2019-01-01
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx

_ROOT = Path(__file__).resolve().parent.parent
API: Final = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
RESPONDENTS: Final = ("PJM", "ERCO", "MISO", "ISNE")
TYPES: Final = ("D", "DF")
REQUIRED_FIELDS: Final = {"period", "respondent", "type", "value"}

OUT_DIR: Final = _ROOT / "data" / "raw" / "electricity_load_weather"
VINTAGES: Final = OUT_DIR / "eia930_vintages.jsonl"        # forward, point-in-time. Append-only.
LATEST_STATE: Final = OUT_DIR / "eia930_latest_state.jsonl"  # backfill. NOT point-in-time.
RECEIPTS: Final = OUT_DIR / "eia930_sweep_receipts.jsonl"

PAGE: Final = 5000
MAX_RETRIES: Final = 5


def canonical(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def key_of(row: dict[str, Any]) -> str:
    return f"{row['respondent']}|{row['type']}|{row['period']}"


def load_last_values(path: Path) -> dict[str, Any]:
    """Last recorded value per key, so a sweep can tell a revision from an unchanged reading."""
    last: dict[str, Any] = {}
    if not path.exists():
        return last
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # An unreadable line means the append-only log is damaged. Refuse to continue:
                # silently skipping it would let a later sweep re-append and look like a revision.
                raise SystemExit(f"ABORT: {path} has an unparseable line; the log is damaged")
            last[rec["key"]] = rec["value"]
    return last


def fetch(api_key: str, start: str, end: str) -> list[dict[str, Any]]:
    """Every page or a hard failure. Partial coverage is never returned."""
    rows: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    with httpx.Client(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "Canli Capital research research@canlicapital.com"},
    ) as client:
        while True:
            params = [
                ("api_key", api_key),
                ("frequency", "hourly"),
                ("data[0]", "value"),
                *(("facets[respondent][]", r) for r in RESPONDENTS),
                *(("facets[type][]", t) for t in TYPES),
                ("start", start),
                ("end", end),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "asc"),
                ("offset", str(offset)),
                ("length", str(PAGE)),
            ]
            for attempt in range(MAX_RETRIES):
                resp = client.get(API, params=params)
                if resp.status_code == 200:
                    break
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = float(resp.headers.get("Retry-After") or 2 ** attempt)
                    print(f"    HTTP {resp.status_code}; retry {attempt+1}/{MAX_RETRIES} in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                raise SystemExit(f"ABORT: EIA returned HTTP {resp.status_code}: {resp.text[:300]}")
            else:
                raise SystemExit(f"ABORT: EIA unavailable after {MAX_RETRIES} attempts at offset {offset}")

            body = resp.json().get("response", {})
            page = body.get("data", []) or []
            if total is None:
                total = int(body.get("total", 0))
                print(f"    EIA reports {total} rows for {start}..{end}")
            for row in page:
                missing = REQUIRED_FIELDS - set(row)
                if missing:
                    raise SystemExit(f"ABORT: row missing required fields {sorted(missing)}: {row}")
            rows.extend(page)
            offset += len(page)
            if not page or offset >= (total or 0):
                break

    if total is not None and len(rows) != total:
        # Fail closed. A short read written to an append-only log is a permanent hole.
        raise SystemExit(f"ABORT: partial coverage {len(rows)}/{total}; refusing to write a hole")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("sweep", "backfill"), required=True)
    ap.add_argument("--days", type=int, default=14, help="sweep: how many days back to re-read")
    ap.add_argument("--start", default=None, help="backfill: ISO date")
    ap.add_argument("--end", default=None)
    a = ap.parse_args()

    api_key = os.environ.get("EIA_API_KEY", "").strip()
    if not api_key or api_key == "DEMO_KEY":
        raise SystemExit(
            "ABORT: EIA_API_KEY is not set (or is DEMO_KEY).\n"
            "  A capture that quietly degrades to a rate-limited public key produces an invisible\n"
            "  gap in an append-only record, and those days cannot be recovered later.\n"
            "  Free key, ~30 seconds: https://www.eia.gov/opendata/register.php"
        )

    now = datetime.now(UTC)
    if a.mode == "sweep":
        start = (now - timedelta(days=a.days)).strftime("%Y-%m-%dT%H")
        end = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H")  # DF is next-day; reach forward
        target, mode_label = VINTAGES, "vintage"
    else:
        if not a.start:
            raise SystemExit("ABORT: --mode backfill requires --start")
        start = f"{a.start}T00"
        end = f"{a.end}T23" if a.end else now.strftime("%Y-%m-%dT%H")
        target, mode_label = LATEST_STATE, "latest_state"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  EIA-930 {a.mode.upper()} -> {target.relative_to(_ROOT)}")
    print(f"  window {start} .. {end}   respondents {RESPONDENTS}   types {TYPES}")

    rows = fetch(api_key, start, end)
    received_at = datetime.now(UTC).isoformat()

    if a.mode == "backfill":
        if LATEST_STATE.exists():
            raise SystemExit(
                f"ABORT: {LATEST_STATE.name} already exists. A backfill is a one-time revised "
                "snapshot; re-running it would overwrite a labelled baseline with a different "
                "revision state and destroy the ability to say which one you held."
            )
        with LATEST_STATE.open("w") as fh:
            for row in rows:
                fh.write(canonical({
                    "key": key_of(row), "value": row["value"], "period": row["period"],
                    "respondent": row["respondent"], "type": row["type"],
                    "received_at": received_at, "record_kind": mode_label,
                    "point_in_time": False,
                    "warning": "REVISED latest-state snapshot. NOT a forecast vintage. Never use as PIT evidence.",
                }).decode())
        appended, revised = len(rows), 0
    else:
        last = load_last_values(VINTAGES)
        appended = revised = 0
        with VINTAGES.open("a") as fh:
            for row in rows:
                k = key_of(row)
                prior = last.get(k, "__ABSENT__")
                if prior == "__ABSENT__" or prior != row["value"]:
                    fh.write(canonical({
                        "key": k, "value": row["value"], "period": row["period"],
                        "respondent": row["respondent"], "type": row["type"],
                        "received_at": received_at, "record_kind": mode_label,
                        "point_in_time": True,
                        "prior_value": None if prior == "__ABSENT__" else prior,
                        "is_revision": prior != "__ABSENT__",
                    }).decode())
                    appended += 1
                    revised += int(prior != "__ABSENT__")
                    last[k] = row["value"]

    receipt = {
        "received_at": received_at, "mode": a.mode, "window_start": start, "window_end": end,
        "respondents": list(RESPONDENTS), "types": list(TYPES),
        "rows_returned": len(rows), "rows_appended": appended, "revisions_detected": revised,
        "payload_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
    }
    with RECEIPTS.open("a") as fh:
        fh.write(canonical(receipt).decode())

    print(f"  rows {len(rows)}   appended {appended}   revisions {revised}")
    print(f"  receipt sha256 {receipt['payload_sha256'][:16]}… -> {RECEIPTS.name}")
    if a.mode == "sweep":
        print("  NOTE: this is point-in-time evidence and only grows. Run it on a schedule; the")
        print("        days you do not capture cannot be bought back later at any price.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
