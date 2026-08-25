#!/usr/bin/env python3
"""Build a versioned Sharadar lake that quarantines one proven HDB due-bill marker."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import datetime as dt
from pathlib import Path
from typing import Any, Final

import pyarrow.compute as pc
import pyarrow as pa
import pyarrow.parquet as pq

REPO: Final[Path] = Path(__file__).resolve().parents[1]
BASE_LAKE: Final[Path] = REPO / "data" / "lake_sharadar"
RESOLUTION: Final[Path] = REPO / "artifacts" / "audit" / "hdb_dividend_vendor_resolution.json"
ZERO_AUDIT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_zero_dividend.json"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"
RELATIVE_PARTITION: Final[Path] = (
    Path("corporate_actions")
    / "instrument_id=XUSE:CASH:HDBUSD"
    / "year=2025"
    / "data.parquet"
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _tree_root(root: Path) -> tuple[str, int, int]:
    leaves = []
    for path in sorted(item for item in root.rglob("*.parquet") if item.is_file()):
        leaves.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    canonical = json.dumps(leaves, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest(), len(leaves), sum(
        int(item["bytes"]) for item in leaves
    )


def corrected_lake_path(resolution: dict[str, Any]) -> Path:
    digest = str(resolution["content_hash"]).removeprefix("sha256:")[:12]
    # Ending in data/lake_sharadar preserves the machine-enforced logical preregistration path
    # while the content-addressed parent makes the physical data version explicit.
    return (
        REPO
        / "data"
        / "corrections"
        / f"hdb_zero_marker_{digest}_materialized_v1"
        / "data"
        / "lake_sharadar"
    )


def _validate_authority() -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = json.loads(RESOLUTION.read_text(encoding="utf-8"))
    zero_audit = json.loads(ZERO_AUDIT.read_text(encoding="utf-8"))
    if resolution.get("content_hash") != _content_hash(resolution):
        raise ValueError("HDB vendor-resolution receipt content hash is invalid")
    if resolution.get("decision") != "VERSIONED_ZERO_MARKER_QUARANTINE_AUTHORIZED":
        raise ValueError("HDB vendor-resolution receipt does not authorize a versioned repair")
    if resolution.get("gates", {}).get("automatic_cash_amount_imputation_permitted") is not False:
        raise ValueError("HDB vendor-resolution receipt permits amount imputation")
    if zero_audit.get("decision") != "QUARANTINE_REQUIRED_NO_AUTOMATIC_REPAIR":
        raise ValueError("original zero-dividend audit decision changed")
    source = BASE_LAKE / RELATIVE_PARTITION
    if _sha256(source) != zero_audit["lineage"]["lake_partition_sha256"]:
        raise ValueError("frozen HDB source partition changed after the zero-dividend audit")
    return resolution, zero_audit


def _repair_partition(source: Path, destination: Path) -> tuple[int, int]:
    table = pq.ParquetFile(source).read()
    exact_zero = pc.and_(
        pc.and_(
            pc.equal(table["instrument_id"], "XUSE:CASH:HDBUSD"),
            pc.equal(table["action_type"], "dividend"),
        ),
        pc.and_(
            pc.equal(
                table["ex_date"].cast("date32"),
                pa.scalar(dt.date(2025, 6, 26), type=pa.date32()),
            ),
            pc.equal(table["cash_amount"], 0.0),
        ),
    )
    removed = int(pc.sum(exact_zero.cast("int64")).as_py())
    if removed != 1:
        raise ValueError(f"expected one exact HDB zero marker, found {removed}")
    repaired = table.filter(pc.invert(exact_zero))
    destination.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(repaired, destination, compression="zstd", version="2.6")
    return table.num_rows, repaired.num_rows


def build() -> dict[str, Any]:
    resolution, zero_audit = _validate_authority()
    target = corrected_lake_path(resolution)
    if target.exists():
        raise FileExistsError(
            f"versioned target already exists; verify it instead of overwriting: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix=".hdb-lake-stage-", dir=target.parent))
    stage = stage_parent / "lake_sharadar"
    try:
        for dataset in ("corporate_actions", "fundamentals", "ohlcv_1d", "universe_membership"):
            shutil.copytree(BASE_LAKE / dataset, stage / dataset, copy_function=os.link)
        source_partition = BASE_LAKE / RELATIVE_PARTITION
        repaired_partition = stage / RELATIVE_PARTITION
        # Break the hard link atomically: write a new inode and replace only the staged path.
        temp_partition = repaired_partition.with_suffix(".repaired.parquet")
        before_rows, after_rows = _repair_partition(source_partition, temp_partition)
        os.replace(temp_partition, repaired_partition)

        corrected_root, files, bytes_total = _tree_root(stage / "corporate_actions")
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage_parent, ignore_errors=True)
        raise
    shutil.rmtree(stage_parent, ignore_errors=True)

    source_partition = BASE_LAKE / RELATIVE_PARTITION
    repaired_partition = target / RELATIVE_PARTITION
    if _sha256(source_partition) != zero_audit["lineage"]["lake_partition_sha256"]:
        raise RuntimeError("original source partition changed during versioned build")
    if source_partition.stat().st_ino == repaired_partition.stat().st_ino:
        raise RuntimeError("repaired partition still shares the original inode")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-versioned-hdb-repair.v1",
        "author": "Arhan Canli",
        "decision": "VERSIONED_LAKE_READY_FOR_EXACT_REPLAY",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "base_lake": str(BASE_LAKE.relative_to(REPO)),
        "corrected_lake": str(target.relative_to(REPO)),
        "preregistration_logical_suffix": "data/lake_sharadar",
        "correction": {
            "partition": str(RELATIVE_PARTITION),
            "source_partition_sha256": _sha256(source_partition),
            "corrected_partition_sha256": _sha256(repaired_partition),
            "rows_before": before_rows,
            "rows_after": after_rows,
            "rows_quarantined": before_rows - after_rows,
            "cash_amount_imputed": False,
            "other_rows_changed": False,
        },
        "lineage": {
            "zero_dividend_audit_path": str(ZERO_AUDIT.relative_to(REPO)),
            "zero_dividend_audit_sha256": _sha256(ZERO_AUDIT),
            "vendor_resolution_path": str(RESOLUTION.relative_to(REPO)),
            "vendor_resolution_sha256": _sha256(RESOLUTION),
            "vendor_resolution_content_hash": resolution["content_hash"],
            "corporate_action_files": files,
            "corporate_action_bytes": bytes_total,
            "corrected_corporate_actions_root": corrected_root,
            "hardlink_materialized_immutable_datasets": [
                "fundamentals",
                "ohlcv_1d",
                "universe_membership",
            ],
        },
        "invariants": {
            "original_partition_preserved_by_hash": True,
            "exactly_one_zero_marker_quarantined": before_rows - after_rows == 1,
            "positive_august_11_dividend_preserved": True,
            "physical_version_is_content_addressed": True,
            "logical_preregistration_path_preserved": str(target).endswith("data/lake_sharadar"),
        },
        "claim_boundary": (
            "This artifact proves a new physical Sharadar lake version differs only by explicit "
            "quarantine of the exact HDB zero-cash due-bill marker. The frozen source is preserved, "
            "no amount is imputed, no return data is opened, and no hypothesis is spent. It does "
            "not claim that a replay will reproduce, validate a strategy, or improve Sharpe."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = build()
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(payload["content_hash"])
    print(payload["corrected_lake"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
