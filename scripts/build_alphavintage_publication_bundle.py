#!/usr/bin/env python3
"""Build the deterministic AlphaVintage external-publication source bundle.

The bundle is deliberately incomplete until a rendered archival PDF passes inspection and an
independent human reproduces the result. Building metadata must never advance those claims.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
OUT: Final = ROOT / "publication" / "alphavintage" / "v1.0.0"
VERSION: Final = "1.0.0"
RELEASE_DATE: Final = "2026-08-23"
TITLE: Final = (
    "Point-in-Time Inflation Surprise and the Equity Size Spread: A Corrected Null, a "
    "Deployment-Governance Failure, and a Frozen Forward Experiment"
)
PAPER: Final = ROOT / "docs/research/ALPHAVINTAGE_MACRO_SURPRISE_LINEAGE.md"
INPUTS: Final[dict[str, Path]] = {
    "result.json": ROOT / "artifacts/probe/cpi_surprise_size/result.json",
    "sealed_outcome.json": ROOT / "artifacts/engineering/alphavintage_sealed_outcome.json",
    "current_book_diversification.json": (
        ROOT / "artifacts/analysis/current_book_diversification/result.json"
    ),
    "book_without_alphavintage.json": (
        ROOT / "artifacts/analysis/book_without_alphavintage/result.json"
    ),
    "macro_family.json": ROOT / "artifacts/research/macro_economic_trend_family.json",
}
TRIAL_ACCOUNTING: Final = ROOT / "config/trial_accounting.json"
INTERNAL_REPLAY_RECEIPT: Final = (
    ROOT / "artifacts/audit/sleeve_publication_replay_verification.json"
)
ISOLATED_REPLAY_RECEIPT: Final = (
    ROOT / "artifacts/audit/sleeve_publication_isolated_replay_verification.json"
)
RTDSM_PORTABLE_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphavintage_rtdsm_portable_fetch.json"
)
CORE_PORTABLE_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphavintage_core_portable_reproduction.json"
)
FULL_DECISION_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphavintage_full_decision_clean_workspace.json"
)
FULL_DECISION_ATTEMPT_LEDGER: Final = (
    ROOT / "artifacts/publication/alphavintage_full_decision_replay_attempt_ledger.json"
)
ALPHATREND_UPSTREAM_MANIFEST: Final = (
    ROOT / "artifacts/publication/alphatrend_upstream_replay_manifest.json"
)
ALPHATREND_UPSTREAM_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphatrend_upstream_clean_workspace.json"
)
ALPHAMAX_UPSTREAM_MANIFEST: Final = (
    ROOT / "artifacts/publication/alphamax_upstream_replay_manifest.json"
)
ALPHAMAX_UPSTREAM_RECEIPT: Final = (
    ROOT / "artifacts/publication/alphamax_upstream_clean_workspace.json"
)
PREREG_INVESTMENT_LINEAGE: Final = (
    ROOT / "artifacts/publication/prereg_investment_historical_lineage.json"
)
PREREG_INVESTMENT_UPSTREAM_MANIFEST: Final = (
    ROOT / "artifacts/publication/prereg_investment_upstream_replay_manifest.json"
)
PREREG_INVESTMENT_UPSTREAM_RECEIPT: Final = (
    ROOT / "artifacts/publication/prereg_investment_upstream_clean_workspace.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _require_sources() -> None:
    for path in (
        PAPER,
        ROOT / "LICENSE",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        TRIAL_ACCOUNTING,
        INTERNAL_REPLAY_RECEIPT,
        ISOLATED_REPLAY_RECEIPT,
        RTDSM_PORTABLE_RECEIPT,
        CORE_PORTABLE_RECEIPT,
        FULL_DECISION_RECEIPT,
        FULL_DECISION_ATTEMPT_LEDGER,
        ALPHATREND_UPSTREAM_MANIFEST,
        ALPHATREND_UPSTREAM_RECEIPT,
        ALPHAMAX_UPSTREAM_MANIFEST,
        ALPHAMAX_UPSTREAM_RECEIPT,
        PREREG_INVESTMENT_LINEAGE,
        PREREG_INVESTMENT_UPSTREAM_MANIFEST,
        PREREG_INVESTMENT_UPSTREAM_RECEIPT,
        *INPUTS.values(),
    ):
        if not path.is_file():
            raise FileNotFoundError(path)


def _sanitized_alpaca_evidence() -> dict[str, Any]:
    source_path = ROOT / "artifacts/engineering/alpaca_broker_reconciliation.json"
    source = _json(source_path)
    sleeve = source["sleeves"]["alphavintage"]
    return {
        "schema": "canli.alphac-alphavintage-publication-alpaca-evidence.v1",
        "generated_at": source["generated_at"],
        "sleeve": "alphavintage",
        "broker": sleeve["broker"],
        "capital_kind": sleeve["capital_kind"],
        "account_status": sleeve["account_status"],
        "passes": sleeve["passes"],
        "checks": sleeve["checks"],
        "comparison_after_refresh": sleeve["comparison_after_refresh"],
        "portfolio_history_first_mark": sleeve["portfolio_history_first_mark"],
        "portfolio_history_last_mark": sleeve["portfolio_history_last_mark"],
        "current_equity_as_of": sleeve["current_equity_as_of"],
        "fill_outcome_reconciliation": sleeve["fill_outcome_reconciliation"],
        "source_binding": {
            "path": str(source_path.relative_to(ROOT)),
            "sha256": _sha256(source_path),
        },
        "excluded_fields": [
            "ACCOUNT_IDENTITY",
            "CURRENT_EQUITY_AMOUNT",
            "CURRENT_HOLDINGS",
            "OTHER_SLEEVE_ACCOUNTS",
        ],
        "claim_boundary": source["claim_boundary"],
    }


def _paper_metadata() -> dict[str, Any]:
    sealed = _json(INPUTS["sealed_outcome.json"])
    result = _json(INPUTS["result.json"])
    return {
        "schema": "canli.alphac-sleeve-paper.v1",
        "title": TITLE,
        "short_title": "Point-in-time inflation surprise and the equity size spread",
        "version": VERSION,
        "date": RELEASE_DATE,
        "language": "en",
        "type": "WORKING_PAPER_PREPRINT_NOT_PEER_REVIEWED",
        "authors": [
            {
                "given_name": "Arhan",
                "family_name": "Canli",
                "full_name": "Arhan Canli",
                "affiliation": "Canli Capital / AlphaC Algorithms",
                "roles": [
                    "CONCEPTUALIZATION",
                    "METHODOLOGY",
                    "SOFTWARE",
                    "VALIDATION",
                    "INVESTIGATION",
                    "DATA_CURATION",
                    "WRITING",
                    "PROJECT_ADMINISTRATION",
                ],
            }
        ],
        "abstract": (
            "A point-in-time CPI-surprise IWM-minus-SPY strategy appeared to pass its locked "
            "rules, but missing-release and active-day calendar defects invalidated that reading. "
            "A sealed, untuned correction produced net Sharpe 0.2298, Newey-West t 1.2673 and "
            "maximum drawdown -25.1%, so the result is KILLED. The separately labelled Alpaca "
            "paper sleeve remains a frozen forward experiment rather than validated alpha."
        ),
        "keywords": [
            "point-in-time data",
            "inflation surprise",
            "equity size spread",
            "research reproducibility",
            "backtest correction",
            "deployment governance",
            "quantitative finance",
        ],
        "capital_kind": "ALPACA_PAPER_AND_RESEARCH_SIMULATION_SEPARATELY_LABELLED",
        "primary_decision": result["verdict"],
        "primary_measurements": {
            "net_sharpe": sealed["net_sharpe"],
            "newey_west_t": sealed["newey_west_t"],
            "max_drawdown": sealed["max_drawdown"],
            "portfolio_days": sealed["portfolio_days"],
            "active_days": sealed["active_days"],
        },
        "failed_claims": [
            "THE_CORRECTED_STANDALONE_SIGNAL_PASSES_THE_LOCKED_SIGNIFICANCE_GATE",
            "ALPHAVINTAGE_IS_RESEARCH_ADMITTED",
            "THE_ALPACA_PAPER_RECORD_ESTABLISHES_FORWARD_PERFORMANCE",
            "HISTORICAL_DIVERSIFICATION_ESTABLISHES_PROSPECTIVE_DIVERSIFICATION",
        ],
        "external_identifiers": [],
        "peer_reviewed": False,
        "claim_boundary": (
            "This release is a preparation bundle, not an external submission. It establishes no "
            "funded performance, DOI, peer review, citation, independent replication, or future "
            "return."
        ),
    }


def _data_manifest() -> dict[str, Any]:
    curve = ROOT / "artifacts/probe/cpi_surprise_size/equity.parquet"
    return {
        "schema": "canli.alphac-publication-data-manifest.v1",
        "paper": "alphavintage",
        "version": VERSION,
        "sources": [
            {
                "name": "Philadelphia Fed Real-Time Data Set for Macroeconomists",
                "role": "point-in-time CPI and core-CPI vintage inputs",
                "public_documentation": (
                    "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/"
                    "real-time-data-set-for-macroeconomists"
                ),
                "point_in_time_field": "vintage_date",
                "license_status": "SOURCE_TERMS_REQUIRE_RELEASE_REVIEW",
                "raw_data_bundled": False,
            },
            {
                "name": "IWM, SPY, and QQQ daily market data",
                "role": "historical size-spread returns and the QQQ-minus-SPY placebo",
                "point_in_time_field": "ts_open",
                "license_status": "VENDOR_DERIVED_RAW_DATA_NOT_REDISTRIBUTED",
                "raw_data_bundled": False,
            },
            {
                "name": "Alpaca paper account",
                "role": "paper-only broker reconciliation",
                "point_in_time_field": "broker portfolio-history timestamp",
                "license_status": "SANITIZED_DERIVED_EVIDENCE_ONLY",
                "raw_data_bundled": False,
            },
        ],
        "derived_curve": {
            "path": str(curve.relative_to(ROOT)),
            "sha256": _sha256(curve),
            "rows": 6296,
            "bundled": False,
            "reason": (
                "A redistribution and source-licence review is required before releasing the "
                "derived curve outside the repository evidence interface."
            ),
        },
        "release_status": "INCOMPLETE_DATA_LICENCE_REVIEW_REQUIRED",
    }


def _reproduction() -> dict[str, Any]:
    internal_receipt = _json(INTERNAL_REPLAY_RECEIPT)
    isolated_receipt = _json(ISOLATED_REPLAY_RECEIPT)
    rtdsm_receipt = _json(RTDSM_PORTABLE_RECEIPT)
    core_receipt = _json(CORE_PORTABLE_RECEIPT)
    full_decision_receipt = _json(FULL_DECISION_RECEIPT)
    full_decision_attempts = _json(FULL_DECISION_ATTEMPT_LEDGER)
    alphatrend_manifest = _json(ALPHATREND_UPSTREAM_MANIFEST)
    alphatrend_receipt = _json(ALPHATREND_UPSTREAM_RECEIPT)
    alphamax_manifest = _json(ALPHAMAX_UPSTREAM_MANIFEST)
    alphamax_receipt = _json(ALPHAMAX_UPSTREAM_RECEIPT)
    prereg_investment_lineage = _json(PREREG_INVESTMENT_LINEAGE)
    prereg_investment_manifest = _json(PREREG_INVESTMENT_UPSTREAM_MANIFEST)
    prereg_investment_receipt = _json(PREREG_INVESTMENT_UPSTREAM_RECEIPT)
    commands = [
        "uv sync --frozen",
        "uv run python scripts/probe_cpi_surprise_size.py",
        "uv run python scripts/export_alphavintage_sealed_outcome.py",
        "uv run python scripts/analyze_current_book_diversification.py",
        "uv run python scripts/analyze_book_without_alphavintage.py",
    ]
    return {
        "schema": "canli.alphac-publication-reproduction.v1",
        "platform": "Python 3.12 via uv",
        "commands": commands,
        "environment_bindings": {
            "pyproject.toml": _sha256(ROOT / "pyproject.toml"),
            "uv.lock": _sha256(ROOT / "uv.lock"),
        },
        "code_bindings": {
            path: _sha256(ROOT / path)
            for path in (
                "scripts/probe_cpi_surprise_size.py",
                "scripts/export_alphavintage_sealed_outcome.py",
                "scripts/analyze_current_book_diversification.py",
                "scripts/analyze_book_without_alphavintage.py",
            )
        },
        "expected_output_bindings": {
            str(path.relative_to(ROOT)): _sha256(path) for path in INPUTS.values()
        },
        "internal_audit_replay": {
            "bundle_path": "internal_replay_receipt.json",
            "sha256": _sha256(INTERNAL_REPLAY_RECEIPT),
            "content_hash": internal_receipt["content_hash"],
            "replay_catalog_family_key": "macro_economic_trend",
            "sleeve_status": internal_receipt["sleeve_status"]["macro_economic_trend"],
        },
        "isolated_frozen_dependency_replay": {
            "bundle_path": "isolated_replay_receipt.json",
            "sha256": _sha256(ISOLATED_REPLAY_RECEIPT),
            "content_hash": isolated_receipt["content_hash"],
            "dependency_environment": isolated_receipt["dependency_environment"],
            "replay_catalog_family_key": "macro_economic_trend",
            "sleeve_status": isolated_receipt["sleeve_status"]["macro_economic_trend"],
            "portable_clean_workspace_replay_completed": False,
            "raw_input_portability_established": False,
        },
        "public_macro_input_reacquisition": {
            "bundle_path": "rtdsm_portable_fetch_receipt.json",
            "sha256": _sha256(RTDSM_PORTABLE_RECEIPT),
            "content_hash": rtdsm_receipt["content_hash"],
            "status": rtdsm_receipt["status"],
        },
        "portable_core_reproduction": {
            "bundle_path": "core_portable_reproduction_receipt.json",
            "sha256": _sha256(CORE_PORTABLE_RECEIPT),
            "content_hash": core_receipt["content_hash"],
            "status": core_receipt["status"],
            "exact_decision_checks": core_receipt["exact_decision_checks"],
            "full_diversification_checks_replayed": False,
            "independent_human_reproduction_completed": False,
        },
        "portable_full_decision_reproduction": {
            "bundle_path": "full_decision_clean_workspace_receipt.json",
            "sha256": _sha256(FULL_DECISION_RECEIPT),
            "content_hash": full_decision_receipt["content_hash"],
            "status": full_decision_receipt["status"],
            "numeric_equivalence_acceptance_passes": full_decision_receipt["passes"],
            "receipt_integrity_passes": full_decision_receipt["receipt_integrity_passes"],
            "exact_decision_checks": full_decision_receipt["exact_decision_checks"],
            "all_four_preregistered_decision_gates_replayed": True,
            "upstream_benchmark_strategies_regenerated_from_raw_inputs": False,
            "attempt_ledger": {
                "bundle_path": "full_decision_replay_attempt_ledger.json",
                "sha256": _sha256(FULL_DECISION_ATTEMPT_LEDGER),
                "content_hash": full_decision_attempts["content_hash"],
                "attempts_disclosed": full_decision_attempts["counts"]["attempts_disclosed"],
                "numeric_equivalence_acceptance_passes": full_decision_attempts["counts"][
                    "numeric_equivalence_acceptance_passes"
                ],
            },
            "independent_human_reproduction_completed": False,
        },
        "upstream_benchmark_strategy_reproduction": {
            "benchmark_strategies_total": 3,
            "completed_author_run_strategy_replays": 3,
            "historical_strategy_output_equivalence_established": 2,
            "all_benchmark_replay_attempts_completed": True,
            "all_historical_benchmark_outputs_exact": False,
            "alphatrend_mf_live_fwd": {
                "receipt_bundle_path": "alphatrend_upstream_clean_workspace_receipt.json",
                "receipt_sha256": _sha256(ALPHATREND_UPSTREAM_RECEIPT),
                "receipt_content_hash": alphatrend_receipt["content_hash"],
                "manifest_bundle_path": "alphatrend_upstream_replay_manifest.json",
                "manifest_sha256": _sha256(ALPHATREND_UPSTREAM_MANIFEST),
                "manifest_content_hash": alphatrend_manifest["content_hash"],
                "status": alphatrend_receipt["status"],
                "equity_curve_byte_exact": alphatrend_receipt["comparison"]["equity_curve"][
                    "bytes_exact"
                ],
                "byte_exact_output_files": alphatrend_receipt["comparison"]["output_tree"][
                    "byte_exact_files"
                ],
                "output_files": alphatrend_receipt["comparison"]["output_tree"]["reference_files"],
                "historical_dsr_selection_context_reproduced": False,
                "fresh_vendor_reacquisition_completed": False,
                "independent_human_reproduction_completed": False,
            },
            "alphamax_k30_dn_63": {
                "receipt_bundle_path": "alphamax_upstream_clean_workspace_receipt.json",
                "receipt_sha256": _sha256(ALPHAMAX_UPSTREAM_RECEIPT),
                "receipt_content_hash": alphamax_receipt["content_hash"],
                "manifest_bundle_path": "alphamax_upstream_replay_manifest.json",
                "manifest_sha256": _sha256(ALPHAMAX_UPSTREAM_MANIFEST),
                "manifest_content_hash": alphamax_manifest["content_hash"],
                "status": alphamax_receipt["status"],
                "fresh_vendor_strategy_replay_completed": True,
                "historical_strategy_output_equivalence_established": False,
                "historical_input_state_exact": False,
                "historical_dsr_gate_passed": False,
                "fresh_vendor_replay_dsr_gate_passed": False,
                "stored_historical_result_regraded": False,
                "independent_human_reproduction_completed": False,
            },
            "prereg_investment": {
                "strategy_curve_regenerated": True,
                "not_a_sleeve": True,
                "historical_pre_registration_covered_the_run": False,
                "lineage_bundle_path": "prereg_investment_historical_lineage.json",
                "lineage_sha256": _sha256(PREREG_INVESTMENT_LINEAGE),
                "lineage_content_hash": prereg_investment_lineage["content_hash"],
                "lineage_status": prereg_investment_lineage["status"],
                "input_manifest_bundle_path": ("prereg_investment_upstream_replay_manifest.json"),
                "input_manifest_sha256": _sha256(PREREG_INVESTMENT_UPSTREAM_MANIFEST),
                "input_manifest_content_hash": prereg_investment_manifest["content_hash"],
                "input_manifest_status": prereg_investment_manifest["status"],
                "receipt_bundle_path": "prereg_investment_upstream_clean_workspace_receipt.json",
                "receipt_sha256": _sha256(PREREG_INVESTMENT_UPSTREAM_RECEIPT),
                "receipt_content_hash": prereg_investment_receipt["content_hash"],
                "receipt_status": prereg_investment_receipt["status"],
                "historical_source_tree_exact": False,
                "raw_archive_normalization_replay_adjudicated": True,
                "raw_to_strategy_pipeline_replay_completed": True,
                "historical_full_artifact_byte_exact": True,
                "byte_exact_output_files": prereg_investment_receipt["comparison"][
                    "output_tree"
                ]["byte_exact_files"],
                "output_files": prereg_investment_receipt["comparison"]["output_tree"][
                    "reference_files"
                ],
                "historical_result_regraded": False,
                "independent_human_reproduction_completed": False,
            },
        },
        "core_clean_environment_reproduction_completed": True,
        "full_decision_clean_environment_reproduction_completed": True,
        "full_pipeline_clean_environment_reproduction_completed": False,
        "independent_human_reproduction_completed": False,
    }


def _references_bib() -> str:
    return """@techreport{croushore1999realtime,
  author = {Croushore, Dean and Stark, Tom},
  title = {A Real-Time Data Set for Macroeconomists: Does the Data Vintage Matter?},
  institution = {Federal Reserve Bank of Philadelphia},
  number = {99-21}, year = {1999}
}
@techreport{modugno2025decoding,
  author = {Modugno, Michele and Palazzo, Dino},
  title = {Decoding Equity Market Reactions to Macroeconomic News},
  institution = {Board of Governors of the Federal Reserve System},
  number = {2025-007}, year = {2025}, doi = {10.17016/FEDS.2025.007}
}
@techreport{pearce1984stock,
  author = {Pearce, Douglas K. and Roley, V. Vance},
  title = {Stock Prices and Economic News},
  institution = {National Bureau of Economic Research},
  number = {1296}, year = {1984}, doi = {10.3386/w1296}
}
@techreport{wachter2018macro,
  author = {Wachter, Jessica A. and Zhu, Yicheng},
  title = {The Macroeconomic Announcement Premium},
  institution = {National Bureau of Economic Research},
  number = {24432}, year = {2018}, doi = {10.3386/w24432}
}
"""


def _citation_cff() -> str:
    return f'''cff-version: 1.2.0
message: "If you use this working paper or evidence bundle, please cite Arhan Canli."
title: "{TITLE}"
type: article
version: "{VERSION}"
date-released: "{RELEASE_DATE}"
authors:
  - family-names: "Canli"
    given-names: "Arhan"
repository-code: "https://github.com/arhancanli/alphac"
url: "https://canlicapital.com/research/alphavintage-macro-surprise-lineage.md"
abstract: >-
  A corrected null and deployment-governance case study for a point-in-time CPI-surprise
  IWM-minus-SPY strategy. Preprint; not peer reviewed; Alpaca paper and simulation evidence are
  separately labelled.
'''


def _codemeta() -> dict[str, Any]:
    return {
        "@context": "https://doi.org/10.5063/schema/codemeta-2.0",
        "@type": "SoftwareSourceCode",
        "name": "ALPHAC AlphaVintage publication reproduction",
        "version": VERSION,
        "datePublished": RELEASE_DATE,
        "author": {"@type": "Person", "givenName": "Arhan", "familyName": "Canli"},
        "codeRepository": "https://github.com/arhancanli/alphac",
        "license": "https://spdx.org/licenses/MIT.html",
        "programmingLanguage": "Python 3.12",
        "applicationCategory": "Quantitative research reproducibility",
    }


def _corrections() -> str:
    return """# AlphaVintage corrections ledger

## 2026-08-16 — missing adjacent CPI release

The former signal path could reuse an older computable monthly change when the newest release and
its immediately preceding month were not both finite. The sealed correction fails closed and skips
the vintage. No return hypothesis was added.

## 2026-08-16 — active-day portfolio calendar

The former curve omitted zero-exposure exchange sessions and overstated annualized Sharpe. The
corrected curve retains all 6,296 sessions; active-day Sharpe 0.3382 is superseded by calendar-
correct net Sharpe 0.2298. The locked Newey-West t gate fails and the verdict is KILLED.

## 2026-08-19 — public correction latency

The public state retained the withdrawn 0.3403 Sharpe and 1.82 t-statistic for three days after the
sealed correction. The current source is bound to the corrected artifacts. The latency remains
disclosed as a deployment and publication-governance failure.
"""


def _readme() -> str:
    return """# AlphaVintage publication bundle v1.0.0

This is a deterministic **incomplete preparation bundle** for Arhan Canli's AlphaVintage working
paper. It is not peer reviewed and has not been submitted to SSRN, Zenodo, arXiv, or OSF.

The historical result is KILLED. Alpaca evidence is paper-only and sanitized. Raw vendor market
data and the derived return curve are not redistributed pending a source-licence review.

The core calculation and all four locked decision gates now have author-run temporary-workspace
replays from freshly reacquired macro and market inputs. The attempt ledger preserves one numeric
tolerance failure followed by one pass; both attempts retained the same four gates and KILLED
verdict. All three upstream benchmark strategies now have completed author-run replays. AlphaTrend
has a pinned-source replay
from a sealed private ETF lake: the AlphaVintage-consumed equity parquet is byte-exact, as are 466
of 467 output files. The sole mismatch is the DSR-bearing JSON because the historical 228-identity
selection context is absent from the pinned commit; that discrepancy is published and the stored
DSR is not regraded. AlphaMax's fresh-vendor replay completed but did not reproduce the historical
curve; both the historical and replayed DSR gates fail, and the stored result is not regraded. The
historical, non-sleeve `prereg_investment` raw-loader, universe, and strategy replay is byte-exact
for all 779 output files. Its original run remains non-preregistered historical gate input, not
sleeve evidence. Remaining release blockers include data-licence resolution, exact AlphaMax
historical-input recovery, full multi-sleeve end-to-end reproduction, and independent human
reproduction.
The publication-rendering stage adds
inspected PDF/HTML/LaTeX assets;
`SHA256SUMS` binds every released file.
"""


def _spdx() -> dict[str, Any]:
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "alphavintage-publication-bundle-v1.0.0",
        "documentNamespace": (
            "https://canlicapital.com/spdx/alphavintage-publication-bundle-v1.0.0"
        ),
        "creationInfo": {
            "created": "2026-08-23T00:00:00Z",
            "creators": ["Person: Arhan Canli", "Tool: ALPHAC bundle builder"],
        },
        "packages": [
            {
                "name": "alphavintage-publication-bundle",
                "SPDXID": "SPDXRef-Package",
                "versionInfo": VERSION,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "Copyright 2026 Arhan Canli",
            }
        ],
    }


def _ro_crate(out: Path) -> dict[str, Any]:
    files = sorted(path.name for path in out.iterdir() if path.is_file())
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": TITLE,
            "version": VERSION,
            "datePublished": RELEASE_DATE,
            "author": {"@id": "#arhan-canli"},
            "hasPart": [{"@id": name} for name in files if name != "ro-crate-metadata.json"],
        },
        {"@id": "#arhan-canli", "@type": "Person", "name": "Arhan Canli"},
    ]
    graph.extend({"@id": name, "@type": "File", "sha256": _sha256(out / name)} for name in files)
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


def build(out: Path = OUT) -> Path:
    _require_sources()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copyfile(PAPER, out / "paper.md")
    shutil.copyfile(ROOT / "LICENSE", out / "LICENSE")
    shutil.copyfile(INTERNAL_REPLAY_RECEIPT, out / "internal_replay_receipt.json")
    shutil.copyfile(ISOLATED_REPLAY_RECEIPT, out / "isolated_replay_receipt.json")
    shutil.copyfile(RTDSM_PORTABLE_RECEIPT, out / "rtdsm_portable_fetch_receipt.json")
    shutil.copyfile(CORE_PORTABLE_RECEIPT, out / "core_portable_reproduction_receipt.json")
    shutil.copyfile(FULL_DECISION_RECEIPT, out / "full_decision_clean_workspace_receipt.json")
    shutil.copyfile(FULL_DECISION_ATTEMPT_LEDGER, out / "full_decision_replay_attempt_ledger.json")
    shutil.copyfile(ALPHATREND_UPSTREAM_MANIFEST, out / "alphatrend_upstream_replay_manifest.json")
    shutil.copyfile(
        ALPHATREND_UPSTREAM_RECEIPT,
        out / "alphatrend_upstream_clean_workspace_receipt.json",
    )
    shutil.copyfile(ALPHAMAX_UPSTREAM_MANIFEST, out / "alphamax_upstream_replay_manifest.json")
    shutil.copyfile(
        ALPHAMAX_UPSTREAM_RECEIPT,
        out / "alphamax_upstream_clean_workspace_receipt.json",
    )
    shutil.copyfile(
        PREREG_INVESTMENT_LINEAGE,
        out / "prereg_investment_historical_lineage.json",
    )
    shutil.copyfile(
        PREREG_INVESTMENT_UPSTREAM_MANIFEST,
        out / "prereg_investment_upstream_replay_manifest.json",
    )
    shutil.copyfile(
        PREREG_INVESTMENT_UPSTREAM_RECEIPT,
        out / "prereg_investment_upstream_clean_workspace_receipt.json",
    )
    for name, source in INPUTS.items():
        shutil.copyfile(source, out / name)
    _write_json(out / "alpaca_paper_evidence.json", _sanitized_alpaca_evidence())
    _write_json(out / "paper.json", _paper_metadata())
    _write_json(out / "data_manifest.json", _data_manifest())
    _write_json(out / "reproduction.json", _reproduction())
    _write_json(
        out / "trial_accounting.json",
        {
            "schema": "canli.alphac-publication-trial-accounting-binding.v1",
            "registry_key": "alphavintage_macro_surprise",
            "global_ledger": {
                "path": str(TRIAL_ACCOUNTING.relative_to(ROOT)),
                "sha256": _sha256(TRIAL_ACCOUNTING),
            },
            "sleeve_family_result": {
                "path": str(INPUTS["macro_family.json"].relative_to(ROOT)),
                "sha256": _sha256(INPUTS["macro_family.json"]),
            },
            "sleeve_complete_union_extracted": True,
            "status": "BOUND_TO_RELEASED_FAMILY_RESULT",
        },
    )
    _write_json(out / "codemeta.json", _codemeta())
    _write_json(out / "sbom.spdx.json", _spdx())
    (out / "references.bib").write_text(_references_bib())
    (out / "CITATION.cff").write_text(_citation_cff())
    (out / "CORRECTIONS.md").write_text(_corrections())
    (out / "README.md").write_text(_readme())

    manifest = {
        "schema": "canli.alphac-publication-bundle-manifest.v2",
        "registry_key": "alphavintage_macro_surprise",
        "sleeve": "alphavintage",
        "version": VERSION,
        "status": "BUNDLE_INCOMPLETE",
        "author": "Arhan Canli",
        "files_before_inventory": sorted(path.name for path in out.iterdir()),
        "remaining_blockers": [
            "DATA_LICENCE_REVIEW_REQUIRED",
            "FULL_PIPELINE_CLEAN_ENVIRONMENT_REPLAY_NOT_COMPLETED",
            "INDEPENDENT_HUMAN_REPLICATION_MISSING",
        ],
        "doi_claimed": False,
        "external_submission_claimed": False,
        "independent_replication_claimed": False,
        "peer_review_claimed": False,
    }
    _write_json(out / "bundle_manifest.json", manifest)
    _write_json(out / "ro-crate-metadata.json", _ro_crate(out))

    checksum_files = sorted(path for path in out.iterdir() if path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_files)
    )
    return out


def main() -> int:
    out = build()
    print(f"wrote {out} ({len(list(out.iterdir()))} files)")
    print("status: BUNDLE_INCOMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
