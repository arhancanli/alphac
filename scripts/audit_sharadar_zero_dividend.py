#!/usr/bin/env python3
"""Audit the sole non-positive Sharadar dividend without opening return data."""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Final

import duckdb

REPO: Final[Path] = Path(__file__).resolve().parent.parent
RAW_ZIP: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
LAKE_GLOB: Final[str] = str(
    REPO / "data" / "lake_sharadar" / "corporate_actions" / "**" / "*.parquet"
)
OUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_zero_dividend.json"
ISSUER_6K: Final[str] = (
    "https://www.sec.gov/Archives/edgar/data/1144967/000119312525146102/d60580dex99.htm"
)
ISSUER_20F: Final[str] = (
    "https://www.sec.gov/Archives/edgar/data/1144967/000119312525158722/d854075d20f.htm"
)
SHARADAR_DOCS: Final[str] = "https://sharadar.com/docs/actions"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _raw_invalid_rows() -> tuple[str, list[dict[str, str]]]:
    with zipfile.ZipFile(RAW_ZIP) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"expected one ACTIONS CSV, found {len(names)}")
        member = names[0]
        with archive.open(member) as raw:
            rows = csv.DictReader(line.decode("utf-8") for line in raw)
            invalid = [
                row
                for row in rows
                if row["action"] == "dividend"
                and row["value"] != ""
                and float(row["value"]) <= 0.0
            ]
    return member, invalid


def build() -> dict[str, Any]:
    member, raw_rows = _raw_invalid_rows()
    lake_rows = duckdb.connect().execute(
        """
        SELECT instrument_id, action_type, ex_date::VARCHAR, available_at::VARCHAR,
               ratio, cash_amount, ingested_at::VARCHAR, filename
        FROM read_parquet(?, filename=true, hive_partitioning=true)
        WHERE action_type = 'dividend' AND cash_amount <= 0
        ORDER BY ex_date, instrument_id
        """,
        [LAKE_GLOB],
    ).fetchall()
    hdb_raw_rows = [
        row
        for row in raw_rows
        if row["ticker"] == "HDB" and row["date"] == "2025-06-26"
    ]
    if len(raw_rows) != 11 or len(hdb_raw_rows) != 1 or len(lake_rows) != 1:
        raise RuntimeError(
            "expected 11 raw defects, one HDB raw defect, and one executable-lake defect; "
            f"found raw={len(raw_rows)}, HDB={len(hdb_raw_rows)}, lake={len(lake_rows)}"
        )
    raw = hdb_raw_rows[0]
    lake = lake_rows[0]
    if (
        raw["ticker"] != "HDB"
        or raw["date"] != "2025-06-26"
        or float(raw["value"]) != 0.0
        or lake[0] != "XUSE:CASH:HDBUSD"
        or float(lake[5]) != 0.0
    ):
        raise RuntimeError("the quarantined defect identity changed")
    lake_path = Path(str(lake[7]))
    if not lake_path.is_absolute():
        lake_path = REPO / lake_path

    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-zero-dividend-audit.v1",
        "author": "Arhan Canli",
        "decision": "QUARANTINE_REQUIRED_NO_AUTOMATIC_REPAIR",
        "status": "DATA_CORRECTION_BLOCKED_ON_EXECUTABLE_SEMANTICS",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "source_defect": {
            "raw_archive_nonpositive_dividend_rows": len(raw_rows),
            "raw_archive_nonpositive_dividend_tickers": sorted(
                row["ticker"] for row in raw_rows
            ),
            "raw_hdb_nonpositive_dividend_rows": len(hdb_raw_rows),
            "lake_nonpositive_dividend_rows": len(lake_rows),
            "raw_hdb_row": raw,
            "lake_row": {
                "instrument_id": lake[0],
                "action_type": lake[1],
                "ex_date": lake[2],
                "available_at": lake[3],
                "ratio": float(lake[4]),
                "cash_amount": float(lake[5]),
                "ingested_at": lake[6],
                "path": str(lake_path.relative_to(REPO)),
            },
        },
        "lineage": {
            "raw_archive_path": str(RAW_ZIP.relative_to(REPO)),
            "raw_archive_sha256": _sha256(RAW_ZIP),
            "raw_member": member,
            "lake_partition_sha256": _sha256(lake_path),
            "loader_path": "scripts/sharadar_load.py",
            "loader_sha256": _sha256(REPO / "scripts" / "sharadar_load.py"),
            "engine_path": "src/alphaforge/backtest/engine.py",
            "engine_sha256": _sha256(REPO / "src" / "alphaforge" / "backtest" / "engine.py"),
        },
        "external_primary_evidence": {
            "issuer_6k": {
                "url": ISSUER_6K,
                "facts": {
                    "recommended_dividend_inr_per_equity_share": 22.0,
                    "record_date": "2025-06-27",
                    "payment_on_or_after": "2025-08-11",
                },
            },
            "issuer_20f": {
                "url": ISSUER_20F,
                "facts": {"equity_shares_per_ads": 3},
            },
            "vendor_schema": {
                "url": SHARADAR_DOCS,
                "facts": {
                    "actions_value_type": "numeric",
                    "date_action_ticker_are_primary_key_fields": True,
                },
            },
        },
        "gates": {
            "raw_hdb_row_uniquely_identified": True,
            "executable_lake_row_uniquely_identified": True,
            "raw_to_lake_propagation_proven": True,
            "issuer_declared_positive_underlying_dividend": True,
            "net_usd_cash_per_ads_established_from_primary_evidence": False,
            "vendor_date_semantics_established_for_this_row": False,
            "automatic_amount_or_date_imputation_permitted": False,
        },
        "quarantine_contract": {
            "future_ingest": (
                "Reject every split or dividend whose value is non-finite or non-positive before "
                "writing the executable corporate-action lake."
            ),
            "existing_row": (
                "Preserve the raw archive and current partition by hash. Do not silently drop, "
                "move, or replace the row in an identity-bound replay."
            ),
            "unlock": (
                "Obtain an issuer/depositary or corrected-vendor record establishing the ADS "
                "ex-date, knowable-at timestamp, and net USD cash amount. Then create a new "
                "versioned corrected lake and replay environment; retain this failed attempt."
            ),
        },
        "claim_boundary": (
            "This audit proves that one of 11 vendor-originated non-positive cash-dividend rows "
            "propagated unchanged into the filtered Sharadar executable lake and that issuer "
            "filings describe a positive "
            "underlying dividend. It does not establish the executable net USD ADS amount, does "
            "not repair the row, opens no returns, and validates no performance claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
