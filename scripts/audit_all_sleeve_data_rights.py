#!/usr/bin/env python3
"""Audit all sleeve bundles for raw-row exclusion and conservative source mapping.

This is an operational publication control, not a legal opinion. It deliberately
keeps source mapping, redistribution posture, replayability and archive integrity
as separate claims.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
POLICY: Final = ROOT / "config" / "data_source_rights_policy.json"
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
OUTPUT: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
WAVE_ONE: Final = {
    "alphavintage_macro_surprise",
    "alphaforge_crypto_carry",
    "alphamax_equity_momentum",
    "alphatrend_managed_futures",
    "crypto_multifactor_engine",
}

RAW_INPUT_EXTENSIONS: Final = {
    ".arrow",
    ".csv",
    ".db",
    ".duckdb",
    ".feather",
    ".jsonl",
    ".parquet",
    ".sqlite",
    ".tsv",
    ".xls",
    ".xlsx",
    ".zip",
}

# A conservative superset is intentional where legacy ledgers mixed instrument
# namespaces or data-lake profiles. The notes preserve that uncertainty instead
# of pretending that a namespace proves a vendor contract.
DEPENDENCIES: Final[dict[str, dict[str, Any]]] = {
    "alphavintage_macro_surprise": {
        "sources": [
            "PHILADELPHIA_FED_RTDSM",
            "YAHOO_FINANCE_MARKET_DATA",
            "ALPACA_PRIVATE_ACCOUNT",
        ],
        "local_input_roots": ["data/lake_macro_vintage", "data/lake_mf"],
        "evidence_bindings": ["docs/research/ALPHAVINTAGE_MACRO_SURPRISE_LINEAGE.md"],
        "mapping_notes": [
            "Research simulation and Alpaca paper evidence remain separately labelled."
        ],
    },
    "alphaforge_crypto_carry": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "evidence_bindings": ["docs/research/CRYPTO_CARRY_LINEAGE.md"],
        "mapping_notes": [],
    },
    "alphamax_equity_momentum": {
        "sources": [
            "MASSIVE_POLYGON_MARKET_DATA",
            "NASDAQ_SHARADAR",
            "YAHOO_FINANCE_MARKET_DATA",
        ],
        "local_input_roots": ["data/lake", "data/lake_sharadar", "data/lake_mf"],
        "evidence_bindings": ["docs/research/ALPHAMAX_EQUITY_MOMENTUM_LINEAGE.md"],
        "mapping_notes": [
            "Multiple historical equity and benchmark lakes contributed to the family."
        ],
    },
    "alphatrend_managed_futures": {
        "sources": ["YAHOO_FINANCE_MARKET_DATA"],
        "local_input_roots": ["data/lake_mf"],
        "evidence_bindings": ["docs/research/ALPHATREND_MANAGED_FUTURES_LINEAGE.md"],
        "mapping_notes": [],
    },
    "crypto_multifactor_engine": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "evidence_bindings": ["docs/research/CRYPTO_MULTIFACTOR_ENGINE_LINEAGE.md"],
        "mapping_notes": [],
    },
    "crypto_defensive": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA", "MASSIVE_POLYGON_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "evidence_bindings": [
            "artifacts/research/crypto_defensive_family.json",
            "artifacts/provenance/legacy_identity_input_provenance.json",
            "docs/research/CRYPTO_DEFENSIVE_LINEAGE.md",
        ],
        "mapping_notes": [
            "Legacy frozen identities contain both BINANCE and XUSE namespaces; the source map "
            "is a conservative superset and does not relabel the family result."
        ],
    },
    "crypto_momentum": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA", "MASSIVE_POLYGON_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "evidence_bindings": [
            "artifacts/research/crypto_momentum_family.json",
            "artifacts/provenance/legacy_identity_input_provenance.json",
            "docs/research/CRYPTO_MOMENTUM_LINEAGE.md",
        ],
        "mapping_notes": [
            "Most identities are Binance-only; one persisted experiment included XUSE in its "
            "recorded namespace set, so the map conservatively retains that dependency."
        ],
    },
    "crypto_reversal": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA"],
        "local_input_roots": ["data/lake"],
        "evidence_bindings": [
            "artifacts/research/crypto_reversal_family.json",
            "docs/research/CRYPTO_REVERSAL_LINEAGE.md",
        ],
        "mapping_notes": [],
    },
    "crypto_vrp": {
        "sources": ["BINANCE_EXCHANGE_MARKET_DATA", "DERIBIT_MARKET_DATA"],
        "local_input_roots": ["data/lake", "data/deribit/dvol_index"],
        "evidence_bindings": [
            "scripts/exp2_crypto_vrp.py",
            "artifacts/research/crypto_vrp_family.json",
        ],
        "mapping_notes": [
            "DVOL/realized-volatility proxy only; no options-surface P&L is claimed."
        ],
    },
    "energy_inventory": {
        "sources": ["EIA_PUBLIC_DATA", "YAHOO_FINANCE_MARKET_DATA"],
        "local_input_roots": ["data/lake_inventory_releases", "data/lake_inventory"],
        "evidence_bindings": [
            "scripts/ingest_eia_wpsr.py",
            "artifacts/probe/eia_petroleum_inventory/input_data_manifest.json",
            "artifacts/provenance/energy_inventory_source_provenance.json",
        ],
        "mapping_notes": [
            "A sanitized historical execution receipt and the exact persisted row counts, date "
            "bounds, partition hashes and shared ingestion timestamp map the ETF rows to the "
            "Yahoo-adjusted loader. This is local provenance evidence, not an independent "
            "attestation or redistribution grant."
        ],
    },
    "equity_insider_activity": {
        "sources": [
            "SEC_PUBLIC_DATA_AND_FILINGS",
            "NASDAQ_SHARADAR",
            "YAHOO_FINANCE_MARKET_DATA",
        ],
        "local_input_roots": ["data/lake_insider", "data/lake_sharadar", "data/lake_mf"],
        "evidence_bindings": [
            "data/lake_insider/manifest.json",
            "scripts/probe_insider_clusters.py",
        ],
        "mapping_notes": [],
    },
    "equity_low_beta": {
        "sources": [
            "BINANCE_EXCHANGE_MARKET_DATA",
            "MASSIVE_POLYGON_MARKET_DATA",
            "NASDAQ_SHARADAR",
        ],
        "local_input_roots": ["data/lake", "data/lake_sharadar"],
        "evidence_bindings": [
            "artifacts/research/equity_low_beta_family.json",
            "artifacts/provenance/legacy_identity_input_provenance.json",
            "docs/research/EQUITY_LOW_BETA_LINEAGE.md",
        ],
        "mapping_notes": [
            "Legacy identity configurations include mixed BINANCE/XUSE namespaces and both "
            "default and Sharadar-era ledgers; this is disclosed rather than normalized away."
        ],
    },
    "equity_narrative_change": {
        "sources": [
            "SEC_PUBLIC_DATA_AND_FILINGS",
            "NASDAQ_SHARADAR",
            "YAHOO_FINANCE_MARKET_DATA",
        ],
        "local_input_roots": ["data/lake_sharadar", "data/lake_mf"],
        "evidence_bindings": [
            "artifacts/probe/earnings_narrative_change/input_data_manifest.json",
            "scripts/probe_earnings_narrative_change.py",
        ],
        "mapping_notes": [],
    },
    "equity_quality": {
        "sources": [
            "BINANCE_EXCHANGE_MARKET_DATA",
            "MASSIVE_POLYGON_MARKET_DATA",
            "NASDAQ_SHARADAR",
        ],
        "local_input_roots": ["data/lake", "data/lake_sharadar"],
        "evidence_bindings": [
            "artifacts/research/equity_quality_family.json",
            "artifacts/provenance/legacy_identity_input_provenance.json",
            "docs/research/EQUITY_QUALITY_LINEAGE.md",
        ],
        "mapping_notes": [
            "The frozen family spans mixed BINANCE/XUSE default-lake identities and "
            "Sharadar-ledger identities; no vendor-purity claim is made."
        ],
    },
    "equity_value_investment": {
        "sources": [
            "BINANCE_EXCHANGE_MARKET_DATA",
            "MASSIVE_POLYGON_MARKET_DATA",
            "NASDAQ_SHARADAR",
        ],
        "local_input_roots": ["data/lake", "data/lake_sharadar"],
        "evidence_bindings": [
            "artifacts/research/equity_value_investment_family.json",
            "artifacts/provenance/legacy_identity_input_provenance.json",
            "docs/research/EQUITY_VALUE_INVESTMENT_LINEAGE.md",
        ],
        "mapping_notes": [
            "The frozen family spans mixed BINANCE/XUSE default-lake identities and "
            "Sharadar-ledger identities; no vendor-purity claim is made."
        ],
    },
    "macro_economic_trend": {
        "sources": [
            "FRED_ECONOMIC_DATA",
            "PHILADELPHIA_FED_RTDSM",
            "YAHOO_FINANCE_MARKET_DATA",
        ],
        "local_input_roots": ["data/lake_macro_vintage", "data/lake_mf"],
        "evidence_bindings": [
            "scripts/probe_econtrend_data.py",
            "artifacts/research/macro_economic_trend_family.json",
        ],
        "mapping_notes": [
            "FRED series retain series-specific ownership restrictions; raw rows remain "
            "withheld pending a series-by-series review."
        ],
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _raw_input_files(bundle_dir: Path) -> list[str]:
    return sorted(
        str(path.relative_to(bundle_dir))
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in RAW_INPUT_EXTENSIONS
    )


def build() -> dict[str, Any]:
    policy = json.loads(POLICY.read_text())
    registry = json.loads(REGISTRY.read_text())
    failures: list[str] = []
    records: list[dict[str, Any]] = []

    sleeves = registry["sleeves"]
    planned_keys = {record["key"] for record in sleeves}
    if planned_keys != set(DEPENDENCIES):
        failures.append("DEPENDENCY_MAP_DOES_NOT_MATCH_ALL_PLANNED_SLEEVES")

    for paper in sleeves:
        key = paper["key"]
        dependency = DEPENDENCIES.get(key)
        if dependency is None:
            continue
        manifest_path = ROOT / paper["bundle_manifest"]
        bundle_dir = manifest_path.parent
        data_manifest_path = bundle_dir / "data_manifest.json"
        raw_files = _raw_input_files(bundle_dir)
        if raw_files:
            failures.append(f"{key}:RAW_INPUT_FILES_PRESENT_IN_PUBLICATION_BUNDLE")
        if not manifest_path.is_file():
            failures.append(f"{key}:BUNDLE_MANIFEST_MISSING")
        if not data_manifest_path.is_file():
            failures.append(f"{key}:DATA_MANIFEST_MISSING")
            data_manifest: dict[str, Any] = {}
        else:
            data_manifest = json.loads(data_manifest_path.read_text())

        source_records: list[dict[str, Any]] = []
        for source_key in dependency["sources"]:
            source = policy["sources"].get(source_key)
            if source is None:
                failures.append(f"{key}:UNKNOWN_SOURCE_CLASS:{source_key}")
                continue
            source_records.append({"source_key": source_key, **source})

        roots = [
            {
                "path": value,
                "present_in_author_workspace": (ROOT / value).exists(),
                "released_in_bundle": False,
            }
            for value in dependency["local_input_roots"]
        ]
        evidence = []
        for value in dependency["evidence_bindings"]:
            path = ROOT / value
            if not path.is_file():
                failures.append(f"{key}:PROVENANCE_EVIDENCE_MISSING:{value}")
            evidence.append(
                {
                    "path": value,
                    "present": path.is_file(),
                    "sha256": _sha256(path) if path.is_file() else None,
                }
            )

        unresolved = dependency.get("unresolved_source_dependencies", [])
        public_terms_review_complete = bool(source_records) and all(
            source.get("public_terms_review_status")
            == "COMPLETE_CONSERVATIVE_DECISION_RECORDED"
            and bool(source.get("terms_observed_on"))
            and bool(source.get("terms_evidence"))
            for source in source_records
        )
        external_publication_clearance_complete = bool(source_records) and all(
            source.get("external_publication_clearance_recorded") is True
            for source in source_records
        )
        records.append(
            {
                "registry_key": key,
                "wave": 1 if key in WAVE_ONE else 2,
                "bundle": str(bundle_dir.relative_to(ROOT)),
                "bundle_raw_input_files": raw_files,
                "raw_third_party_rows_released": False,
                "source_dependencies": source_records,
                "local_input_roots": roots,
                "provenance_evidence": evidence,
                "mapping_notes": dependency["mapping_notes"],
                "unresolved_source_dependencies": unresolved,
                "source_mapping_complete": not unresolved,
                "data_manifest_license_review_complete": (
                    data_manifest.get("license_review_complete") is True
                ),
                "source_public_terms_review_complete": public_terms_review_complete,
                "external_publication_clearance_complete": (
                    external_publication_clearance_complete
                ),
                "release_decision": "RESULTS_MANIFESTS_AND_PAPERS_ONLY_RAW_INPUT_ROWS_EXCLUDED",
            }
        )

    raw_row_free = sum(not record["bundle_raw_input_files"] for record in records)
    rights_complete = sum(record["data_manifest_license_review_complete"] for record in records)
    public_terms_complete = sum(
        record["source_public_terms_review_complete"] for record in records
    )
    external_clearance_complete = sum(
        record["external_publication_clearance_complete"] for record in records
    )
    mapping_complete = sum(record["source_mapping_complete"] for record in records)
    document: dict[str, Any] = {
        "schema": "canli.alphac-all-sleeve-data-rights-audit.v1",
        "author": "Arhan Canli",
        "review_date": policy["review_date"],
        "status": (
            "PASS_RAW_ROW_EXCLUSION_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_INCOMPLETE"
            if not failures and public_terms_complete == len(records)
            else "FAIL"
        ),
        "counts": {
            "planned_sleeves": len(sleeves),
            "audited_sleeves": len(records),
            "raw_row_free_bundles": raw_row_free,
            "source_mapping_complete": mapping_complete,
            "data_license_reviews_complete": rights_complete,
            "public_terms_reviews_complete": public_terms_complete,
            "external_publication_clearances_complete": external_clearance_complete,
            "policy_source_classes": len(policy["sources"]),
        },
        "raw_third_party_rows_released": False,
        "redistribution_rights_cleared_for_all_sleeves": False,
        "records": records,
        "failures": failures,
        "remaining_blockers": [
            "ACCOUNT_SPECIFIC_LICENSE_OR_WRITTEN_PUBLICATION_PERMISSION_REQUIRED",
            "MASSIVE_AND_NASDAQ_DERIVED_OUTPUT_PERMISSION_NOT_RECORDED",
            "YAHOO_AND_BINANCE_DERIVED_OUTPUT_PUBLICATION_NOT_CLEARED",
            "QUALIFIED_RIGHTS_REVIEW_REQUIRED_BEFORE_EXTERNAL_SUBMISSION",
            "LEGACY_EXACT_HISTORICAL_INPUT_ROW_RECEIPTS_NOT_AVAILABLE_FOR_ALL_IDENTITIES",
            "CLEAN_ENVIRONMENT_REPLAY_NOT_COMPLETED",
            "INDEPENDENT_REPLICATION_NOT_COMPLETED",
        ],
        "source_bindings": {
            "policy": {"path": str(POLICY.relative_to(ROOT)), "sha256": _sha256(POLICY)},
            "publication_registry": {
                "path": str(REGISTRY.relative_to(ROOT)),
                "sha256": _sha256(REGISTRY),
            },
        },
        "claim_boundary": (
            "This audit proves only that all audited publication bundles exclude files with the "
            "declared raw-input extensions, records a conservative source map, and binds every "
            "source class to a dated public-terms decision. It is not legal advice, does not grant "
            "account-specific or external-publication rights, does not establish complete "
            "run-level provenance, and does not constitute result reproduction or independent "
            "review."
        ),
    }
    if len(records) != len(sleeves) or raw_row_free != len(sleeves):
        if "ALL_PLANNED_BUNDLES_NOT_AUDITED_RAW_ROW_FREE" not in failures:
            failures.append("ALL_PLANNED_BUNDLES_NOT_AUDITED_RAW_ROW_FREE")
        document["status"] = "FAIL"
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
