#!/usr/bin/env python3
"""Bind Alpaca's HDB due-bill record to the quarantined Sharadar zero row, GET-only."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import httpx

REPO: Final[Path] = Path(__file__).resolve().parents[1]
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "hdb_dividend_vendor_resolution.json"
ENV_PATH: Final[Path] = Path.home() / ".config" / "alphaforge" / "alpaca_equity.env"
ENDPOINT: Final[str] = "https://data.alpaca.markets/v1/corporate-actions"
DOCS: Final[str] = "https://docs.alpaca.markets/us/reference/corporateactions-1"


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def fetch() -> tuple[dict[str, Any], str]:
    env = _load_env(ENV_PATH)
    headers = {
        "APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"],
    }
    params = {
        "symbols": "HDB",
        "types": "cash_dividend",
        "start": "2025-06-01",
        "end": "2025-09-30",
        "region": "all",
        "data_quality": "all",
        "limit": 100,
    }
    retrieved_at = dt.datetime.now(dt.UTC).isoformat()
    response = httpx.get(ENDPOINT, headers=headers, params=params, timeout=30.0)
    response.raise_for_status()
    return response.json(), retrieved_at


def build(response: dict[str, Any], *, retrieved_at: str) -> dict[str, Any]:
    rows = response.get("corporate_actions", {}).get("cash_dividends", [])
    hdb = [row for row in rows if row.get("symbol") == "HDB"]
    due_bill = [
        row
        for row in hdb
        if row.get("due_bill_on_date") == "2025-06-26"
        and row.get("ex_date") == "2025-08-11"
        and row.get("record_date") == "2025-06-26"
    ]
    if len(hdb) != 3 or len(due_bill) != 1:
        raise ValueError(
            f"expected three HDB cash dividends and one June-26 due-bill record; "
            f"found HDB={len(hdb)}, due_bill={len(due_bill)}"
        )
    resolved = due_bill[0]
    if (
        resolved.get("id") != "e8152c16-910e-41a5-bbc8-d2f340b177a0"
        or float(resolved.get("rate", 0.0)) <= 0.0
        or resolved.get("payable_date") != "2025-08-20"
        or resolved.get("process_date") != "2025-08-20"
    ):
        raise ValueError("Alpaca's bound HDB due-bill record changed")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-hdb-dividend-vendor-resolution.v1",
        "author": "Arhan Canli",
        "decision": "VERSIONED_ZERO_MARKER_QUARANTINE_AUTHORIZED",
        "status": "READY_FOR_VERSIONED_DATA_REPAIR_NO_AMOUNT_IMPUTATION",
        "retrieved_at": retrieved_at,
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "source": {
            "provider": "Alpaca Market Data corporate-actions API",
            "endpoint": ENDPOINT,
            "documentation": DOCS,
            "query": {
                "symbols": "HDB",
                "types": "cash_dividend",
                "start": "2025-06-01",
                "end": "2025-09-30",
                "region": "all",
                "data_quality": "all",
            },
            "credentials_published": False,
            "creation_time_guaranteed_by_provider": False,
            "provider_warning": (
                "Alpaca documents that corporate-action creation time is not guaranteed and "
                "records may be delayed by upstream receipt or processing."
            ),
        },
        "vendor_rows": sorted(hdb, key=lambda row: (str(row["ex_date"]), str(row["id"]))),
        "bound_due_bill_record": resolved,
        "resolution": {
            "sharadar_zero_row": {
                "instrument_id": "XUSE:CASH:HDBUSD",
                "source_date": "2025-06-26",
                "cash_amount": 0.0,
            },
            "matching_vendor_semantic": "due_bill_on_date",
            "actual_vendor_ex_date": "2025-08-11",
            "actual_vendor_net_cash_usd_per_ads": float(resolved["rate"]),
            "conservative_knowable_at": retrieved_at,
            "repair_action": (
                "In a new versioned lake, remove only the exact zero-cash June-26 row from the "
                "executable action set as a due-bill administrative marker. Preserve the frozen "
                "source lake and its hashes. Do not alter or replace Sharadar's separate positive "
                "August-11 dividend and do not inject Alpaca's rate into the Sharadar series."
            ),
        },
        "gates": {
            "zero_row_date_matches_vendor_due_bill_on_date": True,
            "zero_row_date_is_not_vendor_ex_date": True,
            "actual_cash_dividend_is_a_separate_positive_event": True,
            "historical_vendor_creation_time_established": False,
            "retrieval_time_is_conservative_knowable_at": True,
            "automatic_cash_amount_imputation_permitted": False,
            "original_lake_mutation_permitted": False,
            "versioned_exact_row_quarantine_permitted": True,
        },
        "claim_boundary": (
            "This GET-only vendor audit identifies the Sharadar June-26 zero row as a due-bill "
            "administrative date associated with a separate positive August-11 HDB ADS dividend. "
            "It authorizes only an explicit versioned quarantine of that exact zero row. It does "
            "not rewrite the frozen lake, backdate vendor knowledge, replace Sharadar's positive "
            "cash event, open returns, spend a hypothesis, or validate performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    response, retrieved_at = fetch()
    payload = build(response, retrieved_at=retrieved_at)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
