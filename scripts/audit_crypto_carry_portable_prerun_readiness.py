#!/usr/bin/env python3
"""Fail-closed, zero-return readiness audit for crypto_carry_portable_v1.

This audit verifies the fresh archive cache, normalized objects, bound comparison,
and pre-result data contract.  It never imports the strategy, computes a signal,
runs a walk-forward leg, reads an equity curve, or writes an experiment ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
CONTRACT: Final = ROOT / "config/crypto_carry_portable_v1_prerun.json"
OUTPUT: Final = ROOT / "artifacts/audit/crypto_carry_portable_prerun_readiness.json"

CONTRACT_SCHEMA: Final = "canli.alphac-crypto-carry-portable-prerun-contract.v1"
ACQUISITION_SCHEMA: Final = "canli.alphac-crypto-carry-portable-fetch.v1"
OUTPUT_SCHEMA: Final = "canli.alphac-crypto-carry-portable-prerun-readiness.v1"
EXPECTED_BINDING_SCHEMAS: Final = {
    "portability_manifest": "canli.alphac-crypto-carry-portability-manifest.v1",
    "instrument_metadata": "canli.alphac-crypto-carry-instrument-metadata.v1",
    "fresh_input_comparison": "canli.alphac-crypto-carry-fresh-input-comparison.v1",
    "historical_replay_correction": "canli.alphac-crypto-carry-replay-correction.v1",
    "prospective_input_snapshot_protocol": (
        "canli.alphac-walkforward-input-snapshot-protocol-receipt.v1"
    ),
}


class ReadinessError(RuntimeError):
    """The portable pre-run evidence does not satisfy the frozen data contract."""


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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReadinessError(f"required JSON is missing: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise ReadinessError(f"required JSON is unreadable: {path}") from error


def _verified_json(path: Path, *, schema: str | None = None) -> dict[str, Any]:
    document = _read_json(path)
    if schema is not None and document.get("schema") != schema:
        raise ReadinessError(f"unexpected schema in {path}: {document.get('schema')!r}")
    if document.get("content_hash") != _content_hash(document):
        raise ReadinessError(f"content hash mismatch: {path}")
    return document


def _repo_path(repo: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ReadinessError("binding path must be a non-empty repository-relative string")
    candidate = (repo / relative).resolve()
    try:
        candidate.relative_to(repo.resolve())
    except ValueError as error:
        raise ReadinessError(f"binding escapes repository: {relative}") from error
    return candidate


def _verify_contract_bindings(
    repo: Path, contract: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    bindings = contract.get("pre_result_evidence_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(EXPECTED_BINDING_SCHEMAS):
        raise ReadinessError("pre-result evidence bindings are incomplete or unexpected")
    verified: dict[str, dict[str, Any]] = {}
    for name, expected_schema in EXPECTED_BINDING_SCHEMAS.items():
        binding = bindings[name]
        if not isinstance(binding, dict) or set(binding) != {"path", "content_hash"}:
            raise ReadinessError(f"malformed contract binding: {name}")
        path = _repo_path(repo, binding["path"])
        document = _verified_json(path, schema=expected_schema)
        if document["content_hash"] != binding["content_hash"]:
            raise ReadinessError(f"contract content-hash binding drifted: {name}")
        verified[name] = {
            "path": str(path.relative_to(repo.resolve())),
            "sha256": _sha256(path),
            "content_hash": document["content_hash"],
            "document": document,
        }
    return verified


def _checksum_value(path: Path, filename: str) -> str:
    try:
        tokens = path.read_text(encoding="utf-8").strip().split()
    except OSError as error:
        raise ReadinessError(f"checksum sidecar is unreadable: {path}") from error
    if len(tokens) != 2 or tokens[1].lstrip("*") != filename or len(tokens[0]) != 64:
        raise ReadinessError(f"checksum sidecar is malformed: {path}")
    return tokens[0].lower()


def _verify_fresh_objects(
    fresh_dir: Path,
    acquisition: dict[str, Any],
    expected_excluded: set[str],
) -> dict[str, Any]:
    selection = acquisition.get("selection")
    if not isinstance(selection, dict):
        raise ReadinessError("fresh acquisition selection is missing")
    symbols = selection.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or len(symbols) != len(set(symbols))
        or not all(isinstance(symbol, str) and symbol for symbol in symbols)
    ):
        raise ReadinessError("fresh acquisition symbol selection is malformed")
    if selection.get("full_frozen_inventory") is not True or selection.get("months") is not None:
        raise ReadinessError("fresh acquisition is not the full frozen inventory")

    unavailable = acquisition.get("unavailable_archive_objects")
    if not isinstance(unavailable, list):
        raise ReadinessError("fresh acquisition unavailable-object inventory is missing")
    unavailable_symbols = {
        row["symbol"]
        for row in unavailable
        if isinstance(row, dict) and isinstance(row.get("symbol"), str)
    }
    if unavailable_symbols != expected_excluded:
        raise ReadinessError(
            "archive-ineligible symbols differ from the frozen contract: "
            f"{sorted(unavailable_symbols)} != {sorted(expected_excluded)}"
        )
    if any(
        not isinstance(row, dict)
        or row.get("dataset") != "funding"
        or row.get("symbol") not in expected_excluded
        for row in unavailable
    ):
        raise ReadinessError("unavailable archive inventory violates the frozen eligibility rule")

    archive_records = acquisition.get("archive_objects")
    if not isinstance(archive_records, list) or not archive_records:
        raise ReadinessError("fresh acquisition has no verified archive objects")
    archive_leaves: list[dict[str, Any]] = []
    archive_keys: set[tuple[str, str, str]] = set()
    for record in archive_records:
        if not isinstance(record, dict):
            raise ReadinessError("archive object record is malformed")
        dataset = record.get("dataset")
        symbol = record.get("symbol")
        filename = record.get("filename")
        claimed = record.get("sha256")
        if (
            dataset not in {"ohlcv", "funding"}
            or not isinstance(symbol, str)
            or not isinstance(filename, str)
            or not isinstance(claimed, str)
        ):
            raise ReadinessError("archive object identity is malformed")
        archive_key = (dataset, symbol, filename)
        if archive_key in archive_keys:
            raise ReadinessError(f"duplicate archive object: {archive_key}")
        archive_keys.add(archive_key)
        path = fresh_dir / "archives" / dataset / symbol / filename
        checksum_path = path.with_name(filename + ".CHECKSUM")
        if not path.is_file() or not checksum_path.is_file():
            raise ReadinessError(f"archive or checksum sidecar is missing: {path}")
        observed = _sha256(path)
        sidecar = _checksum_value(checksum_path, filename)
        if observed != claimed or sidecar != claimed:
            raise ReadinessError(f"archive hash mismatch: {path}")
        size = path.stat().st_size
        if record.get("bytes") != size:
            raise ReadinessError(f"archive byte count mismatch: {path}")
        archive_leaves.append(
            {
                "dataset": dataset,
                "symbol": symbol,
                "filename": filename,
                "bytes": size,
                "sha256": observed,
            }
        )

    normalized_records = acquisition.get("normalized_objects")
    if not isinstance(normalized_records, list) or not normalized_records:
        raise ReadinessError("fresh acquisition has no normalized objects")
    normalized_leaves: list[dict[str, Any]] = []
    normalized_keys: set[tuple[str, str]] = set()
    for record in normalized_records:
        if not isinstance(record, dict):
            raise ReadinessError("normalized object record is malformed")
        dataset = record.get("dataset")
        symbol = record.get("symbol")
        claimed = record.get("sha256")
        if (
            dataset not in {"ohlcv", "funding"}
            or not isinstance(symbol, str)
            or not isinstance(claimed, str)
        ):
            raise ReadinessError("normalized object identity is malformed")
        normalized_key = (dataset, symbol)
        if normalized_key in normalized_keys:
            raise ReadinessError(f"duplicate normalized object: {normalized_key}")
        normalized_keys.add(normalized_key)
        path = fresh_dir / "normalized" / dataset / f"{symbol}.parquet"
        if not path.is_file() or _sha256(path) != claimed:
            raise ReadinessError(f"normalized object hash mismatch: {path}")
        rows = record.get("rows")
        if not isinstance(rows, int) or rows < 0:
            raise ReadinessError(f"normalized row count is invalid: {path}")
        normalized_leaves.append(
            {
                "dataset": dataset,
                "symbol": symbol,
                "rows": rows,
                "sha256": claimed,
            }
        )

    eligible = sorted(set(cast(list[str], symbols)) - expected_excluded)
    expected_pairs = {(dataset, symbol) for symbol in eligible for dataset in ("ohlcv", "funding")}
    missing_pairs = expected_pairs - normalized_keys
    if missing_pairs:
        raise ReadinessError(f"eligible normalized objects are missing: {sorted(missing_pairs)}")

    totals = acquisition.get("totals")
    if not isinstance(totals, dict):
        raise ReadinessError("fresh acquisition totals are missing")
    expected_totals = {
        "archive_objects": len(archive_records),
        "archive_objects_requested": len(archive_records) + len(unavailable),
        "archive_objects_unavailable": len(unavailable),
        "archive_bytes": sum(leaf["bytes"] for leaf in archive_leaves),
        "normalized_rows": sum(leaf["rows"] for leaf in normalized_leaves),
    }
    for total_name, expected in expected_totals.items():
        if totals.get(total_name) != expected:
            raise ReadinessError(f"fresh acquisition total mismatch: {total_name}")

    return {
        "selected_symbols": len(symbols),
        "eligible_symbols": eligible,
        "eligible_instruments": len(eligible),
        "excluded_symbols": sorted(expected_excluded),
        "unavailable_archive_objects": len(unavailable),
        "verified_archive_objects": len(archive_leaves),
        "verified_archive_bytes": sum(leaf["bytes"] for leaf in archive_leaves),
        "archive_inventory_root_sha256": hashlib.sha256(_canonical(archive_leaves)).hexdigest(),
        "verified_normalized_objects": len(normalized_leaves),
        "verified_normalized_rows": sum(leaf["rows"] for leaf in normalized_leaves),
        "normalized_inventory_root_sha256": hashlib.sha256(
            _canonical(normalized_leaves)
        ).hexdigest(),
    }


def _verify_comparison(
    comparison: dict[str, Any], eligible_symbols: list[str], expected_excluded: set[str]
) -> dict[str, Any]:
    records = comparison.get("records")
    if not isinstance(records, list):
        raise ReadinessError("fresh-input comparison records are missing")
    by_symbol = {
        record["symbol"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("symbol"), str)
    }
    if set(by_symbol) != set(eligible_symbols) | expected_excluded:
        raise ReadinessError("fresh-input comparison symbol inventory differs from acquisition")
    failures: list[str] = []
    for symbol in eligible_symbols:
        record = by_symbol[symbol]
        ohlcv = record.get("ohlcv")
        funding = record.get("funding")
        if not isinstance(ohlcv, dict) or not isinstance(funding, dict):
            failures.append(f"{symbol}:MISSING_COMPARISON_SECTION")
            continue
        if ohlcv.get("local_only_rows") != 0:
            failures.append(f"{symbol}:LOCAL_ONLY_OHLCV_ROWS")
        if funding.get("local_only_rows") != 0:
            failures.append(f"{symbol}:LOCAL_ONLY_FUNDING_ROWS")
        if ohlcv.get("fresh_only_inside_lifecycle") != 0:
            failures.append(f"{symbol}:FRESH_ONLY_OHLCV_INSIDE_LIFECYCLE")
        if funding.get("fresh_only_inside_lifecycle") != 0:
            failures.append(f"{symbol}:FRESH_ONLY_FUNDING_INSIDE_LIFECYCLE")
    if failures:
        raise ReadinessError("eligible input-equivalence gate failed: " + ", ".join(failures))

    totals = comparison.get("totals")
    if not isinstance(totals, dict):
        raise ReadinessError("fresh-input comparison totals are missing")
    revised_fields = totals.get("ohlcv_field_mismatches_on_overlap")
    if not isinstance(revised_fields, int) or revised_fields <= 0:
        raise ReadinessError("new-identity boundary requires observed current-archive revisions")
    excluded_local_only = sum(
        int(by_symbol[symbol][dataset]["local_only_rows"])
        for symbol in expected_excluded
        for dataset in ("ohlcv", "funding")
    )
    if excluded_local_only != totals.get("ohlcv_local_only_rows", 0) + totals.get(
        "funding_local_only_rows", 0
    ):
        raise ReadinessError("local-only rows are not confined to archive-ineligible symbols")
    return {
        "eligible_local_only_ohlcv_rows": 0,
        "eligible_local_only_funding_rows": 0,
        "eligible_fresh_only_rows_inside_lifecycle": 0,
        "excluded_symbol_local_only_rows": excluded_local_only,
        "overlap_ohlcv_field_revisions": revised_fields,
        "fresh_archive_is_new_run_authority": True,
        "historical_input_equivalence": False,
    }


def _walkforward_legs(start: str, end: str, train_bars: int, test_bars: int) -> int:
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        raise ReadinessError("walk-forward bounds must be timezone-aware")
    hours_float = (end_dt.astimezone(UTC) - start_dt.astimezone(UTC)).total_seconds() / 3600
    if hours_float != int(hours_float):
        raise ReadinessError("walk-forward bounds are not aligned to the hourly grid")
    remaining = int(hours_float) - train_bars
    return 0 if remaining <= 0 else -(-remaining // test_bars)


def build(repo: Path, fresh_dir: Path, contract_path: Path) -> dict[str, Any]:
    repo = repo.resolve()
    fresh_dir = fresh_dir.resolve()
    contract = _verified_json(contract_path, schema=CONTRACT_SCHEMA)
    if contract.get("status") != "CANDIDATE_DATA_CONTRACT_FROZEN_BEFORE_RETURN_COMPUTE":
        raise ReadinessError("portable pre-run contract is not frozen")
    governance = contract.get("governance")
    if not isinstance(governance, dict) or governance != {
        "hypotheses_spent_by_this_contract": 0,
        "new_return_trials_executed_by_this_contract": 0,
        "return_metrics_computed_by_this_contract": False,
        "return_execution_authorized": False,
        "reservation_created": False,
        "reservation_may_be_created_only_after_all_non_return_prerequisites_pass": True,
    }:
        raise ReadinessError("pre-result governance boundary is missing or widened")

    verified = _verify_contract_bindings(repo, contract)
    portability = verified["portability_manifest"]["document"]
    metadata = verified["instrument_metadata"]["document"]
    comparison = verified["fresh_input_comparison"]["document"]
    correction = verified["historical_replay_correction"]["document"]
    snapshot = verified["prospective_input_snapshot_protocol"]["document"]
    if portability.get("passes") is not True or metadata.get("passes") is not True:
        raise ReadinessError("frozen portability or metadata inventory does not pass")
    if correction.get("status") != "OPEN_CORRECTION_EXTERNAL_SUBMISSION_BLOCKED":
        raise ReadinessError("historical replay correction is not open and fail-closed")
    if snapshot.get("status") != "PASS_PROSPECTIVE_PRIVATE_INPUT_SNAPSHOT_ENFORCED":
        raise ReadinessError("prospective input-snapshot protocol is not enforced")

    source_contract = contract.get("source_contract")
    if not isinstance(source_contract, dict):
        raise ReadinessError("source contract is missing")
    expected_excluded = set(source_contract.get("expected_archive_ineligible_symbols", []))
    if not expected_excluded or not all(isinstance(value, str) for value in expected_excluded):
        raise ReadinessError("expected archive-ineligible symbols are missing")

    manifest_path = fresh_dir / "source_manifest.json"
    acquisition = _verified_json(manifest_path, schema=ACQUISITION_SCHEMA)
    if acquisition.get("status") != "INCOMPLETE_OFFICIAL_ARCHIVE_COVERAGE":
        raise ReadinessError("expected the source-level incomplete status before exclusion")
    object_audit = _verify_fresh_objects(fresh_dir, acquisition, expected_excluded)
    if object_audit["eligible_instruments"] != source_contract.get(
        "expected_eligible_instrument_count"
    ):
        raise ReadinessError("derived eligible instrument count differs from the frozen contract")

    comparison_audit = _verify_comparison(
        comparison, object_audit["eligible_symbols"], expected_excluded
    )
    metadata_ids = {
        row.get("instrument_id")
        for row in metadata.get("records", [])
        if isinstance(row, dict)
    }
    expected_ids = {f"BINANCE:PERP:{symbol}" for symbol in object_audit["eligible_symbols"]}
    if not expected_ids.issubset(metadata_ids):
        raise ReadinessError("bound metadata packet does not cover every eligible instrument")

    walkforward = contract.get("walkforward_contract")
    if not isinstance(walkforward, dict):
        raise ReadinessError("walk-forward contract is missing")
    legs = _walkforward_legs(
        walkforward["start_inclusive"],
        walkforward["end_exclusive"],
        walkforward["train_bars"],
        walkforward["test_bars"],
    )
    if legs != walkforward.get("expected_walkforward_legs"):
        raise ReadinessError("walk-forward leg count differs from the frozen contract")
    unavailable_months = sorted(
        row["month"] for row in acquisition["unavailable_archive_objects"]
    )
    # The bound gap currently ends in 2022-08. Derive the next month explicitly,
    # avoiding a claim that the alternate preserves the original test span.
    last_gap = datetime.fromisoformat(unavailable_months[-1] + "-01")
    next_month_year = last_gap.year + (1 if last_gap.month == 12 else 0)
    next_month = 1 if last_gap.month == 12 else last_gap.month + 1
    delayed_start = f"{next_month_year:04d}-{next_month:02d}-01T00:00:00+00:00"
    delayed_legs = _walkforward_legs(
        delayed_start,
        walkforward["end_exclusive"],
        walkforward["train_bars"],
        walkforward["test_bars"],
    )

    evidence_bindings = {
        name: {key: value for key, value in item.items() if key != "document"}
        for name, item in verified.items()
    }
    document: dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS_DATA_ELIGIBILITY_LOCKED_READY_FOR_PORTABLE_LAKE_BUILD_RETURN_BLOCKED",
        "author": "Arhan Canli",
        "passes_zero_return_data_readiness": True,
        "contract_binding": {
            "path": str(contract_path.resolve().relative_to(repo)),
            "sha256": _sha256(contract_path),
            "content_hash": contract["content_hash"],
        },
        "evidence_bindings": evidence_bindings,
        "fresh_acquisition_binding": {
            "path": str(manifest_path),
            "sha256": _sha256(manifest_path),
            "content_hash": acquisition["content_hash"],
            "source_status": acquisition["status"],
        },
        "source_object_audit": object_audit,
        "input_equivalence_audit": comparison_audit,
        "locked_candidate": {
            "return_identity_id": contract["identity"]["return_identity_id"],
            "identity_classification": "NEW_PROSPECTIVE_IDENTITY_NOT_A_REPLICATION",
            "instrument_ids": sorted(expected_ids),
            "instrument_count": len(expected_ids),
            "excluded_symbols": sorted(expected_excluded),
            "walkforward_legs": legs,
            "start_inclusive": walkforward["start_inclusive"],
            "end_exclusive": walkforward["end_exclusive"],
        },
        "pre_result_design_comparison": {
            "recommended": {
                "design": "EXCLUDE_ARCHIVE_INELIGIBLE_SYMBOLS",
                "instruments": len(expected_ids),
                "walkforward_legs": legs,
                "preserves_original_window": True,
                "selection_uses_return_information": False,
                "reason": (
                    "The exclusion is the deterministic consequence of missing required "
                    "official archive objects and preserves the full declared time span."
                ),
            },
            "alternate_not_selected": {
                "design": "DELAY_START_TO_FIRST_COMPLETE_MONTH",
                "start_inclusive": delayed_start,
                "instruments": len(object_audit["eligible_symbols"]) + len(expected_excluded),
                "walkforward_legs": delayed_legs,
                "preserves_original_window": False,
                "selection_uses_return_information": False,
            },
        },
        "remaining_fail_closed_prerequisites": [
            "PERSISTENT_PORTABLE_LAKE_AND_COVERAGE_MANIFEST_NOT_YET_BUILT",
            "COMPLETE_RETURN_PREREGISTRATION_NOT_YET_FROZEN",
            "RETURN_IDENTITY_RESERVATION_NOT_YET_CREATED_OR_VALIDATED",
            "NO_RETURN_EXECUTION_AUTHORIZED",
        ],
        "research_accounting": {
            "new_return_trials_executed": 0,
            "return_metrics_computed": False,
            "hypotheses_spent": 0,
            "experiment_ledger_mutated": False,
            "strategy_imported_or_executed": False,
        },
        "claim_boundary": (
            "This audit proves the bound fresh cache and data-only exclusion rule are ready "
            "for a persistent portable-lake build. It does not compute or imply performance, "
            "authorize a return run, spend a hypothesis, repair the historical result, grant "
            "redistribution rights, or constitute independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    document = build(ROOT, args.fresh_dir, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {args.output}")
    print(json.dumps(document["source_object_audit"], indent=2, sort_keys=True))
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
