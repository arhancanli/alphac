from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_crypto_carry_portable_prerun_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("crypto_portable_prerun_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ReadinessError = MODULE.ReadinessError


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    document["content_hash"] = "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(
    fresh: Path, dataset: str, symbol: str, filename: str, payload: bytes
) -> dict[str, Any]:
    path = fresh / "archives" / dataset / symbol / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    digest = _sha(path)
    path.with_name(filename + ".CHECKSUM").write_text(
        f"{digest}  {filename}\n", encoding="utf-8"
    )
    return {
        "dataset": dataset,
        "symbol": symbol,
        "filename": filename,
        "sha256": digest,
        "bytes": len(payload),
    }


def _normalized(fresh: Path, dataset: str, symbol: str, rows: int) -> dict[str, Any]:
    path = fresh / "normalized" / dataset / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"{dataset}:{symbol}:{rows}".encode())
    return {
        "dataset": dataset,
        "symbol": symbol,
        "rows": rows,
        "sha256": _sha(path),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    fresh = tmp_path / "fresh"
    documents: dict[str, tuple[str, dict[str, Any], str]] = {
        "portability_manifest": (
            "artifacts/publication/portability.json",
            {
                "schema": "canli.alphac-crypto-carry-portability-manifest.v1",
                "passes": True,
            },
            "portability",
        ),
        "instrument_metadata": (
            "artifacts/publication/metadata.json",
            {
                "schema": "canli.alphac-crypto-carry-instrument-metadata.v1",
                "passes": True,
                "records": [
                    {"instrument_id": "BINANCE:PERP:GOOD"},
                    {"instrument_id": "BINANCE:PERP:BAD"},
                ],
            },
            "metadata",
        ),
        "fresh_input_comparison": (
            "artifacts/publication/comparison.json",
            {
                "schema": "canli.alphac-crypto-carry-fresh-input-comparison.v1",
                "records": [
                    {
                        "symbol": "GOOD",
                        "ohlcv": {
                            "local_only_rows": 0,
                            "fresh_only_inside_lifecycle": 0,
                        },
                        "funding": {
                            "local_only_rows": 0,
                            "fresh_only_inside_lifecycle": 0,
                        },
                    },
                    {
                        "symbol": "BAD",
                        "ohlcv": {
                            "local_only_rows": 0,
                            "fresh_only_inside_lifecycle": 0,
                        },
                        "funding": {
                            "local_only_rows": 1,
                            "fresh_only_inside_lifecycle": 0,
                        },
                    },
                ],
                "totals": {
                    "ohlcv_local_only_rows": 0,
                    "funding_local_only_rows": 1,
                    "ohlcv_field_mismatches_on_overlap": 2,
                },
            },
            "comparison",
        ),
        "historical_replay_correction": (
            "artifacts/publication/correction.json",
            {
                "schema": "canli.alphac-crypto-carry-replay-correction.v1",
                "status": "OPEN_CORRECTION_EXTERNAL_SUBMISSION_BLOCKED",
            },
            "correction",
        ),
        "prospective_input_snapshot_protocol": (
            "artifacts/audit/snapshot.json",
            {
                "schema": "canli.alphac-walkforward-input-snapshot-protocol-receipt.v1",
                "status": "PASS_PROSPECTIVE_PRIVATE_INPUT_SNAPSHOT_ENFORCED",
            },
            "snapshot",
        ),
    }
    bindings: dict[str, dict[str, str]] = {}
    for name, (relative, document, _) in documents.items():
        sealed = _seal(document)
        _write_json(repo / relative, sealed)
        bindings[name] = {"path": relative, "content_hash": sealed["content_hash"]}

    contract = _seal(
        {
            "schema": "canli.alphac-crypto-carry-portable-prerun-contract.v1",
            "status": "CANDIDATE_DATA_CONTRACT_FROZEN_BEFORE_RETURN_COMPUTE",
            "identity": {"return_identity_id": "crypto_carry_portable_v1"},
            "pre_result_evidence_bindings": bindings,
            "source_contract": {
                "expected_archive_ineligible_symbols": ["BAD"],
                "expected_eligible_instrument_count": 1,
            },
            "walkforward_contract": {
                "start_inclusive": "2021-06-01T00:00:00+00:00",
                "end_exclusive": "2026-06-01T00:00:00+00:00",
                "train_bars": 6048,
                "test_bars": 1512,
                "expected_walkforward_legs": 25,
            },
            "governance": {
                "hypotheses_spent_by_this_contract": 0,
                "new_return_trials_executed_by_this_contract": 0,
                "return_metrics_computed_by_this_contract": False,
                "return_execution_authorized": False,
                "reservation_created": False,
                "reservation_may_be_created_only_after_all_non_return_prerequisites_pass": True,
            },
        }
    )
    contract_path = repo / "config/prerun.json"
    _write_json(contract_path, contract)

    archives = [
        _object(fresh, "ohlcv", "GOOD", "GOOD-1h-2022-08.zip", b"good-bars"),
        _object(fresh, "funding", "GOOD", "GOOD-fundingRate-2022-08.zip", b"good-funding"),
        _object(fresh, "ohlcv", "BAD", "BAD-1h-2022-08.zip", b"bad-bars"),
    ]
    normalized = [
        _normalized(fresh, dataset, symbol, rows)
        for symbol, rows in (("GOOD", 10), ("BAD", 5))
        for dataset in ("ohlcv", "funding")
    ]
    unavailable = [
        {
            "dataset": "funding",
            "symbol": "BAD",
            "month": "2022-08",
            "filename": "BAD-fundingRate-2022-08.zip",
        }
    ]
    acquisition = _seal(
        {
            "schema": "canli.alphac-crypto-carry-portable-fetch.v1",
            "status": "INCOMPLETE_OFFICIAL_ARCHIVE_COVERAGE",
            "selection": {
                "full_frozen_inventory": True,
                "symbols": ["BAD", "GOOD"],
                "months": None,
            },
            "archive_objects": archives,
            "unavailable_archive_objects": unavailable,
            "normalized_objects": normalized,
            "totals": {
                "archive_objects": len(archives),
                "archive_objects_requested": len(archives) + len(unavailable),
                "archive_objects_unavailable": len(unavailable),
                "archive_bytes": sum(record["bytes"] for record in archives),
                "normalized_rows": sum(record["rows"] for record in normalized),
            },
        }
    )
    _write_json(fresh / "source_manifest.json", acquisition)
    return repo, fresh, contract_path


def test_zero_return_readiness_passes_and_preserves_full_window(tmp_path: Path) -> None:
    repo, fresh, contract = _fixture(tmp_path)
    result = MODULE.build(repo, fresh, contract)
    assert result["status"] == (
        "PASS_DATA_ELIGIBILITY_LOCKED_READY_FOR_PORTABLE_LAKE_BUILD_RETURN_BLOCKED"
    )
    assert result["locked_candidate"]["instrument_ids"] == ["BINANCE:PERP:GOOD"]
    assert result["locked_candidate"]["walkforward_legs"] == 25
    assert result["pre_result_design_comparison"]["alternate_not_selected"][
        "walkforward_legs"
    ] == 18
    assert result["research_accounting"] == {
        "new_return_trials_executed": 0,
        "return_metrics_computed": False,
        "hypotheses_spent": 0,
        "experiment_ledger_mutated": False,
        "strategy_imported_or_executed": False,
    }
    assert result["content_hash"] == MODULE._content_hash(result)


def test_readiness_fails_if_a_verified_archive_is_tampered(tmp_path: Path) -> None:
    repo, fresh, contract = _fixture(tmp_path)
    archive = fresh / "archives/ohlcv/GOOD/GOOD-1h-2022-08.zip"
    archive.write_bytes(b"tampered")
    with pytest.raises(ReadinessError, match="archive hash mismatch"):
        MODULE.build(repo, fresh, contract)


def test_readiness_fails_if_an_eligible_symbol_needs_local_rows(tmp_path: Path) -> None:
    repo, fresh, contract = _fixture(tmp_path)
    path = repo / "artifacts/publication/comparison.json"
    comparison = json.loads(path.read_text(encoding="utf-8"))
    comparison["records"][0]["funding"]["local_only_rows"] = 1
    comparison["totals"]["funding_local_only_rows"] = 2
    _write_json(path, _seal(comparison))
    contract_document = json.loads(contract.read_text(encoding="utf-8"))
    contract_document["pre_result_evidence_bindings"]["fresh_input_comparison"][
        "content_hash"
    ] = json.loads(path.read_text(encoding="utf-8"))["content_hash"]
    _write_json(contract, _seal(contract_document))
    with pytest.raises(ReadinessError, match="LOCAL_ONLY_FUNDING_ROWS"):
        MODULE.build(repo, fresh, contract)


def test_readiness_rejects_any_return_authorization_in_data_contract(tmp_path: Path) -> None:
    repo, fresh, contract = _fixture(tmp_path)
    document = json.loads(contract.read_text(encoding="utf-8"))
    document["governance"]["return_execution_authorized"] = True
    _write_json(contract, _seal(document))
    with pytest.raises(ReadinessError, match="governance boundary"):
        MODULE.build(repo, fresh, contract)
