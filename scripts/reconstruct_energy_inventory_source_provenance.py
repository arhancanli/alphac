#!/usr/bin/env python3
"""Reconstruct the energy-inventory ETF source identity without overstating scope."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pyarrow.parquet as pq

ROOT: Final = Path(__file__).resolve().parents[1]
RECEIPT: Final = (
    ROOT / "artifacts/provenance/energy_inventory_historical_execution_receipt.json"
)
INPUT_MANIFEST: Final = (
    ROOT / "artifacts/probe/eia_petroleum_inventory/input_data_manifest.json"
)
LOADER: Final = ROOT / "scripts/mf_etf_load.py"
OUTPUT: Final = ROOT / "artifacts/provenance/energy_inventory_source_provenance.json"

EXPECTED_COMMAND: Final = (
    "MF_BASKET_OVERRIDE=USO,UGA,DBC uv run python scripts/mf_etf_load.py "
    "--lake-dir data/lake_inventory --var-dir var_inventory"
)
EXPECTED_COVERAGE: Final = {
    "USO": {
        "rows": 5119,
        "first_ts_ms": 1144627200000,
        "last_ts_ms": 1786665600000,
    },
    "UGA": {
        "rows": 4645,
        "first_ts_ms": 1204156800000,
        "last_ts_ms": 1786665600000,
    },
    "DBC": {
        "rows": 5163,
        "first_ts_ms": 1139184000000,
        "last_ts_ms": 1786665600000,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _millis(value: Any) -> int:
    return int(value.timestamp() * 1000)


def _coverage(symbol: str, partitions: list[dict[str, Any]]) -> dict[str, Any]:
    rows = 0
    first: int | None = None
    last: int | None = None
    ingested_at: set[str] = set()
    partition_bindings_valid = True
    for partition in partitions:
        path = ROOT / partition["path"]
        partition_bindings_valid &= (
            path.is_file()
            and path.stat().st_size == partition["bytes"]
            and _sha256(path) == partition["sha256"]
        )
        table = pq.ParquetFile(path).read(columns=["ts_open", "ingested_at"])
        timestamps = [_millis(value) for value in table["ts_open"].to_pylist()]
        rows += len(timestamps)
        first = min(timestamps) if first is None else min(first, min(timestamps))
        last = max(timestamps) if last is None else max(last, max(timestamps))
        ingested_at.update(value.isoformat() for value in table["ingested_at"].to_pylist())
    actual = {
        "rows": rows,
        "first_ts_ms": first,
        "last_ts_ms": last,
    }
    return {
        "symbol": symbol,
        **actual,
        "expected": EXPECTED_COVERAGE[symbol],
        "matches_execution_stdout": actual == EXPECTED_COVERAGE[symbol],
        "partition_bindings_valid": partition_bindings_valid,
        "distinct_ingested_at": sorted(ingested_at),
    }


def build() -> dict[str, Any]:
    receipt = json.loads(RECEIPT.read_text())
    manifest = json.loads(INPUT_MANIFEST.read_text())
    loader_text = LOADER.read_text()
    execution = receipt["execution"]
    started_at = _iso(execution["started_at"])
    completed_at = _iso(execution["completed_at"])

    failures: list[str] = []
    if execution["command"] != EXPECTED_COMMAND or execution["exit_code"] != 0:
        failures.append("HISTORICAL_EXECUTION_RECEIPT_MISMATCH")
    if set(manifest["market_data_partitions"]) != set(EXPECTED_COVERAGE):
        failures.append("MARKET_DATA_SYMBOL_SET_MISMATCH")

    coverage = [
        _coverage(symbol, manifest["market_data_partitions"][symbol])
        for symbol in EXPECTED_COVERAGE
    ]
    if not all(row["matches_execution_stdout"] for row in coverage):
        failures.append("PERSISTED_COVERAGE_DOES_NOT_MATCH_EXECUTION_RECEIPT")
    if not all(row["partition_bindings_valid"] for row in coverage):
        failures.append("INPUT_MANIFEST_PARTITION_BINDING_INVALID")

    ingestion_times = {
        value for row in coverage for value in row["distinct_ingested_at"]
    }
    if len(ingestion_times) != 1:
        failures.append("PERSISTED_ROWS_DO_NOT_SHARE_ONE_INGESTION_TIMESTAMP")
        ingestion_within_execution = False
    else:
        ingestion_within_execution = started_at <= _iso(next(iter(ingestion_times))) <= completed_at
        if not ingestion_within_execution:
            failures.append("INGESTION_TIMESTAMP_OUTSIDE_EXECUTION_WINDOW")

    loader_markers = {
        "declares_yahoo_adjusted_total_return": (
            "Source = Yahoo daily, ADJUSTED" in loader_text
        ),
        "uses_yahoo_chart_endpoint": "query1.finance.yahoo.com/v8/finance/chart" in loader_text,
        "applies_adjusted_close_ratio": 'ratio = df["adjclose"] / df["close"]' in loader_text,
        "supports_basket_override": 'os.environ.get("MF_BASKET_OVERRIDE"' in loader_text,
    }
    if not all(loader_markers.values()):
        failures.append("CURRENT_LOADER_SOURCE_MARKERS_INCOMPLETE")

    document: dict[str, Any] = {
        "schema": "canli.alphac-energy-inventory-source-provenance.v1",
        "author": "Arhan Canli",
        "reconstruction_date": "2026-08-24",
        "status": (
            "PASS_LOCAL_SOURCE_IDENTITY_RECONSTRUCTED" if not failures else "FAIL"
        ),
        "source_identity": "YAHOO_FINANCE_MARKET_DATA",
        "source_mapping_complete": not failures,
        "confidence": (
            "LOCALLY_VERIFIED_HISTORICAL_EXECUTION_RECEIPT"
            if not failures
            else "UNRESOLVED"
        ),
        "historical_execution": {
            "command": execution["command"],
            "started_at": execution["started_at"],
            "completed_at": execution["completed_at"],
            "exit_code": execution["exit_code"],
            "stdout": execution["stdout"],
            "receipt_path": str(RECEIPT.relative_to(ROOT)),
            "receipt_sha256": _sha256(RECEIPT),
            "private_session_basename": receipt["captured_from"]["session_basename"],
            "private_session_sha256_at_capture": receipt["captured_from"][
                "session_sha256_at_capture"
            ],
        },
        "persisted_lake_reconciliation": {
            "input_manifest_path": str(INPUT_MANIFEST.relative_to(ROOT)),
            "input_manifest_sha256": _sha256(INPUT_MANIFEST),
            "coverage": coverage,
            "single_ingestion_timestamp": (
                next(iter(ingestion_times)) if len(ingestion_times) == 1 else None
            ),
            "ingestion_timestamp_within_execution_window": ingestion_within_execution,
        },
        "loader_binding": {
            "path": str(LOADER.relative_to(ROOT)),
            "current_sha256": _sha256(LOADER),
            "markers": loader_markers,
            "exact_historical_loader_bytes_proven": False,
        },
        "raw_rows_released": False,
        "redistribution_rights_established": False,
        "independent_attestation_completed": False,
        "failures": failures,
        "claim_boundary": (
            "The local execution receipt, exact persisted coverage, one ingestion timestamp inside "
            "the execution window, and current loader implementation jointly establish the Yahoo "
            "source mapping for this workspace. This does not prove the exact historical loader "
            "bytes, grant redistribution rights, reproduce the research result, or constitute "
            "independent verification."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if document["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
