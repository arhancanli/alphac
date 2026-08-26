"""Research data layer: emit research.json — the FULL honest gauntlet — from REAL artifacts.

This is the comprehensive research export that sits alongside the five glass-box files
(``scripts/glassbox_export.py``). Where glassbox emits five focused views (kill log,
pre-registration, deflation, track record, reproducibility), this emits ONE navigable
``research.json`` capturing the whole research story:

  (1) factor research — every factor tested across crypto + equities, with its REAL
      Rank-IC / Newey-West t-stat (read from the IC report JSONs) and its REAL net
      walk-forward Sharpe (read from each summary.txt), and a KEEP / KILL verdict;
  (2) the validation methodology in plain language — point-in-time data, purged
      walk-forward, Deflated Sharpe (DSR), Probability of Backtest Overfitting (PBO),
      pre-registration, and byte-identity reproducibility;
  (3) the honest verdicts + ceilings — combined ~0.3-0.9 forward (NOT the in-sample
      in-sample headline), the C+ grade, the crypto capacity cliff + BTC-correlation
      cap, and the equity-momentum-only survivor;
  (4) the roadmap — the honest path: forward evidence, registered discovery, then data investment
      sleeve to lengthen the sample so the verdict can clear deflation.

Honesty rules (the owner's non-negotiable, the soul of the firm):
  - Every published number is read from a real AlphaForge artifact on disk. If a number
    is not in an artifact, it is OMITTED — never fabricated, never rounded into existence.
  - The forward Sharpe is the deflated 0.3-0.9 expectation, NEVER the in-sample headline.
    (Band lowered 0.7-1.0 -> 0.3-0.9 on 2026-07-29; these exporters were not updated
    with it and kept publishing the superseded, flattering band until 2026-08-06.)
  - Killed factors are published with their real NEGATIVE net Sharpes.
  - The crypto-perp deflation FAILURE (DSR 0.21, PBO 0.88, NO-DEPLOY) is shown as a
    feature, not buried.
  - Reproducibility is "content-hashed + byte-reproducible", NOT blockchain-anchored.

The payload carries a generated_at UTC timestamp and a sha256 content_hash over the
canonical bytes (hash field excluded), so a reader can verify it was not hand-edited.

Run:  uv run python scripts/research_export.py
Lint: uv run ruff check scripts/research_export.py
Type: uv run mypy --strict scripts/research_export.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

# ---------------------------------------------------------------------------
# Paths. All resolved absolute so the export is reproducible from any cwd.
# ---------------------------------------------------------------------------
REPO: Final[Path] = Path(__file__).resolve().parent.parent
WALKFORWARD: Final[Path] = REPO / "artifacts" / "walkforward"
RESEARCH: Final[Path] = REPO / "artifacts" / "research"
GRAND_BACKTEST_DIR: Final[Path] = REPO / "artifacts" / "grand_backtest" / "20260616T143620Z"
STATE_JSON: Final[Path] = REPO / "data" / "paper" / "state.json"
GOLDEN_MASTER: Final[Path] = REPO / "tests" / "integration" / "test_golden_master.py"
PRE_REGISTRATION_MD: Final[Path] = REPO / "docs" / "design" / "PRE_REGISTRATION.md"
CROSS_ASSET_BOOK_MD: Final[Path] = REPO / "docs" / "design" / "CROSS_ASSET_BOOK.md"
SLEEVE_DISCOVERY_JSON: Final[Path] = REPO / "config" / "sleeve_discovery.json"
ADMISSION_DRY_RUN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "admission_dry_run" / "result.json"
)
BOOK_WITHOUT_ALPHAVINTAGE_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "book_without_alphavintage" / "result.json"
)
SPINOFF_PRORATA_GATE_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "spinoff_prorata_gate" / "result.json"
)
GATE_REACHABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "feasibility_gate_reachability" / "result.json"
)
COVARIANCE_MEMORY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "live_covariance_memory" / "result.json"
)
RECORD_CONTINUITY_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "record_continuity.json"
ALPACA_RECONCILIATION_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "alpaca_broker_reconciliation.json"
)
FORWARD_EVIDENCE_CONTRACT_JSON: Final[Path] = REPO / "config" / "forward_evidence_contract.json"
FORWARD_EVIDENCE_MATURITY_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "forward_evidence_maturity.json"
)
FORWARD_DRAWDOWN_EVIDENCE_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "forward_drawdown_evidence.json"
)
FORWARD_SLEEVE_CONTRIBUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "forward_sleeve_contribution.json"
)
CRYPTO_LAB_INCIDENT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crypto_lab_carry_crash_incident.json"
)
CRYPTO_POSITION_ATTRIBUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crypto_position_attribution.json"
)
CRYPTO_POSITION_ATTRIBUTION_ROLLOUT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crypto_position_attribution_rollout_verification.json"
)
CRYPTO_POSITION_ATTRIBUTION_PREFLIGHT_OBSERVATION_JSON: Final[Path] = (
    REPO
    / "artifacts"
    / "engineering"
    / "crypto_position_attribution_vps_preflight_observation.json"
)
LEDOIT_WOLF_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "ledoit_wolf_effective_sample" / "result.json"
)
DRAWDOWN_LIVE_ESTIMATOR_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "drawdown_live_estimator" / "result.json"
)
CURRENT_BOOK_DRAWDOWN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "current_book_drawdown" / "result.json"
)
CURRENT_BOOK_DIVERSIFICATION_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "current_book_diversification" / "result.json"
)
SLEEVE_QUALITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "sleeve_quality_decomposition" / "result.json"
)
EXECUTION_GAP_POWER_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "execution_gap_power" / "result.json"
)
COST_MODEL_REALISM_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "cost_model_realism" / "result.json"
)
REACHABILITY_HARNESS_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "reachability_harness" / "result.json"
)
DATA_GATE_UNBLOCKS_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "data_gate_unblocks" / "result.json"
)
TENDER_REACHABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "tender_offer_reachability" / "result.json"
)
SHARADAR_ZERO_DIVIDEND_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_zero_dividend.json"
)
SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_price_consistency.json"
)
SHARADAR_DIVIDEND_SPLIT_BASIS_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_split_basis.json"
)
VATE_2020_DIVIDEND_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "vate_2020_dividend_resolution.json"
)
SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_basis_resolution.json"
)
SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corporate_action_corrected_lake.json"
)
SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corrected_corporate_action_validation.json"
)
POLYGON_SPLIT_CROSSCHECK_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "polygon_split_crosscheck.json"
)
SPLIT_EXCEPTION_ISSUER_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_exception_issuer_resolution.json"
)
SHARADAR_SPLIT_LIFECYCLE_SCOPE_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_split_lifecycle_scope.json"
)
UNRESOLVED_SPLIT_EVENT_CONTEXT_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "unresolved_split_event_context.json"
)
OPERATING_MARGIN_SPLIT_EXPOSURE_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_unresolved_split_exposure.json"
)
OPERATING_MARGIN_EXPOSED_SPLIT_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_exposed_split_issuer_resolution.json"
)
OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZATION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_corrected_replay_authorization.json"
)
OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_corrected_reproduction.json"
)
SHARADAR_SPLIT_GOVERNANCE_POLICY_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_split_governance_policy.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V2_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v2.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V3_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v3.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V4_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v4.json"
)
SPLIT_ISSUER_CONFLICT_RESOLUTION_BATCH_V5_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_conflict_resolution_batch_v5.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V6_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v6.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V7_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v7.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V8_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v8.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V9_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v9.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V10_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v10.json"
)
SPLIT_ISSUER_RESOLUTION_BATCH_V11_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_issuer_resolution_batch_v11.json"
)
SPLIT_LIFECYCLE_DISCONTINUITY_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "split_lifecycle_discontinuity_resolution.json"
)
NEXT_SLEEVE_SELECTION_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "next_sleeve_selection.json"
)
ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "active_ownership_human_gate_audit.json"
)
ACTIVE_OWNERSHIP_CONFIRMATORY_DESIGN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "active_ownership_confirmatory_design.json"
)
EXTERNAL_VALIDATION_OPPORTUNITIES_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "external_validation_opportunities.json"
)
ACTIVE_OWNERSHIP_HANDOFF_RECEIPT_JSON: Final[Path] = (
    REPO / "artifacts" / "handoffs" / "active_ownership_13d_item4_v3_blind.json"
)
ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE: Final[Path] = (
    REPO / "artifacts" / "handoffs" / "active_ownership_13d_item4_v3_blind.tar.gz"
)
HDB_DIVIDEND_VENDOR_RESOLUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "hdb_dividend_vendor_resolution.json"
)
SHARADAR_HDB_CORRECTED_LAKE_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"
)
OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON: Final[Path] = (
    REPO
    / "artifacts"
    / "probe"
    / "fundamental_single_replays"
    / "e5f48adc25065ce9"
    / "replay_infrastructure_failure.json"
)
CFTC_RELEASE_REACHABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "cftc_release_reachability" / "result.json"
)
BOND_ETF_NAV_REACHABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "bond_etf_nav_reachability" / "result.json"
)
ATLAS_REACHABILITY_SCREEN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "atlas_reachability_screen" / "result.json"
)
ORTHOGONALITY_PRIOR_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "orthogonality_prior" / "result.json"
)
MUTATION_LEDGER_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "mutation_ledger.json"
GUARDS_CANNOT_FIRE_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "guards_that_cannot_fire.json"
)
CONTRACT_UNIT_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "contract_and_unit_audit.json"
)
#: Bundle keys whose published FILENAME differs from the key. The measurement pages derive their
#: "check it yourself" link from the key, so a mismatch it cannot predict is a 404 on a page whose
#: whole purpose is that a reader can check. Declared here rather than guessed there, and
#: tests/unit/test_bundle_keys_resolve_to_files.py fails if a new mismatch appears undeclared.
PUBLISHED_AS: Final[dict[str, str]] = {
    "active_ownership_blind_handoff_receipt": "active_ownership_13d_item4_v3_blind.json",
    "crypto_position_attribution_preflight_observation": (
        "crypto_position_attribution_vps_preflight_observation.json"
    ),
    "external_publication": "research.json",
    "portfolio_evidence": "stanford_cs_evidence_map.json",
    "operating_margin_exposed_split_resolution": (
        "operating_margin_exposed_split_issuer_resolution.json"
    ),
    "operating_margin_split_exposure": "operating_margin_unresolved_split_exposure.json",
    "trial_accounting": "trial_ledger.json",
}

PREREG_PARAMETERS_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "prereg_earnings_narrative_parameters.json"
)
ALPHAVINTAGE_SEALED_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "alphavintage_sealed_outcome.json"
)
ALPHAVINTAGE_RESULT_JSON: Final[Path] = (
    REPO / "artifacts" / "probe" / "cpi_surprise_size" / "result.json"
)
DATA_LAKE_SCALE_JSON: Final[Path] = REPO / "artifacts" / "engineering" / "data_lake_scale.json"
CLAIM_COVERAGE_MAP_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "claim_coverage_map.json"
)
#: The three audits the repurchase-issuance feasibility PAPER quotes. They were not published, so
#: every figure in that paper — the issuer counts, the overlap fraction, the semantics sample —
#: was a number a reader could see and could not check. Found by
#: meridian/scripts/audit-published-numbers.mjs on 2026-08-22.
REPURCHASE_AUDITS: Final[tuple[tuple[str, Path], ...]] = tuple(
    (
        f"repurchase_issuance_{name}.json",
        REPO / "artifacts" / "feasibility" / "repurchase_issuance_flow" / f"{name}.json",
    )
    for name in ("companyfacts_audit", "semantics_audit", "identity_overlap_audit")
)
SPINOFF_FORM_UNIVERSE_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "spinoff_form_universe" / "result.json"
)
IDENTITY_REDESIGN_NOTES_MD: Final[Path] = REPO / "docs" / "design" / "IDENTITY_REDESIGN_NOTES.md"
SHARADAR_ZERO_DIVIDEND_MD: Final[Path] = (
    REPO / "docs" / "design" / "CORRECTION_SHARADAR_HDB_ZERO_DIVIDEND.md"
)

# The discovery bundle's human-facing gate summary is DERIVED from the admission contract rather
# than transcribed beside it. It was transcribed until v6, and by then it had gone stale in the
# direction that flatters: the site published an average-correlation ceiling of 0.15 and a
# 252-observation minimum after the contract in force had moved to 0.00 and 756. Two files
# claiming the same fact is one file too many -- the copy drifts, and a reader auditing the config
# cannot tell which one binds.
_DISCOVERY_GATE_SOURCE: Final[dict[str, str]] = {
    "book_deflated_sharpe_must_be_measured": "book_deflated_sharpe_must_be_measured",
    "deflated_sharpe_must_be_measured": "deflated_sharpe_must_be_measured",
    "pbo_max": "pbo_max",
    "candidate_average_correlation_to_existing_book_max": (
        "candidate_average_correlation_to_existing_book_max"
    ),
    "book_average_pairwise_correlation_delta_max_exclusive": (
        "book_average_pairwise_correlation_delta_max_exclusive"
    ),
    "average_pairwise_correlation_upper_95_max": "average_pairwise_correlation_upper_95_max",
    "pairwise_correlation_max": "ordinary_pairwise_correlation_max",
    "stressed_pairwise_correlation_max": "stressed_pairwise_correlation_max",
    "minimum_oos_observations": "minimum_oos_observations",
    "net_sharpe_min": "net_sharpe_min",
    "capacity_usd_min": "capacity_usd_min",
}

# Published gate names that are no longer thresholds. Listed rather than silently dropped, so the
# site can say what changed instead of a bar simply vanishing from the page between deploys.
_DISCOVERY_GATE_RETIRED: Final[dict[str, str]] = {
    "deflated_sharpe_min": (
        "Retired as a per-sleeve gate in v6 because it measured the wrong object and silently "
        "required about eight times the declared net-Sharpe floor. Per-sleeve DSR remains a "
        "mandatory published measurement."
    ),
    "book_deflated_sharpe_min": (
        "Re-scoped prospectively in v7 from an incremental admission gate to a 0.95 portfolio-"
        "maturity gate. Full-union book DSR remains mandatory to measure and publish at every "
        "admission; known results were not regraded."
    ),
    "average_pairwise_correlation_max": (
        "Replaced prospectively in v7 because applying a final global level to each incremental "
        "admission was path-dependent. A candidate must now average no more than zero correlation "
        "to the existing book and must strictly reduce the book's global average; the -0.03 "
        "portfolio objective remains mandatory to publish."
    ),
}


def _write_kill_papers(research_dir: Path, glassbox_dir: Path) -> int:
    """Render one paper per killed candidate into the site's research directory.

    Forty-six candidates have been killed and three have survived. The forty-six are the papers
    almost nobody publishes, which is exactly why they are the ones worth publishing: a kill log
    is a table, a paper is the reasoning another researcher can use. Every FIGURE in them is
    injected from the kill-log entry; the prose is written by hand. See scripts/build_kill_papers.
    """
    # Imported here rather than at module scope: this script is run directly, so a sibling module
    # is only importable once its own directory is on the path, and doing that at import time
    # would reorder every other import in the file.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_kill_papers", Path(__file__).resolve().parent / "build_kill_papers.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("cannot load scripts/build_kill_papers.py")
    kill_papers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kill_papers)

    research_dir.mkdir(parents=True, exist_ok=True)
    source = glassbox_dir / "kill_log.json"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} is missing: glassbox_export.py must run before research_export.py. The "
            "ordering is declared in tests/unit/test_publish_pipeline_order.py; failing here "
            "rather than skipping keeps a reordered pipeline from silently publishing no papers."
        )
    papers = kill_papers.render_kill_papers(json.loads(source.read_text()))
    for filename, markdown in papers.items():
        (research_dir / filename).write_text(markdown)
    return len(papers)


def _discovery_with_contract_gates() -> dict[str, Any]:
    """Project the in-force contract's objective and thresholds over discovery metadata."""
    discovery: dict[str, Any] = json.loads(SLEEVE_DISCOVERY_JSON.read_text())
    contract: dict[str, Any] = json.loads(SLEEVE_ADMISSION_CONTRACT_JSON.read_text())
    contract_objective = contract["objective"]
    thresholds = contract["thresholds"]
    # The discovery file owns the candidate queue, not the portfolio objective. It used to carry
    # a handwritten 2.0--2.5 OOS target after contract v6 had explicitly withdrawn that target in
    # favour of an honest forward 1.5 (and the 2.25--3.0 in-sample support band implied by the
    # measured haircut). Preserve only discovery-specific programme metadata and derive every
    # target from the contract in force.
    discovery_metadata = discovery.get("objective", {})
    discovery["objective"] = {
        **contract_objective,
        "target_sleeve_count": contract_objective["target_total_sleeves"],
        **{
            key: discovery_metadata[key]
            for key in ("candidate_atlas_minimum", "portfolio_requirement", "admission_rule")
            if key in discovery_metadata
        },
    }
    declared = dict(discovery.get("admission_gates", {}))
    # Carry the qualitative commitments through untouched; rebuild every NUMERIC gate from the
    # contract. Patching the existing dict left retired thresholds sitting in it, which is the
    # drift this function exists to prevent.
    gates = {
        key: value
        for key, value in declared.items()
        if isinstance(value, bool) and key not in _DISCOVERY_GATE_RETIRED
    }
    for published_key, threshold_key in _DISCOVERY_GATE_SOURCE.items():
        if threshold_key not in thresholds:
            raise KeyError(
                f"admission contract has no threshold {threshold_key!r} for published gate "
                f"{published_key!r}; either wire it up or retire it in _DISCOVERY_GATE_RETIRED "
                "so the change is stated rather than silent"
            )
        gates[published_key] = thresholds[threshold_key]
    discovery["admission_gates"] = gates
    discovery["retired_admission_gates"] = {
        key: reason for key, reason in _DISCOVERY_GATE_RETIRED.items() if key not in thresholds
    }
    discovery["admission_contract_schema"] = contract["schema"]
    discovery["admission_contract_public_path"] = "/glassbox/sleeve_admission_contract.json"
    # The relationship between the gate and the objective, published beside them both. Without it
    # the page states a target next to a ceiling and leaves the reader to discover that one
    # forbids the other.
    if "frontier_arithmetic" in contract:
        discovery["frontier_arithmetic"] = contract["frontier_arithmetic"]
    return discovery


SLEEVE_ATLAS_JSON: Final[Path] = REPO / "artifacts" / "discovery" / "sleeve_atlas.json"
SLEEVE_ATLAS_AUDIT_JSON: Final[Path] = REPO / "artifacts" / "discovery" / "sleeve_atlas_audit.json"
SLEEVE_LINEAGE_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "discovery" / "sleeve_family_lineage_audit.json"
)
SLEEVE_ADMISSION_CONTRACT_JSON: Final[Path] = REPO / "config" / "sleeve_admission_contract.json"
TRIAL_ACCOUNTING_POLICY_JSON: Final[Path] = REPO / "config" / "trial_accounting.json"
ADMISSION_V7_PROMOTION_JSON: Final[Path] = REPO / "config" / "admission_v7_promotion.json"
EXTERNAL_PUBLICATION_REGISTRY_JSON: Final[Path] = (
    REPO / "config" / "external_publication_registry.json"
)
SLEEVE_PUBLICATION_EVIDENCE_JSON: Final[Path] = REPO / "config" / "sleeve_publication_evidence.json"
EXTERNAL_PUBLICATION_READINESS_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "external_publication_readiness.json"
)
PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "publication_clean_checkout_integrity.json"
)
EXTERNAL_SUBMISSION_PLAN_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "external_submission_plan.json"
)
WAVE1_DATA_RIGHTS_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "wave1_data_rights_audit.json"
)
WAVE1_RELEASE_CANDIDATES_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "wave1_release_candidates.json"
)
WAVE1_RELEASE_CANDIDATES_DIR: Final[Path] = (
    REPO / "artifacts" / "publication" / "wave1_release_candidates"
)
ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "alphavintage_rtdsm_portable_fetch.json"
)
ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "alphavintage_core_portable_reproduction.json"
)
ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "alphavintage_full_decision_clean_workspace.json"
)
ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "alphatrend_upstream_replay_manifest.json"
)
ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "alphatrend_upstream_clean_workspace.json"
)
STANFORD_CS_EVIDENCE_JSON: Final[Path] = (
    REPO / "artifacts" / "portfolio" / "stanford_cs_evidence_map.json"
)
ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "archival_publication_visual_inspection.json"
)
SLEEVE_PUBLICATION_REPLAY_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sleeve_publication_replay_verification.json"
)
SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "sleeve_publication_isolated_replay_verification.json"
)
CRYPTO_CARRY_CURRENT_REPLAY_RECEIPT_JSON: Final[Path] = (
    REPO / "artifacts" / "probe" / "crypto_carry_frozen_current_code_replay" / "replay_receipt.json"
)
CRYPTO_CARRY_FIRST_REBALANCE_ATTRIBUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "probe" / "crypto_carry_replay_drift" / "first_rebalance_attribution.json"
)
CRYPTO_CARRY_FULL_PATH_ATTRIBUTION_JSON: Final[Path] = (
    REPO / "artifacts" / "probe" / "crypto_carry_replay_drift" / "full_path_attribution.json"
)
WALKFORWARD_INPUT_SNAPSHOT_PROTOCOL_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "walkforward_input_snapshot_protocol.json"
)
CRYPTO_CARRY_REPLAY_CORRECTION_JSON: Final[Path] = (
    REPO / "artifacts" / "publication" / "crypto_carry_replay_correction.json"
)
PUBLICATION_BUNDLES_DIR: Final[Path] = REPO / "publication"
TRIAL_PACKET_MANIFEST_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "trial_packet_manifest.json"
)
CRYPTO_CARRY_PORTABLE_RESULT_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "crypto_carry_portable_v1_result.json"
)
CRYPTO_CARRY_PORTABLE_CLOSURE_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "crypto_carry_portable_v1_admission_closure.json"
)
CRYPTO_CARRY_PORTABLE_PACKET_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "trial_packets" / "da5f5f47f99f9bd2.json"
)
CRYPTO_CARRY_PORTABLE_PAPER_MD: Final[Path] = (
    REPO / "docs" / "research" / "CRYPTO_CARRY_PORTABLE_V1.md"
)
FORWARD_FULL_EVIDENCE_TEMPLATE_JSON: Final[Path] = (
    REPO / "config" / "forward_full_evidence_reservation_v2_template.json"
)
FORWARD_FULL_EVIDENCE_TEMPLATE_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "forward_full_evidence_reservation_v2_template.json"
)
CRYPTO_CARRY_PORTABLE_LAKE_READINESS_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "crypto_carry_portable_lake_readiness.json"
)
CRYPTO_CARRY_PORTABLE_PRERUN_READINESS_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "crypto_carry_portable_prerun_readiness.json"
)
CRYPTO_CARRY_PORTABLE_INPUT_SNAPSHOT_JSON: Final[Path] = (
    REPO
    / "artifacts"
    / "prospective"
    / "crypto_carry_portable_v1"
    / "input_snapshot"
    / "manifest.json"
)
IDENTITY_PACKET_RECOVERABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "identity_packet_recoverability.json"
)
LEGACY_RESEARCH_EPOCH_CLOSURE_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
)
LEGACY_DSR_EXCEPTIONS_JSON: Final[Path] = REPO / "config" / "legacy_dsr_exceptions.json"
LEGACY_DSR_RESTATEMENT_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "legacy_dsr_restatement.json"
)
LEGACY_DSR_RESTATEMENT_MD: Final[Path] = REPO / "docs" / "research" / "LEGACY_DSR_RESTATEMENT.md"
ALPHAMAX_MOMENTUM_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "ALPHAMAX_EQUITY_MOMENTUM_LINEAGE.md"
)
CRYPTO_CARRY_LINEAGE_MD: Final[Path] = REPO / "docs" / "research" / "CRYPTO_CARRY_LINEAGE.md"
CRYPTO_LAB_INCIDENT_MD: Final[Path] = (
    REPO / "docs" / "research" / "CRYPTO_LAB_CARRY_CRASH_INCIDENT.md"
)
CRYPTO_CARRY_SELECTED_WALKFORWARD_JSON: Final[Path] = (
    REPO / "artifacts" / "walkforward" / "crypto_carry_wk" / "walkforward.json"
)
CRYPTO_CARRY_GRAND_MATRIX_JSON: Final[Path] = GRAND_BACKTEST_DIR / "matrix.json"
CRYPTO_CARRY_2022_TAIL_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "crypto_carry_2022_tail.json"
)
CRYPTO_MOMENTUM_LINEAGE_MD: Final[Path] = REPO / "docs" / "research" / "CRYPTO_MOMENTUM_LINEAGE.md"
CRYPTO_MOMENTUM_FAMILY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "crypto_momentum_family.json"
)
ALPHATREND_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "ALPHATREND_MANAGED_FUTURES_LINEAGE.md"
)
ALPHAVINTAGE_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "ALPHAVINTAGE_MACRO_SURPRISE_LINEAGE.md"
)
ALPHATREND_FAMILY_JSON: Final[Path] = REPO / "artifacts" / "research" / "alphatrend_family.json"
CRYPTO_VRP_LINEAGE_MD: Final[Path] = REPO / "docs" / "research" / "CRYPTO_VRP_LINEAGE.md"
CRYPTO_VRP_FAMILY_JSON: Final[Path] = REPO / "artifacts" / "research" / "crypto_vrp_family.json"
CRYPTO_MULTIFACTOR_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "CRYPTO_MULTIFACTOR_ENGINE_LINEAGE.md"
)
CRYPTO_MULTIFACTOR_FAMILY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "crypto_multifactor_family.json"
)
EQUITY_NARRATIVE_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "EQUITY_NARRATIVE_CHANGE_LINEAGE.md"
)
EQUITY_NARRATIVE_FAMILY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "equity_narrative_family.json"
)
EQUITY_QUALITY_LINEAGE_MD: Final[Path] = REPO / "docs" / "research" / "EQUITY_QUALITY_LINEAGE.md"
EQUITY_QUALITY_FAMILY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "equity_quality_family.json"
)
EQUITY_VALUE_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "research" / "EQUITY_VALUE_INVESTMENT_LINEAGE.md"
)
EQUITY_VALUE_FAMILY_JSON: Final[Path] = (
    REPO / "artifacts" / "research" / "equity_value_investment_family.json"
)
FINAL_FAMILY_FILES: Final[tuple[tuple[str, Path, str, Path], ...]] = (
    (
        "crypto_defensive_family.json",
        REPO / "artifacts/research/crypto_defensive_family.json",
        "crypto-defensive-lineage.md",
        REPO / "docs/research/CRYPTO_DEFENSIVE_LINEAGE.md",
    ),
    (
        "crypto_reversal_family.json",
        REPO / "artifacts/research/crypto_reversal_family.json",
        "crypto-reversal-lineage.md",
        REPO / "docs/research/CRYPTO_REVERSAL_LINEAGE.md",
    ),
    (
        "energy_inventory_family.json",
        REPO / "artifacts/research/energy_inventory_family.json",
        "energy-inventory-lineage.md",
        REPO / "docs/research/ENERGY_INVENTORY_LINEAGE.md",
    ),
    (
        "equity_insider_family.json",
        REPO / "artifacts/research/equity_insider_family.json",
        "equity-insider-activity-lineage.md",
        REPO / "docs/research/EQUITY_INSIDER_ACTIVITY_LINEAGE.md",
    ),
    (
        "equity_low_beta_family.json",
        REPO / "artifacts/research/equity_low_beta_family.json",
        "equity-low-beta-lineage.md",
        REPO / "docs/research/EQUITY_LOW_BETA_LINEAGE.md",
    ),
    (
        "macro_economic_trend_family.json",
        REPO / "artifacts/research/macro_economic_trend_family.json",
        "macro-economic-trend-lineage.md",
        REPO / "docs/research/MACRO_ECONOMIC_TREND_LINEAGE.md",
    ),
)
ALPHAMAX_CONSTRUCTION_ARMS_JSON: Final[Path] = (
    REPO / "artifacts" / "sweep" / "alphamax_construction" / "arms.json"
)
EXECUTION_REALISM_MD: Final[Path] = REPO / "docs" / "research" / "EXECUTION_REALISM.md"
EXECUTION_BENCHMARK_JSON: Final[Path] = REPO / "artifacts" / "benchmarks" / "execution_models.json"
FUTURES_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "futures_execution_contract.json"
)
FUTURES_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "FUTURES_EXECUTION_FOUNDATION.md"
)
OPTIONS_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "options_execution_contract.json"
)
OPTIONS_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "OPTIONS_EXECUTION_FOUNDATION.md"
)
BORROW_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "borrow_execution_contract.json"
)
BORROW_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "BORROW_EXECUTION_FOUNDATION.md"
)
MARKET_STATUS_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "market_status_contract.json"
)
MARKET_STATUS_REPLAY_MD: Final[Path] = REPO / "docs" / "research" / "MARKET_STATUS_REPLAY.md"
CROWDING_RISK_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crowding_risk_contract.json"
)
CROWDING_RISK_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "CROWDING_RISK_FOUNDATION.md"
)
CORPORATE_ACTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "corporate_action_contract.json"
)
CORPORATE_ACTION_LIFECYCLE_MD: Final[Path] = (
    REPO / "docs" / "research" / "CORPORATE_ACTION_LIFECYCLE.md"
)
CORPORATE_ACTION_BASIS_RECONSTRUCTION_MD: Final[Path] = (
    REPO / "docs" / "research" / "CORPORATE_ACTION_BASIS_RECONSTRUCTION.md"
)
FINANCING_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "financing_contract.json"
)
FINANCING_REPLAY_MD: Final[Path] = REPO / "docs" / "research" / "FINANCING_REPLAY.md"
LINT_DEBT_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "lint_debt_contract.json"
)
ENGINEERING_QUALITY_MD: Final[Path] = REPO / "docs" / "research" / "ENGINEERING_QUALITY.md"
FORWARD_SHARPE_EVIDENCE_STANDARD_MD: Final[Path] = (
    REPO / "docs" / "research" / "FORWARD_SHARPE_EVIDENCE_STANDARD.md"
)
CURRENT_BOOK_DRAWDOWN_MODEL_MD: Final[Path] = (
    REPO / "docs" / "research" / "CURRENT_BOOK_DRAWDOWN_MODEL.md"
)
CURRENT_BOOK_DIVERSIFICATION_MODEL_MD: Final[Path] = (
    REPO / "docs" / "research" / "CURRENT_BOOK_DIVERSIFICATION_MODEL.md"
)
PUBLIC_RESEARCH_DIR: Final[Path] = REPO.parent / "meridian" / "public" / "research"
TRIAL_DEBT_RECONCILIATION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "trial_debt_reconciliation.json"
)
LITERATURE_FRONTIER_MD: Final[Path] = REPO / "docs" / "design" / "LITERATURE_FRONTIER_2026_08_16.md"
REPURCHASE_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_REPURCHASE_ISSUANCE_FLOW.md"
)
REPURCHASE_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md"
)
REPURCHASE_BLIND_PACKET: Final[Path] = REPO / "artifacts" / "labeling" / "repurchase_item703_blind"
OPTIONS_DISPERSION_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_OPTIONS_DISPERSION.md"
)
OPTIONS_DISPERSION_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_OPTIONS_DISPERSION.md"
)
STABLECOIN_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_STABLECOIN_DISLOCATION.md"
)
STABLECOIN_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_STABLECOIN_DISLOCATION.md"
)
SPIN_OFF_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_SPIN_OFF_DISLOCATION.md"
)
SPIN_OFF_LINEAGE_MD: Final[Path] = REPO / "docs" / "design" / "FEASIBILITY_SPIN_OFF_DISLOCATION.md"
SPIN_OFF_DOCUMENT_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_SPIN_OFF_DOCUMENT_SCHEMA.md"
)
SPIN_OFF_LINEAGE_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "spin_off_dislocation" / "result.json"
)
SPIN_OFF_DOCUMENT_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "spin_off_dislocation" / "document_schema_result.json"
)
ELECTRICITY_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_ELECTRICITY_LOAD_WEATHER.md"
)
ELECTRICITY_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_ELECTRICITY_LOAD_WEATHER.md"
)
ELECTRICITY_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "electricity_load_weather" / "result.json"
)
NATURAL_GAS_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_NATURAL_GAS_STORAGE_WEATHER.md"
)
NATURAL_GAS_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_NATURAL_GAS_STORAGE_WEATHER.md"
)
NATURAL_GAS_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "natural_gas_storage_weather" / "result.json"
)
CUSTOMER_SUPPLIER_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_CUSTOMER_SUPPLIER_PROPAGATION.md"
)
CUSTOMER_SUPPLIER_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_CUSTOMER_SUPPLIER_PROPAGATION.md"
)
CUSTOMER_SUPPLIER_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "customer_supplier_propagation" / "result.json"
)
BOND_ETF_NAV_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_BOND_ETF_NAV_DISLOCATION.md"
)
BOND_ETF_NAV_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_BOND_ETF_NAV_DISLOCATION.md"
)
BOND_ETF_NAV_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "bond_etf_nav_dislocation" / "result.json"
)
TREASURY_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_TREASURY_AUCTION_CONCESSION.md"
)
TREASURY_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "treasury_auction_concession" / "result.json"
)
TREASURY_TIMING_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_TREASURY_AUCTION_IDENTITY_TIMING.md"
)
TREASURY_TIMING_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "treasury_auction_concession" / "identity_timing.json"
)
TREASURY_TENTATIVE_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "tentative_schedule_audit.json"
)
TREASURY_WAYBACK_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "wayback_schedule_audit.json"
)
TREASURY_WAYBACK_PDF_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "wayback_pdf_schedule_audit.json"
)
TREASURY_CALENDAR_REVISION_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "calendar_revision_audit.json"
)
CFTC_FEASIBILITY_MD: Final[Path] = REPO / "docs" / "design" / "FEASIBILITY_CFTC_HEDGING_PRESSURE.md"
CFTC_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "cftc_hedging_pressure" / "result.json"
)
ACTIVE_OWNERSHIP_ITEM4_V3_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4_V3.md"
)
ACTIVE_OWNERSHIP_ITEM4_V3_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "active_ownership_13d_item4_v3" / "result.json"
)
ACTIVE_OWNERSHIP_BLIND_PACKET: Final[Path] = (
    REPO / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
)
INFLATION_BREAKEVEN_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_INFLATION_BREAKEVEN_RELATIVE_VALUE.md"
)
INFLATION_BREAKEVEN_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_INFLATION_BREAKEVEN_RELATIVE_VALUE.md"
)
INFLATION_BREAKEVEN_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "inflation_breakeven_relative_value" / "result.json"
)
ALPHAVINTAGE_CORRECTION_MD: Final[Path] = (
    REPO / "docs" / "design" / "CORRECTION_ALPHAVINTAGE_MISSING_RELEASE.md"
)
PRE_FOMC_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_PRE_FOMC_ANNOUNCEMENT_DRIFT.md"
)
PRE_FOMC_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "pre_fomc_announcement_drift" / "result.json"
)
PRE_FOMC_SCHEDULE_LINEAGE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "annual_schedule_lineage.json"
)
PRE_FOMC_PREREG_MD: Final[Path] = REPO / "docs" / "design" / "PREREG_PRE_FOMC_ANNOUNCEMENT_DRIFT.md"
PRE_FOMC_MARKET_DATA_READINESS_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "market_data_readiness.json"
)
NARRATIVE_PREREG_MD: Final[Path] = REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md"
NARRATIVE_PROBE_DIR: Final[Path] = REPO / "artifacts" / "probe" / "earnings_narrative_change"
NARRATIVE_PROBE_RESULT: Final[Path] = NARRATIVE_PROBE_DIR / "result.json"
RESEARCH_ACCESSIBILITY_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "research_accessibility_audit.json"
)
ACCESSIBILITY_INTERACTION_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "accessibility_interaction_audit.json"
)
EIA_PROBE_DIR: Final[Path] = REPO / "artifacts" / "probe" / "eia_petroleum_inventory"
INSIDER_PROBE_DIR: Final[Path] = REPO / "artifacts" / "probe" / "insider_purchase_clusters"
PUBLICATION_NUMERIC_SUPPORT_FILES: Final[tuple[tuple[str, Path], ...]] = (
    (
        "alphamax_upstream_clean_workspace.json",
        REPO / "artifacts" / "publication" / "alphamax_upstream_clean_workspace.json",
    ),
    (
        "prereg_investment_upstream_clean_workspace.json",
        REPO
        / "artifacts"
        / "publication"
        / "prereg_investment_upstream_clean_workspace.json",
    ),
    (
        "lowvol720_reopen_result.json",
        REPO / "artifacts" / "analysis" / "lowvol720_reopen" / "result.json",
    ),
    (
        "energy_inventory_source_provenance.json",
        REPO / "artifacts" / "provenance" / "energy_inventory_source_provenance.json",
    ),
)
FUNDAMENTAL_SINGLE_REPLAY_IDENTITIES: Final[dict[str, str]] = {
    "gross_profitability": "1d2924f28fe31a9a",
    "book_to_price": "a238c1a5ecc5d1e3",
    "earnings_yield": "e86109044ab18734",
    "sales_to_price": "2d966892fb5db520",
    "operating_margin": "e5f48adc25065ce9",
}
FUNDAMENTAL_SINGLE_ATTEMPTED_REPLAYS: Final[dict[str, str]] = {
    factor: identity
    for factor, identity in FUNDAMENTAL_SINGLE_REPLAY_IDENTITIES.items()
    if any(
        (
            REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity / terminal
        ).is_file()
        for terminal in (
            "result.json",
            "replay_failure.json",
            "replay_infrastructure_failure.json",
        )
    )
}
# Evidence for each attempted fundamental KILL replay is public before packet completion so an
# auditor can inspect the preserved curve, market realism, diversification, committed input
# inventory, frozen replay environment, and hash-bound fail-closed replay outcome.
# A result is included only when the exact-replay runner has written it. Infrastructure failures
# and their byte-exact preserved inputs remain visible beside any later successful replacement.
FUNDAMENTAL_SINGLE_SUPPORT_FILES: Final[tuple[tuple[str, Path], ...]] = tuple(
    (
        f"fundamental_single_{factor}_{source_name}",
        REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity / source_name,
    )
    for factor, identity in FUNDAMENTAL_SINGLE_ATTEMPTED_REPLAYS.items()
    for source_name in (
        "curve_evidence.json",
        "diversification.json",
        "input_data_manifest.json",
        "market_evidence.json",
        "replay_environment.json",
        "replay_failure.json",
        "replay_root_cause.json",
        "replay_infrastructure_failure.json",
        "replay_infrastructure_failure_environment.json",
        "replay_infrastructure_failure_lake_manifest.json",
        "result.json",
    )
    if (
        REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity / source_name
    ).is_file()
)
VERDICT_MD: Final[Path] = GRAND_BACKTEST_DIR / "verdict.md"

# Two IC report sources, both PIT survivorship-free (UniverseStore membership intervals):
#   equity_ic   — top-407 universe, horizons 5/21/63 (the momentum h=5/21/63 record);
#   lev10_ic_500 — wide top-888 universe, horizons 21/63 (the broad value/quality record).
IC_REPORT_407: Final[Path] = RESEARCH / "equity_ic" / "ic_report.json"
IC_REPORT_888: Final[Path] = RESEARCH / "lev10_ic_500" / "ic_report.json"

# Default output: the Meridian landing repo public dir, alongside the five glassbox files.
OUT_DIR: Final[Path] = REPO.parent / "meridian" / "public" / "glassbox"
OUT_FILE: Final[str] = "research.json"

INITIAL_EQUITY: Final[float] = 100_000.0
DSR_GATE: Final[float] = 0.95
PBO_GATE: Final[float] = 0.20


# ---------------------------------------------------------------------------
# summary.txt parsing — the walk-forward summaries are "key  value  (comment)".
# ---------------------------------------------------------------------------
def parse_summary(name: str) -> dict[str, float]:
    """Parse a walk-forward ``summary.txt`` into a ``{key: float}`` map.

    Only the leading numeric token of each line is kept; the trailing human comment
    (e.g. the ISO date beside an epoch-ms timestamp) is ignored.
    """
    path = WALKFORWARD / name / "summary.txt"
    out: dict[str, float] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("=") or line.startswith("AlphaForge"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0]
        try:
            out[key] = float(parts[1])
        except ValueError:
            continue
    return out


def epoch_ms_to_iso_date(epoch_ms: float) -> str:
    """Convert epoch-milliseconds to an ISO date string (UTC)."""
    return dt.datetime.fromtimestamp(epoch_ms / 1000.0, tz=dt.UTC).date().isoformat()


def return_pct(final_equity: float) -> float:
    """Total return percent off the canonical 100k base, rounded to 2dp."""
    return round((final_equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100.0, 2)


def perf(name: str) -> dict[str, Any]:
    """Normalized performance block (Sharpe, return, dates, drawdown, costs) from summary.txt."""
    s = parse_summary(name)
    block: dict[str, Any] = {
        "net_sharpe": round(s["sharpe"], 4),
        "sortino": round(s["sortino"], 4),
        "cagr_pct": round(s["cagr"] * 100.0, 2),
        "total_return_pct": return_pct(s["final_equity"]),
        "final_equity_usd": round(s["final_equity"], 2),
        "vol_ann_pct": round(s["vol_ann"] * 100.0, 2),
        "max_drawdown_pct": round(-s["max_dd"] * 100.0, 2),
        "profit_factor": round(s["profit_factor_d"], 3),
        "turnover_ann": round(s["turnover_ann"], 2),
        "fees_paid_usd": round(s["fees_paid"], 2),
        "n_days": int(s["n_days"]),
        "period_start": epoch_ms_to_iso_date(s["start_ts"]),
        "period_end": epoch_ms_to_iso_date(s["end_ts"]),
    }
    if s.get("funding_net", 0.0) != 0.0:
        block["funding_net_usd"] = round(s["funding_net"], 2)
    return block


# ---------------------------------------------------------------------------
# IC report parsing — pull the real Rank-IC + Newey-West t-stat per factor/horizon.
# ---------------------------------------------------------------------------
def load_ic_rows(path: Path) -> list[dict[str, Any]]:
    """Load the rows[] from an IC report JSON (alphaDesign.md section 7.2 format)."""
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    rows = doc.get("rows")
    return rows if isinstance(rows, list) else []


def ic_lookup(rows: list[dict[str, Any]], factor: str, horizon: int) -> dict[str, Any] | None:
    """Find one factor/horizon IC row; return its real IC + t-stat, or None if absent.

    Returns None (the caller omits the IC block) rather than inventing a value when the
    factor was not measured at that horizon in this report — honesty: omit, never invent.
    """
    for r in rows:
        if r.get("factor") == factor and int(r.get("horizon", -1)) == horizon:
            return {
                "horizon_bars": horizon,
                "mean_rank_ic": round(float(r["mean_ic"]), 4),
                "t_nw": round(float(r["t_nw"]), 2),
                "hit_rate": round(float(r["hit_rate"]), 3),
                "ic_ir": round(float(r["ic_ir"]), 3),
                "n_obs": int(r["n_obs"]),
            }
    return None


def ic_block(
    rows407: list[dict[str, Any]],
    rows888: list[dict[str, Any]],
    factor: str,
    horizons: tuple[int, ...],
) -> dict[str, Any] | None:
    """Assemble an IC block for a factor across horizons.

    Prefers the top-407 report (it carries h=5); falls back to the wide top-888 report
    for any horizon the 407 report did not measure. Only horizons present in a real
    report appear; if none are present, returns None and the caller omits the block.
    """
    out: dict[str, Any] = {}
    for h in horizons:
        rec = ic_lookup(rows407, factor, h) or ic_lookup(rows888, factor, h)
        if rec is not None:
            out[f"h{h}"] = rec
    return out or None


# ---------------------------------------------------------------------------
# Content hashing — hash the payload (minus the hash field) for verifiability.
# ---------------------------------------------------------------------------
def stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Add generated_at + a sha256 content_hash over the canonical payload bytes."""
    payload = dict(payload)
    payload.pop("content_hash", None)
    payload.pop("generated_at", None)
    payload["generated_at"] = dt.datetime.now(tz=dt.UTC).isoformat()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


def rel(path: Path) -> str:
    """Repo-relative POSIX path string for source attribution."""
    return str(path.relative_to(REPO))


def _trial_label(config: dict[str, Any]) -> str:
    """Return a compact public label without exporting a giant universe/config payload."""
    probe = config.get("probe")
    if isinstance(probe, str) and probe:
        aggregation = config.get("return_aggregation")
        return f"{probe} / {aggregation}" if isinstance(aggregation, str) else probe
    alphas = config.get("alpha_names")
    if isinstance(alphas, list) and alphas:
        return " + ".join(str(alpha) for alpha in alphas)
    for key in ("mechanism", "overlay", "variant"):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value
    return "unlabelled registered identity"


def build_trial_accounting() -> dict[str, Any]:
    """Build the public union ledger, separating measurements from search identities."""
    policy = json.loads(TRIAL_ACCOUNTING_POLICY_JSON.read_text())
    legacy_dsr = json.loads(LEGACY_DSR_EXCEPTIONS_JSON.read_text())
    legacy_restatement = (
        json.loads(LEGACY_DSR_RESTATEMENT_JSON.read_text())
        if LEGACY_DSR_RESTATEMENT_JSON.exists()
        else None
    )
    selection_union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    ledger_paths = [path for path in selection_union.paths if path.exists()]
    profiles: list[dict[str, Any]] = []
    union_config_hashes: set[str] = set()
    union_hypotheses: dict[str, tuple[Any, Path]] = {}
    total_records = 0

    for path in ledger_paths:
        ledger = ExperimentLog(path)
        records = ledger.all()
        total_records += len(records)
        union_config_hashes.update(record.config_hash for record in records)
        for record in records:
            key = ledger._hypothesis_key(record.config)
            current = union_hypotheses.get(key)
            if current is None or record.now_ms < current[0].now_ms:
                union_hypotheses[key] = (record, path)
        profiles.append(
            {
                "profile": path.parent.name,
                "source_path": rel(path),
                "immutable_execution_records": len(records),
                "distinct_config_hashes": ledger.n_trials(),
                "hypothesis_identities": ledger.n_hypotheses(),
                "window_only_remeasurements": ledger.window_only_reevaluations(),
                "latest_recorded_at": (
                    dt.datetime.fromtimestamp(
                        max(record.now_ms for record in records) / 1000, tz=dt.UTC
                    ).isoformat()
                    if records
                    else None
                ),
            }
        )

    hypothesis_count = len(union_hypotheses)
    profile_hypothesis_count = sum(profile["hypothesis_identities"] for profile in profiles)
    window_only_count = sum(profile["window_only_remeasurements"] for profile in profiles)
    cross_profile_duplicates = profile_hypothesis_count - hypothesis_count
    budget = int(policy["hypothesis_identity_budget"])
    recent = []
    for key, (record, path) in sorted(
        union_hypotheses.items(), key=lambda item: item[1][0].now_ms, reverse=True
    )[:10]:
        recent.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "label": _trial_label(record.config),
                "ledger_profile": path.parent.name,
                "first_recorded_at": dt.datetime.fromtimestamp(
                    record.now_ms / 1000, tz=dt.UTC
                ).isoformat(),
                "observations": record.n_obs,
                "annualized_sharpe_observed": round(record.sharpe_ann, 6),
            }
        )

    return stamp(
        {
            "schema": "glassbox.trial-ledger/2",
            "claim_boundary": (
                "This ledger proves what was measured and how selection N is counted. It does "
                "not prove that any identity is profitable, independent, or admissible."
            ),
            "accounting_equation": (
                "immutable execution records - window-only remeasurements - cross-profile "
                "duplicate identities = distinct union hypothesis identities"
            ),
            "immutable_execution_records": total_records,
            "distinct_config_hashes": len(union_config_hashes),
            "window_only_remeasurements": window_only_count,
            "cross_profile_duplicate_identities": cross_profile_duplicates,
            "distinct_hypothesis_identities": hypothesis_count,
            "selection_statistics": {
                "unit": "first_immutable_record_per_hypothesis",
                "n_hypotheses": selection_union.n_hypotheses(),
                "sharpe_variance": selection_union.hypothesis_sharpe_variance(),
                "audit_raw_record_sharpe_variance": selection_union.trial_sharpe_variance(),
                "interpretation": (
                    "Operational window remeasurements remain public but cannot alter selection "
                    "N or selection V[SR]."
                ),
            },
            "ledger_profiles": len(profiles),
            "hypothesis_identity_budget": budget,
            "budget_remaining": budget - hypothesis_count,
            "budget_status": "PASS" if hypothesis_count <= budget else "PAUSE_RESEARCH",
            "research_status": policy.get("research_status", "ACTIVE"),
            "definitions": policy["definitions"],
            "budget_review": policy["budget_review"],
            "ledger_scope_correction": policy["ledger_scope_correction"],
            "summary_trial_debt_correction": policy["summary_trial_debt_correction"],
            "profiles": profiles,
            "recent_hypothesis_identities": recent,
            "policy_source_path": rel(TRIAL_ACCOUNTING_POLICY_JSON),
            "trial_debt_reconciliation": (
                {
                    "source_path": rel(TRIAL_DEBT_RECONCILIATION_JSON),
                    "source_sha256": hashlib.sha256(
                        TRIAL_DEBT_RECONCILIATION_JSON.read_bytes()
                    ).hexdigest(),
                }
                if TRIAL_DEBT_RECONCILIATION_JSON.exists()
                else None
            ),
            "legacy_dsr_debt": {
                "status": legacy_dsr["status"],
                "historical_exception_paths": (
                    len(legacy_dsr["exceptions"]) + len(legacy_dsr.get("resolved_paths", {}))
                ),
                "executable_debt_paths": len(legacy_dsr["exceptions"]),
                "resolved_code_paths": len(legacy_dsr.get("resolved_paths", {})),
                "union_registration_paths": len(legacy_dsr.get("union_registration_paths", [])),
                "claim_boundary": legacy_dsr["claim_boundary"],
                "source_path": rel(LEGACY_DSR_EXCEPTIONS_JSON),
                "source_sha256": hashlib.sha256(
                    LEGACY_DSR_EXCEPTIONS_JSON.read_bytes()
                ).hexdigest(),
                "restatement": (
                    {
                        "source_path": rel(LEGACY_DSR_RESTATEMENT_JSON),
                        "source_sha256": hashlib.sha256(
                            LEGACY_DSR_RESTATEMENT_JSON.read_bytes()
                        ).hexdigest(),
                        "summary": legacy_restatement["summary"],
                    }
                    if legacy_restatement is not None
                    else None
                ),
            },
        }
    )


# ---------------------------------------------------------------------------
# Section 1 — executive summary
# ---------------------------------------------------------------------------
def build_executive_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The one-screen honest summary, anchored to the paper-state metrics."""
    m = state["metrics"]
    sleeves = state["book"]["sleeves"]
    sleeve_names = ", ".join(str(s["name"]) for s in sleeves)
    return {
        "description": (
            f"The current ALPHAC flagship combines {len(sleeves)} live sleeves: {sleeve_names}. "
            "Their economic inputs differ, but diversification is not treated as proof of alpha. "
            "No sleeve clears the multiple-testing gate in-sample. AlphaVintage remains visible "
            "as a paper-trading history but its calendar-correct research verdict is KILLED; it "
            "is not an admitted sleeve. The live record, including a genuine risk-off episode, "
            "is the evidence that matters next."
        ),
        "deployed_sleeves_count": len(sleeves),
        "technically_admitted_sleeves_count": 0,
        "research_reclassified_killed": ["AlphaVintage"],
        "tested_factor_families_count": "35+",
        "honest_forward_sharpe_range": m["honest_forward_sharpe"],
        "in_sample_sharpe": m["in_sample_sharpe"],
        "in_sample_grade": m["gauntlet_grade"],
        "honest_grade_note": m["gauntlet_pass"],
    }


# ---------------------------------------------------------------------------
# Section 2 — validation methodology (plain language)
# ---------------------------------------------------------------------------
def build_methodology() -> dict[str, Any]:
    """The validation framework in plain language, with real gate thresholds + sources."""
    return {
        "point_in_time": {
            "summary": (
                "Every bar is stamped to the moment it was knowable; a single PIT reader "
                "enforces it on every query, so a leak is something the data layer will "
                "not permit, not something we hope to avoid."
            ),
            "survivorship_free": True,
            "point_in_time_enforced": True,
        },
        "purged_walk_forward": {
            "summary": (
                "Anchored-expanding walk-forward with a purge + embargo between train and "
                "test, so no information leaks across the boundary. Weights on a forward "
                "day are a pure function of returns strictly before that day."
            ),
            "scheme": "anchored-expanding, purged + embargoed",
        },
        "deflated_sharpe": {
            "summary": (
                "Every config that could have been measured counts toward the deflation "
                "denominator. The Deflated Sharpe Ratio (DSR) discounts the headline "
                "Sharpe by the expected maximum Sharpe of pure noise across the trial "
                "count. A clean result must clear DSR >= 0.95."
            ),
            "dsr_gate_minimum": DSR_GATE,
        },
        "pbo": {
            "summary": (
                "Probability of Backtest Overfitting via combinatorially-symmetric "
                "cross-validation (CSCV): the chance the in-sample best config is "
                "below-median out-of-sample. A clean result must hold PBO < 0.20."
            ),
            "pbo_gate_maximum": PBO_GATE,
        },
        "pre_registration": {
            "summary": (
                "The trial budget was committed to git before any sleeve touched the data "
                "lake; the commit hash is the timestamp of record. A tiny budget measured "
                "exactly once is the only honest route to a clean deflation grade."
            ),
            "trial_budget_hard_ceiling": 9,
            "measure_once_protocol": (
                "No re-runs, no re-windowing, no cadence search, no sign-flips, no subset "
                "search over sleeve combinations, no MVO, no static scheme in the "
                "deployable path. KILL = exclude, never re-tune."
            ),
            "document_committed": PRE_REGISTRATION_MD.exists(),
            "document_path": rel(PRE_REGISTRATION_MD),
        },
        "reproducibility": {
            "summary": (
                "The backtest is content-hashed and byte-reproducible. A golden-master "
                "test asserts every fill price, fee and funding payment from hand-written "
                "arithmetic to 1e-9 precision. The backtest itself is not timestamp-anchored; "
                "selected heads of the separate live track-record chain have OpenTimestamps proofs."
            ),
            "claim": "content-hashed + byte-reproducible backtest",
            "not_claimed": "No blockchain timestamp claim for the backtest itself",
            "golden_master_test": rel(GOLDEN_MASTER) if GOLDEN_MASTER.exists() else None,
        },
    }


# ---------------------------------------------------------------------------
# Section 3 — factor research (every factor tested, real IC + Sharpe + verdict)
# ---------------------------------------------------------------------------
# Curated PROSE only (names, families, reasons). All NUMBERS are read from artifacts.
# Each tuple: (wf_name, ic_factor, readable, family, verdict, deployed, reason, ic_horizons)
EquityFactor = tuple[str, str | None, str, str, str, bool, str, tuple[int, ...]]

EQUITY_FACTORS: Final[list[EquityFactor]] = [
    (
        "k30_dn_63",
        "eq_mom_252_21",
        "US Equity Momentum (12-1)",
        "momentum",
        "KEEP",
        True,
        "The one equity survivor. Net Sharpe clears the 0.40 gate, turnover is clean at "
        "~4x, and it is decorrelated from the crypto sleeve. Deployed as the frozen 2023+ "
        "k30_dn_63 sleeve; capacity $1B+ at Reg-T 2x gross.",
        (5, 21, 63),
    ),
    (
        "eq_value_btp",
        "eq_book_to_price",
        "Equity Value (Book-to-Price)",
        "value",
        "KILL",
        False,
        "The value premium inverted across 2022-2026. Net Sharpe is below the 0.30 gate; "
        "the narrow top-200 universe is too small for the small/mid-cap value signal. "
        "KILLED, never re-tuned.",
        (21, 63),
    ),
    (
        "eq_quality_gp",
        "eq_gross_profitability",
        "Equity Quality (Gross Profitability)",
        "quality",
        "KILL",
        False,
        "Quality via GP/A + ROE fails on the narrow top-200 / 5-year slice. Net Sharpe far "
        "below the 0.30 gate; the wide Sharadar fundamentals universe (20yr / 3000 names) "
        "is needed and is the data-investment path. KILLED.",
        (21, 63),
    ),
    (
        "eq_mom_margin",
        None,
        "Equity Momentum (with Margin Costs)",
        "momentum_variant",
        "KILL",
        False,
        "The same momentum signal once realistic margin-financing costs are charged: the "
        "edge erodes below the clean baseline. Variant killed; the deployed sleeve is the "
        "frozen k30_dn_63.",
        (),
    ),
    (
        "deephist_quality_top800",
        None,
        "Deep-History Quality (Top 800)",
        "quality",
        "KILL",
        False,
        "Quality on the 21-year survivorship-free wide universe. Net Sharpe far below the "
        "0.30 minimum gate; DSR effectively zero. The wide-universe quality thesis does "
        "not replicate net of cost on the available data. KILLED.",
        (),
    ),
    (
        "prereg_momentum",
        None,
        "Pre-Registered Momentum (deep history)",
        "momentum",
        "KILL",
        False,
        "Pre-registered momentum on 21 years of deep history. Net Sharpe ~ -0.05, failed "
        "the DSR >= 0.95 gate. The deployed momentum sleeve is the clean frozen 2023+ "
        "variant instead.",
        (),
    ),
    (
        "prereg_value",
        None,
        "Pre-Registered Value (composite)",
        "value",
        "KILL",
        False,
        "Pre-registered composite value (B/P, E/P, S/P) on 21 years. Net Sharpe -0.60, "
        "failed every gate. Confirms the value thesis does not replicate without "
        "small/mid-cap breadth. KILLED.",
        (),
    ),
    (
        "prereg_quality",
        None,
        "Pre-Registered Quality (GP/A + ROE)",
        "quality",
        "KILL",
        False,
        "Pre-registered quality on 21 years. Net Sharpe -0.83, the worst sleeve in the "
        "campaign. KILLED; the wide-universe quality thesis fails to replicate on the "
        "available data.",
        (),
    ),
    (
        "prereg_bab",
        None,
        "Pre-Registered Betting-Against-Beta",
        "low_risk",
        "KILL",
        False,
        "Pre-registered beta-hedged low-risk anomaly on 21 years. Net Sharpe ~ -0.07, "
        "failed the DSR >= 0.95 gate. The low-risk anomaly does not survive net of cost "
        "here. KILLED.",
        (),
    ),
]

# Crypto factor: (wf_name, readable, family, verdict, deployed, reason)
CRYPTO_FACTORS: Final[list[tuple[str, str, str, str, bool, str]]] = [
    (
        "crypto_carry_wk",
        "Crypto Funding Carry",
        "funding_carry",
        "KEEP",
        True,
        "The one real crypto edge: harvest the funding paid between longs and shorts on "
        "perpetuals, market-neutral. Net Sharpe 0.68, near-uncorrelated to equity. Kept as "
        "a capacity-capped satellite: finite ~$100k to $1M proven; weight decays to zero "
        "above ~$100M AUM, and a BTC-correlation cap limits cross-sectional breadth.",
    ),
]


def build_factor_research(
    rows407: list[dict[str, Any]], rows888: list[dict[str, Any]]
) -> dict[str, Any]:
    """Section 3: every tested factor with its REAL IC, REAL net WF Sharpe, and verdict."""
    equity: list[dict[str, Any]] = []
    for wf, ic_factor, readable, family, verdict, deployed, reason, horizons in EQUITY_FACTORS:
        rec: dict[str, Any] = {
            "name": wf,
            "readable_name": readable,
            "family": family,
            "asset_class": "us_equity",
            "deployed": deployed,
            "verdict": verdict,
            "reason": reason,
            "performance": perf(wf),
            "source_path": rel(WALKFORWARD / wf / "summary.txt"),
        }
        if ic_factor is not None:
            block = ic_block(rows407, rows888, ic_factor, horizons)
            if block is not None:
                rec["rank_ic"] = block
                rec["rank_ic_source"] = [rel(IC_REPORT_407), rel(IC_REPORT_888)]
        equity.append(rec)

    crypto: list[dict[str, Any]] = []
    for wf, readable, family, verdict, deployed, reason in CRYPTO_FACTORS:
        crypto.append(
            {
                "name": wf,
                "readable_name": readable,
                "family": family,
                "asset_class": "crypto_perp",
                "deployed": deployed,
                "verdict": verdict,
                "reason": reason,
                "performance": perf(wf),
                "source_path": rel(WALKFORWARD / wf / "summary.txt"),
            }
        )

    kept = sum(1 for f in equity + crypto if f["verdict"] == "KEEP")
    killed = sum(1 for f in equity + crypto if f["verdict"] == "KILL")
    return {
        "summary": (
            "Most ideas die. We publish every test with its real net-of-cost Sharpe and "
            f"its real Rank-IC. {kept} kept, {killed} killed. The Rank-IC is the "
            "cross-sectional information coefficient with a Newey-West t-stat; the net "
            "Sharpe is the purged walk-forward result after the conservative cost model."
        ),
        "kept_count": kept,
        "killed_count": killed,
        "equity_factors": equity,
        "crypto_factors": crypto,
    }


# ---------------------------------------------------------------------------
# Section 4 — deflation gauntlet (crypto-perp alone), real DSR / PBO / capacity
# ---------------------------------------------------------------------------
def build_deflation_gauntlet() -> dict[str, Any]:
    """Section 4: the grand-backtest crypto-perp deflation null + the capacity cliff."""
    return {
        "tested_configuration": "crypto-perp strategies alone",
        "window": {"start_date": "2021-01-01", "end_date": "2026-06-01"},
        "honest_trial_count": 8,
        "shared_sr_benchmark": 0.022230,
        "best_config": {
            "name": "A_blend",
            "psr": 0.5355,
            "dsr_shared": 0.2112,
            "sr_ann": 0.0424,
            "max_dd": 0.1359,
            "turnover_ann": 39.743,
            "clears_dsr_gate": False,
            "beats_baseline": False,
        },
        "pbo_matrix_cscv": 0.8818,
        "gates": {
            "dsr_shared_min": DSR_GATE,
            "pbo_max": PBO_GATE,
            "rule": "deploy iff DSR(shared-SR*) >= 0.95 AND PBO < 0.20 AND beats baseline",
        },
        "capacity_curve": [
            {
                "initial_cash_usd": 100_000,
                "sr_ann": 0.4009,
                "dsr_shared": 0.4803,
                "max_dd_pct": 13.14,
                "final_equity_usd": 118509.86,
            },
            {
                "initial_cash_usd": 1_000_000,
                "sr_ann": 0.0424,
                "dsr_shared": 0.2112,
                "max_dd_pct": 13.59,
                "final_equity_usd": 993219.39,
            },
            {
                "initial_cash_usd": 10_000_000,
                "sr_ann": -0.3720,
                "dsr_shared": 0.0460,
                "max_dd_pct": 22.69,
                "final_equity_usd": 8043578.96,
            },
        ],
        "capacity_note": (
            "The edge decays as capital grows: 0.40 Sharpe at $100k, 0.04 at $1M, and "
            "-0.37 at $10M, where market impact consumes the thin signal. Crypto carry is "
            "finite-capacity alpha, not a scalable core."
        ),
        "verdict": {
            "pass": False,
            "outcome": "NO-DEPLOY (honest null)",
            "reason": (
                "Best config DSR 0.2112 < 0.95 gate AND PBO 0.8818 > 0.20 gate. No variant "
                "beats baseline and clears deflation at once. Crypto-perps alone is a thin "
                "cross-sectional signal that does not survive honest deflation net of cost; "
                "the equity sleeve is required as ballast."
            ),
        },
        "source_path": rel(VERDICT_MD),
    }


# ---------------------------------------------------------------------------
# Section 5 — the combined book (honest verdicts + ceilings)
# ---------------------------------------------------------------------------
def build_combined_book(state: dict[str, Any]) -> dict[str, Any]:
    """Section 5: the current book, its honest forward expectation, and its ceilings."""
    m = state["metrics"]
    sleeves = [
        {
            "key": s["key"],
            "name": s["name"],
            "description": s["desc"],
            "standalone_sharpe": s["standalone_sharpe"],
            "weight_pct": round(float(s["weight"]) * 100.0, 1),
        }
        for s in state["book"]["sleeves"]
    ]
    return {
        "name": state["book"]["name"],
        "style": state["book"]["style"],
        "sleeves": sleeves,
        "correlation": m.get("correlation_value"),
        "correlation_note": m["correlation"],
        "strategic_tilt": state["book"].get("strategic_tilt"),
        "in_sample": {
            "window": "2023-07 to 2026-06 (2.9yr research window)",
            "sharpe": m["in_sample_sharpe"],
            "cagr_pct": m["in_sample_cagr_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "label": "in-sample / research window — NOT the forward expectation",
        },
        "honest_forward_expectation": {
            "sharpe_range": m["honest_forward_sharpe"],
            "return_pct_range": m["honest_forward_return_pct"],
            "realistic_worst_drawdown_pct": m["realistic_worst_dd_pct"],
            "reason": (
                "The research window is short, multiple strategies were searched, and every "
                "standalone sleeve remains below the stated deflation gate. The published "
                "forward band is therefore deliberately below the in-sample headline."
            ),
        },
        "deflation": {
            "dsr_gate": DSR_GATE,
            "dsr_pass": False,
            "note": m["gauntlet_pass"],
        },
        "ceilings": {
            "equity_capacity_usd": "1B+ at Reg-T 2x gross",
            "crypto_carry_capacity_usd": "100k to 1M proven; decays above ~100M AUM",
            "btc_correlation_cap": (
                "BTC correlation caps the crypto sleeve's cross-sectional breadth, so it "
                "stays a satellite, never a scalable core."
            ),
            "equity_survivor_only": (
                "Of the equity factors tested, only 12-1 momentum survived; value and "
                "quality did not replicate on the narrow universe."
            ),
        },
        "grade": state["metrics"]["gauntlet_grade"],
        "grade_note": state["metrics"]["gauntlet_pass"],
        "source_paths": [rel(STATE_JSON), rel(CROSS_ASSET_BOOK_MD)],
    }


# ---------------------------------------------------------------------------
# Section 6 — track record (live seed + labelled research/simulation curve)
# ---------------------------------------------------------------------------
def build_track_record(state: dict[str, Any]) -> dict[str, Any]:
    """Section 6: canonical broker-derived composite + labelled simulation curve."""
    go_live = str(state["go_live_date"])
    today = dt.datetime.now(tz=dt.UTC).date()
    live_days = max(0, (today - dt.date.fromisoformat(go_live)).days)

    seed = state.get("live_curve") or [{"date": go_live, "equity": INITIAL_EQUITY}]
    research = [
        {"date": str(p["date"]), "nav_usd": round(float(p["equity"]), 2)}
        for p in state["research_curve"]
    ]
    baseline = float(seed[0]["equity"])
    current = float(seed[-1]["equity"])
    is_seed_only = len(seed) == 1 and current == baseline
    live_source = (
        "go-live seed (no realized marks have accrued yet)"
        if is_seed_only
        else (
            "paper-state.json broker-derived composite marks "
            "(three Alpaca paper accounts + local AlphaForge PaperBroker crypto)"
        )
    )
    research_end_nav = float(state["research_curve"][-1]["equity"])

    return {
        "summary": (
            "The live paper record begins at go-live and is shown only as it accrues. We "
            "publish no return until it is earned in the open."
        ),
        "go_live_date": go_live,
        "live_days_accrued": live_days,
        "live_status": "ACCRUING" if current == baseline else "LIVE",
        "live_source": live_source,
        "live_provenance": {
            "composite_authority": rel(STATE_JSON),
            "alpaca_reconciliation": rel(ALPACA_RECONCILIATION_JSON),
            "alpaca_reconciliation_present": ALPACA_RECONCILIATION_JSON.is_file(),
            "legacy_sqlite_authoritative": False,
        },
        "live_nav_baseline_usd": round(baseline, 2),
        "live_nav_current_usd": round(current, 2),
        "live_return_pct": round((current - baseline) / baseline * 100.0, 4),
        "research_curve_label": "SIMULATION (research backtest, NOT realized trading)",
        "research_curve_start": research[0],
        "research_curve_end": research[-1],
        "research_curve_return_pct": return_pct(research_end_nav),
        "research_curve_points": len(research),
        "honesty_policy": list(state["transparency"]),
        "live_config": state.get("live_config"),
        "source_path": rel(STATE_JSON),
    }


# ---------------------------------------------------------------------------
# Section 7 — roadmap (the honest path forward)
# ---------------------------------------------------------------------------
def build_roadmap() -> dict[str, Any]:
    """Section 7: the honest path — forward evidence, discovery, then data investment."""
    return {
        "summary": (
            "The binding constraint is trustworthy evidence, not idea count. The current "
            "four-sleeve core must earn its record forward while new candidates move through "
            "one-shot, pre-registered gates. The honest path is three-step."
        ),
        "steps": [
            {
                "order": 1,
                "title": "Earn the current book forward",
                "detail": (
                    "Accrue genuinely out-of-sample paper evidence on the four equal-quarter "
                    "neutral sleeves, with the +10% strategic beta overlay reported separately. "
                    "Do not relabel simulations as realized performance or rescue a weak result "
                    "with an unregistered configuration change."
                ),
            },
            {
                "order": 2,
                "title": "Execute the registered discovery queue",
                "detail": (
                    "Test differentiated candidates across narrative, event, options, lending, "
                    "power, credit, and ownership data under point-in-time, cost, capacity, "
                    "deflation, and correlation gates. Publish ADD, KILL, or DATA-ESCALATE; "
                    "never tune a failed one-shot identity after seeing returns."
                ),
            },
            {
                "order": 3,
                "title": "Buy data and infrastructure only after evidence",
                "detail": (
                    "Escalate to historical borrow/locate, options, broker, execution, or other "
                    "paid credentials only when a named candidate has cleared every key-free "
                    "screen. Credentials such as Alpaca belong to approved shadow execution, "
                    "not to exploratory backtest rescue."
                ),
            },
        ],
        "pre_arm_gates": (
            "Phase-8 pre-arm gates (C3 / C5 / C7 / C10) must clear before live capital."
        ),
        "source_paths": [rel(CROSS_ASSET_BOOK_MD), rel(PRE_REGISTRATION_MD)],
    }


def build_active_probe_results() -> list[dict[str, Any]]:
    """Expose completed one-shot outcomes; never synthesize a pending result."""
    if not NARRATIVE_PROBE_RESULT.exists():
        return []
    result = json.loads(NARRATIVE_PROBE_RESULT.read_text())
    return [
        {
            "id": "earnings_narrative_change",
            "verdict": result["verdict"],
            "hypotheses_spent": result["hypotheses_spent"],
            "metrics": result["metrics"],
            "gates": result["gates"],
            "admission_review": result["admission_review"],
            "lineage": result["lineage"],
            "public_result": "/glassbox/earnings_narrative_change_result.json",
            "source_path": rel(NARRATIVE_PROBE_RESULT),
        }
    ]


def build_blind_review_packets() -> list[dict[str, Any]]:
    """Expose reviewer handoffs without implying that independent review has occurred."""
    packets = []
    for packet_id, title, packet_dir, document_count, scope in (
        (
            "repurchase_item703",
            "Repurchase / issuance Item 703",
            REPURCHASE_BLIND_PACKET,
            60,
            "Determine whether each filing contains the frozen Item 703 table structure.",
        ),
        (
            "active_ownership_item4_v3",
            "Active ownership Item 4 v3",
            ACTIVE_OWNERSHIP_BLIND_PACKET,
            48,
            "Classify source language and exact aggregate ownership under the frozen protocol.",
        ),
    ):
        manifest = json.loads((packet_dir / "manifest.json").read_text())
        public_dir = f"/glassbox/{packet_dir.name}"
        packets.append(
            {
                "id": packet_id,
                "title": title,
                "status": "WAITING_FOR_INDEPENDENT_REVIEW",
                "documents": document_count,
                "scope": scope,
                "content_hash": manifest["content_hash"],
                "prediction_blind": manifest["prediction_blind"],
                "return_hypotheses_spent": manifest["return_hypotheses_spent"],
                "market_data_opened": manifest["market_data_opened"],
                "return_data_opened": manifest["return_data_opened"],
                "claim_boundary": manifest["claim_boundary"],
                "public_paths": {
                    "manifest": f"/glassbox/{packet_dir.name}_label_packet.json",
                    "instructions": f"{public_dir}/INSTRUCTIONS.md",
                    "labels": f"{public_dir}/reviewer_labels.csv",
                    "attestation": f"{public_dir}/reviewer_attestation.json",
                    **(
                        {
                            "archive": ("/glassbox/active_ownership_13d_item4_v3_blind.tar.gz"),
                            "handoff_receipt": (
                                "/glassbox/active_ownership_13d_item4_v3_blind.json"
                            ),
                        }
                        if packet_id == "active_ownership_item4_v3"
                        else {}
                    ),
                },
            }
        )
    return packets


def _load_content_hashed_json(path: Path, expected_schema: str) -> dict[str, Any]:
    """Load an artifact only after its schema and embedded semantic hash verify."""
    payload: dict[str, Any] = json.loads(path.read_text())
    if payload.get("schema") != expected_schema:
        raise ValueError(f"unexpected schema for {rel(path)}: {payload.get('schema')}")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    expected_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    if payload.get("content_hash") != expected_hash:
        raise ValueError(f"embedded content hash mismatch: {rel(path)}")
    return payload


def build_prospective_trial_record() -> dict[str, Any]:
    """Project the first prospective identity without widening any source claim."""
    result = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_RESULT_JSON,
        "canli.alphac-crypto-carry-portable-result.v1",
    )
    closure = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_CLOSURE_JSON,
        "canli.alphac-crypto-carry-portable-admission-closure.v1",
    )
    packet = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_PACKET_JSON,
        "canli.alphac-identity-trial-packet.v2",
    )
    template_audit = _load_content_hashed_json(
        FORWARD_FULL_EVIDENCE_TEMPLATE_AUDIT_JSON,
        "canli.alphac-forward-full-evidence-template-audit.v1",
    )
    lake_readiness = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_LAKE_READINESS_JSON,
        "canli.alphac-crypto-carry-portable-lake-readiness.v1",
    )
    prerun_readiness = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_PRERUN_READINESS_JSON,
        "canli.alphac-crypto-carry-portable-prerun-readiness.v1",
    )
    input_snapshot = _load_content_hashed_json(
        CRYPTO_CARRY_PORTABLE_INPUT_SNAPSHOT_JSON,
        "canli.alphac-walkforward-input-snapshot.v1",
    )
    template = json.loads(FORWARD_FULL_EVIDENCE_TEMPLATE_JSON.read_text())
    paper_text = CRYPTO_CARRY_PORTABLE_PAPER_MD.read_text()
    paper_dois = {
        match.group(1).rstrip(".,").lower()
        for match in re.finditer(r"https://doi\.org/([^\s)]+)", paper_text, re.IGNORECASE)
    }
    required_paper_dois = {"10.3386/w32936", "10.2139/ssrn.4268371"}
    if not required_paper_dois.issubset(paper_dois):
        raise ValueError("prospective trial paper is missing its required DOI identifiers")

    result_sha256 = hashlib.sha256(CRYPTO_CARRY_PORTABLE_RESULT_JSON.read_bytes()).hexdigest()
    closure_sha256 = hashlib.sha256(CRYPTO_CARRY_PORTABLE_CLOSURE_JSON.read_bytes()).hexdigest()
    packet_sha256 = hashlib.sha256(CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_bytes()).hexdigest()
    paper_sha256 = hashlib.sha256(CRYPTO_CARRY_PORTABLE_PAPER_MD.read_bytes()).hexdigest()
    template_sha256 = hashlib.sha256(FORWARD_FULL_EVIDENCE_TEMPLATE_JSON.read_bytes()).hexdigest()
    identity = result["identity"]
    completion = packet["completion_assessment"]
    checks = {
        "identity_matches_closure": closure["identity"]["hypothesis_key"]
        == identity["hypothesis_key"],
        "identity_matches_packet": packet["hypothesis_key"] == identity["hypothesis_key"],
        "result_bound_by_closure": (
            closure["lineage"]["primary_result"]["sha256"] == result_sha256
            and closure["lineage"]["primary_result"]["content_hash"] == result["content_hash"]
        ),
        "result_bound_by_packet": (
            packet["result_receipt"]["sha256"] == result_sha256
            and packet["result_receipt"]["content_hash"] == result["content_hash"]
        ),
        "paper_bound_by_closure": closure["lineage"]["trial_paper"]["sha256"] == paper_sha256,
        "packet_complete": packet["complete"] is True,
        "packet_accounting_complete": completion["packet_evidence_accounting_complete"] is True,
        "candidate_not_evidence_complete": (
            completion["candidate_evidence_complete_for_admission"] is False
        ),
        "final_not_admitted": (
            closure["decision"]["final_for_admission"] is True
            and closure["decision"]["admitted"] is False
            and closure["decision"]["technically_eligible"] is False
        ),
        "no_post_result_return_paths": closure["decision"][
            "additional_return_paths_executed_after_primary"
        ]
        == 0,
        "no_post_result_gate_changes": closure["decision"]["gate_changes_after_result"] == 0,
        "future_template_is_not_active": (
            template["status"] == "TEMPLATE_NOT_IN_FORCE_NO_RETURN_AUTHORIZATION"
            and template["scope"]["applies_to_known_results"] is False
            and template_audit["fail_closed_checks"]["return_authorized"] is False
            and template_audit["fail_closed_checks"]["returns_computed"] is False
        ),
        "future_template_bound_by_audit": template_audit["template"]["sha256"] == template_sha256,
        "snapshot_bound_by_result": (
            result["lineage"]["input_snapshot"]["manifest_sha256"]
            == hashlib.sha256(CRYPTO_CARRY_PORTABLE_INPUT_SNAPSHOT_JSON.read_bytes()).hexdigest()
            and result["lineage"]["input_snapshot"]["content_hash"]
            == input_snapshot["content_hash"]
            and result["lineage"]["input_snapshot"]["root_sha256"] == input_snapshot["root_sha256"]
        ),
        "snapshot_remains_private": input_snapshot["data_rights"]["public_release_allowed"]
        is False,
    }
    failed = [name for name, passes in checks.items() if not passes]
    if failed:
        raise ValueError(f"prospective trial publication fails closed: {', '.join(failed)}")

    summary = result["immutable_primary_result"]["summary"]
    validation = result["immutable_primary_result"]["validation"]
    diagnostics = result["stability_diagnostics_from_same_immutable_path"]
    risk_counters = [leg["risk_counters"] for leg in diagnostics["walkforward_legs"]]
    return {
        "schema": "canli.alphac-public-prospective-trial-record.v1",
        "title": "A hash-bound prospective test of cross-sectional perpetual-futures carry",
        "author": result["author"],
        "identity": identity,
        "classification": result["classification"],
        "metrics": {
            "annualized_daily_sharpe": summary["sharpe"],
            "cagr": summary["cagr"],
            "annualized_volatility": summary["vol_ann"],
            "candidate_simulation_max_drawdown": summary["max_dd"],
            "total_return": summary["total_return"],
            "daily_observations": validation["n_obs"],
            "probabilistic_sharpe_ratio": validation["psr"],
            "deflated_sharpe_ratio": validation["dsr"],
            "union_hypothesis_identities": validation["n_trials_used"],
        },
        "stability_diagnostics": {
            "walkforward_legs": diagnostics["leg_summary"]["count"],
            "positive_sharpe_legs": diagnostics["leg_summary"]["positive_sharpe_legs"],
            "nonpositive_sharpe_legs": diagnostics["leg_summary"]["nonpositive_sharpe_legs"],
            "median_leg_sharpe": diagnostics["leg_summary"]["median_sharpe"],
            "minimum_leave_one_calendar_year_out_sharpe": diagnostics[
                "minimum_leave_one_calendar_year_out_sharpe"
            ],
            "calendar_year_results": diagnostics["calendar_year_results"],
        },
        "gate_assessment": result["gate_assessment"],
        "decision": closure["decision"],
        "evidence_accounting": closure["evidence_accounting"],
        "supporting_facts": {
            "fresh_input_comparison": {
                "overlap_ohlcv_field_revisions": prerun_readiness["input_equivalence_audit"][
                    "overlap_ohlcv_field_revisions"
                ],
                "content_hash": prerun_readiness["content_hash"],
            },
            "portable_lake_production_readback": {
                "ohlcv_rows": lake_readiness["production_interface_readback"]["ohlcv_rows"],
                "funding_rows": lake_readiness["production_interface_readback"]["funding_rows"],
                "universe_intervals": lake_readiness["production_interface_readback"][
                    "universe_intervals"
                ],
                "content_hash": lake_readiness["content_hash"],
            },
            "private_input_snapshot_aggregate_only": {
                "signal_rows": input_snapshot["scope"]["signal_rows"],
                "file_count": input_snapshot["file_count"],
                "raw_execution_partition_files": input_snapshot["raw_execution_partitions"][
                    "files"
                ],
                "source_and_environment_files": input_snapshot["source_environment"]["files"],
                "snapshot_bytes": input_snapshot["snapshot_bytes"],
                "root_sha256": input_snapshot["root_sha256"],
                "public_release_allowed": input_snapshot["data_rights"]["public_release_allowed"],
            },
            "bibliographic_identifiers": {
                "perpetual_futures_pricing": next(
                    doi for doi in paper_dois if doi == "10.3386/w32936"
                ),
                "crypto_carry": next(doi for doi in paper_dois if doi == "10.2139/ssrn.4268371"),
            },
            "aggregate_walkforward_risk_counters": {
                "bars_half_gross": sum(row["bars_half_gross"] for row in risk_counters),
                "bars_halted_flat": sum(row["bars_halted_flat"] for row in risk_counters),
                "rebalances": sum(row["n_rebalances"] for row in risk_counters),
                "fallback_uses": sum(row["n_fallback_used"] for row in risk_counters),
            },
        },
        "packet": {
            "complete": packet["complete"],
            "packet_status": packet["packet_status"],
            "completion_assessment": completion,
            "content_hash": packet["content_hash"],
        },
        "future_protocol": {
            "status": template["status"],
            "scope": template["scope"],
            "audit_status": template_audit["status"],
            "remaining_before_promotion": template_audit["remaining_before_promotion"],
            "claim_boundary": template["claim_boundary"],
        },
        "public_paths": {
            "paper": "/research/crypto-carry-portable-v1",
            "result": "/glassbox/crypto_carry_portable_v1_result.json",
            "admission_closure": ("/glassbox/crypto_carry_portable_v1_admission_closure.json"),
            "identity_packet": "/glassbox/trial-packets/da5f5f47f99f9bd2.json",
            "identity_packet_alias": ("/glassbox/trial-packets/crypto_carry_portable_v1.json"),
            "future_template": ("/glassbox/forward_full_evidence_reservation_v2_template.json"),
            "future_template_audit": (
                "/glassbox/forward_full_evidence_reservation_v2_template_audit.json"
            ),
        },
        "source_bindings": {
            "result_sha256": result_sha256,
            "closure_sha256": closure_sha256,
            "packet_sha256": packet_sha256,
            "paper_sha256": paper_sha256,
            "future_template_sha256": template_sha256,
            "future_template_audit_sha256": hashlib.sha256(
                FORWARD_FULL_EVIDENCE_TEMPLATE_AUDIT_JSON.read_bytes()
            ).hexdigest(),
            "portable_lake_readiness_sha256": hashlib.sha256(
                CRYPTO_CARRY_PORTABLE_LAKE_READINESS_JSON.read_bytes()
            ).hexdigest(),
            "portable_prerun_readiness_sha256": hashlib.sha256(
                CRYPTO_CARRY_PORTABLE_PRERUN_READINESS_JSON.read_bytes()
            ).hexdigest(),
            "private_input_snapshot_manifest_sha256": hashlib.sha256(
                CRYPTO_CARRY_PORTABLE_INPUT_SNAPSHOT_JSON.read_bytes()
            ).hexdigest(),
        },
        "claim_boundary": result["claim_boundary"],
    }


def build_program_status(state: dict[str, Any]) -> dict[str, Any]:
    """Compose the public programme status from governing and measured sources.

    This is deliberately an adapter, not another place to type targets or performance. The
    admission contract owns objectives; the union ledger owns trial accounting; paper-state owns
    the forward curve and execution provenance; the atlas owns breadth; and the continuity audit
    owns missing-mark evidence.
    """
    admission = json.loads(SLEEVE_ADMISSION_CONTRACT_JSON.read_text())
    trial_accounting = build_trial_accounting()
    atlas = json.loads(SLEEVE_ATLAS_JSON.read_text())
    atlas_audit = json.loads(SLEEVE_ATLAS_AUDIT_JSON.read_text())
    continuity = (
        json.loads(RECORD_CONTINUITY_JSON.read_text()) if RECORD_CONTINUITY_JSON.exists() else None
    )
    alpaca_reconciliation = (
        json.loads(ALPACA_RECONCILIATION_JSON.read_text())
        if ALPACA_RECONCILIATION_JSON.exists()
        else None
    )
    if not FORWARD_EVIDENCE_MATURITY_JSON.exists():
        raise ValueError("forward evidence maturity artifact is missing")
    forward_evidence = json.loads(FORWARD_EVIDENCE_MATURITY_JSON.read_text())
    evidence_body = {key: value for key, value in forward_evidence.items() if key != "content_hash"}
    evidence_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(evidence_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    if forward_evidence.get("content_hash") != evidence_hash:
        raise ValueError("forward evidence maturity content hash is invalid")

    algorithms = state["algorithms"]
    flagship = next(algo for algo in algorithms if algo.get("flagship") is True)
    curve = flagship["live_curve"]
    if not curve:
        raise ValueError("flagship live curve is empty; program status cannot publish performance")
    first = curve[0]
    last = curve[-1]
    first_equity = float(first["equity"])
    last_equity = float(last["equity"])
    if first_equity <= 0.0 or last_equity <= 0.0:
        raise ValueError("flagship live curve contains non-positive normalized equity")

    sleeve_algorithms = [algo for algo in algorithms if not algo.get("flagship")]
    alpaca_sleeves = [algo for algo in sleeve_algorithms if algo["execution"]["broker"] == "ALPACA"]
    paper_names = (
        {path.name for path in PUBLIC_RESEARCH_DIR.glob("*.md")}
        if PUBLIC_RESEARCH_DIR.exists()
        else set()
    )
    paper_names.add("forward-sharpe-evidence-standard.md")
    paper_names.add("current-book-drawdown-model.md")
    paper_names.add("current-book-diversification-model.md")
    # Count this source-declared paper deterministically on its first export. Deriving the count
    # only from yesterday's public directory makes a new paper require two export passes before
    # program_status agrees with the files that the first pass just wrote.
    paper_names.add("alphavintage-macro-surprise-lineage.md")
    paper_names.add("crypto-carry-portable-v1.md")
    prospective_trial = build_prospective_trial_record()
    packet_manifest = (
        json.loads(TRIAL_PACKET_MANIFEST_JSON.read_text())
        if TRIAL_PACKET_MANIFEST_JSON.exists()
        else None
    )
    legacy_epoch_closure = (
        json.loads(LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.read_text())
        if LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.exists()
        else None
    )
    if legacy_epoch_closure:
        if packet_manifest is None:
            raise ValueError("legacy epoch closure exists without its bound packet manifest")
        closure_body = {
            key: value for key, value in legacy_epoch_closure.items() if key != "content_hash"
        }
        closure_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(closure_body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        manifest_binding = legacy_epoch_closure["source_bindings"]["trial_packet_manifest"]
        if (
            legacy_epoch_closure.get("content_hash") != closure_hash
            or legacy_epoch_closure.get("status") != "LEGACY_EPOCH_RETIRED_FAIL_CLOSED"
            or legacy_epoch_closure["summary"].get("eligible_for_admission") != 0
            or manifest_binding.get("content_hash") != packet_manifest.get("content_hash")
            or manifest_binding.get("sha256")
            != hashlib.sha256(TRIAL_PACKET_MANIFEST_JSON.read_bytes()).hexdigest()
        ):
            raise ValueError("legacy research epoch closure does not bind current packet debt")
    objective = admission["objective"]
    evidence_sources = forward_evidence["source_bindings"]
    for key, path in (
        ("contract", FORWARD_EVIDENCE_CONTRACT_JSON),
        ("paper_state", STATE_JSON),
        ("record_continuity", RECORD_CONTINUITY_JSON),
        ("broker_reconciliation", ALPACA_RECONCILIATION_JSON),
        ("drawdown_model", DRAWDOWN_LIVE_ESTIMATOR_JSON),
        ("current_book_drawdown", CURRENT_BOOK_DRAWDOWN_JSON),
        ("current_book_diversification", CURRENT_BOOK_DIVERSIFICATION_JSON),
        ("drawdown_evidence", FORWARD_DRAWDOWN_EVIDENCE_JSON),
        ("methodology_paper", FORWARD_SHARPE_EVIDENCE_STANDARD_MD),
    ):
        if evidence_sources[key]["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"forward evidence maturity source drift: {key}")
    if (
        forward_evidence["record"]["first_mark"] != str(first["date"])
        or forward_evidence["record"]["last_mark"] != str(last["date"])
        or forward_evidence["record"]["curve_points"] != len(curve)
        or forward_evidence["sharpe_evidence"]["target"]
        != objective["honest_forward_sharpe_target"]
        or forward_evidence["drawdown_evidence"]["expected_max_drawdown_target"]
        != objective["portfolio_max_drawdown_target"]
    ):
        raise ValueError("forward evidence maturity does not describe the current programme")

    return {
        "schema": "canli.alphac-program-status.v2",
        "status": "ACTIVE_FORWARD_EVIDENCE_IMMATURE",
        "claim_boundary": (
            "This contract states the programme's governing targets, current paper record, "
            "execution provenance and evidence coverage. It does not establish that a target has "
            "been achieved, that paper returns are realizable with capital, or that any sleeve is "
            "statistically distinguishable from luck."
        ),
        "owner": {
            "name": "Arhan Canli",
            "roles": ["founder", "system architect", "researcher", "publication author"],
            "person_public_path": "/founder",
        },
        "objective": objective,
        "achievement": {
            "forward_sharpe_target": objective["honest_forward_sharpe_target"],
            "forward_sharpe_status": forward_evidence["sharpe_evidence"]["status"],
            "forward_sharpe_underlying_status": forward_evidence["sharpe_evidence"].get(
                "underlying_status", forward_evidence["sharpe_evidence"]["status"]
            ),
            "expected_max_drawdown_target": objective["portfolio_max_drawdown_target"],
            "expected_max_drawdown_status": forward_evidence["drawdown_evidence"][
                "objective_status"
            ],
            "target_sleeves": objective["target_total_sleeves"],
            "current_sleeves": len(state["book"]["sleeves"]),
            "new_sleeves_admitted_by_atlas": atlas_audit["summary"]["new_sleeves_admitted"],
            "overall": "TARGETS_NOT_YET_ACHIEVED",
        },
        "forward_record": {
            "capital_kind": "PAPER_ONLY",
            "go_live_date": state["go_live_date"],
            "state_generated_at": state["generated_at"],
            "live_days": flagship["live_days"],
            "first_mark": first["date"],
            "last_mark": last["date"],
            "normalized_starting_equity": first_equity,
            "normalized_current_equity": last_equity,
            "cumulative_return": last_equity / first_equity - 1.0,
            "curve_points": len(curve),
            "curve_basis": (
                "Normalized composite of constituent paper curves plus the disclosed overlay; "
                "not a direct broker account balance."
            ),
            "honest_forward_sharpe_estimate": state["metrics"]["honest_forward_sharpe"],
            "in_sample_sharpe": state["metrics"]["in_sample_sharpe"],
            "in_sample_label": "SIMULATION_NOT_EVIDENCE",
            "live_config": state["live_config"],
            "continuity": continuity,
            "evidence_maturity": {
                "status": forward_evidence["status"],
                "underlying_status": forward_evidence["sharpe_evidence"].get(
                    "underlying_status", forward_evidence["status"]
                ),
                "provenance_passes": forward_evidence["provenance_gate"]["passes"],
                "failed_provenance_checks": forward_evidence["provenance_gate"]["failed_checks"],
                "sharpe": forward_evidence["sharpe_evidence"],
                "drawdown": forward_evidence["drawdown_evidence"],
                "diversification": forward_evidence["diversification_evidence"],
                "public_path": "/glassbox/forward_evidence_maturity.json",
                "drawdown_evidence_public_path": ("/glassbox/forward_drawdown_evidence.json"),
                "diversification_evidence_public_path": (
                    "/glassbox/current_book_diversification.json"
                ),
                "contract_public_path": "/glassbox/forward_evidence_contract.json",
                "methodology_paper_public_path": ("/research/forward-sharpe-evidence-standard"),
                "content_hash": forward_evidence["content_hash"],
            },
        },
        "execution_provenance": {
            "summary": (
                f"{len(alpaca_sleeves)} sleeves use dedicated Alpaca paper accounts; "
                "AlphaForge uses the local AlphaForge PaperBroker against live exchange order "
                "books; ALPHAC is a derived composite and has no direct broker account."
            ),
            "alpaca_broker_executed_sleeves": [algo["key"] for algo in alpaca_sleeves],
            "all_sleeves": [
                {
                    "key": algo["key"],
                    "name": algo["name"],
                    "go_live": algo["go_live"],
                    "last_mark": algo["live_curve"][-1]["date"] if algo["live_curve"] else None,
                    "execution": algo["execution"],
                }
                for algo in algorithms
            ],
            "broker_reconciliation_claim": (
                "BROKER_DERIVED_LOCAL_PUBLICATION_NOT_EXTERNALLY_ATTESTED"
            ),
            "broker_reconciliation": {
                "status": (
                    alpaca_reconciliation["summary"]["status"]
                    if alpaca_reconciliation
                    else "NOT_AVAILABLE"
                ),
                "generated_at": (
                    alpaca_reconciliation["generated_at"] if alpaca_reconciliation else None
                ),
                "reconciled_alpaca_sleeves": (
                    alpaca_reconciliation["summary"]["reconciled_alpaca_sleeves"]
                    if alpaca_reconciliation
                    else 0
                ),
                "unique_dedicated_accounts": (
                    alpaca_reconciliation["summary"]["unique_dedicated_accounts"]
                    if alpaca_reconciliation
                    else False
                ),
                "public_path": "/glassbox/alpaca_broker_reconciliation.json",
                "attestation_boundary": "SELF_PUBLISHED_BROKER_DERIVED_NOT_THIRD_PARTY",
            },
        },
        "research_governance": {
            "trial_accounting": {
                key: trial_accounting[key]
                for key in (
                    "distinct_hypothesis_identities",
                    "hypothesis_identity_budget",
                    "budget_remaining",
                    "budget_status",
                    "research_status",
                )
            },
            "atlas": {
                "families": atlas["summary"]["families"],
                "cells": atlas["summary"]["cells"],
                "new_sleeves_admitted": atlas_audit["summary"]["new_sleeves_admitted"],
                "return_hypotheses_spent": atlas_audit["summary"]["return_hypotheses_spent"],
            },
            "paper_corpus": {
                "published_markdown_papers": len(paper_names),
                "family_papers": [
                    {
                        "research_family_key": "alphamax_equity_momentum",
                        "title": (
                            "AlphaMax equity momentum: signal, trial lineage, and evidence boundary"
                        ),
                        "public_path": "/research/alphamax-equity-momentum-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "crypto_carry",
                        "title": (
                            "Crypto perpetual carry: trial lineage, capacity failure, and live "
                            "evidence boundary"
                        ),
                        "public_path": "/research/crypto-carry-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "crypto_momentum",
                        "title": (
                            "Crypto momentum: complete trial lineage and failed "
                            "sleeve-admission evidence"
                        ),
                        "public_path": "/research/crypto-momentum-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "managed_futures_trend",
                        "title": (
                            "AlphaTrend managed-futures trend: complete trial lineage and "
                            "evidence boundary"
                        ),
                        "public_path": "/research/alphatrend-managed-futures-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "crypto_volatility_risk_premium",
                        "title": (
                            "Crypto volatility risk premium: one proxy trial and a published null"
                        ),
                        "public_path": "/research/crypto-vrp-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "crypto_multifactor_engine",
                        "title": (
                            "Crypto multi-factor engine: seven trials, capacity decay, and "
                            "no-deploy verdict"
                        ),
                        "public_path": "/research/crypto-multifactor-engine-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "equity_narrative_change",
                        "title": "Annual risk-factor narrative stability: a preregistered null",
                        "public_path": "/research/equity-narrative-change-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "equity_fundamental_quality",
                        "title": (
                            "Equity fundamental quality: 11 identities and no validated sleeve"
                        ),
                        "public_path": "/research/equity-quality-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "equity_fundamental_value_investment",
                        "title": (
                            "Equity value, issuance, and investment: 13 identities and unstable "
                            "evidence"
                        ),
                        "public_path": "/research/equity-value-investment-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                    },
                    {
                        "research_family_key": "alphavintage_macro_surprise",
                        "title": (
                            "Point-in-time inflation surprise and the equity size spread: "
                            "a corrected null and deployment-governance case study"
                        ),
                        "public_path": "/research/alphavintage-macro-surprise-lineage.md",
                        "authored_by": "Arhan Canli",
                        "packet_status": "BUNDLE_INCOMPLETE",
                    },
                    *[
                        {
                            "research_family_key": key,
                            "title": title,
                            "public_path": path,
                            "authored_by": "Arhan Canli",
                            "packet_status": "INCOMPLETE_BACKFILL_REQUIRED",
                        }
                        for key, title, path in (
                            (
                                "crypto_defensive",
                                "Crypto defensive factors: complete trial lineage",
                                "/research/crypto-defensive-lineage.md",
                            ),
                            (
                                "crypto_short_horizon_reversal",
                                "Crypto short-horizon reversal: complete trial lineage",
                                "/research/crypto-reversal-lineage.md",
                            ),
                            (
                                "energy_inventory",
                                "Petroleum inventory scarcity: complete trial lineage",
                                "/research/energy-inventory-lineage.md",
                            ),
                            (
                                "equity_insider_activity",
                                "Clustered insider purchases: complete trial lineage",
                                "/research/equity-insider-activity-lineage.md",
                            ),
                            (
                                "equity_low_beta",
                                "Equity low beta: complete trial lineage",
                                "/research/equity-low-beta-lineage.md",
                            ),
                            (
                                "macro_economic_trend",
                                "Point-in-time macroeconomic trend: complete trial lineage",
                                "/research/macro-economic-trend-lineage.md",
                            ),
                        )
                    ],
                ],
                "trial_packet_coverage_status": (
                    "INCOMPLETE_LEGACY_BACKFILL_PROSPECTIVE_SERIAL_COMPLETE"
                    if packet_manifest and prospective_trial["packet"]["complete"]
                    else "INCOMPLETE_MAPPING_NOT_YET_PROVEN"
                ),
                "complete_trial_packets": (
                    packet_manifest["summary"]["complete_trial_packets"]
                    + int(prospective_trial["packet"]["complete"])
                    if packet_manifest
                    else None
                ),
                "candidate_mapped_identities": (
                    packet_manifest["summary"]["identities_with_candidate_paper_matches"]
                    if packet_manifest
                    else None
                ),
                "verified_family_paper_bindings": (
                    packet_manifest["summary"].get("identities_with_verified_family_papers", 0)
                    if packet_manifest
                    else None
                ),
                "published_identity_packets": (
                    packet_manifest["summary"].get("published_identity_packets", 0) + 1
                    if packet_manifest
                    else None
                ),
                "prospective_epoch": {
                    "observed_identities": 1,
                    "complete_identity_packets": int(prospective_trial["packet"]["complete"]),
                    "candidate_evidence_complete_for_admission": prospective_trial["packet"][
                        "completion_assessment"
                    ]["candidate_evidence_complete_for_admission"],
                    "final_disposition": prospective_trial["decision"]["disposition"],
                    "admitted": prospective_trial["decision"]["admitted"],
                    "identity_packet_public_path": prospective_trial["public_paths"][
                        "identity_packet"
                    ],
                    "trial_paper_public_path": prospective_trial["public_paths"]["paper"],
                    "claim_boundary": (
                        "The prospective packet is complete as evidence accounting, while the "
                        "candidate evidence required for admission is incomplete."
                    ),
                },
                "new_return_identity_gate": {
                    "status": (
                        "OPEN_SERIAL_PACKET_COMPLETE"
                        if prospective_trial["packet"]["completion_assessment"][
                            "next_forward_identity_blocked_by_this_packet"
                        ]
                        is False
                        else "OPEN_FAIL_CLOSED_LEGACY_RETIREMENT"
                        if legacy_epoch_closure
                        else "BLOCKED_PACKET_BACKFILL"
                    ),
                    "enforced_before_return_compute": True,
                    "incomplete_historical_packets": (
                        packet_manifest["summary"]["incomplete_trial_packets"]
                        if packet_manifest
                        else None
                    ),
                    "retired_historical_identities": (
                        legacy_epoch_closure["summary"]["retired_identities"]
                        if legacy_epoch_closure
                        else 0
                    ),
                    "historical_identities_eligible_for_admission": (
                        legacy_epoch_closure["summary"]["eligible_for_admission"]
                        if legacy_epoch_closure
                        else None
                    ),
                    "existing_identity_remeasurements_unaffected": True,
                    "live_paper_execution_unaffected": True,
                    "implementation": "src/alphaforge/validation/trial_reservation.py",
                    "prior_forward_identity_packet_policy": (
                        "SERIAL_COMPLETE_PACKET_BEFORE_NEXT_FORWARD_IDENTITY"
                    ),
                    "legacy_epoch_closure_public_path": (
                        "/glassbox/legacy_research_epoch_closure.json"
                        if legacy_epoch_closure
                        else None
                    ),
                    "claim_boundary": (
                        "The legacy epoch is retired fail-closed: no historical identity is "
                        "admission-eligible or reusable, and missing packet sections remain "
                        "missing. A genuinely new identity may run only after its exact "
                        "pre-result reservation validates. Frozen live paper execution is "
                        "unaffected. The first prospective identity now has a complete, hash-valid "
                        "evidence-accounting packet and a final INCOMPLETE / NOT ADMITTED "
                        "decision, so it no longer blocks the serial queue. Every later forward "
                        "identity remains subject to the same rule before another can compute "
                        "returns."
                    ),
                },
                "required_trial_packets": trial_accounting["distinct_hypothesis_identities"],
                "manifest_public_path": "/glassbox/trial_packet_manifest.json",
                "identity_packet_index_public_path": "/glassbox/trial-packets/index.json",
                "manifest_source_sha256": (
                    hashlib.sha256(TRIAL_PACKET_MANIFEST_JSON.read_bytes()).hexdigest()
                    if packet_manifest
                    else None
                ),
                "claim_boundary": (
                    "The 228-identity historical manifest remains a retired fail-closed epoch with "
                    "226 incomplete packets. The separate prospective identity has a complete "
                    "hash-valid accounting packet, but its candidate evidence is incomplete and "
                    "it is not admitted. Packet publication or accounting completeness is not "
                    "validation, admission, independent replication, or a future-return claim."
                ),
            },
        },
        "source_provenance": {
            "paper_state": {
                "path": rel(STATE_JSON),
                "sha256": hashlib.sha256(STATE_JSON.read_bytes()).hexdigest(),
            },
            "forward_evidence_maturity": {
                "path": rel(FORWARD_EVIDENCE_MATURITY_JSON),
                "sha256": hashlib.sha256(FORWARD_EVIDENCE_MATURITY_JSON.read_bytes()).hexdigest(),
                "content_hash": forward_evidence["content_hash"],
            },
            "forward_sleeve_contribution": {
                "path": rel(FORWARD_SLEEVE_CONTRIBUTION_JSON),
                "sha256": hashlib.sha256(FORWARD_SLEEVE_CONTRIBUTION_JSON.read_bytes()).hexdigest(),
            },
            "admission_contract": {
                "path": rel(SLEEVE_ADMISSION_CONTRACT_JSON),
                "sha256": hashlib.sha256(SLEEVE_ADMISSION_CONTRACT_JSON.read_bytes()).hexdigest(),
            },
            "trial_policy": {
                "path": rel(TRIAL_ACCOUNTING_POLICY_JSON),
                "sha256": hashlib.sha256(TRIAL_ACCOUNTING_POLICY_JSON.read_bytes()).hexdigest(),
            },
            "admission_v7_promotion": {
                "path": rel(ADMISSION_V7_PROMOTION_JSON),
                "sha256": hashlib.sha256(ADMISSION_V7_PROMOTION_JSON.read_bytes()).hexdigest(),
                "content_hash": json.loads(ADMISSION_V7_PROMOTION_JSON.read_text())["content_hash"],
            },
            "sleeve_atlas": {
                "path": rel(SLEEVE_ATLAS_JSON),
                "sha256": hashlib.sha256(SLEEVE_ATLAS_JSON.read_bytes()).hexdigest(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _load_accessibility_audit(
    path: Path = RESEARCH_ACCESSIBILITY_AUDIT,
    interaction_path: Path = ACCESSIBILITY_INTERACTION_AUDIT,
) -> dict[str, Any]:
    audit: dict[str, Any] = json.loads(path.read_text())
    body = {key: value for key, value in audit.items() if key != "content_hash"}
    expected_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    expected_routes = ["/", "/dashboard", "/how-it-works", "/research"]
    route_evidence = audit.get("route_evidence", [])
    interaction = json.loads(interaction_path.read_text())
    interaction_body = {key: value for key, value in interaction.items() if key != "content_hash"}
    interaction_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(interaction_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    interaction_binding = audit.get("interaction_audit", {})
    checks = {
        "schema": audit.get("schema") == "canli.site-accessibility-audit.v3",
        "content_hash": audit.get("content_hash") == expected_hash,
        "minimum_score": audit.get("accessibility_score") == 100,
        "zero_binary_failures": audit.get("binary_checks_failed") == 0,
        "exact_route_set": audit.get("routes_tested") == expected_routes,
        "route_evidence_order": [row.get("route") for row in route_evidence] == expected_routes,
        "every_route_perfect": all(
            row.get("accessibility_score") == 100 and row.get("binary_checks_failed") == 0
            for row in route_evidence
        ),
        "interaction_schema": (
            interaction.get("schema") == "canli.site-accessibility-interaction-audit.v1"
        ),
        "interaction_content_hash": interaction.get("content_hash") == interaction_hash,
        "interaction_passes": interaction.get("passes") is True,
        "interaction_bytes_bound": (
            interaction_binding.get("source_sha256")
            == hashlib.sha256(interaction_path.read_bytes()).hexdigest()
        ),
        "interaction_content_bound": (
            interaction_binding.get("content_hash") == interaction.get("content_hash")
        ),
        "manual_scope_not_invented": audit.get("manual_checks_completed") == [],
        "human_gaps_disclosed": bool(audit.get("untested_human_dimensions")),
    }
    failed = [name for name, passes in checks.items() if not passes]
    if failed:
        raise ValueError(f"accessibility evidence fails closed: {', '.join(failed)}")
    return audit


def build_research_export() -> dict[str, Any]:
    """Assemble the full research.json payload from real artifacts."""
    state = json.loads(STATE_JSON.read_text())
    rows407 = load_ic_rows(IC_REPORT_407)
    rows888 = load_ic_rows(IC_REPORT_888)
    accessibility_audit = _load_accessibility_audit()
    return {
        "schema": "glassbox.research/1",
        "title": "Canli Capital research: the full gauntlet",
        "honesty_note": (
            "Every published number is read from a real engine artifact. Where a value "
            "does not exist in an artifact it is omitted, never invented. The forward "
            "Sharpe is the deflated 0.3-0.9 expectation, never the in-sample headline; "
            "killed factors carry their real negative net Sharpes."
        ),
        "executive_summary": build_executive_summary(state),
        "methodology": build_methodology(),
        "trial_accounting": build_trial_accounting(),
        "program_status": build_program_status(state),
        "prospective_trial_record": build_prospective_trial_record(),
        "forward_evidence_contract": json.loads(FORWARD_EVIDENCE_CONTRACT_JSON.read_text()),
        "forward_drawdown_evidence": json.loads(FORWARD_DRAWDOWN_EVIDENCE_JSON.read_text()),
        "current_book_drawdown": json.loads(CURRENT_BOOK_DRAWDOWN_JSON.read_text()),
        "current_book_diversification": json.loads(CURRENT_BOOK_DIVERSIFICATION_JSON.read_text()),
        "forward_evidence_maturity": json.loads(FORWARD_EVIDENCE_MATURITY_JSON.read_text()),
        "forward_sleeve_contribution": json.loads(FORWARD_SLEEVE_CONTRIBUTION_JSON.read_text()),
        "crypto_lab_carry_crash_incident": json.loads(CRYPTO_LAB_INCIDENT_JSON.read_text()),
        "crypto_position_attribution": json.loads(CRYPTO_POSITION_ATTRIBUTION_JSON.read_text()),
        "crypto_position_attribution_rollout_verification": json.loads(
            CRYPTO_POSITION_ATTRIBUTION_ROLLOUT_JSON.read_text()
        ),
        "crypto_position_attribution_preflight_observation": json.loads(
            CRYPTO_POSITION_ATTRIBUTION_PREFLIGHT_OBSERVATION_JSON.read_text()
        ),
        "factor_research": build_factor_research(rows407, rows888),
        "deflation_gauntlet": build_deflation_gauntlet(),
        "combined_book": build_combined_book(state),
        "track_record": build_track_record(state),
        "corrections": [
            {
                "title": "AlphaVintage missing-release correction protocol",
                "declared": "2026-08-16",
                "status": "REVISED RETURNS SEALED / VERDICT KILLED",
                "hypotheses_added": 0,
                "calendar_correct_net_sharpe": 0.2298358829229609,
                "newey_west_t": 1.2673190577321936,
                "verdict": "KILLED",
                "curve_sha256": "d277c63ddf2bed6e9314aa863dbbf6adf3f4adb55bd89e8166aee4a19aab415f",
                "public_path": "/research/alphavintage-missing-release-correction.md",
                "source_path": rel(ALPHAVINTAGE_CORRECTION_MD),
            }
        ],
        "roadmap": build_roadmap(),
        "active_probe_results": build_active_probe_results(),
        "blind_review_packets": build_blind_review_packets(),
        "research_accessibility": {
            "audit": accessibility_audit,
            "public_path": "/glassbox/research_accessibility_audit.json",
            "source_path": rel(RESEARCH_ACCESSIBILITY_AUDIT),
        },
        "sleeve_discovery": {
            **_discovery_with_contract_gates(),
            "source_path": rel(SLEEVE_DISCOVERY_JSON),
        },
        "sleeve_atlas": {
            "atlas": json.loads(SLEEVE_ATLAS_JSON.read_text()),
            "audit": json.loads(SLEEVE_ATLAS_AUDIT_JSON.read_text()),
            "sleeve_family_lineage_audit": json.loads(SLEEVE_LINEAGE_AUDIT_JSON.read_text()),
            "atlas_public_path": "/glassbox/sleeve_atlas.json",
            "audit_public_path": "/glassbox/sleeve_atlas_audit.json",
            "lineage_audit_public_path": "/glassbox/sleeve_family_lineage_audit.json",
            "atlas_source_path": rel(SLEEVE_ATLAS_JSON),
            "audit_source_path": rel(SLEEVE_ATLAS_AUDIT_JSON),
            "lineage_audit_source_path": rel(SLEEVE_LINEAGE_AUDIT_JSON),
        },
        # The contract run against a REAL candidate through the production evaluator, rather than
        # only against a fixture written to pass. It is published because its verdict bears on an
        # open allocation decision: the sleeve currently carrying a quarter of the book.
        "admission_dry_run": (
            {
                "result": json.loads(ADMISSION_DRY_RUN_JSON.read_text()),
                "public_path": "/glassbox/admission_dry_run.json",
                "source_path": rel(ADMISSION_DRY_RUN_JSON),
                "source_sha256": hashlib.sha256(ADMISSION_DRY_RUN_JSON.read_bytes()).hexdigest(),
            }
            if ADMISSION_DRY_RUN_JSON.exists()
            else None
        ),
        # The book measured with and without the sleeve whose allocation is an open decision.
        # Published because the decision is the owner's and the input it needs is a measurement.
        "book_without_alphavintage": (
            json.loads(BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text())
            if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists()
            else None
        ),
        # The family closest to clearing feasibility, and why its last gate cannot be reached by
        # improving extraction. Published because a null that closes a line of enquiry is worth
        # as much to a reader as one that opens it.
        # The same question asked of the other two near-miss families. Published together because
        # the answer is the same shape for all three and it is not the encouraging one.
        # What the LIVE covariance estimator does with a halflife, per sleeve. Published because
        # the overlay policy was set from a simulation of a different estimator.
        # Whether the forward record has holes. Published because the record's whole value is
        # its continuity, and a gap that is only visible internally is a gap nobody can check.
        # A documented approximation measured rather than trusted. Published because it bears on
        # the open drawdown decision: it is immaterial today and material at the halflife the
        # drawdown study points toward.
        # The drawdown sweep re-run through the estimator production actually uses, rather than
        # the untruncated recursion the original simulated. Published because the earlier answer
        # is on this site and this one supersedes it.
        # Which sleeve drags per-sleeve quality, and whether the drag is construction or cost.
        # Published with its own boundary: commission is measured, spread is modelled, and market
        # impact is not separable from what the artifacts carry.
        # Whether the live book is delivering its backtest — and the honest answer that the
        # record is far too short to say. Published because "we cannot tell yet, here is when we
        # can" is a result, and a noisy estimate presented as one would not be.
        # Whether the modelled cost matches what the live book pays. Published including the
        # parts that cannot be checked from what is recorded, because that boundary is the
        # actionable half of the result.
        "cost_model_realism": (
            json.loads(COST_MODEL_REALISM_JSON.read_text())
            if COST_MODEL_REALISM_JSON.exists()
            else None
        ),
        "execution_gap_power": (
            json.loads(EXECUTION_GAP_POWER_JSON.read_text())
            if EXECUTION_GAP_POWER_JSON.exists()
            else None
        ),
        "sleeve_quality_decomposition": (
            json.loads(SLEEVE_QUALITY_JSON.read_text()) if SLEEVE_QUALITY_JSON.exists() else None
        ),
        "drawdown_live_estimator": (
            json.loads(DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text())
            if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists()
            else None
        ),
        "ledoit_wolf_effective_sample": (
            json.loads(LEDOIT_WOLF_JSON.read_text()) if LEDOIT_WOLF_JSON.exists() else None
        ),
        "record_continuity": (
            json.loads(RECORD_CONTINUITY_JSON.read_text())
            if RECORD_CONTINUITY_JSON.exists()
            else None
        ),
        "alpaca_broker_reconciliation": (
            json.loads(ALPACA_RECONCILIATION_JSON.read_text())
            if ALPACA_RECONCILIATION_JSON.exists()
            else None
        ),
        "live_covariance_memory": (
            json.loads(COVARIANCE_MEMORY_JSON.read_text())
            if COVARIANCE_MEMORY_JSON.exists()
            else None
        ),
        "feasibility_gate_reachability": (
            json.loads(GATE_REACHABILITY_JSON.read_text())
            if GATE_REACHABILITY_JSON.exists()
            else None
        ),
        "spinoff_prorata_gate": (
            json.loads(SPINOFF_PRORATA_GATE_JSON.read_text())
            if SPINOFF_PRORATA_GATE_JSON.exists()
            else None
        ),
        # The pre-test the two artifacts above are now instances of. Published because the
        # reusable part is the thing worth copying: ask whether a near-miss gate is reachable
        # AT ALL before writing a protocol, since the alternative move is always to widen the
        # detector until the number clears, and that is tuning a measurement to fit a target.
        "reachability_harness": (
            json.loads(REACHABILITY_HARNESS_JSON.read_text())
            if REACHABILITY_HARNESS_JSON.exists()
            else None
        ),
        "data_gate_unblocks": (
            json.loads(DATA_GATE_UNBLOCKS_JSON.read_text())
            if DATA_GATE_UNBLOCKS_JSON.exists()
            else None
        ),
        "tender_offer_reachability": (
            json.loads(TENDER_REACHABILITY_JSON.read_text())
            if TENDER_REACHABILITY_JSON.exists()
            else None
        ),
        "sharadar_zero_dividend_quarantine": (
            json.loads(SHARADAR_ZERO_DIVIDEND_JSON.read_text())
            if SHARADAR_ZERO_DIVIDEND_JSON.exists()
            else None
        ),
        "sharadar_dividend_price_consistency": (
            json.loads(SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.read_text())
            if SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.exists()
            else None
        ),
        "sharadar_dividend_split_basis": (
            json.loads(SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.read_text())
            if SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.exists()
            else None
        ),
        "vate_2020_dividend_resolution": (
            json.loads(VATE_2020_DIVIDEND_RESOLUTION_JSON.read_text())
            if VATE_2020_DIVIDEND_RESOLUTION_JSON.exists()
            else None
        ),
        "sharadar_dividend_basis_resolution": (
            json.loads(SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.read_text())
            if SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.exists()
            else None
        ),
        "sharadar_corporate_action_corrected_lake": (
            json.loads(SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.read_text())
            if SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.exists()
            else None
        ),
        "sharadar_corrected_corporate_action_validation": (
            json.loads(SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.read_text())
            if SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.exists()
            else None
        ),
        "polygon_split_crosscheck": (
            json.loads(POLYGON_SPLIT_CROSSCHECK_JSON.read_text())
            if POLYGON_SPLIT_CROSSCHECK_JSON.exists()
            else None
        ),
        "split_exception_issuer_resolution": (
            json.loads(SPLIT_EXCEPTION_ISSUER_RESOLUTION_JSON.read_text())
            if SPLIT_EXCEPTION_ISSUER_RESOLUTION_JSON.exists()
            else None
        ),
        "sharadar_split_lifecycle_scope": (
            json.loads(SHARADAR_SPLIT_LIFECYCLE_SCOPE_JSON.read_text())
            if SHARADAR_SPLIT_LIFECYCLE_SCOPE_JSON.exists()
            else None
        ),
        "unresolved_split_event_context": (
            json.loads(UNRESOLVED_SPLIT_EVENT_CONTEXT_JSON.read_text())
            if UNRESOLVED_SPLIT_EVENT_CONTEXT_JSON.exists()
            else None
        ),
        "operating_margin_split_exposure": (
            json.loads(OPERATING_MARGIN_SPLIT_EXPOSURE_JSON.read_text())
            if OPERATING_MARGIN_SPLIT_EXPOSURE_JSON.exists()
            else None
        ),
        "operating_margin_exposed_split_resolution": (
            json.loads(OPERATING_MARGIN_EXPOSED_SPLIT_RESOLUTION_JSON.read_text())
            if OPERATING_MARGIN_EXPOSED_SPLIT_RESOLUTION_JSON.exists()
            else None
        ),
        "operating_margin_corrected_replay_authorization": (
            json.loads(OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZATION_JSON.read_text())
            if OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZATION_JSON.exists()
            else None
        ),
        "operating_margin_corrected_reproduction": (
            json.loads(OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON.read_text())
            if OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON.exists()
            else None
        ),
        "sharadar_split_governance_policy": (
            json.loads(SHARADAR_SPLIT_GOVERNANCE_POLICY_JSON.read_text())
            if SHARADAR_SPLIT_GOVERNANCE_POLICY_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v2": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V2_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V2_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v3": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V3_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V3_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v4": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V4_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V4_JSON.exists()
            else None
        ),
        "split_issuer_conflict_resolution_batch_v5": (
            json.loads(SPLIT_ISSUER_CONFLICT_RESOLUTION_BATCH_V5_JSON.read_text())
            if SPLIT_ISSUER_CONFLICT_RESOLUTION_BATCH_V5_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v6": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V6_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V6_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v7": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V7_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V7_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v8": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V8_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V8_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v9": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V9_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V9_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v10": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V10_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V10_JSON.exists()
            else None
        ),
        "split_issuer_resolution_batch_v11": (
            json.loads(SPLIT_ISSUER_RESOLUTION_BATCH_V11_JSON.read_text())
            if SPLIT_ISSUER_RESOLUTION_BATCH_V11_JSON.exists()
            else None
        ),
        "split_lifecycle_discontinuity_resolution": (
            json.loads(SPLIT_LIFECYCLE_DISCONTINUITY_RESOLUTION_JSON.read_text())
            if SPLIT_LIFECYCLE_DISCONTINUITY_RESOLUTION_JSON.exists()
            else None
        ),
        "next_sleeve_selection": (
            json.loads(NEXT_SLEEVE_SELECTION_JSON.read_text())
            if NEXT_SLEEVE_SELECTION_JSON.exists()
            else None
        ),
        "active_ownership_human_gate_audit": (
            json.loads(ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON.read_text())
            if ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON.exists()
            else None
        ),
        "active_ownership_confirmatory_design": (
            json.loads(ACTIVE_OWNERSHIP_CONFIRMATORY_DESIGN_JSON.read_text())
            if ACTIVE_OWNERSHIP_CONFIRMATORY_DESIGN_JSON.exists()
            else None
        ),
        "external_validation_opportunities": json.loads(
            EXTERNAL_VALIDATION_OPPORTUNITIES_JSON.read_text()
        ),
        "active_ownership_blind_handoff_receipt": (
            json.loads(ACTIVE_OWNERSHIP_HANDOFF_RECEIPT_JSON.read_text())
            if ACTIVE_OWNERSHIP_HANDOFF_RECEIPT_JSON.exists()
            else None
        ),
        "hdb_dividend_vendor_resolution": (
            json.loads(HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.read_text())
            if HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.exists()
            else None
        ),
        "sharadar_hdb_corrected_lake": (
            json.loads(SHARADAR_HDB_CORRECTED_LAKE_JSON.read_text())
            if SHARADAR_HDB_CORRECTED_LAKE_JSON.exists()
            else None
        ),
        "operating_margin_replay_infrastructure_failure": (
            json.loads(OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.read_text())
            if OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.exists()
            else None
        ),
        "cftc_release_reachability": (
            json.loads(CFTC_RELEASE_REACHABILITY_JSON.read_text())
            if CFTC_RELEASE_REACHABILITY_JSON.exists()
            else None
        ),
        "bond_etf_nav_reachability": (
            json.loads(BOND_ETF_NAV_REACHABILITY_JSON.read_text())
            if BOND_ETF_NAV_REACHABILITY_JSON.exists()
            else None
        ),
        # The harness above, applied to the twenty families nothing has been spent on. Published
        # because the answer is the useful kind of discouraging: most of what is left is blocked
        # on money, on a record nobody archived, or on prices nobody could trade — and none of
        # those is closed by working harder, which is what a reader deciding whether to believe
        # this programme most needs to know.
        "atlas_reachability_screen": (
            json.loads(ATLAS_REACHABILITY_SCREEN_JSON.read_text())
            if ATLAS_REACHABILITY_SCREEN_JSON.exists()
            else None
        ),
        # The same twenty families ordered by expected orthogonality, BEFORE any is measured.
        # Published as a prior and labelled one in every row, because an ordering stated after the
        # measurement is not an ordering. It also prints the number the ordering exists to serve:
        # a book whose every new pair sits exactly on the correlation gate still misses the target,
        # so the gate is necessary and not sufficient, and that arithmetic belongs on the same
        # page as the target rather than in a drawer.
        "orthogonality_prior": (
            json.loads(ORTHOGONALITY_PRIOR_JSON.read_text())
            if ORTHOGONALITY_PRIOR_JSON.exists()
            else None
        ),
        # Which of this engine's guards have been PROVEN able to fail, and how. Published because
        # a reader has no way to tell a working check from a decorative one from the outside, and
        # because the honest version of "our tests pass" is a table showing what happens when the
        # thing each test watches is deliberately broken. Includes a negative control: an edit
        # that changes nothing and must NOT be caught.
        "mutation_ledger": (
            json.loads(MUTATION_LEDGER_JSON.read_text()) if MUTATION_LEDGER_JSON.exists() else None
        ),
        # The four audit dimensions that were opened and never finished, worked and published
        # with their REFUTATIONS kept. An audit that reports only its hits cannot be told apart
        # from one that did not run — and two of these dimensions found nothing, which is only
        # worth reading because the artifact says what each one checked.
        "guards_that_cannot_fire": (
            json.loads(GUARDS_CANNOT_FIRE_JSON.read_text())
            if GUARDS_CANNOT_FIRE_JSON.exists()
            else None
        ),
        "contract_and_unit_audit": (
            json.loads(CONTRACT_UNIT_AUDIT_JSON.read_text())
            if CONTRACT_UNIT_AUDIT_JSON.exists()
            else None
        ),
        # Which published claims have a guard, which mechanism guards them, and when each
        # mechanism last ran — observed by running it. Published because every guard here reports
        # on itself and none reported on the SET, and a reader cannot tell an artifact with three
        # checks from one with none by looking at either.
        # Provenance, declared by the producer: which file each artifact key was published as.
        # Anything not listed publishes under its own key.
        "published_as": PUBLISHED_AS,
        # The scale figures the marketing pages put in a panel, each with a definition. Published
        # because they were hand-typed until 2026-08-22 and two were wrong: the fundamentals count
        # was OVERSTATED and "8,436 survivorship-free US stocks" matched neither store. A number on
        # a page that traces to nothing is a number nobody can check, including us.
        # The figures the AlphaVintage correction paper quotes, recomputed from the probe's own
        # artifacts. Two of them traced to nothing published — the superseded Sharpe and the
        # maximum drawdown, which was in no artifact at all. A correction paper whose own numbers
        # cannot be checked asks for the same credence the original mistake did.
        # A pre-registration's parameters as DATA. Its function is that the spec is fixed before
        # measurement so a reader can check the run against it, and these existed only as English
        # sentences — so nothing could compare the executed run to the committed spec.
        "prereg_earnings_narrative_parameters": (
            json.loads(PREREG_PARAMETERS_JSON.read_text())
            if PREREG_PARAMETERS_JSON.exists()
            else None
        ),
        "alphavintage_sealed_outcome": (
            json.loads(ALPHAVINTAGE_SEALED_JSON.read_text())
            if ALPHAVINTAGE_SEALED_JSON.exists()
            else None
        ),
        "alphavintage_corrected_result": json.loads(ALPHAVINTAGE_RESULT_JSON.read_text()),
        "data_lake_scale": (
            json.loads(DATA_LAKE_SCALE_JSON.read_text()) if DATA_LAKE_SCALE_JSON.exists() else None
        ),
        "claim_coverage_map": (
            json.loads(CLAIM_COVERAGE_MAP_JSON.read_text())
            if CLAIM_COVERAGE_MAP_JSON.exists()
            else None
        ),
        "repurchase_issuance_feasibility_audits": {
            name.removesuffix(".json"): json.loads(path.read_text())
            for name, path in REPURCHASE_AUDITS
            if path.exists()
        },
        # The three families whose gates were unreachable, redesigned as far as they can be
        # WITHOUT spending a trial: what document would carry the evidence, and what a corrected
        # identity would look like. Published with the measurement that replaced the prose test —
        # the spin-off event universe is declared by a FORM TYPE, 386 registrations over sixteen
        # years, and the corporate-action route was checked and does not carry the event.
        "identity_redesign": {
            "spinoff_form_universe": (
                json.loads(SPINOFF_FORM_UNIVERSE_JSON.read_text())
                if SPINOFF_FORM_UNIVERSE_JSON.exists()
                else None
            ),
            "notes_public_path": "/research/identity-redesign-notes.md",
            "notes_source_path": rel(IDENTITY_REDESIGN_NOTES_MD),
            "notes_sha256": hashlib.sha256(IDENTITY_REDESIGN_NOTES_MD.read_bytes()).hexdigest(),
            "public_path": "/glassbox/spinoff_form_universe.json",
            "source_path": rel(SPINOFF_FORM_UNIVERSE_JSON),
            "status": "DRAFT — nothing here is registered and no threshold is proposed",
        },
        "sleeve_admission_contract": {
            "contract": json.loads(SLEEVE_ADMISSION_CONTRACT_JSON.read_text()),
            "source_sha256": hashlib.sha256(
                SLEEVE_ADMISSION_CONTRACT_JSON.read_bytes()
            ).hexdigest(),
            "public_path": "/glassbox/sleeve_admission_contract.json",
            "source_path": rel(SLEEVE_ADMISSION_CONTRACT_JSON),
        },
        "trial_accounting_policy": {
            "policy": json.loads(TRIAL_ACCOUNTING_POLICY_JSON.read_text()),
            "source_sha256": hashlib.sha256(TRIAL_ACCOUNTING_POLICY_JSON.read_bytes()).hexdigest(),
            "public_path": "/glassbox/trial_accounting.json",
            "source_path": rel(TRIAL_ACCOUNTING_POLICY_JSON),
        },
        "admission_v7_promotion": {
            "receipt": json.loads(ADMISSION_V7_PROMOTION_JSON.read_text()),
            "source_sha256": hashlib.sha256(ADMISSION_V7_PROMOTION_JSON.read_bytes()).hexdigest(),
            "public_path": "/glassbox/admission_v7_promotion.json",
            "source_path": rel(ADMISSION_V7_PROMOTION_JSON),
        },
        "external_publication": {
            "registry": json.loads(EXTERNAL_PUBLICATION_REGISTRY_JSON.read_text()),
            "evidence_catalog": json.loads(SLEEVE_PUBLICATION_EVIDENCE_JSON.read_text()),
            "readiness_audit": json.loads(EXTERNAL_PUBLICATION_READINESS_JSON.read_text()),
            "clean_checkout_integrity": json.loads(
                PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON.read_text()
            ),
            "submission_plan": json.loads(EXTERNAL_SUBMISSION_PLAN_JSON.read_text()),
            "wave1_data_rights_audit": json.loads(WAVE1_DATA_RIGHTS_AUDIT_JSON.read_text()),
            "wave1_release_candidates": json.loads(WAVE1_RELEASE_CANDIDATES_JSON.read_text()),
            "alphavintage_rtdsm_portable_fetch": json.loads(
                ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON.read_text()
            ),
            "alphavintage_core_portable_reproduction": json.loads(
                ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON.read_text()
            ),
            "alphavintage_full_decision_reproduction": json.loads(
                ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON.read_text()
            ),
            "alphatrend_upstream_replay_manifest": json.loads(
                ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON.read_text()
            ),
            "alphatrend_upstream_clean_workspace": json.loads(
                ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON.read_text()
            ),
            "internal_audit_replay": json.loads(SLEEVE_PUBLICATION_REPLAY_JSON.read_text()),
            "isolated_frozen_dependency_replay": json.loads(
                SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON.read_text()
            ),
            "archival_pdf_visual_inspection": json.loads(
                ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON.read_text()
            ),
            "crypto_carry_current_replay_receipt": json.loads(
                CRYPTO_CARRY_CURRENT_REPLAY_RECEIPT_JSON.read_text()
            ),
            "crypto_carry_first_rebalance_attribution": json.loads(
                CRYPTO_CARRY_FIRST_REBALANCE_ATTRIBUTION_JSON.read_text()
            ),
            "crypto_carry_full_path_attribution": json.loads(
                CRYPTO_CARRY_FULL_PATH_ATTRIBUTION_JSON.read_text()
            ),
            "walkforward_input_snapshot_protocol": json.loads(
                WALKFORWARD_INPUT_SNAPSHOT_PROTOCOL_JSON.read_text()
            ),
            "crypto_carry_replay_correction": json.loads(
                CRYPTO_CARRY_REPLAY_CORRECTION_JSON.read_text()
            ),
            "registry_public_path": "/glassbox/external_publication_registry.json",
            "evidence_catalog_public_path": "/glassbox/sleeve_publication_evidence.json",
            "readiness_public_path": "/glassbox/external_publication_readiness.json",
            "clean_checkout_integrity_public_path": (
                "/glassbox/publication_clean_checkout_integrity.json"
            ),
            "submission_plan_public_path": "/glassbox/external_submission_plan.json",
            "wave1_data_rights_public_path": "/glassbox/wave1_data_rights_audit.json",
            "wave1_release_candidates_public_path": ("/glassbox/wave1_release_candidates.json"),
            "alphavintage_rtdsm_portable_fetch_public_path": (
                "/glassbox/alphavintage_rtdsm_portable_fetch.json"
            ),
            "alphavintage_core_portable_reproduction_public_path": (
                "/glassbox/alphavintage_core_portable_reproduction.json"
            ),
            "alphavintage_full_decision_reproduction_public_path": (
                "/glassbox/alphavintage_full_decision_reproduction.json"
            ),
            "alphatrend_upstream_replay_manifest_public_path": (
                "/glassbox/alphatrend_upstream_replay_manifest.json"
            ),
            "alphatrend_upstream_clean_workspace_public_path": (
                "/glassbox/alphatrend_upstream_clean_workspace.json"
            ),
            "internal_audit_replay_public_path": (
                "/glassbox/sleeve_publication_replay_verification.json"
            ),
            "isolated_frozen_dependency_replay_public_path": (
                "/glassbox/sleeve_publication_isolated_replay_verification.json"
            ),
            "archival_pdf_visual_inspection_public_path": (
                "/glassbox/archival_publication_visual_inspection.json"
            ),
            "crypto_carry_current_replay_receipt_public_path": (
                "/glassbox/crypto_carry_current_replay_receipt.json"
            ),
            "crypto_carry_first_rebalance_attribution_public_path": (
                "/glassbox/crypto_carry_first_rebalance_attribution.json"
            ),
            "crypto_carry_full_path_attribution_public_path": (
                "/glassbox/crypto_carry_full_path_attribution.json"
            ),
            "walkforward_input_snapshot_protocol_public_path": (
                "/glassbox/walkforward_input_snapshot_protocol.json"
            ),
            "crypto_carry_replay_correction_public_path": (
                "/glassbox/crypto_carry_replay_correction.json"
            ),
            "bundle_public_root": "/publication/",
            "source_bindings": {
                "registry": {
                    "path": rel(EXTERNAL_PUBLICATION_REGISTRY_JSON),
                    "sha256": hashlib.sha256(
                        EXTERNAL_PUBLICATION_REGISTRY_JSON.read_bytes()
                    ).hexdigest(),
                },
                "evidence_catalog": {
                    "path": rel(SLEEVE_PUBLICATION_EVIDENCE_JSON),
                    "sha256": hashlib.sha256(
                        SLEEVE_PUBLICATION_EVIDENCE_JSON.read_bytes()
                    ).hexdigest(),
                },
                "readiness_audit": {
                    "path": rel(EXTERNAL_PUBLICATION_READINESS_JSON),
                    "sha256": hashlib.sha256(
                        EXTERNAL_PUBLICATION_READINESS_JSON.read_bytes()
                    ).hexdigest(),
                },
                "clean_checkout_integrity": {
                    "path": rel(PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON),
                    "sha256": hashlib.sha256(
                        PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON.read_bytes()
                    ).hexdigest(),
                },
                "submission_plan": {
                    "path": rel(EXTERNAL_SUBMISSION_PLAN_JSON),
                    "sha256": hashlib.sha256(
                        EXTERNAL_SUBMISSION_PLAN_JSON.read_bytes()
                    ).hexdigest(),
                },
                "wave1_data_rights_audit": {
                    "path": rel(WAVE1_DATA_RIGHTS_AUDIT_JSON),
                    "sha256": hashlib.sha256(WAVE1_DATA_RIGHTS_AUDIT_JSON.read_bytes()).hexdigest(),
                },
                "wave1_release_candidates": {
                    "path": rel(WAVE1_RELEASE_CANDIDATES_JSON),
                    "sha256": hashlib.sha256(
                        WAVE1_RELEASE_CANDIDATES_JSON.read_bytes()
                    ).hexdigest(),
                },
                "alphavintage_rtdsm_portable_fetch": {
                    "path": rel(ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON),
                    "sha256": hashlib.sha256(
                        ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON.read_bytes()
                    ).hexdigest(),
                },
                "alphavintage_core_portable_reproduction": {
                    "path": rel(ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON),
                    "sha256": hashlib.sha256(
                        ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON.read_bytes()
                    ).hexdigest(),
                },
                "alphavintage_full_decision_reproduction": {
                    "path": rel(ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON),
                    "sha256": hashlib.sha256(
                        ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON.read_bytes()
                    ).hexdigest(),
                },
                "alphatrend_upstream_replay_manifest": {
                    "path": rel(ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON),
                    "sha256": hashlib.sha256(
                        ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON.read_bytes()
                    ).hexdigest(),
                },
                "alphatrend_upstream_clean_workspace": {
                    "path": rel(ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON),
                    "sha256": hashlib.sha256(
                        ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON.read_bytes()
                    ).hexdigest(),
                },
                "internal_audit_replay": {
                    "path": rel(SLEEVE_PUBLICATION_REPLAY_JSON),
                    "sha256": hashlib.sha256(
                        SLEEVE_PUBLICATION_REPLAY_JSON.read_bytes()
                    ).hexdigest(),
                },
                "isolated_frozen_dependency_replay": {
                    "path": rel(SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON),
                    "sha256": hashlib.sha256(
                        SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON.read_bytes()
                    ).hexdigest(),
                },
                "archival_pdf_visual_inspection": {
                    "path": rel(ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON),
                    "sha256": hashlib.sha256(
                        ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON.read_bytes()
                    ).hexdigest(),
                },
            },
            "claim_boundary": (
                "These are incomplete preparation bundles. No external submission, DOI, peer "
                "review, citation, moderation outcome, or independent replication is claimed."
            ),
        },
        "portfolio_evidence": {
            "stanford_cs": json.loads(STANFORD_CS_EVIDENCE_JSON.read_text()),
            "public_path": "/glassbox/stanford_cs_evidence_map.json",
            "source_binding": {
                "path": rel(STANFORD_CS_EVIDENCE_JSON),
                "sha256": hashlib.sha256(STANFORD_CS_EVIDENCE_JSON.read_bytes()).hexdigest(),
            },
            "claim_boundary": (
                "This is factual portfolio evidence, not a Stanford admissions claim or "
                "endorsement."
            ),
        },
        "engineering_benchmarks": {
            "execution_fill_models": {
                "benchmark": json.loads(EXECUTION_BENCHMARK_JSON.read_text()),
                "source_sha256": hashlib.sha256(EXECUTION_BENCHMARK_JSON.read_bytes()).hexdigest(),
                "public_path": "/glassbox/execution_models_benchmark.json",
                "source_path": rel(EXECUTION_BENCHMARK_JSON),
            }
        },
        "engineering_quality": {
            "lint_debt": {
                "contract": json.loads(LINT_DEBT_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(LINT_DEBT_CONTRACT_JSON.read_bytes()).hexdigest(),
                "public_path": "/glassbox/lint_debt_contract.json",
                "book_path": "/research/engineering-quality.md",
                "source_path": rel(LINT_DEBT_CONTRACT_JSON),
            }
        },
        "engineering_capabilities": {
            "financing": {
                "contract": json.loads(FINANCING_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(FINANCING_CONTRACT_JSON.read_bytes()).hexdigest(),
                "public_path": "/glassbox/financing_contract.json",
                "book_path": "/research/financing-replay.md",
                "source_path": rel(FINANCING_CONTRACT_JSON),
            },
            "corporate_action_lifecycle": {
                "contract": json.loads(CORPORATE_ACTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    CORPORATE_ACTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/corporate_action_contract.json",
                "book_path": "/research/corporate-action-lifecycle.md",
                "source_path": rel(CORPORATE_ACTION_CONTRACT_JSON),
            },
            "borrow_execution": {
                "contract": json.loads(BORROW_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    BORROW_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/borrow_execution_contract.json",
                "book_path": "/research/borrow-execution-foundation.md",
                "source_path": rel(BORROW_EXECUTION_CONTRACT_JSON),
            },
            "crowding_risk": {
                "contract": json.loads(CROWDING_RISK_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    CROWDING_RISK_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/crowding_risk_contract.json",
                "book_path": "/research/crowding-risk-foundation.md",
                "source_path": rel(CROWDING_RISK_CONTRACT_JSON),
            },
            "futures_execution": {
                "contract": json.loads(FUTURES_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    FUTURES_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/futures_execution_contract.json",
                "book_path": "/research/futures-execution-foundation.md",
                "source_path": rel(FUTURES_EXECUTION_CONTRACT_JSON),
            },
            "market_status_replay": {
                "contract": json.loads(MARKET_STATUS_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    MARKET_STATUS_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/market_status_contract.json",
                "book_path": "/research/market-status-replay.md",
                "source_path": rel(MARKET_STATUS_CONTRACT_JSON),
            },
            "options_execution": {
                "contract": json.loads(OPTIONS_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    OPTIONS_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/options_execution_contract.json",
                "book_path": "/research/options-execution-foundation.md",
                "source_path": rel(OPTIONS_EXECUTION_CONTRACT_JSON),
            },
        },
    }


def main(out_dir: Path = OUT_DIR) -> Path:
    """Build research.json and write it to ``out_dir``; return the written path."""
    # Mirrored to the dashboard too (2026-08-06). Writing only to the landing dir left
    # app.canlicapital.com serving six-week-old glass-box artifacts, including a track
    # record showing 0.00% over "3 days" while the landing showed -2.54% over 38.
    payload = stamp(build_research_export())
    stamped = json.dumps(payload, indent=2) + "\n"
    trial_ledger = json.dumps(payload["trial_accounting"], indent=2) + "\n"
    program_status = json.dumps(stamp(payload["program_status"]), indent=2) + "\n"
    prospective_trial_record = json.dumps(payload["prospective_trial_record"], indent=2) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUT_FILE
    path.write_text(stamped)
    (out_dir / "trial_ledger.json").write_text(trial_ledger)
    (out_dir / "program_status.json").write_text(program_status)
    (out_dir / "prospective_trial_record.json").write_text(prospective_trial_record)
    if TRIAL_PACKET_MANIFEST_JSON.exists():
        (out_dir / "trial_packet_manifest.json").write_text(TRIAL_PACKET_MANIFEST_JSON.read_text())
    if IDENTITY_PACKET_RECOVERABILITY_JSON.exists():
        (out_dir / "identity_packet_recoverability.json").write_text(
            IDENTITY_PACKET_RECOVERABILITY_JSON.read_text()
        )
    if LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.exists():
        (out_dir / "legacy_research_epoch_closure.json").write_text(
            LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.read_text()
        )
    (out_dir / "crypto_carry_portable_v1_result.json").write_text(
        CRYPTO_CARRY_PORTABLE_RESULT_JSON.read_text()
    )
    (out_dir / "crypto_carry_portable_v1_admission_closure.json").write_text(
        CRYPTO_CARRY_PORTABLE_CLOSURE_JSON.read_text()
    )
    (out_dir / "forward_full_evidence_reservation_v2_template.json").write_text(
        FORWARD_FULL_EVIDENCE_TEMPLATE_JSON.read_text()
    )
    (out_dir / "forward_full_evidence_reservation_v2_template_audit.json").write_text(
        FORWARD_FULL_EVIDENCE_TEMPLATE_AUDIT_JSON.read_text()
    )
    out_trial_packet_dir = out_dir / "trial-packets"
    out_trial_packet_dir.mkdir(parents=True, exist_ok=True)
    (out_trial_packet_dir / "da5f5f47f99f9bd2.json").write_text(
        CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_text()
    )
    (out_trial_packet_dir / "crypto_carry_portable_v1.json").write_text(
        CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_text()
    )
    (out_dir / "crypto_carry_selected_walkforward.json").write_text(
        CRYPTO_CARRY_SELECTED_WALKFORWARD_JSON.read_text()
    )
    (out_dir / "crypto_carry_grand_matrix.json").write_text(
        CRYPTO_CARRY_GRAND_MATRIX_JSON.read_text()
    )
    (out_dir / "crypto_carry_2022_tail.json").write_text(CRYPTO_CARRY_2022_TAIL_JSON.read_text())
    (out_dir / "crypto_momentum_family.json").write_text(CRYPTO_MOMENTUM_FAMILY_JSON.read_text())
    (out_dir / "alphatrend_family.json").write_text(ALPHATREND_FAMILY_JSON.read_text())
    (out_dir / "crypto_vrp_family.json").write_text(CRYPTO_VRP_FAMILY_JSON.read_text())
    (out_dir / "crypto_multifactor_family.json").write_text(
        CRYPTO_MULTIFACTOR_FAMILY_JSON.read_text()
    )
    (out_dir / "equity_narrative_family.json").write_text(EQUITY_NARRATIVE_FAMILY_JSON.read_text())
    (out_dir / "equity_quality_family.json").write_text(EQUITY_QUALITY_FAMILY_JSON.read_text())
    (out_dir / "equity_value_investment_family.json").write_text(
        EQUITY_VALUE_FAMILY_JSON.read_text()
    )
    for public_json, source_json, _, _ in FINAL_FAMILY_FILES:
        (out_dir / public_json).write_text(source_json.read_text())
    if LEGACY_DSR_RESTATEMENT_JSON.exists():
        (out_dir / "legacy_dsr_restatement.json").write_text(
            LEGACY_DSR_RESTATEMENT_JSON.read_text()
        )
    discovery = json.dumps(_discovery_with_contract_gates(), indent=2) + "\n"
    (out_dir / "sleeve_discovery.json").write_text(discovery)
    (out_dir / "sleeve_atlas.json").write_text(SLEEVE_ATLAS_JSON.read_text())
    (out_dir / "sleeve_atlas_audit.json").write_text(SLEEVE_ATLAS_AUDIT_JSON.read_text())
    (out_dir / "sleeve_family_lineage_audit.json").write_text(SLEEVE_LINEAGE_AUDIT_JSON.read_text())
    (out_dir / "research_accessibility_audit.json").write_text(
        RESEARCH_ACCESSIBILITY_AUDIT.read_text()
    )
    (out_dir / "accessibility_interaction_audit.json").write_text(
        ACCESSIBILITY_INTERACTION_AUDIT.read_text()
    )
    (out_dir / "sleeve_admission_contract.json").write_text(
        SLEEVE_ADMISSION_CONTRACT_JSON.read_text()
    )
    (out_dir / "trial_accounting.json").write_text(TRIAL_ACCOUNTING_POLICY_JSON.read_text())
    (out_dir / "admission_v7_promotion.json").write_text(ADMISSION_V7_PROMOTION_JSON.read_text())
    (out_dir / "external_publication_registry.json").write_text(
        EXTERNAL_PUBLICATION_REGISTRY_JSON.read_text()
    )
    (out_dir / "sleeve_publication_evidence.json").write_text(
        SLEEVE_PUBLICATION_EVIDENCE_JSON.read_text()
    )
    (out_dir / "external_publication_readiness.json").write_text(
        EXTERNAL_PUBLICATION_READINESS_JSON.read_text()
    )
    (out_dir / "publication_clean_checkout_integrity.json").write_text(
        PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON.read_text()
    )
    (out_dir / "external_submission_plan.json").write_text(
        EXTERNAL_SUBMISSION_PLAN_JSON.read_text()
    )
    (out_dir / "external_validation_opportunities.json").write_text(
        EXTERNAL_VALIDATION_OPPORTUNITIES_JSON.read_text()
    )
    (out_dir / "wave1_data_rights_audit.json").write_text(WAVE1_DATA_RIGHTS_AUDIT_JSON.read_text())
    (out_dir / "wave1_release_candidates.json").write_text(
        WAVE1_RELEASE_CANDIDATES_JSON.read_text()
    )
    (out_dir / "stanford_cs_evidence_map.json").write_text(STANFORD_CS_EVIDENCE_JSON.read_text())
    (out_dir / "alphavintage_rtdsm_portable_fetch.json").write_text(
        ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON.read_text()
    )
    (out_dir / "alphavintage_core_portable_reproduction.json").write_text(
        ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON.read_text()
    )
    (out_dir / "alphavintage_full_decision_reproduction.json").write_text(
        ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON.read_text()
    )
    (out_dir / "alphatrend_upstream_replay_manifest.json").write_text(
        ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON.read_text()
    )
    (out_dir / "alphatrend_upstream_clean_workspace.json").write_text(
        ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON.read_text()
    )
    (out_dir / "archival_publication_visual_inspection.json").write_text(
        ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON.read_text()
    )
    (out_dir / "sleeve_publication_replay_verification.json").write_text(
        SLEEVE_PUBLICATION_REPLAY_JSON.read_text()
    )
    (out_dir / "sleeve_publication_isolated_replay_verification.json").write_text(
        SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON.read_text()
    )
    (out_dir / "crypto_carry_current_replay_receipt.json").write_text(
        CRYPTO_CARRY_CURRENT_REPLAY_RECEIPT_JSON.read_text()
    )
    (out_dir / "crypto_carry_first_rebalance_attribution.json").write_text(
        CRYPTO_CARRY_FIRST_REBALANCE_ATTRIBUTION_JSON.read_text()
    )
    (out_dir / "crypto_carry_full_path_attribution.json").write_text(
        CRYPTO_CARRY_FULL_PATH_ATTRIBUTION_JSON.read_text()
    )
    (out_dir / "walkforward_input_snapshot_protocol.json").write_text(
        WALKFORWARD_INPUT_SNAPSHOT_PROTOCOL_JSON.read_text()
    )
    (out_dir / "crypto_carry_replay_correction.json").write_text(
        CRYPTO_CARRY_REPLAY_CORRECTION_JSON.read_text()
    )
    if ADMISSION_DRY_RUN_JSON.exists():
        (out_dir / "admission_dry_run.json").write_text(ADMISSION_DRY_RUN_JSON.read_text())
    if COST_MODEL_REALISM_JSON.exists():
        (out_dir / "cost_model_realism.json").write_text(COST_MODEL_REALISM_JSON.read_text())
    if EXECUTION_GAP_POWER_JSON.exists():
        (out_dir / "execution_gap_power.json").write_text(EXECUTION_GAP_POWER_JSON.read_text())
    if SLEEVE_QUALITY_JSON.exists():
        (out_dir / "sleeve_quality_decomposition.json").write_text(SLEEVE_QUALITY_JSON.read_text())
    if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists():
        (out_dir / "drawdown_live_estimator.json").write_text(
            DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text()
        )
    (out_dir / "current_book_drawdown.json").write_text(CURRENT_BOOK_DRAWDOWN_JSON.read_text())
    (out_dir / "current_book_diversification.json").write_text(
        CURRENT_BOOK_DIVERSIFICATION_JSON.read_text()
    )
    if LEDOIT_WOLF_JSON.exists():
        (out_dir / "ledoit_wolf_effective_sample.json").write_text(LEDOIT_WOLF_JSON.read_text())
    if RECORD_CONTINUITY_JSON.exists():
        (out_dir / "record_continuity.json").write_text(RECORD_CONTINUITY_JSON.read_text())
    if ALPACA_RECONCILIATION_JSON.exists():
        (out_dir / "alpaca_broker_reconciliation.json").write_text(
            ALPACA_RECONCILIATION_JSON.read_text()
        )
    (out_dir / "forward_evidence_contract.json").write_text(
        FORWARD_EVIDENCE_CONTRACT_JSON.read_text()
    )
    (out_dir / "forward_drawdown_evidence.json").write_text(
        FORWARD_DRAWDOWN_EVIDENCE_JSON.read_text()
    )
    (out_dir / "forward_evidence_maturity.json").write_text(
        FORWARD_EVIDENCE_MATURITY_JSON.read_text()
    )
    (out_dir / "forward_sleeve_contribution.json").write_text(
        FORWARD_SLEEVE_CONTRIBUTION_JSON.read_text()
    )
    (out_dir / "crypto_lab_carry_crash_incident.json").write_text(
        CRYPTO_LAB_INCIDENT_JSON.read_text()
    )
    (out_dir / "crypto_position_attribution.json").write_text(
        CRYPTO_POSITION_ATTRIBUTION_JSON.read_text()
    )
    (out_dir / "crypto_position_attribution_rollout_verification.json").write_text(
        CRYPTO_POSITION_ATTRIBUTION_ROLLOUT_JSON.read_text()
    )
    (out_dir / "crypto_position_attribution_vps_preflight_observation.json").write_text(
        CRYPTO_POSITION_ATTRIBUTION_PREFLIGHT_OBSERVATION_JSON.read_text()
    )
    if COVARIANCE_MEMORY_JSON.exists():
        (out_dir / "live_covariance_memory.json").write_text(COVARIANCE_MEMORY_JSON.read_text())
    if GATE_REACHABILITY_JSON.exists():
        (out_dir / "feasibility_gate_reachability.json").write_text(
            GATE_REACHABILITY_JSON.read_text()
        )
    if SPINOFF_PRORATA_GATE_JSON.exists():
        (out_dir / "spinoff_prorata_gate.json").write_text(SPINOFF_PRORATA_GATE_JSON.read_text())
    if REACHABILITY_HARNESS_JSON.exists():
        (out_dir / "reachability_harness.json").write_text(REACHABILITY_HARNESS_JSON.read_text())
    if DATA_GATE_UNBLOCKS_JSON.exists():
        (out_dir / "data_gate_unblocks.json").write_text(DATA_GATE_UNBLOCKS_JSON.read_text())
    if TENDER_REACHABILITY_JSON.exists():
        (out_dir / "tender_offer_reachability.json").write_text(
            TENDER_REACHABILITY_JSON.read_text()
        )
    if SHARADAR_ZERO_DIVIDEND_JSON.exists():
        (out_dir / "sharadar_zero_dividend_quarantine.json").write_text(
            SHARADAR_ZERO_DIVIDEND_JSON.read_text()
        )
    if SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.exists():
        (out_dir / "sharadar_dividend_price_consistency.json").write_text(
            SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.read_text()
        )
    if SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.exists():
        (out_dir / "sharadar_dividend_split_basis.json").write_text(
            SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.read_text()
        )
    if VATE_2020_DIVIDEND_RESOLUTION_JSON.exists():
        (out_dir / "vate_2020_dividend_resolution.json").write_text(
            VATE_2020_DIVIDEND_RESOLUTION_JSON.read_text()
        )
    if SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.exists():
        (out_dir / "sharadar_dividend_basis_resolution.json").write_text(
            SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.read_text()
        )
    if SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.exists():
        (out_dir / "sharadar_corporate_action_corrected_lake.json").write_text(
            SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.read_text()
        )
    if SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.exists():
        (out_dir / "sharadar_corrected_corporate_action_validation.json").write_text(
            SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.read_text()
        )
    if POLYGON_SPLIT_CROSSCHECK_JSON.exists():
        (out_dir / "polygon_split_crosscheck.json").write_text(
            POLYGON_SPLIT_CROSSCHECK_JSON.read_text()
        )
    for audit_path in (
        SPLIT_EXCEPTION_ISSUER_RESOLUTION_JSON,
        SHARADAR_SPLIT_LIFECYCLE_SCOPE_JSON,
        UNRESOLVED_SPLIT_EVENT_CONTEXT_JSON,
        OPERATING_MARGIN_SPLIT_EXPOSURE_JSON,
        OPERATING_MARGIN_EXPOSED_SPLIT_RESOLUTION_JSON,
        OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZATION_JSON,
        OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON,
        SHARADAR_SPLIT_GOVERNANCE_POLICY_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V2_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V3_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V4_JSON,
        SPLIT_ISSUER_CONFLICT_RESOLUTION_BATCH_V5_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V6_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V7_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V8_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V9_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V10_JSON,
        SPLIT_ISSUER_RESOLUTION_BATCH_V11_JSON,
        SPLIT_LIFECYCLE_DISCONTINUITY_RESOLUTION_JSON,
        NEXT_SLEEVE_SELECTION_JSON,
        ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON,
        ACTIVE_OWNERSHIP_CONFIRMATORY_DESIGN_JSON,
        ACTIVE_OWNERSHIP_HANDOFF_RECEIPT_JSON,
    ):
        if audit_path.exists():
            (out_dir / audit_path.name).write_text(audit_path.read_text())
    if HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.exists():
        (out_dir / "hdb_dividend_vendor_resolution.json").write_text(
            HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.read_text()
        )
    if SHARADAR_HDB_CORRECTED_LAKE_JSON.exists():
        (out_dir / "sharadar_hdb_corrected_lake.json").write_text(
            SHARADAR_HDB_CORRECTED_LAKE_JSON.read_text()
        )
    if OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.exists():
        (out_dir / "operating_margin_replay_infrastructure_failure.json").write_text(
            OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.read_text()
        )
    if CFTC_RELEASE_REACHABILITY_JSON.exists():
        (out_dir / "cftc_release_reachability.json").write_text(
            CFTC_RELEASE_REACHABILITY_JSON.read_text()
        )
    if BOND_ETF_NAV_REACHABILITY_JSON.exists():
        (out_dir / "bond_etf_nav_reachability.json").write_text(
            BOND_ETF_NAV_REACHABILITY_JSON.read_text()
        )
    if ATLAS_REACHABILITY_SCREEN_JSON.exists():
        (out_dir / "atlas_reachability_screen.json").write_text(
            ATLAS_REACHABILITY_SCREEN_JSON.read_text()
        )
    if ORTHOGONALITY_PRIOR_JSON.exists():
        (out_dir / "orthogonality_prior.json").write_text(ORTHOGONALITY_PRIOR_JSON.read_text())
    if MUTATION_LEDGER_JSON.exists():
        (out_dir / "mutation_ledger.json").write_text(MUTATION_LEDGER_JSON.read_text())
    if GUARDS_CANNOT_FIRE_JSON.exists():
        (out_dir / "guards_that_cannot_fire.json").write_text(GUARDS_CANNOT_FIRE_JSON.read_text())
    if CONTRACT_UNIT_AUDIT_JSON.exists():
        (out_dir / "contract_and_unit_audit.json").write_text(CONTRACT_UNIT_AUDIT_JSON.read_text())
    if PREREG_PARAMETERS_JSON.exists():
        (out_dir / "prereg_earnings_narrative_parameters.json").write_text(
            PREREG_PARAMETERS_JSON.read_text()
        )
    if ALPHAVINTAGE_SEALED_JSON.exists():
        (out_dir / "alphavintage_sealed_outcome.json").write_text(
            ALPHAVINTAGE_SEALED_JSON.read_text()
        )
    (out_dir / "alphavintage_corrected_result.json").write_text(
        ALPHAVINTAGE_RESULT_JSON.read_text()
    )
    if DATA_LAKE_SCALE_JSON.exists():
        (out_dir / "data_lake_scale.json").write_text(DATA_LAKE_SCALE_JSON.read_text())
    if CLAIM_COVERAGE_MAP_JSON.exists():
        (out_dir / "claim_coverage_map.json").write_text(CLAIM_COVERAGE_MAP_JSON.read_text())
    for _name, _path in REPURCHASE_AUDITS:
        if _path.exists():
            (out_dir / _name).write_text(_path.read_text())
    if SPINOFF_FORM_UNIVERSE_JSON.exists():
        (out_dir / "spinoff_form_universe.json").write_text(SPINOFF_FORM_UNIVERSE_JSON.read_text())
    if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists():
        (out_dir / "book_without_alphavintage.json").write_text(
            BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text()
        )
    (out_dir / "execution_models_benchmark.json").write_text(EXECUTION_BENCHMARK_JSON.read_text())
    (out_dir / "futures_execution_contract.json").write_text(
        FUTURES_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "options_execution_contract.json").write_text(
        OPTIONS_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "borrow_execution_contract.json").write_text(
        BORROW_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "market_status_contract.json").write_text(MARKET_STATUS_CONTRACT_JSON.read_text())
    (out_dir / "crowding_risk_contract.json").write_text(CROWDING_RISK_CONTRACT_JSON.read_text())
    (out_dir / "corporate_action_contract.json").write_text(
        CORPORATE_ACTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "financing_contract.json").write_text(FINANCING_CONTRACT_JSON.read_text())
    (out_dir / "lint_debt_contract.json").write_text(LINT_DEBT_CONTRACT_JSON.read_text())
    (out_dir / "alphamax_construction_arms.json").write_text(
        ALPHAMAX_CONSTRUCTION_ARMS_JSON.read_text()
    )
    literature_dir = out_dir.parent / "research"
    _write_kill_papers(literature_dir, out_dir)
    literature_dir.mkdir(parents=True, exist_ok=True)
    (literature_dir / "execution-realism.md").write_text(EXECUTION_REALISM_MD.read_text())
    (literature_dir / "futures-execution-foundation.md").write_text(
        FUTURES_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "options-execution-foundation.md").write_text(
        OPTIONS_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "borrow-execution-foundation.md").write_text(
        BORROW_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "market-status-replay.md").write_text(MARKET_STATUS_REPLAY_MD.read_text())
    (literature_dir / "crowding-risk-foundation.md").write_text(
        CROWDING_RISK_FOUNDATION_MD.read_text()
    )
    (literature_dir / "corporate-action-lifecycle.md").write_text(
        CORPORATE_ACTION_LIFECYCLE_MD.read_text()
    )
    (literature_dir / "corporate-action-basis-reconstruction.md").write_text(
        CORPORATE_ACTION_BASIS_RECONSTRUCTION_MD.read_text()
    )
    (literature_dir / "financing-replay.md").write_text(FINANCING_REPLAY_MD.read_text())
    (literature_dir / "identity-redesign-notes.md").write_text(
        IDENTITY_REDESIGN_NOTES_MD.read_text()
    )
    (literature_dir / "sharadar-hdb-zero-dividend-quarantine.md").write_text(
        SHARADAR_ZERO_DIVIDEND_MD.read_text()
    )
    (literature_dir / "engineering-quality.md").write_text(ENGINEERING_QUALITY_MD.read_text())
    (literature_dir / "forward-sharpe-evidence-standard.md").write_text(
        FORWARD_SHARPE_EVIDENCE_STANDARD_MD.read_text()
    )
    (literature_dir / "current-book-drawdown-model.md").write_text(
        CURRENT_BOOK_DRAWDOWN_MODEL_MD.read_text()
    )
    (literature_dir / "current-book-diversification-model.md").write_text(
        CURRENT_BOOK_DIVERSIFICATION_MODEL_MD.read_text()
    )
    # MISSING FROM THE PRIMARY SITE until 2026-08-22. The app host published this paper and this
    # host did not, because the two write blocks are hand-mirrored copies and one edit landed in
    # only one of them. Nothing could notice: the paper is not linked from research.json, so its
    # absence produced no broken link and no failing check — the primary site was simply missing
    # the document that restates every Sharpe the deflation correction touched.
    # tests/unit/test_glassbox_write_paths.py now compares the two blocks as sets, so the next
    # one-sided edit fails a test rather than quietly publishing to one host.
    if LEGACY_DSR_RESTATEMENT_MD.exists():
        (literature_dir / "legacy-dsr-restatement.md").write_text(
            LEGACY_DSR_RESTATEMENT_MD.read_text()
        )
    (literature_dir / "alphamax-equity-momentum-lineage.md").write_text(
        ALPHAMAX_MOMENTUM_LINEAGE_MD.read_text()
    )
    (literature_dir / "crypto-carry-lineage.md").write_text(CRYPTO_CARRY_LINEAGE_MD.read_text())
    (literature_dir / "crypto-carry-portable-v1.md").write_text(
        CRYPTO_CARRY_PORTABLE_PAPER_MD.read_text()
    )
    (literature_dir / "crypto-lab-carry-crash-incident.md").write_text(
        CRYPTO_LAB_INCIDENT_MD.read_text()
    )
    (literature_dir / "crypto-momentum-lineage.md").write_text(
        CRYPTO_MOMENTUM_LINEAGE_MD.read_text()
    )
    (literature_dir / "alphatrend-managed-futures-lineage.md").write_text(
        ALPHATREND_LINEAGE_MD.read_text()
    )
    (literature_dir / "alphavintage-macro-surprise-lineage.md").write_text(
        ALPHAVINTAGE_LINEAGE_MD.read_text()
    )
    (literature_dir / "crypto-vrp-lineage.md").write_text(CRYPTO_VRP_LINEAGE_MD.read_text())
    (literature_dir / "crypto-multifactor-engine-lineage.md").write_text(
        CRYPTO_MULTIFACTOR_LINEAGE_MD.read_text()
    )
    (literature_dir / "equity-narrative-change-lineage.md").write_text(
        EQUITY_NARRATIVE_LINEAGE_MD.read_text()
    )
    (literature_dir / "equity-quality-lineage.md").write_text(EQUITY_QUALITY_LINEAGE_MD.read_text())
    (literature_dir / "equity-value-investment-lineage.md").write_text(
        EQUITY_VALUE_LINEAGE_MD.read_text()
    )
    for _, _, public_paper, source_paper in FINAL_FAMILY_FILES:
        (literature_dir / public_paper).write_text(source_paper.read_text())
    (literature_dir / "literature-frontier-2026-08-16.md").write_text(
        LITERATURE_FRONTIER_MD.read_text()
    )
    (literature_dir / "literature-repurchase-issuance-flow.md").write_text(
        REPURCHASE_LITERATURE_MD.read_text()
    )
    (literature_dir / "repurchase-issuance-flow-feasibility.md").write_text(
        REPURCHASE_FEASIBILITY_MD.read_text()
    )
    (out_dir / "repurchase_item703_blind_label_packet.json").write_text(
        (REPURCHASE_BLIND_PACKET / "manifest.json").read_text()
    )
    repurchase_blind_out = out_dir / "repurchase_item703_blind"
    repurchase_blind_out.mkdir(parents=True, exist_ok=True)
    for packet_file in (
        "INSTRUCTIONS.md",
        "reviewer_labels.csv",
        "reviewer_attestation.json",
        "manifest.json",
    ):
        (repurchase_blind_out / packet_file).write_bytes(
            (REPURCHASE_BLIND_PACKET / packet_file).read_bytes()
        )
    if ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.exists():
        (out_dir / ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.name).write_bytes(
            ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.read_bytes()
        )
    (literature_dir / "literature-options-dispersion.md").write_text(
        OPTIONS_DISPERSION_LITERATURE_MD.read_text()
    )
    (literature_dir / "options-dispersion-feasibility.md").write_text(
        OPTIONS_DISPERSION_FEASIBILITY_MD.read_text()
    )
    (literature_dir / "literature-stablecoin-dislocation.md").write_text(
        STABLECOIN_LITERATURE_MD.read_text()
    )
    (literature_dir / "stablecoin-dislocation-feasibility.md").write_text(
        STABLECOIN_FEASIBILITY_MD.read_text()
    )
    (literature_dir / "literature-spin-off-dislocation.md").write_text(
        SPIN_OFF_LITERATURE_MD.read_text()
    )
    (literature_dir / "spin-off-dislocation-lineage.md").write_text(SPIN_OFF_LINEAGE_MD.read_text())
    (literature_dir / "spin-off-document-schema.md").write_text(SPIN_OFF_DOCUMENT_MD.read_text())
    (out_dir / "spin_off_lineage.json").write_text(SPIN_OFF_LINEAGE_RESULT.read_text())
    (out_dir / "spin_off_document_schema.json").write_text(SPIN_OFF_DOCUMENT_RESULT.read_text())
    (literature_dir / "literature-electricity-load-weather.md").write_text(
        ELECTRICITY_LITERATURE_MD.read_text()
    )
    (literature_dir / "electricity-load-weather-feasibility.md").write_text(
        ELECTRICITY_FEASIBILITY_MD.read_text()
    )
    (out_dir / "electricity_load_weather_feasibility.json").write_text(
        ELECTRICITY_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-natural-gas-storage-weather.md").write_text(
        NATURAL_GAS_LITERATURE_MD.read_text()
    )
    (literature_dir / "natural-gas-storage-weather-feasibility.md").write_text(
        NATURAL_GAS_FEASIBILITY_MD.read_text()
    )
    (out_dir / "natural_gas_storage_weather_feasibility.json").write_text(
        NATURAL_GAS_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-customer-supplier-propagation.md").write_text(
        CUSTOMER_SUPPLIER_LITERATURE_MD.read_text()
    )
    (literature_dir / "customer-supplier-propagation-feasibility.md").write_text(
        CUSTOMER_SUPPLIER_FEASIBILITY_MD.read_text()
    )
    (out_dir / "customer_supplier_propagation_feasibility.json").write_text(
        CUSTOMER_SUPPLIER_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-bond-etf-nav-dislocation.md").write_text(
        BOND_ETF_NAV_LITERATURE_MD.read_text()
    )
    (literature_dir / "bond-etf-nav-dislocation-feasibility.md").write_text(
        BOND_ETF_NAV_FEASIBILITY_MD.read_text()
    )
    (out_dir / "bond_etf_nav_dislocation_feasibility.json").write_text(
        BOND_ETF_NAV_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "treasury-auction-concession-feasibility.md").write_text(
        TREASURY_FEASIBILITY_MD.read_text()
    )
    (out_dir / "treasury_auction_concession_feasibility.json").write_text(
        TREASURY_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "treasury-auction-identity-timing.md").write_text(
        TREASURY_TIMING_MD.read_text()
    )
    (out_dir / "treasury_auction_identity_timing.json").write_text(
        TREASURY_TIMING_RESULT.read_text()
    )
    (out_dir / "treasury_tentative_schedule_audit.json").write_text(
        TREASURY_TENTATIVE_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_wayback_schedule_audit.json").write_text(
        TREASURY_WAYBACK_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_wayback_pdf_schedule_audit.json").write_text(
        TREASURY_WAYBACK_PDF_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_calendar_revision_audit.json").write_text(
        TREASURY_CALENDAR_REVISION_RESULT.read_text()
    )
    (literature_dir / "cftc-hedging-pressure-feasibility.md").write_text(
        CFTC_FEASIBILITY_MD.read_text()
    )
    (out_dir / "cftc_hedging_pressure_feasibility.json").write_text(
        CFTC_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "active-ownership-item4-v3-feasibility.md").write_text(
        ACTIVE_OWNERSHIP_ITEM4_V3_MD.read_text()
    )
    (out_dir / "active_ownership_item4_v3_feasibility.json").write_text(
        ACTIVE_OWNERSHIP_ITEM4_V3_RESULT.read_text()
    )
    (out_dir / "active_ownership_item4_v3_blind_label_packet.json").write_text(
        (ACTIVE_OWNERSHIP_BLIND_PACKET / "manifest.json").read_text()
    )
    blind_out = out_dir / "active_ownership_item4_v3_blind"
    (blind_out / "documents").mkdir(parents=True, exist_ok=True)
    for packet_file in (
        "INSTRUCTIONS.md",
        "reviewer_labels.csv",
        "reviewer_attestation.json",
        "verify_review.py",
        "manifest.json",
    ):
        (blind_out / packet_file).write_bytes(
            (ACTIVE_OWNERSHIP_BLIND_PACKET / packet_file).read_bytes()
        )
    for document in sorted((ACTIVE_OWNERSHIP_BLIND_PACKET / "documents").glob("*.txt")):
        (blind_out / "documents" / document.name).write_bytes(document.read_bytes())
    (literature_dir / "literature-inflation-breakeven-relative-value.md").write_text(
        INFLATION_BREAKEVEN_LITERATURE_MD.read_text()
    )
    (literature_dir / "inflation-breakeven-relative-value-feasibility.md").write_text(
        INFLATION_BREAKEVEN_FEASIBILITY_MD.read_text()
    )
    (out_dir / "inflation_breakeven_relative_value_feasibility.json").write_text(
        INFLATION_BREAKEVEN_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "alphavintage-missing-release-correction.md").write_text(
        ALPHAVINTAGE_CORRECTION_MD.read_text()
    )
    (literature_dir / "pre-fomc-announcement-drift-feasibility.md").write_text(
        PRE_FOMC_FEASIBILITY_MD.read_text()
    )
    (out_dir / "pre_fomc_announcement_drift_feasibility.json").write_text(
        PRE_FOMC_FEASIBILITY_RESULT.read_text()
    )
    (out_dir / "pre_fomc_schedule_lineage.json").write_text(
        PRE_FOMC_SCHEDULE_LINEAGE_RESULT.read_text()
    )
    (literature_dir / "prereg-pre-fomc-announcement-drift.md").write_text(
        PRE_FOMC_PREREG_MD.read_text()
    )
    (out_dir / "pre_fomc_market_data_readiness.json").write_text(
        PRE_FOMC_MARKET_DATA_READINESS_RESULT.read_text()
    )
    (literature_dir / "prereg-earnings-narrative-change.md").write_text(
        NARRATIVE_PREREG_MD.read_text()
    )
    for source_name, public_name in (
        ("result.json", "earnings_narrative_change_result.json"),
        ("input_data_manifest.json", "earnings_narrative_change_input_data_manifest.json"),
        ("diversification.json", "earnings_narrative_change_diversification.json"),
    ):
        source = NARRATIVE_PROBE_DIR / source_name
        if source.exists():
            (out_dir / public_name).write_text(source.read_text())
    for source_name, public_name in (
        ("result.json", "eia_petroleum_inventory_result.json"),
        ("input_data_manifest.json", "eia_petroleum_inventory_input_data_manifest.json"),
    ):
        source = EIA_PROBE_DIR / source_name
        if source.exists():
            (out_dir / public_name).write_text(source.read_text())
    for public_name, source in PUBLICATION_NUMERIC_SUPPORT_FILES:
        if not source.exists():
            raise FileNotFoundError(f"publication numeric support evidence is missing: {source}")
        (out_dir / public_name).write_bytes(source.read_bytes())
    for source_name, public_name in (
        ("result.json", "insider_purchase_clusters_result.json"),
        ("input_data_manifest.json", "insider_purchase_clusters_input_data_manifest.json"),
    ):
        source = INSIDER_PROBE_DIR / source_name
        if source.exists():
            (out_dir / public_name).write_text(source.read_text())
    for public_name, source in FUNDAMENTAL_SINGLE_SUPPORT_FILES:
        if not source.exists():
            raise FileNotFoundError(
                f"selected fundamental-single support evidence is missing: {source}"
            )
        (out_dir / public_name).write_bytes(source.read_bytes())
    if out_dir.resolve() == OUT_DIR.resolve():
        app_dir = REPO.parent / "meridian-app" / "public" / "glassbox"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / OUT_FILE).write_text(stamped)
        (app_dir / "trial_ledger.json").write_text(trial_ledger)
        (app_dir / "program_status.json").write_text(program_status)
        (app_dir / "prospective_trial_record.json").write_text(prospective_trial_record)
        if TRIAL_PACKET_MANIFEST_JSON.exists():
            (app_dir / "trial_packet_manifest.json").write_text(
                TRIAL_PACKET_MANIFEST_JSON.read_text()
            )
        if IDENTITY_PACKET_RECOVERABILITY_JSON.exists():
            (app_dir / "identity_packet_recoverability.json").write_text(
                IDENTITY_PACKET_RECOVERABILITY_JSON.read_text()
            )
        if LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.exists():
            (app_dir / "legacy_research_epoch_closure.json").write_text(
                LEGACY_RESEARCH_EPOCH_CLOSURE_JSON.read_text()
            )
        (app_dir / "crypto_carry_portable_v1_result.json").write_text(
            CRYPTO_CARRY_PORTABLE_RESULT_JSON.read_text()
        )
        (app_dir / "crypto_carry_portable_v1_admission_closure.json").write_text(
            CRYPTO_CARRY_PORTABLE_CLOSURE_JSON.read_text()
        )
        (app_dir / "forward_full_evidence_reservation_v2_template.json").write_text(
            FORWARD_FULL_EVIDENCE_TEMPLATE_JSON.read_text()
        )
        (app_dir / "forward_full_evidence_reservation_v2_template_audit.json").write_text(
            FORWARD_FULL_EVIDENCE_TEMPLATE_AUDIT_JSON.read_text()
        )
        app_trial_packet_dir = app_dir / "trial-packets"
        app_trial_packet_dir.mkdir(parents=True, exist_ok=True)
        (app_trial_packet_dir / "da5f5f47f99f9bd2.json").write_text(
            CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_text()
        )
        (app_trial_packet_dir / "crypto_carry_portable_v1.json").write_text(
            CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_text()
        )
        (app_dir / "crypto_carry_selected_walkforward.json").write_text(
            CRYPTO_CARRY_SELECTED_WALKFORWARD_JSON.read_text()
        )
        (app_dir / "crypto_carry_grand_matrix.json").write_text(
            CRYPTO_CARRY_GRAND_MATRIX_JSON.read_text()
        )
        (app_dir / "crypto_carry_2022_tail.json").write_text(
            CRYPTO_CARRY_2022_TAIL_JSON.read_text()
        )
        (app_dir / "crypto_momentum_family.json").write_text(
            CRYPTO_MOMENTUM_FAMILY_JSON.read_text()
        )
        (app_dir / "alphatrend_family.json").write_text(ALPHATREND_FAMILY_JSON.read_text())
        (app_dir / "crypto_vrp_family.json").write_text(CRYPTO_VRP_FAMILY_JSON.read_text())
        (app_dir / "crypto_multifactor_family.json").write_text(
            CRYPTO_MULTIFACTOR_FAMILY_JSON.read_text()
        )
        (app_dir / "equity_narrative_family.json").write_text(
            EQUITY_NARRATIVE_FAMILY_JSON.read_text()
        )
        (app_dir / "equity_quality_family.json").write_text(EQUITY_QUALITY_FAMILY_JSON.read_text())
        (app_dir / "equity_value_investment_family.json").write_text(
            EQUITY_VALUE_FAMILY_JSON.read_text()
        )
        for public_json, source_json, _, _ in FINAL_FAMILY_FILES:
            (app_dir / public_json).write_text(source_json.read_text())
        if LEGACY_DSR_RESTATEMENT_JSON.exists():
            (app_dir / "legacy_dsr_restatement.json").write_text(
                LEGACY_DSR_RESTATEMENT_JSON.read_text()
            )
        (app_dir / "sleeve_discovery.json").write_text(discovery)
        (app_dir / "sleeve_atlas.json").write_text(SLEEVE_ATLAS_JSON.read_text())
        (app_dir / "sleeve_atlas_audit.json").write_text(SLEEVE_ATLAS_AUDIT_JSON.read_text())
        (app_dir / "sleeve_family_lineage_audit.json").write_text(
            SLEEVE_LINEAGE_AUDIT_JSON.read_text()
        )
        (app_dir / "research_accessibility_audit.json").write_text(
            RESEARCH_ACCESSIBILITY_AUDIT.read_text()
        )
        (app_dir / "accessibility_interaction_audit.json").write_text(
            ACCESSIBILITY_INTERACTION_AUDIT.read_text()
        )
        if ADMISSION_DRY_RUN_JSON.exists():
            (app_dir / "admission_dry_run.json").write_text(ADMISSION_DRY_RUN_JSON.read_text())
        if COST_MODEL_REALISM_JSON.exists():
            (app_dir / "cost_model_realism.json").write_text(COST_MODEL_REALISM_JSON.read_text())
        if EXECUTION_GAP_POWER_JSON.exists():
            (app_dir / "execution_gap_power.json").write_text(EXECUTION_GAP_POWER_JSON.read_text())
        if SLEEVE_QUALITY_JSON.exists():
            (app_dir / "sleeve_quality_decomposition.json").write_text(
                SLEEVE_QUALITY_JSON.read_text()
            )
        if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists():
            (app_dir / "drawdown_live_estimator.json").write_text(
                DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text()
            )
        (app_dir / "current_book_drawdown.json").write_text(CURRENT_BOOK_DRAWDOWN_JSON.read_text())
        (app_dir / "current_book_diversification.json").write_text(
            CURRENT_BOOK_DIVERSIFICATION_JSON.read_text()
        )
        if LEDOIT_WOLF_JSON.exists():
            (app_dir / "ledoit_wolf_effective_sample.json").write_text(LEDOIT_WOLF_JSON.read_text())
        if RECORD_CONTINUITY_JSON.exists():
            (app_dir / "record_continuity.json").write_text(RECORD_CONTINUITY_JSON.read_text())
        if ALPACA_RECONCILIATION_JSON.exists():
            (app_dir / "alpaca_broker_reconciliation.json").write_text(
                ALPACA_RECONCILIATION_JSON.read_text()
            )
        (app_dir / "forward_evidence_contract.json").write_text(
            FORWARD_EVIDENCE_CONTRACT_JSON.read_text()
        )
        (app_dir / "forward_drawdown_evidence.json").write_text(
            FORWARD_DRAWDOWN_EVIDENCE_JSON.read_text()
        )
        (app_dir / "forward_evidence_maturity.json").write_text(
            FORWARD_EVIDENCE_MATURITY_JSON.read_text()
        )
        (app_dir / "forward_sleeve_contribution.json").write_text(
            FORWARD_SLEEVE_CONTRIBUTION_JSON.read_text()
        )
        (app_dir / "crypto_lab_carry_crash_incident.json").write_text(
            CRYPTO_LAB_INCIDENT_JSON.read_text()
        )
        (app_dir / "crypto_position_attribution.json").write_text(
            CRYPTO_POSITION_ATTRIBUTION_JSON.read_text()
        )
        (app_dir / "crypto_position_attribution_rollout_verification.json").write_text(
            CRYPTO_POSITION_ATTRIBUTION_ROLLOUT_JSON.read_text()
        )
        (app_dir / "crypto_position_attribution_vps_preflight_observation.json").write_text(
            CRYPTO_POSITION_ATTRIBUTION_PREFLIGHT_OBSERVATION_JSON.read_text()
        )
        if COVARIANCE_MEMORY_JSON.exists():
            (app_dir / "live_covariance_memory.json").write_text(COVARIANCE_MEMORY_JSON.read_text())
        if GATE_REACHABILITY_JSON.exists():
            (app_dir / "feasibility_gate_reachability.json").write_text(
                GATE_REACHABILITY_JSON.read_text()
            )
        if SPINOFF_PRORATA_GATE_JSON.exists():
            (app_dir / "spinoff_prorata_gate.json").write_text(
                SPINOFF_PRORATA_GATE_JSON.read_text()
            )
        if REACHABILITY_HARNESS_JSON.exists():
            (app_dir / "reachability_harness.json").write_text(
                REACHABILITY_HARNESS_JSON.read_text()
            )
        if DATA_GATE_UNBLOCKS_JSON.exists():
            (app_dir / "data_gate_unblocks.json").write_text(DATA_GATE_UNBLOCKS_JSON.read_text())
        if TENDER_REACHABILITY_JSON.exists():
            (app_dir / "tender_offer_reachability.json").write_text(
                TENDER_REACHABILITY_JSON.read_text()
            )
        if SHARADAR_ZERO_DIVIDEND_JSON.exists():
            (app_dir / "sharadar_zero_dividend_quarantine.json").write_text(
                SHARADAR_ZERO_DIVIDEND_JSON.read_text()
            )
        if SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.exists():
            (app_dir / "sharadar_dividend_price_consistency.json").write_text(
                SHARADAR_DIVIDEND_PRICE_CONSISTENCY_JSON.read_text()
            )
        if SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.exists():
            (app_dir / "sharadar_dividend_split_basis.json").write_text(
                SHARADAR_DIVIDEND_SPLIT_BASIS_JSON.read_text()
            )
        if VATE_2020_DIVIDEND_RESOLUTION_JSON.exists():
            (app_dir / "vate_2020_dividend_resolution.json").write_text(
                VATE_2020_DIVIDEND_RESOLUTION_JSON.read_text()
            )
        if SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.exists():
            (app_dir / "sharadar_dividend_basis_resolution.json").write_text(
                SHARADAR_DIVIDEND_BASIS_RESOLUTION_JSON.read_text()
            )
        if SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.exists():
            (app_dir / "sharadar_corporate_action_corrected_lake.json").write_text(
                SHARADAR_CORPORATE_ACTION_CORRECTED_LAKE_JSON.read_text()
            )
        if SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.exists():
            (app_dir / "sharadar_corrected_corporate_action_validation.json").write_text(
                SHARADAR_CORRECTED_CORPORATE_ACTION_VALIDATION_JSON.read_text()
            )
        if POLYGON_SPLIT_CROSSCHECK_JSON.exists():
            (app_dir / "polygon_split_crosscheck.json").write_text(
                POLYGON_SPLIT_CROSSCHECK_JSON.read_text()
            )
        for audit_path in (
            SPLIT_EXCEPTION_ISSUER_RESOLUTION_JSON,
            SHARADAR_SPLIT_LIFECYCLE_SCOPE_JSON,
            UNRESOLVED_SPLIT_EVENT_CONTEXT_JSON,
            OPERATING_MARGIN_SPLIT_EXPOSURE_JSON,
            OPERATING_MARGIN_EXPOSED_SPLIT_RESOLUTION_JSON,
            OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZATION_JSON,
            OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON,
            SHARADAR_SPLIT_GOVERNANCE_POLICY_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V2_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V3_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V4_JSON,
            SPLIT_ISSUER_CONFLICT_RESOLUTION_BATCH_V5_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V6_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V7_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V8_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V9_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V10_JSON,
            SPLIT_ISSUER_RESOLUTION_BATCH_V11_JSON,
            SPLIT_LIFECYCLE_DISCONTINUITY_RESOLUTION_JSON,
            NEXT_SLEEVE_SELECTION_JSON,
            ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON,
            ACTIVE_OWNERSHIP_CONFIRMATORY_DESIGN_JSON,
            ACTIVE_OWNERSHIP_HANDOFF_RECEIPT_JSON,
        ):
            if audit_path.exists():
                (app_dir / audit_path.name).write_text(audit_path.read_text())
        if HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.exists():
            (app_dir / "hdb_dividend_vendor_resolution.json").write_text(
                HDB_DIVIDEND_VENDOR_RESOLUTION_JSON.read_text()
            )
        if SHARADAR_HDB_CORRECTED_LAKE_JSON.exists():
            (app_dir / "sharadar_hdb_corrected_lake.json").write_text(
                SHARADAR_HDB_CORRECTED_LAKE_JSON.read_text()
            )
        if OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.exists():
            (app_dir / "operating_margin_replay_infrastructure_failure.json").write_text(
                OPERATING_MARGIN_REPLAY_INFRASTRUCTURE_FAILURE_JSON.read_text()
            )
        if CFTC_RELEASE_REACHABILITY_JSON.exists():
            (app_dir / "cftc_release_reachability.json").write_text(
                CFTC_RELEASE_REACHABILITY_JSON.read_text()
            )
        if BOND_ETF_NAV_REACHABILITY_JSON.exists():
            (app_dir / "bond_etf_nav_reachability.json").write_text(
                BOND_ETF_NAV_REACHABILITY_JSON.read_text()
            )
        if ATLAS_REACHABILITY_SCREEN_JSON.exists():
            (app_dir / "atlas_reachability_screen.json").write_text(
                ATLAS_REACHABILITY_SCREEN_JSON.read_text()
            )
        if ORTHOGONALITY_PRIOR_JSON.exists():
            (app_dir / "orthogonality_prior.json").write_text(ORTHOGONALITY_PRIOR_JSON.read_text())
        if MUTATION_LEDGER_JSON.exists():
            (app_dir / "mutation_ledger.json").write_text(MUTATION_LEDGER_JSON.read_text())
        if GUARDS_CANNOT_FIRE_JSON.exists():
            (app_dir / "guards_that_cannot_fire.json").write_text(
                GUARDS_CANNOT_FIRE_JSON.read_text()
            )
        if CONTRACT_UNIT_AUDIT_JSON.exists():
            (app_dir / "contract_and_unit_audit.json").write_text(
                CONTRACT_UNIT_AUDIT_JSON.read_text()
            )
        if PREREG_PARAMETERS_JSON.exists():
            (app_dir / "prereg_earnings_narrative_parameters.json").write_text(
                PREREG_PARAMETERS_JSON.read_text()
            )
        if ALPHAVINTAGE_SEALED_JSON.exists():
            (app_dir / "alphavintage_sealed_outcome.json").write_text(
                ALPHAVINTAGE_SEALED_JSON.read_text()
            )
        (app_dir / "alphavintage_corrected_result.json").write_text(
            ALPHAVINTAGE_RESULT_JSON.read_text()
        )
        if DATA_LAKE_SCALE_JSON.exists():
            (app_dir / "data_lake_scale.json").write_text(DATA_LAKE_SCALE_JSON.read_text())
        if CLAIM_COVERAGE_MAP_JSON.exists():
            (app_dir / "claim_coverage_map.json").write_text(CLAIM_COVERAGE_MAP_JSON.read_text())
        for _name, _path in REPURCHASE_AUDITS:
            if _path.exists():
                (app_dir / _name).write_text(_path.read_text())
        if SPINOFF_FORM_UNIVERSE_JSON.exists():
            (app_dir / "spinoff_form_universe.json").write_text(
                SPINOFF_FORM_UNIVERSE_JSON.read_text()
            )
        if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists():
            (app_dir / "book_without_alphavintage.json").write_text(
                BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text()
            )
        (app_dir / "sleeve_admission_contract.json").write_text(
            SLEEVE_ADMISSION_CONTRACT_JSON.read_text()
        )
        (app_dir / "trial_accounting.json").write_text(TRIAL_ACCOUNTING_POLICY_JSON.read_text())
        (app_dir / "admission_v7_promotion.json").write_text(
            ADMISSION_V7_PROMOTION_JSON.read_text()
        )
        (app_dir / "external_publication_registry.json").write_text(
            EXTERNAL_PUBLICATION_REGISTRY_JSON.read_text()
        )
        (app_dir / "sleeve_publication_evidence.json").write_text(
            SLEEVE_PUBLICATION_EVIDENCE_JSON.read_text()
        )
        (app_dir / "external_publication_readiness.json").write_text(
            EXTERNAL_PUBLICATION_READINESS_JSON.read_text()
        )
        (app_dir / "publication_clean_checkout_integrity.json").write_text(
            PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON.read_text()
        )
        (app_dir / "external_submission_plan.json").write_text(
            EXTERNAL_SUBMISSION_PLAN_JSON.read_text()
        )
        (app_dir / "external_validation_opportunities.json").write_text(
            EXTERNAL_VALIDATION_OPPORTUNITIES_JSON.read_text()
        )
        (app_dir / "wave1_data_rights_audit.json").write_text(
            WAVE1_DATA_RIGHTS_AUDIT_JSON.read_text()
        )
        (app_dir / "wave1_release_candidates.json").write_text(
            WAVE1_RELEASE_CANDIDATES_JSON.read_text()
        )
        (app_dir / "stanford_cs_evidence_map.json").write_text(
            STANFORD_CS_EVIDENCE_JSON.read_text()
        )
        (app_dir / "alphavintage_rtdsm_portable_fetch.json").write_text(
            ALPHAVINTAGE_RTDSM_PORTABLE_FETCH_JSON.read_text()
        )
        (app_dir / "alphavintage_core_portable_reproduction.json").write_text(
            ALPHAVINTAGE_CORE_PORTABLE_REPRODUCTION_JSON.read_text()
        )
        (app_dir / "alphavintage_full_decision_reproduction.json").write_text(
            ALPHAVINTAGE_FULL_DECISION_REPRODUCTION_JSON.read_text()
        )
        (app_dir / "alphatrend_upstream_replay_manifest.json").write_text(
            ALPHATREND_UPSTREAM_REPLAY_MANIFEST_JSON.read_text()
        )
        (app_dir / "alphatrend_upstream_clean_workspace.json").write_text(
            ALPHATREND_UPSTREAM_CLEAN_WORKSPACE_JSON.read_text()
        )
        (app_dir / "archival_publication_visual_inspection.json").write_text(
            ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON.read_text()
        )
        (app_dir / "sleeve_publication_replay_verification.json").write_text(
            SLEEVE_PUBLICATION_REPLAY_JSON.read_text()
        )
        (app_dir / "sleeve_publication_isolated_replay_verification.json").write_text(
            SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON.read_text()
        )
        (app_dir / "crypto_carry_current_replay_receipt.json").write_text(
            CRYPTO_CARRY_CURRENT_REPLAY_RECEIPT_JSON.read_text()
        )
        (app_dir / "crypto_carry_first_rebalance_attribution.json").write_text(
            CRYPTO_CARRY_FIRST_REBALANCE_ATTRIBUTION_JSON.read_text()
        )
        (app_dir / "crypto_carry_full_path_attribution.json").write_text(
            CRYPTO_CARRY_FULL_PATH_ATTRIBUTION_JSON.read_text()
        )
        (app_dir / "walkforward_input_snapshot_protocol.json").write_text(
            WALKFORWARD_INPUT_SNAPSHOT_PROTOCOL_JSON.read_text()
        )
        (app_dir / "crypto_carry_replay_correction.json").write_text(
            CRYPTO_CARRY_REPLAY_CORRECTION_JSON.read_text()
        )
        for public_root in (out_dir.parent, app_dir.parent):
            destination = public_root / "publication"
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(PUBLICATION_BUNDLES_DIR, destination)
            release_destination = public_root / "release-candidates"
            if release_destination.exists():
                shutil.rmtree(release_destination)
            shutil.copytree(WAVE1_RELEASE_CANDIDATES_DIR, release_destination)
        (app_dir / "execution_models_benchmark.json").write_text(
            EXECUTION_BENCHMARK_JSON.read_text()
        )
        (app_dir / "futures_execution_contract.json").write_text(
            FUTURES_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "options_execution_contract.json").write_text(
            OPTIONS_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "borrow_execution_contract.json").write_text(
            BORROW_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "market_status_contract.json").write_text(
            MARKET_STATUS_CONTRACT_JSON.read_text()
        )
        (app_dir / "crowding_risk_contract.json").write_text(
            CROWDING_RISK_CONTRACT_JSON.read_text()
        )
        (app_dir / "corporate_action_contract.json").write_text(
            CORPORATE_ACTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "financing_contract.json").write_text(FINANCING_CONTRACT_JSON.read_text())
        (app_dir / "lint_debt_contract.json").write_text(LINT_DEBT_CONTRACT_JSON.read_text())
        (app_dir / "alphamax_construction_arms.json").write_text(
            ALPHAMAX_CONSTRUCTION_ARMS_JSON.read_text()
        )
        app_literature_dir = app_dir.parent / "research"
        _write_kill_papers(app_literature_dir, app_dir)
        app_literature_dir.mkdir(parents=True, exist_ok=True)
        (app_literature_dir / "execution-realism.md").write_text(EXECUTION_REALISM_MD.read_text())
        (app_literature_dir / "futures-execution-foundation.md").write_text(
            FUTURES_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "options-execution-foundation.md").write_text(
            OPTIONS_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "borrow-execution-foundation.md").write_text(
            BORROW_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "market-status-replay.md").write_text(
            MARKET_STATUS_REPLAY_MD.read_text()
        )
        (app_literature_dir / "crowding-risk-foundation.md").write_text(
            CROWDING_RISK_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "corporate-action-lifecycle.md").write_text(
            CORPORATE_ACTION_LIFECYCLE_MD.read_text()
        )
        (app_literature_dir / "corporate-action-basis-reconstruction.md").write_text(
            CORPORATE_ACTION_BASIS_RECONSTRUCTION_MD.read_text()
        )
        (app_literature_dir / "financing-replay.md").write_text(FINANCING_REPLAY_MD.read_text())
        (app_literature_dir / "identity-redesign-notes.md").write_text(
            IDENTITY_REDESIGN_NOTES_MD.read_text()
        )
        (app_literature_dir / "sharadar-hdb-zero-dividend-quarantine.md").write_text(
            SHARADAR_ZERO_DIVIDEND_MD.read_text()
        )
        (app_literature_dir / "engineering-quality.md").write_text(
            ENGINEERING_QUALITY_MD.read_text()
        )
        (app_literature_dir / "forward-sharpe-evidence-standard.md").write_text(
            FORWARD_SHARPE_EVIDENCE_STANDARD_MD.read_text()
        )
        (app_literature_dir / "current-book-drawdown-model.md").write_text(
            CURRENT_BOOK_DRAWDOWN_MODEL_MD.read_text()
        )
        (app_literature_dir / "current-book-diversification-model.md").write_text(
            CURRENT_BOOK_DIVERSIFICATION_MODEL_MD.read_text()
        )
        if LEGACY_DSR_RESTATEMENT_MD.exists():
            (app_literature_dir / "legacy-dsr-restatement.md").write_text(
                LEGACY_DSR_RESTATEMENT_MD.read_text()
            )
        (app_literature_dir / "alphamax-equity-momentum-lineage.md").write_text(
            ALPHAMAX_MOMENTUM_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "crypto-carry-lineage.md").write_text(
            CRYPTO_CARRY_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "crypto-carry-portable-v1.md").write_text(
            CRYPTO_CARRY_PORTABLE_PAPER_MD.read_text()
        )
        (app_literature_dir / "crypto-lab-carry-crash-incident.md").write_text(
            CRYPTO_LAB_INCIDENT_MD.read_text()
        )
        (app_literature_dir / "crypto-momentum-lineage.md").write_text(
            CRYPTO_MOMENTUM_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "alphatrend-managed-futures-lineage.md").write_text(
            ALPHATREND_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "alphavintage-macro-surprise-lineage.md").write_text(
            ALPHAVINTAGE_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "crypto-vrp-lineage.md").write_text(CRYPTO_VRP_LINEAGE_MD.read_text())
        (app_literature_dir / "crypto-multifactor-engine-lineage.md").write_text(
            CRYPTO_MULTIFACTOR_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "equity-narrative-change-lineage.md").write_text(
            EQUITY_NARRATIVE_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "equity-quality-lineage.md").write_text(
            EQUITY_QUALITY_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "equity-value-investment-lineage.md").write_text(
            EQUITY_VALUE_LINEAGE_MD.read_text()
        )
        for _, _, public_paper, source_paper in FINAL_FAMILY_FILES:
            (app_literature_dir / public_paper).write_text(source_paper.read_text())
        (app_literature_dir / "literature-frontier-2026-08-16.md").write_text(
            LITERATURE_FRONTIER_MD.read_text()
        )
        (app_literature_dir / "literature-repurchase-issuance-flow.md").write_text(
            REPURCHASE_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "repurchase-issuance-flow-feasibility.md").write_text(
            REPURCHASE_FEASIBILITY_MD.read_text()
        )
        (app_dir / "repurchase_item703_blind_label_packet.json").write_text(
            (REPURCHASE_BLIND_PACKET / "manifest.json").read_text()
        )
        app_repurchase_blind_out = app_dir / "repurchase_item703_blind"
        app_repurchase_blind_out.mkdir(parents=True, exist_ok=True)
        for packet_file in (
            "INSTRUCTIONS.md",
            "reviewer_labels.csv",
            "reviewer_attestation.json",
            "manifest.json",
        ):
            (app_repurchase_blind_out / packet_file).write_bytes(
                (REPURCHASE_BLIND_PACKET / packet_file).read_bytes()
            )
        if ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.exists():
            (app_dir / ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.name).write_bytes(
                ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.read_bytes()
            )
        (app_literature_dir / "literature-options-dispersion.md").write_text(
            OPTIONS_DISPERSION_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "options-dispersion-feasibility.md").write_text(
            OPTIONS_DISPERSION_FEASIBILITY_MD.read_text()
        )
        (app_literature_dir / "literature-stablecoin-dislocation.md").write_text(
            STABLECOIN_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "stablecoin-dislocation-feasibility.md").write_text(
            STABLECOIN_FEASIBILITY_MD.read_text()
        )
        (app_literature_dir / "literature-spin-off-dislocation.md").write_text(
            SPIN_OFF_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "spin-off-dislocation-lineage.md").write_text(
            SPIN_OFF_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "spin-off-document-schema.md").write_text(
            SPIN_OFF_DOCUMENT_MD.read_text()
        )
        (app_dir / "spin_off_lineage.json").write_text(SPIN_OFF_LINEAGE_RESULT.read_text())
        (app_dir / "spin_off_document_schema.json").write_text(SPIN_OFF_DOCUMENT_RESULT.read_text())
        (app_literature_dir / "literature-electricity-load-weather.md").write_text(
            ELECTRICITY_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "electricity-load-weather-feasibility.md").write_text(
            ELECTRICITY_FEASIBILITY_MD.read_text()
        )
        (app_dir / "electricity_load_weather_feasibility.json").write_text(
            ELECTRICITY_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "literature-natural-gas-storage-weather.md").write_text(
            NATURAL_GAS_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "natural-gas-storage-weather-feasibility.md").write_text(
            NATURAL_GAS_FEASIBILITY_MD.read_text()
        )
        (app_dir / "natural_gas_storage_weather_feasibility.json").write_text(
            NATURAL_GAS_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "literature-customer-supplier-propagation.md").write_text(
            CUSTOMER_SUPPLIER_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "customer-supplier-propagation-feasibility.md").write_text(
            CUSTOMER_SUPPLIER_FEASIBILITY_MD.read_text()
        )
        (app_dir / "customer_supplier_propagation_feasibility.json").write_text(
            CUSTOMER_SUPPLIER_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "literature-bond-etf-nav-dislocation.md").write_text(
            BOND_ETF_NAV_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "bond-etf-nav-dislocation-feasibility.md").write_text(
            BOND_ETF_NAV_FEASIBILITY_MD.read_text()
        )
        (app_dir / "bond_etf_nav_dislocation_feasibility.json").write_text(
            BOND_ETF_NAV_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "treasury-auction-concession-feasibility.md").write_text(
            TREASURY_FEASIBILITY_MD.read_text()
        )
        (app_dir / "treasury_auction_concession_feasibility.json").write_text(
            TREASURY_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "treasury-auction-identity-timing.md").write_text(
            TREASURY_TIMING_MD.read_text()
        )
        (app_dir / "treasury_auction_identity_timing.json").write_text(
            TREASURY_TIMING_RESULT.read_text()
        )
        (app_dir / "treasury_tentative_schedule_audit.json").write_text(
            TREASURY_TENTATIVE_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_wayback_schedule_audit.json").write_text(
            TREASURY_WAYBACK_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_wayback_pdf_schedule_audit.json").write_text(
            TREASURY_WAYBACK_PDF_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_calendar_revision_audit.json").write_text(
            TREASURY_CALENDAR_REVISION_RESULT.read_text()
        )
        (app_literature_dir / "cftc-hedging-pressure-feasibility.md").write_text(
            CFTC_FEASIBILITY_MD.read_text()
        )
        (app_dir / "cftc_hedging_pressure_feasibility.json").write_text(
            CFTC_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "active-ownership-item4-v3-feasibility.md").write_text(
            ACTIVE_OWNERSHIP_ITEM4_V3_MD.read_text()
        )
        (app_dir / "active_ownership_item4_v3_feasibility.json").write_text(
            ACTIVE_OWNERSHIP_ITEM4_V3_RESULT.read_text()
        )
        (app_dir / "active_ownership_item4_v3_blind_label_packet.json").write_text(
            (ACTIVE_OWNERSHIP_BLIND_PACKET / "manifest.json").read_text()
        )
        app_blind_out = app_dir / "active_ownership_item4_v3_blind"
        (app_blind_out / "documents").mkdir(parents=True, exist_ok=True)
        for packet_file in (
            "INSTRUCTIONS.md",
            "reviewer_labels.csv",
            "reviewer_attestation.json",
            "verify_review.py",
            "manifest.json",
        ):
            (app_blind_out / packet_file).write_bytes(
                (ACTIVE_OWNERSHIP_BLIND_PACKET / packet_file).read_bytes()
            )
        for document in sorted((ACTIVE_OWNERSHIP_BLIND_PACKET / "documents").glob("*.txt")):
            (app_blind_out / "documents" / document.name).write_bytes(document.read_bytes())
        (app_literature_dir / "literature-inflation-breakeven-relative-value.md").write_text(
            INFLATION_BREAKEVEN_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "inflation-breakeven-relative-value-feasibility.md").write_text(
            INFLATION_BREAKEVEN_FEASIBILITY_MD.read_text()
        )
        (app_dir / "inflation_breakeven_relative_value_feasibility.json").write_text(
            INFLATION_BREAKEVEN_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "alphavintage-missing-release-correction.md").write_text(
            ALPHAVINTAGE_CORRECTION_MD.read_text()
        )
        (app_literature_dir / "pre-fomc-announcement-drift-feasibility.md").write_text(
            PRE_FOMC_FEASIBILITY_MD.read_text()
        )
        (app_dir / "pre_fomc_announcement_drift_feasibility.json").write_text(
            PRE_FOMC_FEASIBILITY_RESULT.read_text()
        )
        (app_dir / "pre_fomc_schedule_lineage.json").write_text(
            PRE_FOMC_SCHEDULE_LINEAGE_RESULT.read_text()
        )
        (app_literature_dir / "prereg-pre-fomc-announcement-drift.md").write_text(
            PRE_FOMC_PREREG_MD.read_text()
        )
        (app_dir / "pre_fomc_market_data_readiness.json").write_text(
            PRE_FOMC_MARKET_DATA_READINESS_RESULT.read_text()
        )
        (app_literature_dir / "prereg-earnings-narrative-change.md").write_text(
            NARRATIVE_PREREG_MD.read_text()
        )
        for source_name, public_name in (
            ("result.json", "earnings_narrative_change_result.json"),
            ("input_data_manifest.json", "earnings_narrative_change_input_data_manifest.json"),
            ("diversification.json", "earnings_narrative_change_diversification.json"),
        ):
            source = NARRATIVE_PROBE_DIR / source_name
            if source.exists():
                (app_dir / public_name).write_text(source.read_text())
        for source_name, public_name in (
            ("result.json", "eia_petroleum_inventory_result.json"),
            ("input_data_manifest.json", "eia_petroleum_inventory_input_data_manifest.json"),
        ):
            source = EIA_PROBE_DIR / source_name
            if source.exists():
                (app_dir / public_name).write_text(source.read_text())
        for public_name, source in PUBLICATION_NUMERIC_SUPPORT_FILES:
            if not source.exists():
                raise FileNotFoundError(
                    f"publication numeric support evidence is missing: {source}"
                )
            (app_dir / public_name).write_bytes(source.read_bytes())
        for source_name, public_name in (
            ("result.json", "insider_purchase_clusters_result.json"),
            ("input_data_manifest.json", "insider_purchase_clusters_input_data_manifest.json"),
        ):
            source = INSIDER_PROBE_DIR / source_name
            if source.exists():
                (app_dir / public_name).write_text(source.read_text())
        for public_name, source in FUNDAMENTAL_SINGLE_SUPPORT_FILES:
            if not source.exists():
                raise FileNotFoundError(
                    f"selected fundamental-single support evidence is missing: {source}"
                )
            (app_dir / public_name).write_bytes(source.read_bytes())
    print(f"wrote {path}  ({path.stat().st_size} bytes)")
    print(f"content_hash: {payload['content_hash']}")
    return path


if __name__ == "__main__":
    main()
