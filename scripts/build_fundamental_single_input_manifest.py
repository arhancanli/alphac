#!/usr/bin/env python3
"""Commit the complete in-window lake snapshot for the selected fundamental replay."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
IDENTITY: Final[str] = "1d2924f28fe31a9a"
RUN: Final[Path] = REPO / "artifacts" / "walkforward" / "single_gross_profitability"
LAKE: Final[Path] = REPO / "data" / "lake_sharadar"
CORRECTED_LAKE_MANIFEST: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"
)
OUT: Final[Path] = REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
DATASETS: Final[tuple[str, ...]] = (
    "ohlcv_1d",
    "fundamentals",
    "universe_membership",
    "corporate_actions",
)
START_YEAR: Final[int] = 2000
END_YEAR: Final[int] = 2026
CANDIDATES: Final[dict[str, str]] = {
    "single_gross_profitability": "1d2924f28fe31a9a",
    "single_book_to_price": "a238c1a5ecc5d1e3",
    "single_earnings_yield": "e86109044ab18734",
    "single_sales_to_price": "2d966892fb5db520",
    "single_operating_margin": "e5f48adc25065ce9",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _partition(path: Path) -> dict[str, Any]:
    try:
        name = str(path.relative_to(REPO))
    except ValueError:
        name = str(path)
    return {
        "path": name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def aggregate_partitions(paths: list[Path], *, workers: int = 8) -> dict[str, Any]:
    ordered = sorted(set(paths))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        leaves = list(executor.map(_partition, ordered))
    groups: dict[str, list[dict[str, Any]]] = {}
    for leaf in leaves:
        year = next(
            (
                part.removeprefix("year=")
                for part in Path(leaf["path"]).parts
                if part.startswith("year=")
            ),
            "unpartitioned",
        )
        groups.setdefault(year, []).append(leaf)
    shards = []
    for year, members in sorted(groups.items()):
        shards.append(
            {
                "year": year,
                "files": len(members),
                "bytes": sum(item["bytes"] for item in members),
                "root_sha256": _content_hash(members),
            }
        )
    return {
        "files": len(leaves),
        "bytes": sum(item["bytes"] for item in leaves),
        "year_shards": shards,
        "root_sha256": _content_hash(shards),
    }


def _dataset_paths(dataset: str, instrument_ids: list[str], lake_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for instrument_id in instrument_ids:
        root = lake_dir / dataset / f"instrument_id={instrument_id}"
        for year in range(START_YEAR, END_YEAR + 1):
            path = root / f"year={year}" / "data.parquet"
            if path.is_file():
                paths.append(path)
    return paths


def _instrument_metadata(instrument_ids: list[str]) -> dict[str, Any]:
    database = REPO / "var_sharadar" / "ops.sqlite"
    placeholders = ",".join("?" for _ in instrument_ids)
    query = (
        "SELECT * FROM instruments_v WHERE instrument_id IN ("
        + placeholders
        + ") ORDER BY instrument_id, valid_from_ms"
    )
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        cursor = connection.execute(query, instrument_ids)
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()
    if len({row["instrument_id"] for row in rows}) != len(instrument_ids):
        raise ValueError("instrument metadata does not cover the selected universe")
    return {
        "database": str(database.relative_to(REPO)),
        "rows": len(rows),
        "distinct_instruments": len({row["instrument_id"] for row in rows}),
        "logical_rows_sha256": _content_hash(rows),
    }


def _authorized_data_environment(lake_dir: Path) -> dict[str, Any]:
    if lake_dir.resolve() == LAKE.resolve():
        return {
            "kind": "FROZEN_ORIGINAL_SHARADAR_LAKE",
            "lake_dir": str(LAKE.relative_to(REPO)),
            "versioned_correction_manifest": None,
        }
    correction = json.loads(CORRECTED_LAKE_MANIFEST.read_text(encoding="utf-8"))
    declared = (REPO / correction["corrected_lake"]).resolve()
    if (
        lake_dir.resolve() != declared
        or correction.get("content_hash")
        != "sha256:"
        + _content_hash({key: value for key, value in correction.items() if key != "content_hash"})
        or correction.get("correction", {}).get("cash_amount_imputed") is not False
        or correction.get("correction", {}).get("rows_quarantined") != 1
    ):
        raise ValueError("alternate input manifest lake is not the authorized HDB correction")
    return {
        "kind": "VERSIONED_SHARADAR_HDB_ZERO_MARKER_QUARANTINE",
        "lake_dir": str(lake_dir.relative_to(REPO)),
        "versioned_correction_manifest": str(CORRECTED_LAKE_MANIFEST.relative_to(REPO)),
        "versioned_correction_manifest_sha256": _sha256(CORRECTED_LAKE_MANIFEST),
        "versioned_correction_content_hash": correction["content_hash"],
        "rows_quarantined": 1,
        "cash_amount_imputed": False,
    }


def build_manifest(
    run_name: str = "single_gross_profitability",
    identity: str = IDENTITY,
    lake_dir: Path = LAKE,
) -> dict[str, Any]:
    run = REPO / "artifacts" / "walkforward" / run_name
    artifact = json.loads((run / "walkforward.json").read_text(encoding="utf-8"))
    instrument_ids = list(artifact["config"]["instrument_ids"])
    if len(instrument_ids) != 6_820 or instrument_ids != sorted(set(instrument_ids)):
        raise ValueError("expected the sorted, unique corrected 6,820-id universe")
    data_environment = _authorized_data_environment(lake_dir)
    snapshots = {
        dataset: aggregate_partitions(_dataset_paths(dataset, instrument_ids, lake_dir))
        for dataset in DATASETS
    }
    required_files = {
        relative: _sha256(REPO / relative)
        for relative in (
            "configs/base.yaml",
            "configs/sharadar.yaml",
            "data/research/universe_allowlist_20260619.json",
            "docs/design/PREREG_FUNDAMENTAL_SINGLES.md",
        )
    }
    manifest: dict[str, Any] = {
        "schema": "canli.alphac-fundamental-single-input-manifest.v1",
        "evidence_date": "2026-08-22",
        "hypothesis_key": identity,
        "run_name": run_name,
        "scope": {
            "start_year_inclusive": START_YEAR,
            "end_year_inclusive": END_YEAR,
            "instrument_ids": len(instrument_ids),
            "instrument_ids_sha256": _content_hash(instrument_ids),
            "rule": (
                "Every existing year partition for every selected instrument in each named "
                "dataset is committed; this conservative snapshot may include an in-window "
                "partition the engine did not touch, but cannot omit one."
            ),
        },
        "datasets": snapshots,
        "data_environment": data_environment,
        "instrument_metadata": _instrument_metadata(instrument_ids),
        "required_files_sha256": required_files,
        "summary": {
            "partition_files": sum(item["files"] for item in snapshots.values()),
            "partition_bytes": sum(item["bytes"] for item in snapshots.values()),
        },
        "claim_boundary": (
            "This is a deterministic content commitment to private licensed inputs, not a "
            "redistribution of Sharadar data. Independent byte verification requires lawful "
            "access to the same source snapshot."
        ),
    }
    manifest["content_hash"] = "sha256:" + _content_hash(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "run_name", nargs="?", default="single_gross_profitability", choices=CANDIDATES
    )
    parser.add_argument("--lake-dir", type=Path, default=LAKE)
    args = parser.parse_args()
    identity = CANDIDATES[args.run_name]
    lake_dir = args.lake_dir if args.lake_dir.is_absolute() else REPO / args.lake_dir
    manifest = build_manifest(args.run_name, identity, lake_dir)
    out = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    out.mkdir(parents=True, exist_ok=True)
    (out / "input_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
