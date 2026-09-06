#!/usr/bin/env python3
"""Audit Wave 1 publication bundles against the conservative data-rights policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
POLICY: Final = ROOT / "config" / "data_source_rights_policy.json"
SUBMISSION_PLAN: Final = ROOT / "artifacts" / "publication" / "external_submission_plan.json"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "wave1_data_rights_audit.json"

DEPENDENCIES: Final = {
    "alphavintage_macro_surprise": {
        "sources": [
            "PHILADELPHIA_FED_RTDSM",
            "YAHOO_FINANCE_MARKET_DATA",
            "ALPACA_PRIVATE_ACCOUNT",
        ],
        "consumed_market_symbols": ["IWM", "SPY", "QQQ"],
        "local_input_roots": [
            "data/lake_macro_vintage/tier2_vintage",
            "data/lake_mf/ohlcv_1d",
        ],
        "derived_objects_withheld": ["artifacts/probe/cpi_surprise_size/equity.parquet"],
        "portable_reproduction_status": (
            "AUTHOR_RUN_CORE_REPRODUCTION_FROM_FRESH_INPUTS_FULL_DIVERSIFICATION_NOT_REPLAYED"
        ),
    },
    "alphaforge_crypto_carry": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "derived_objects_withheld": [
            "artifacts/walkforward/crypto_carry_wk/equity.parquet",
            "artifacts/probe/crypto_carry_frozen_current_code_replay/equity.parquet",
        ],
        "portable_reproduction_status": (
            "REQUIRES_FRESH_OFFICIAL_DOWNLOAD_OR_SEPARATELY_LICENSED_ACCESS"
        ),
    },
    "alphamax_equity_momentum": {
        "sources": [
            "MASSIVE_POLYGON_MARKET_DATA",
            "NASDAQ_SHARADAR",
            "YAHOO_FINANCE_MARKET_DATA",
        ],
        "local_input_roots": ["data/lake", "data/lake_sharadar", "data/lake_mf"],
        "derived_objects_withheld": ["artifacts/walkforward/k30_dn_63/equity.parquet"],
        "portable_reproduction_status": (
            "REQUIRES_FRESH_OFFICIAL_DOWNLOAD_OR_SEPARATELY_LICENSED_ACCESS"
        ),
    },
    "alphatrend_managed_futures": {
        "sources": ["YAHOO_FINANCE_MARKET_DATA"],
        "local_input_roots": ["data/lake_mf"],
        "derived_objects_withheld": ["artifacts/walkforward/mf_live_fwd/equity.parquet"],
        "portable_reproduction_status": (
            "REQUIRES_FRESH_OFFICIAL_DOWNLOAD_OR_SEPARATELY_LICENSED_ACCESS"
        ),
    },
    "crypto_multifactor_engine": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "derived_objects_withheld": ["artifacts/grand_backtest/20260616T143620Z/equity.parquet"],
        "portable_reproduction_status": (
            "REQUIRES_FRESH_OFFICIAL_DOWNLOAD_OR_SEPARATELY_LICENSED_ACCESS"
        ),
    },
}

RAW_EXTENSIONS: Final = {".csv", ".parquet", ".arrow", ".feather", ".duckdb", ".sqlite"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _bundle_raw_files(bundle_dir: Path) -> list[str]:
    return sorted(
        str(path.relative_to(bundle_dir))
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in RAW_EXTENSIONS
    )


def build() -> dict[str, Any]:
    policy = json.loads(POLICY.read_text())
    plan = json.loads(SUBMISSION_PLAN.read_text())
    wave1 = [record for record in plan["records"] if record["wave"] == 1]
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    wave1_source_keys = sorted(
        {source for dependency in DEPENDENCIES.values() for source in dependency["sources"]}
    )

    if {record["registry_key"] for record in wave1} != set(DEPENDENCIES):
        failures.append("WAVE1_DEPENDENCY_MAP_DOES_NOT_MATCH_SUBMISSION_PLAN")

    for record in wave1:
        key = record["registry_key"]
        dependency = DEPENDENCIES[key]
        manifest_path = ROOT / record["source_objects"]["bundle_manifest"]["path"]
        bundle_dir = manifest_path.parent
        raw_files = _bundle_raw_files(bundle_dir)
        if raw_files:
            failures.append(f"{key}:RAW_TABULAR_FILES_PRESENT_IN_PUBLICATION_BUNDLE")

        source_records = []
        for source_key in dependency["sources"]:
            if source_key not in policy["sources"]:
                failures.append(f"{key}:UNKNOWN_SOURCE:{source_key}")
                continue
            source_records.append({"source_key": source_key, **policy["sources"][source_key]})

        roots = []
        for value in dependency["local_input_roots"]:
            path = ROOT / value
            roots.append({"path": value, "present": path.exists(), "kind": "directory"})
            if not path.exists():
                failures.append(f"{key}:DECLARED_LOCAL_INPUT_ROOT_MISSING:{value}")

        withheld = []
        for value in dependency["derived_objects_withheld"]:
            path = ROOT / value
            withheld.append(
                {
                    "path": value,
                    "present": path.is_file(),
                    "sha256": _sha256(path) if path.is_file() else None,
                    "bytes": path.stat().st_size if path.is_file() else None,
                    "public_bundle_path": None,
                }
            )

        records.append(
            {
                "registry_key": key,
                "bundle": str(bundle_dir.relative_to(ROOT)),
                "bundle_raw_tabular_files": raw_files,
                "raw_vendor_rows_released": False,
                "source_dependencies": source_records,
                "local_input_roots": roots,
                "consumed_market_symbols": dependency.get("consumed_market_symbols", []),
                "derived_objects_withheld": withheld,
                "release_decision": "RESULTS_AND_MANIFESTS_ONLY_RAW_ROWS_WITHHELD",
                "portable_reproduction_status": dependency["portable_reproduction_status"],
            }
        )

    public_terms_reviewed = sum(
        policy["sources"][source_key].get("public_terms_review_status")
        == "COMPLETE_CONSERVATIVE_DECISION_RECORDED"
        and policy["sources"][source_key].get("terms_observed_on") == policy["review_date"]
        and bool(policy["sources"][source_key].get("terms_evidence"))
        for source_key in wave1_source_keys
    )
    external_clearances = sum(
        policy["sources"][source_key].get("external_publication_clearance_recorded") is True
        for source_key in wave1_source_keys
    )
    if public_terms_reviewed != len(wave1_source_keys):
        failures.append("WAVE1_PUBLIC_TERMS_REVIEW_INCOMPLETE")

    document: dict[str, Any] = {
        "schema": "canli.alphac-wave1-data-rights-audit.v2",
        "author": "Arhan Canli",
        "review_date": policy["review_date"],
        "status": (
            "PASS_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_REQUIRED"
            if not failures
            else "FAIL"
        ),
        "wave1_papers": len(records),
        "source_classes": len(policy["sources"]),
        "wave1_source_classes": len(wave1_source_keys),
        "public_terms_reviews_complete": public_terms_reviewed,
        "external_publication_clearances_recorded": external_clearances,
        "source_public_terms_review_complete": (
            public_terms_reviewed == len(wave1_source_keys)
        ),
        "external_publication_clearance_complete": (
            external_clearances == len(wave1_source_keys)
        ),
        "raw_vendor_rows_released": False,
        "policy_binding": {"path": str(POLICY.relative_to(ROOT)), "sha256": _sha256(POLICY)},
        "submission_plan_binding": {
            "path": str(SUBMISSION_PLAN.relative_to(ROOT)),
            "sha256": _sha256(SUBMISSION_PLAN),
            "content_hash": plan["content_hash"],
        },
        "records": records,
        "failures": failures,
        "remaining_blockers": [
            "MASSIVE_APPLICABLE_ORDER_FORM_OR_EXPRESS_WRITTEN_CONSENT_REQUIRED",
            "NASDAQ_APPLICABLE_ORDER_FORM_PERMISSION_OR_PRIOR_WRITTEN_APPROVAL_REQUIRED",
            "YAHOO_FINANCE_DERIVED_RESULT_PUBLICATION_NOT_CLEARED",
            "BINANCE_DERIVED_RESULT_PUBLICATION_NOT_EXPLICITLY_CLEARED",
            "ALPACA_ACCOUNT_AGGREGATE_OWNER_AND_CURRENT_TERMS_REVIEW_REQUIRED",
            "QUALIFIED_RIGHTS_REVIEW_REQUIRED_BEFORE_EXTERNAL_SUBMISSION",
            "PORTABLE_FETCH_RECIPES_AND_COVERAGE_MANIFESTS_NOT_COMPLETE",
            "FRESH_REVIEWER_ACQUISITION_NOT_EXECUTED",
        ],
        "claim_boundary": (
            "This audit proves that no raw tabular input file is inside a Wave 1 publication "
            "bundle and that a dated public-terms decision is recorded for each Wave 1 source "
            "class. It is not legal advice and does not establish account-specific permission, "
            "external-publication clearance, portable reproduction, or independent review."
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
