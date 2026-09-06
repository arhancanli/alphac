#!/usr/bin/env python3
"""Classify legacy identity inputs by persisted ledger profile and namespace.

The result is deliberately narrower than a raw-row lineage receipt: it establishes
source classes and expected lake roots, while leaving exact historical input-row
bindings unresolved unless an identity already carries them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "artifacts/provenance/legacy_identity_input_provenance.json"
FAMILY_ARTIFACTS: Final = (
    "artifacts/research/crypto_defensive_family.json",
    "artifacts/research/crypto_momentum_family.json",
    "artifacts/research/equity_low_beta_family.json",
    "artifacts/research/equity_quality_family.json",
    "artifacts/research/equity_value_investment_family.json",
)

PROFILE_BINDINGS: Final = {
    "DEFAULT_SHARED_LAKE": {
        "lake_root": "data/lake",
        "var_root": "var",
        "configuration_evidence": ["configs/base.yaml", "configs/equity.yaml"],
        "namespace_sources": {
            "BINANCE": "BINANCE_EXCHANGE_MARKET_DATA",
            "XUSE": "MASSIVE_POLYGON_MARKET_DATA",
        },
        "confidence": "REPOSITORY_PROFILE_AND_NAMESPACE_BOUND",
    },
    "SHARADAR_RESEARCH_LAKE": {
        "lake_root": "data/lake_sharadar",
        "var_root": "var_sharadar",
        "configuration_evidence": ["configs/sharadar.yaml"],
        "namespace_sources": {"XUSE": "NASDAQ_SHARADAR"},
        "confidence": "DEDICATED_REPOSITORY_PROFILE_AND_LEDGER_BOUND",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _profile(ledger_path: str) -> str | None:
    if ledger_path == "var_sharadar/experiments.jsonl":
        return "SHARADAR_RESEARCH_LAKE"
    if ledger_path == "var/experiments.jsonl" or ledger_path.startswith("artifacts/exp1/"):
        return "DEFAULT_SHARED_LAKE"
    return None


def _ledger_hashes(path: Path) -> set[str]:
    hashes: set[str] = set()
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line).get("config_hash")
            if value is not None:
                hashes.add(str(value))
    return hashes


def _identity_namespaces(identity: dict[str, Any]) -> tuple[list[str], dict[str, int] | None]:
    configuration = identity.get("configuration") or {}
    instrument_ids = configuration.get("instrument_ids")
    if isinstance(instrument_ids, list):
        counts: dict[str, int] = {}
        for instrument_id in instrument_ids:
            namespace = str(instrument_id).split(":", 1)[0]
            counts[namespace] = counts.get(namespace, 0) + 1
        return sorted(counts), dict(sorted(counts.items()))
    namespaces = [str(value) for value in configuration.get("instrument_namespaces") or []]
    count = configuration.get("instrument_count")
    if len(namespaces) == 1 and isinstance(count, int):
        return sorted(namespaces), {namespaces[0]: count}
    return sorted(namespaces), None


def build() -> dict[str, Any]:
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    artifact_bindings: list[dict[str, str]] = []
    ledger_cache: dict[str, tuple[str, set[str]]] = {}

    for relative in FAMILY_ARTIFACTS:
        artifact_path = ROOT / relative
        family = json.loads(artifact_path.read_text())
        artifact_bindings.append({"path": relative, "sha256": _sha256(artifact_path)})
        for identity in family["identities"]:
            ledger_path = str(identity["ledger_source_path"])
            ledger = ROOT / ledger_path
            profile_key = _profile(ledger_path)
            namespaces, namespace_counts = _identity_namespaces(identity)
            if profile_key is None:
                failures.append(f"{identity['hypothesis_key']}:UNKNOWN_LEDGER_PROFILE")
                continue
            profile = PROFILE_BINDINGS[profile_key]
            unknown_namespaces = sorted(set(namespaces) - set(profile["namespace_sources"]))
            if unknown_namespaces:
                failures.append(
                    f"{identity['hypothesis_key']}:UNKNOWN_NAMESPACES:{','.join(unknown_namespaces)}"
                )
            if ledger_path not in ledger_cache:
                if not ledger.is_file():
                    failures.append(f"{identity['hypothesis_key']}:LEDGER_MISSING:{ledger_path}")
                    ledger_cache[ledger_path] = ("", set())
                else:
                    ledger_cache[ledger_path] = (_sha256(ledger), _ledger_hashes(ledger))
            current_ledger_sha256, current_config_hashes = ledger_cache[ledger_path]
            config_hash = str(identity["config_hash"])
            recoverable = config_hash in current_config_hashes
            if not recoverable:
                failures.append(f"{identity['hypothesis_key']}:CONFIG_HASH_NOT_IN_CURRENT_LEDGER")

            source_classes = sorted(
                {
                    profile["namespace_sources"][value]
                    for value in namespaces
                    if value in profile["namespace_sources"]
                }
            )
            records.append(
                {
                    "family_key": family["family_key"],
                    "family_artifact": relative,
                    "hypothesis_key": identity["hypothesis_key"],
                    "config_hash": config_hash,
                    "alpha_names": identity.get("alpha_names")
                    or (identity.get("configuration") or {}).get("alpha_names"),
                    "ledger_source_path": ledger_path,
                    "ledger_sha256_declared_at_family_seal": identity.get(
                        "ledger_source_sha256"
                    ),
                    "ledger_current_sha256": current_ledger_sha256 or None,
                    "config_hash_recoverable_in_current_ledger": recoverable,
                    "profile_classification": profile_key,
                    "lake_root": profile["lake_root"],
                    "instrument_namespaces": namespaces,
                    "instrument_namespace_counts": namespace_counts,
                    "source_classes": source_classes,
                    "source_class_mapping_complete": bool(namespaces)
                    and not unknown_namespaces,
                    "mapping_confidence": profile["confidence"],
                    "historical_execution_command_receipt_available": False,
                    "exact_historical_input_row_hashes_available": False,
                }
            )

    profile_evidence = {
        key: {
            **value,
            "configuration_evidence": [
                {"path": path, "sha256": _sha256(ROOT / path)}
                for path in value["configuration_evidence"]
            ],
        }
        for key, value in PROFILE_BINDINGS.items()
    }
    mixed = sum(len(record["instrument_namespaces"]) > 1 for record in records)
    complete = sum(record["source_class_mapping_complete"] for record in records)
    exact_rows = sum(record["exact_historical_input_row_hashes_available"] for record in records)
    document: dict[str, Any] = {
        "schema": "canli.alphac-legacy-identity-input-provenance.v1",
        "author": "Arhan Canli",
        "reconstruction_date": "2026-08-24",
        "status": "PASS_SOURCE_CLASS_MAPPING_EXACT_ROW_LINEAGE_INCOMPLETE"
        if not failures
        else "FAIL",
        "counts": {
            "families": len(FAMILY_ARTIFACTS),
            "identities": len(records),
            "mixed_namespace_identities": mixed,
            "source_class_mappings_complete": complete,
            "exact_historical_input_row_bindings_complete": exact_rows,
        },
        "profile_evidence": profile_evidence,
        "family_artifact_bindings": artifact_bindings,
        "records": records,
        "source_class_mapping_complete": complete == len(records) and not failures,
        "exact_historical_input_row_lineage_complete": exact_rows == len(records),
        "raw_rows_released": False,
        "independent_attestation_completed": False,
        "failures": failures,
        "remaining_blockers": [
            "EXACT_HISTORICAL_EXECUTION_COMMAND_RECEIPTS_NOT_AVAILABLE_FOR_ALL_IDENTITIES",
            "EXACT_HISTORICAL_INPUT_ROW_HASHES_NOT_AVAILABLE_FOR_ALL_IDENTITIES",
            "DATA_LICENSE_AND_REDISTRIBUTION_REVIEW_REMAINS_SEPARATE",
        ],
        "claim_boundary": (
            "This reconstruction maps each frozen identity to source classes using its persisted "
            "ledger path, instrument namespaces, and repository profile configuration. It does "
            "not establish the exact historical command, exact input-row set, redistribution "
            "rights, result reproduction, or independent verification. Mixed namespaces remain "
            "mixed and are not relabelled."
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
