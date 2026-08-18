"""The public research contract must describe the same book as paper-state.

This closes the defect where research.json stayed on the old two/three-sleeve story while the
live artifact had moved to four equal quarters and a smaller strategic tilt.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def modules():
    loaded = []
    for name in ("paper_trading_state", "research_export"):
        path = REPO / "scripts" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"{name}_freshness_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded


def test_research_composition_and_tilt_are_derived_from_state(modules) -> None:
    pts, research = modules
    state = {
        "book": {
            "name": "ALPHAC",
            "style": "test",
            "sleeves": [
                {"key": key, "name": key, "desc": key, "standalone_sharpe": 0.1, "weight": weight}
                for key, weight in pts.BOOK_WEIGHTS.items()
            ],
            "strategic_tilt": {"pct": pts.STRATEGIC_TILT_PCT},
        },
        "metrics": {
            "in_sample_sharpe": 1.0,
            "in_sample_cagr_pct": 1.0,
            "max_drawdown_pct": -1.0,
            "honest_forward_sharpe": "0 to 1",
            "honest_forward_return_pct": "0 to 1",
            "realistic_worst_dd_pct": "-1 to -2",
            "correlation_value": pts.RHO_BAR,
            "correlation": "derived correlation prose",
            "gauntlet_grade": "C+",
            "gauntlet_pass": "not cleared",
        },
    }

    summary = research.build_executive_summary(state)
    book = research.build_combined_book(state)

    assert summary["deployed_sleeves_count"] == len(pts.BOOK_WEIGHTS)
    assert summary["technically_admitted_sleeves_count"] == 0
    assert [s["key"] for s in book["sleeves"]] == list(pts.BOOK_WEIGHTS)
    assert book["correlation"] == pts.RHO_BAR
    assert book["strategic_tilt"]["pct"] == pts.STRATEGIC_TILT_PCT


def test_current_metric_prose_uses_current_tilt_and_correlation_constants() -> None:
    source = (REPO / "scripts" / "paper_trading_state.py").read_text()
    assert '"correlation_value": RHO_BAR' in source
    assert "f\"0.3 to 0.9 (the {TILT_PROSE} beta" in source


@pytest.mark.workspace_evidence
def test_open_book_exposes_sealed_alphavintage_correction(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    correction = payload["corrections"][0]
    assert correction["status"] == "REVISED RETURNS SEALED / VERDICT KILLED"
    assert correction["hypotheses_added"] == 0
    assert correction["verdict"] == "KILLED"
    assert correction["public_path"] == "/research/alphavintage-missing-release-correction.md"


@pytest.mark.workspace_evidence
def test_export_carries_fail_closed_sleeve_atlas(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    section = payload["sleeve_atlas"]
    atlas = section["atlas"]
    audit = section["audit"]

    assert atlas["summary"]["families"] == 40
    assert atlas["summary"]["cells"] == 240
    assert atlas["objective"]["target_total_sleeves"] == 14
    assert atlas["objective"]["minimum_new_sleeves"] == 10
    assert atlas["summary"]["return_data_opened"] == 0
    assert atlas["summary"]["family_return_data_opened"] == 1
    assert atlas["summary"]["family_return_hypotheses_spent"] == 1
    assert audit["summary"]["cells_audited"] == 240
    assert audit["summary"]["gate_evaluations"] == 2880
    assert audit["summary"]["lineage_families"] == {
        "ACTIVE_FEASIBILITY": 6,
        "DUPLICATE_OVERLAP": 7,
        "IDENTITY_REDESIGN_REQUIRED": 2,
        "NOVEL_ATLAS": 20,
        "RETIRED_KILLED": 5,
    }
    assert audit["summary"]["overlap_review_required"] == 42
    assert audit["summary"]["identity_redesign_required"] == 12
    assert audit["summary"]["forward_only_monitoring"] == 6
    assert audit["summary"]["new_sleeves_admitted"] == 0
    assert audit["summary"]["return_hypotheses_spent"] == 0
    assert section["atlas_public_path"] == "/glassbox/sleeve_atlas.json"
    assert section["audit_public_path"] == "/glassbox/sleeve_atlas_audit.json"
    assert section["lineage_audit"]["summary"]["decision"] == "PASS"
    assert section["lineage_audit"]["summary"]["current_book_exact_match"] is True
    assert section["lineage_audit"]["summary"]["family_failures"] == 0
    assert section["lineage_audit_public_path"] == "/glassbox/sleeve_family_lineage_audit.json"


@pytest.mark.workspace_evidence
def test_export_carries_shared_brutal_admission_contract(modules) -> None:
    _, research = modules
    section = research.build_research_export()["sleeve_admission_contract"]
    contract = section["contract"]

    assert contract["schema"] == "canli.alphac-sleeve-admission-contract.v4"
    assert contract["evidence_checks_per_candidate"] == 75
    assert len(contract["execution_dimensions"]) == 26
    assert len(contract["required_robustness"]) == 17
    assert contract["objective"]["targets_are_admission_evidence"] is False
    assert contract["thresholds"]["deflated_sharpe_min"] == 0.95
    assert contract["thresholds"]["pbo_max"] == 0.2
    assert contract["thresholds"]["pairwise_correlation_upper_95_max"] == 0.35
    assert contract["thresholds"]["capacity_minimum_stressed_fill_ratio"] == 0.95
    assert contract["diversification_evidence_policy"]["default_bootstrap_samples"] == 2000
    assert section["public_path"] == "/glassbox/sleeve_admission_contract.json"
    assert len(section["source_sha256"]) == 64


@pytest.mark.workspace_evidence
def test_export_distinguishes_ledger_records_from_hypothesis_identities(modules) -> None:
    _, research = modules
    ledger = research.build_research_export()["trial_accounting"]

    assert ledger["schema"] == "glassbox.trial-ledger/2"
    assert ledger["immutable_execution_records"] >= ledger["distinct_hypothesis_identities"]
    assert (
        ledger["immutable_execution_records"]
        - ledger["window_only_remeasurements"]
        - ledger["cross_profile_duplicate_identities"]
        == ledger["distinct_hypothesis_identities"]
    )
    assert sum(p["immutable_execution_records"] for p in ledger["profiles"]) == ledger[
        "immutable_execution_records"
    ]
    assert ledger["budget_status"] == "PAUSE_RESEARCH"
    assert ledger["distinct_hypothesis_identities"] == 162
    assert ledger["budget_remaining"] == (
        ledger["hypothesis_identity_budget"] - ledger["distinct_hypothesis_identities"]
    )
    assert ledger["budget_remaining"] == -2
    assert ledger["research_status"] == "PAUSED_BUDGET_REVIEW"
    assert ledger["trial_debt_reconciliation"]["source_path"] == (
        "artifacts/audit/trial_debt_reconciliation.json"
    )
    assert len(ledger["trial_debt_reconciliation"]["source_sha256"]) == 64
    assert ledger["legacy_dsr_debt"]["status"] == "CODE_RESOLVED_HISTORICAL_CLAIMS_RETIRED"
    assert ledger["legacy_dsr_debt"]["historical_exception_paths"] == 12
    assert ledger["legacy_dsr_debt"]["executable_debt_paths"] == 0
    assert ledger["legacy_dsr_debt"]["resolved_code_paths"] == 12
    assert ledger["legacy_dsr_debt"]["union_registration_paths"] == 7
    assert len(ledger["legacy_dsr_debt"]["source_sha256"]) == 64
    restatement = ledger["legacy_dsr_debt"]["restatement"]
    assert restatement["summary"]["restated_variants"] == 33
    assert restatement["summary"]["restated_variants_clearing_dsr_0_95"] == 0
    assert restatement["summary"]["retired_families"] == 7
    assert len(restatement["source_sha256"]) == 64
    assert ledger["recent_hypothesis_identities"]
    assert all("instrument_ids" not in row for row in ledger["recent_hypothesis_identities"])
    selection = ledger["selection_statistics"]
    assert selection["unit"] == "first_immutable_record_per_hypothesis"
    assert selection["n_hypotheses"] == ledger["distinct_hypothesis_identities"]
    assert selection["sharpe_variance"] > 0.0
    assert selection["audit_raw_record_sharpe_variance"] > 0.0


@pytest.mark.workspace_evidence
def test_execution_realism_book_page_is_published_identically() -> None:
    source = REPO / "docs" / "research" / "EXECUTION_REALISM.md"
    legacy = REPO.parent / "meridian" / "public" / "research" / "execution-realism.md"
    app = REPO.parent / "meridian-app" / "public" / "research" / "execution-realism.md"

    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_execution_benchmark_is_honest_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_benchmarks"][
        "execution_fill_models"
    ]
    benchmark = section["benchmark"]
    source = REPO / "artifacts" / "benchmarks" / "execution_models.json"
    public_name = "execution_models_benchmark.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name

    assert benchmark["classification"] == "local engineering microbenchmark; not return evidence"
    assert benchmark["workload"]["market_data_opened"] is False
    assert benchmark["workload"]["hypotheses_spent"] == 0
    assert all(len(case["elapsed_ns_samples"]) == 7 for case in benchmark["cases"])
    assert section["public_path"] == "/glassbox/execution_models_benchmark.json"
    assert len(section["source_sha256"]) == 64
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_futures_capability_is_bounded_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"][
        "futures_execution"
    ]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "futures_execution_contract.json"
    public_name = "futures_execution_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name
    book = REPO / "docs" / "research" / "FUTURES_EXECUTION_FOUNDATION.md"
    legacy_book = (
        REPO.parent / "meridian" / "public" / "research" / "futures-execution-foundation.md"
    )
    app_book = (
        REPO.parent
        / "meridian-app"
        / "public"
        / "research"
        / "futures-execution-foundation.md"
    )

    assert contract["status"] == "DOMAIN_PRIMITIVES_ONLY"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/futures_execution_contract.json"
    assert section["book_path"] == "/research/futures-execution-foundation.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_options_capability_is_bounded_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"][
        "options_execution"
    ]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "options_execution_contract.json"
    public_name = "options_execution_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name
    book = REPO / "docs" / "research" / "OPTIONS_EXECUTION_FOUNDATION.md"
    legacy_book = (
        REPO.parent / "meridian" / "public" / "research" / "options-execution-foundation.md"
    )
    app_book = (
        REPO.parent
        / "meridian-app"
        / "public"
        / "research"
        / "options-execution-foundation.md"
    )

    assert contract["status"] == "DOMAIN_PRIMITIVES_ONLY"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/options_execution_contract.json"
    assert section["book_path"] == "/research/options-execution-foundation.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_borrow_capability_is_bounded_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"]["borrow_execution"]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "borrow_execution_contract.json"
    public_name = "borrow_execution_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name
    book = REPO / "docs" / "research" / "BORROW_EXECUTION_FOUNDATION.md"
    legacy_book = (
        REPO.parent / "meridian" / "public" / "research" / "borrow-execution-foundation.md"
    )
    app_book = (
        REPO.parent
        / "meridian-app"
        / "public"
        / "research"
        / "borrow-execution-foundation.md"
    )

    assert contract["status"] == "EVENT_DRIVEN_BACKTEST_INTEGRATED"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/borrow_execution_contract.json"
    assert section["book_path"] == "/research/borrow-execution-foundation.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_market_status_capability_is_bounded_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"][
        "market_status_replay"
    ]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "market_status_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "MARKET_STATUS_REPLAY.md"
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "market-status-replay.md"
    app_book = (
        REPO.parent / "meridian-app" / "public" / "research" / "market-status-replay.md"
    )

    assert contract["status"] == "EVENT_DRIVEN_BACKTEST_INTEGRATED"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/market_status_contract.json"
    assert section["book_path"] == "/research/market-status-replay.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_crowding_capability_confesses_coverage_and_publishes_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"]["crowding_risk"]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "crowding_risk_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "CROWDING_RISK_FOUNDATION.md"
    legacy_book = (
        REPO.parent / "meridian" / "public" / "research" / "crowding-risk-foundation.md"
    )
    app_book = (
        REPO.parent / "meridian-app" / "public" / "research" / "crowding-risk-foundation.md"
    )

    assert contract["status"] == "PRETRADE_INTEGRATED_NO_HISTORICAL_COVERAGE"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/crowding_risk_contract.json"
    assert section["book_path"] == "/research/crowding-risk-foundation.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_corporate_action_capability_is_bounded_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"][
        "corporate_action_lifecycle"
    ]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "corporate_action_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "CORPORATE_ACTION_LIFECYCLE.md"
    legacy_book = (
        REPO.parent / "meridian" / "public" / "research" / "corporate-action-lifecycle.md"
    )
    app_book = (
        REPO.parent
        / "meridian-app"
        / "public"
        / "research"
        / "corporate-action-lifecycle.md"
    )

    assert contract["status"] == "EVENT_DRIVEN_BACKTEST_INTEGRATED"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/corporate_action_contract.json"
    assert section["book_path"] == "/research/corporate-action-lifecycle.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_financing_capability_confesses_coverage_and_publishes_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_capabilities"]["financing"]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "financing_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "FINANCING_REPLAY.md"
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "financing-replay.md"
    app_book = REPO.parent / "meridian-app" / "public" / "research" / "financing-replay.md"

    assert contract["status"] == "EVENT_DRIVEN_BACKTEST_INTEGRATED_NO_HISTORICAL_COVERAGE"
    assert contract["trial_accounting"]["hypotheses_spent"] == 0
    assert contract["trial_accounting"]["returns_evaluated"] is False
    assert section["public_path"] == "/glassbox/financing_contract.json"
    assert section["book_path"] == "/research/financing-replay.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()


@pytest.mark.workspace_evidence
def test_lint_debt_boundary_publishes_identically_without_a_clean_repo_claim(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_quality"]["lint_debt"]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "lint_debt_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "ENGINEERING_QUALITY.md"
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "engineering-quality.md"
    app_book = REPO.parent / "meridian-app" / "public" / "research" / "engineering-quality.md"

    assert contract["status"] == "PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT"
    assert contract["scopes"]["production"]["violations"] == 0
    assert contract["scopes"]["tests"]["violations"] == 0
    assert contract["scopes"]["historical_scripts"]["violations"] > 0
    assert section["public_path"] == "/glassbox/lint_debt_contract.json"
    assert section["book_path"] == "/research/engineering-quality.md"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
    assert book.read_bytes() == legacy_book.read_bytes() == app_book.read_bytes()
