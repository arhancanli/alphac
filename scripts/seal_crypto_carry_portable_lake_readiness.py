#!/usr/bin/env python3
"""Seal a publication-safe, zero-return receipt for the portable crypto lake."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore

ROOT: Final = Path(__file__).resolve().parents[1]
PRIVATE_ROOT: Final = ROOT / "var/portable_crypto_carry_v1"
READINESS: Final = ROOT / "artifacts/audit/crypto_carry_portable_prerun_readiness.json"
OUTPUT: Final = ROOT / "artifacts/audit/crypto_carry_portable_lake_readiness.json"
PRIVATE_MANIFEST_SCHEMA: Final = "canli.alphac-crypto-carry-portable-lake.v1"
OUTPUT_SCHEMA: Final = "canli.alphac-crypto-carry-portable-lake-readiness.v1"
PROHIBITED_RETURN_ARTIFACTS: Final = frozenset(
    {
        "walkforward.json",
        "equity.parquet",
        "fills.parquet",
        "funding.parquet",
        "orders.parquet",
        "positions.parquet",
        "experiments.jsonl",
    }
)
CODE_PATHS: Final = (
    "scripts/audit_crypto_carry_portable_prerun_readiness.py",
    "scripts/build_crypto_carry_portable_lake.py",
    "scripts/seal_crypto_carry_portable_lake_readiness.py",
    "src/alphaforge/data/store/reader.py",
    "src/alphaforge/data/store/writer.py",
    "src/alphaforge/data/universe/builder.py",
    "src/alphaforge/validation/input_snapshot.py",
    "pyproject.toml",
    "uv.lock",
)


class LakeReadinessError(RuntimeError):
    """The private lake cannot support a truthful preregistration packet."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_json(path: Path, schema: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise LakeReadinessError(f"required JSON is missing: {path}")
    try:
        document = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise LakeReadinessError(f"required JSON is unreadable: {path}") from error
    if schema is not None and document.get("schema") != schema:
        raise LakeReadinessError(f"unexpected schema: {path}")
    if document.get("content_hash") != _content_hash(document):
        raise LakeReadinessError(f"content hash mismatch: {path}")
    return document


def _validate_private_root(root: Path) -> dict[str, Any]:
    manifest = _verified_json(root / "portable_lake_manifest.json", PRIVATE_MANIFEST_SCHEMA)
    if manifest.get("status") != "PASS_ISOLATED_PORTABLE_LAKE_BUILT_ZERO_RETURN":
        raise LakeReadinessError(f"private portable lake status is not passing: {root}")
    inventory = manifest.get("output_inventory")
    leaves = inventory.get("leaves") if isinstance(inventory, dict) else None
    if not isinstance(inventory, dict) or not isinstance(leaves, list) or not leaves:
        raise LakeReadinessError(f"private portable lake leaf inventory is missing: {root}")
    observed = []
    for path in sorted((root / "lake").rglob("data.parquet")):
        observed.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if observed != leaves:
        raise LakeReadinessError(f"private portable lake leaf inventory drifted: {root}")
    ops = root / "ops.sqlite"
    if not ops.is_file() or _sha256(ops) != inventory.get("ops_sqlite_sha256"):
        raise LakeReadinessError(f"private portable metadata store drifted: {root}")
    unexpected = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name in PROHIBITED_RETURN_ARTIFACTS
    )
    if unexpected:
        raise LakeReadinessError(f"return artifacts exist in data-only root: {unexpected}")
    return manifest


def _to_ms(value: str) -> int:
    import pandas as pd

    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise LakeReadinessError(f"timestamp is not timezone-aware: {value}")
    return int(timestamp.tz_convert("UTC").timestamp() * 1000)


def build(
    repo: Path,
    private_root: Path,
    readiness_path: Path,
    comparison_root: Path | None,
) -> dict[str, Any]:
    repo = repo.resolve()
    private_root = private_root.resolve()
    readiness = _verified_json(readiness_path)
    private = _validate_private_root(private_root)
    if private["readiness_binding"]["content_hash"] != readiness["content_hash"]:
        raise LakeReadinessError("private lake does not bind the current pre-run readiness")
    if private.get("research_accounting") != {
        "experiment_ledger_mutated": False,
        "hypotheses_spent": 0,
        "new_return_trials_executed": 0,
        "return_metrics_computed": False,
        "strategy_imported_or_executed": False,
    }:
        raise LakeReadinessError("private lake research-accounting boundary drifted")

    comparison: dict[str, Any] | None = None
    if comparison_root is not None:
        comparison = _validate_private_root(comparison_root.resolve())
        if comparison != private:
            raise LakeReadinessError("clean-room repeat build is not byte-identical")

    ids = cast(list[str], private["construction"]["instrument_ids"])
    start = _to_ms(private["construction"]["start_inclusive"])
    end = _to_ms(private["construction"]["end_exclusive"])
    paths = LakePaths(private_root / "lake")
    reader = PITDataReader(paths)
    ohlcv = reader.ohlcv(ids, start=start, end=end, as_of=end, tf=Timeframe.H1)
    funding = reader.funding(ids, start=start, end=end, as_of=end)
    expected_ohlcv = sum(
        row["retained_rows"]
        for row in private["conversion_records"]
        if row["dataset"] == "ohlcv"
    )
    expected_funding = sum(
        row["retained_rows"]
        for row in private["conversion_records"]
        if row["dataset"] == "funding"
    )
    if ohlcv.num_rows != expected_ohlcv or funding.num_rows != expected_funding:
        raise LakeReadinessError("production PIT read counts differ from the sealed conversion")
    universe = UniverseStore(paths).read_intervals()
    if universe.num_rows != private["universe_rebuild"]["intervals"]:
        raise LakeReadinessError("production universe read differs from the sealed rebuild")
    with InstrumentStore(private_root / "ops.sqlite") as instruments:
        known = instruments.all_known(as_of=end - 1)
    if [instrument.instrument_id for instrument in known] != sorted(ids):
        raise LakeReadinessError("production instrument store differs from the locked candidate")

    code_bindings = []
    for relative in CODE_PATHS:
        path = repo / relative
        if not path.is_file():
            raise LakeReadinessError(f"required code or environment binding is missing: {relative}")
        code_bindings.append(
            {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        )

    inventory = private["output_inventory"]
    document: dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS_PORTABLE_DATA_PREREQUISITES_COMPLETE_READY_TO_PREREGISTER_RETURN_BLOCKED",
        "author": "Arhan Canli",
        "private_lake_binding": {
            "manifest_sha256": _sha256(private_root / "portable_lake_manifest.json"),
            "manifest_content_hash": private["content_hash"],
            "leaf_files": inventory["leaf_files"],
            "leaf_bytes": inventory["leaf_bytes"],
            "leaf_inventory_root_sha256": inventory["leaf_inventory_root_sha256"],
            "ops_sqlite_sha256": inventory["ops_sqlite_sha256"],
            "market_rows": private["conversion_totals"]["retained_rows"],
            "universe_intervals": private["universe_rebuild"]["intervals"],
            "private_not_authorized_for_publication": True,
        },
        "clean_repeat_build": {
            "executed": comparison is not None,
            "byte_identical_manifest": comparison == private if comparison is not None else False,
            "manifest_content_hash": comparison["content_hash"] if comparison is not None else None,
            "leaf_inventory_root_sha256": (
                comparison["output_inventory"]["leaf_inventory_root_sha256"]
                if comparison is not None
                else None
            ),
            "ops_sqlite_sha256": (
                comparison["output_inventory"]["ops_sqlite_sha256"]
                if comparison is not None
                else None
            ),
        },
        "production_interface_readback": {
            "instrument_records": len(known),
            "ohlcv_rows": ohlcv.num_rows,
            "funding_rows": funding.num_rows,
            "universe_intervals": universe.num_rows,
            "pit_ohlcv_as_of_end": True,
            "pit_funding_available_at_as_of_end": True,
            "strategy_or_return_engine_invoked": False,
        },
        "candidate": {
            "return_identity_id": readiness["locked_candidate"]["return_identity_id"],
            "identity_classification": readiness["locked_candidate"][
                "identity_classification"
            ],
            "instrument_count": len(ids),
            "excluded_symbols": readiness["locked_candidate"]["excluded_symbols"],
            "walkforward_legs": readiness["locked_candidate"]["walkforward_legs"],
        },
        "code_and_environment_bindings": code_bindings,
        "remaining_fail_closed_prerequisites": [
            "COMPLETE_RETURN_PREREGISTRATION_NOT_YET_FROZEN",
            "RETURN_IDENTITY_RESERVATION_NOT_YET_CREATED_OR_VALIDATED",
            "NO_RETURN_EXECUTION_AUTHORIZED",
        ],
        "research_accounting": private["research_accounting"],
        "publication_boundary": {
            "raw_archives_published": False,
            "derived_market_rows_published": False,
            "public_receipt_contains_only_counts_hashes_and_method_facts": True,
            "redistribution_rights_established": False,
            "independent_replication": False,
        },
        "claim_boundary": (
            "This receipt proves the private isolated lake is hash-stable, clean-repeat "
            "deterministic when the repeat-build section passes, and readable through the "
            "production PIT data interfaces. It does not expose market rows, compute or imply "
            "returns, authorize a trial, spend a hypothesis, grant redistribution rights, "
            "repair the historical result, or constitute independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=PRIVATE_ROOT)
    parser.add_argument("--readiness", type=Path, default=READINESS)
    parser.add_argument("--comparison-root", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    document = build(ROOT, args.private_root, args.readiness, args.comparison_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {args.output}")
    print(json.dumps(document["production_interface_readback"], indent=2, sort_keys=True))
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
