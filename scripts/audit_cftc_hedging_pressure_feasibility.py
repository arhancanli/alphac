#!/usr/bin/env python3
"""Audit CFTC COT metadata without loading positions, prices, or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

DATASET_ID: Final = "72hh-3qpy"
API: Final = f"https://publicreporting.cftc.gov/resource/{DATASET_ID}.json"
METADATA_API: Final = f"https://publicreporting.cftc.gov/api/views/{DATASET_ID}"
RAW: Final = Path("data/raw/cftc_hedging_pressure/disaggregated_futures_metadata.json")
OUT_DIR: Final = Path("artifacts/feasibility/cftc_hedging_pressure")
PAGE_SIZE: Final = 50_000
FIELDS: Final = [
    "id",
    "market_and_exchange_names",
    "report_date_as_yyyy_mm_dd",
    "yyyy_report_week_ww",
    "contract_market_name",
    "cftc_contract_market_code",
    "cftc_market_code",
    "cftc_region_code",
    "cftc_commodity_code",
    "commodity_name",
    "contract_units",
    "cftc_subgroup_code",
    "commodity",
    "commodity_subgroup_name",
    "commodity_group_name",
]
SAFE_EVENT_FIELDS: Final = [
    "event_identity",
    "report_date",
    "conservative_default_available_date",
    "release_timestamp_verified",
    "report_week",
    "market_and_exchange_name",
    "contract_market_name",
    "contract_market_code",
    "market_code",
    "region_code",
    "commodity_code",
    "commodity_name",
    "contract_units",
    "commodity_subgroup_code",
    "commodity_subgroup_name",
    "commodity_group_name",
    "source_url",
]
MIN_ROWS: Final = 100_000
MIN_YEARS: Final = 15
MIN_COMPLETENESS: Final = 0.99
MIN_TUESDAY_RATE: Final = 0.98
MIN_RELEASE_LINEAGE: Final = 0.95


def canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_payload() -> dict[str, Any]:
    headers = {"User-Agent": "Canli Capital research research@canlicapital.com"}
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True, headers=headers) as client:
        metadata_response = client.get(METADATA_API)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        offset = 0
        while True:
            response = client.get(
                API,
                params={
                    "$select": ",".join(FIELDS),
                    "$order": "report_date_as_yyyy_mm_dd,id",
                    "$limit": PAGE_SIZE,
                    "$offset": offset,
                },
            )
            response.raise_for_status()
            page = response.json()
            records.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return {
        "dataset": {
            "id": metadata.get("id"),
            "name": metadata.get("name"),
            "rows_updated_at": metadata.get("rowsUpdatedAt"),
            "metadata_updated_at": metadata.get("metadataUpdatedAt"),
        },
        "data": records,
    }


def nullable(value: Any) -> Any:
    return None if value in (None, "", "null") else value


def build_manifest(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        report_date = pd.to_datetime(
            nullable(record.get("report_date_as_yyyy_mm_dd")), errors="coerce"
        )
        rows.append(
            {
                "event_identity": nullable(record.get("id")),
                "report_date": report_date,
                # CFTC says Tuesday data are generally released Friday, but also says
                # complete historical release dates do not exist. Monday is only a
                # conservative default for a future preregistration, never verified PIT lineage.
                "conservative_default_available_date": report_date + pd.Timedelta(days=6),
                "release_timestamp_verified": False,
                "report_week": nullable(record.get("yyyy_report_week_ww")),
                "market_and_exchange_name": nullable(
                    record.get("market_and_exchange_names")
                ),
                "contract_market_name": nullable(record.get("contract_market_name")),
                "contract_market_code": nullable(
                    record.get("cftc_contract_market_code")
                ),
                "market_code": nullable(record.get("cftc_market_code")),
                "region_code": nullable(record.get("cftc_region_code")),
                "commodity_code": nullable(record.get("cftc_commodity_code")),
                "commodity_name": nullable(
                    record.get("commodity_name") or record.get("commodity")
                ),
                "contract_units": nullable(record.get("contract_units")),
                "commodity_subgroup_code": nullable(record.get("cftc_subgroup_code")),
                "commodity_subgroup_name": nullable(
                    record.get("commodity_subgroup_name")
                ),
                "commodity_group_name": nullable(record.get("commodity_group_name")),
                "source_url": API,
            }
        )
    return (
        pd.DataFrame(rows, columns=SAFE_EVENT_FIELDS)
        .sort_values(["report_date", "event_identity"], na_position="last")
        .reset_index(drop=True)
    )


def summarize(frame: pd.DataFrame, raw_sha256: str) -> dict[str, Any]:
    rows = len(frame)
    core_fields = [
        "event_identity",
        "report_date",
        "contract_market_code",
        "contract_market_name",
        "commodity_code",
        "commodity_name",
        "commodity_group_name",
    ]
    completeness = {
        field: float(frame[field].notna().mean()) if rows else 0.0 for field in core_fields
    }
    unique_identity_rate = (
        float(frame["event_identity"].nunique(dropna=True) / rows) if rows else 0.0
    )
    tuesday_rate = float(frame["report_date"].dt.dayofweek.eq(1).mean()) if rows else 0.0
    release_lineage_rate = (
        float(frame["release_timestamp_verified"].mean()) if rows else 0.0
    )
    years = int(frame["report_date"].dt.year.nunique()) if rows else 0
    markets = int(frame["contract_market_code"].nunique(dropna=True)) if rows else 0
    names_per_code = frame.groupby("contract_market_code")["contract_market_name"].nunique()
    stable_market_code_rate = (
        float(names_per_code.eq(1).mean()) if len(names_per_code) else 0.0
    )
    gates = {
        "minimum_metadata_rows": rows >= MIN_ROWS,
        "minimum_history_years": years >= MIN_YEARS,
        "core_field_completeness": min(completeness.values(), default=0.0)
        >= MIN_COMPLETENESS,
        "unique_event_identity": unique_identity_rate == 1.0,
        "report_date_is_tuesday": tuesday_rate >= MIN_TUESDAY_RATE,
        "exact_historical_release_lineage": release_lineage_rate >= MIN_RELEASE_LINEAGE,
        # A tradable-map file must be separately reviewed and sealed before returns.
        "fixed_tradable_contract_mapping": False,
    }
    decision = "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED"
    first_date = frame["report_date"].min()
    last_date = frame["report_date"].max()
    return {
        "schema": "canli.feasibility.cftc-hedging-pressure.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_metadata_only_no_positions_no_prices_no_returns",
        "dataset_id": DATASET_ID,
        "source_url": API,
        "metadata_rows": rows,
        "raw_sha256": raw_sha256,
        "first_report_date": first_date.date().isoformat() if pd.notna(first_date) else None,
        "last_report_date": last_date.date().isoformat() if pd.notna(last_date) else None,
        "history_years": years,
        "contract_markets": markets,
        "core_field_completeness": completeness,
        "unique_event_identity_rate": unique_identity_rate,
        "tuesday_report_date_rate": tuesday_rate,
        "exact_release_timestamp_lineage_rate": release_lineage_rate,
        "stable_market_code_name_rate": stable_market_code_rate,
        "gates": gates,
        "decision": decision,
        "blocking_reasons": [name for name, passed in gates.items() if not passed],
        "return_hypotheses_spent": 0,
    }


def run(raw_path: Path, out_dir: Path) -> dict[str, Any]:
    payload = fetch_payload()
    raw_bytes = canonical_json(payload)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_raw = raw_path.with_suffix(raw_path.suffix + ".tmp")
    temporary_raw.write_bytes(raw_bytes)
    temporary_raw.replace(raw_path)

    frame = build_manifest(payload["data"])
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "events.parquet"
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    frame.to_parquet(temporary_manifest, index=False, compression="zstd")
    temporary_manifest.replace(manifest_path)

    result = summarize(frame, sha256_bytes(raw_bytes))
    result["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    result_path = out_dir / "result.json"
    temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_result.write_text(json.dumps(result, indent=2) + "\n")
    temporary_result.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    print(json.dumps(run(args.raw, args.out_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
