"""The public research contract must describe the same book as paper-state.

This closes the defect where research.json stayed on the old two/three-sleeve story while the
live artifact had moved to four equal quarters and a smaller strategic tilt.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _research_module():
    path = REPO / "scripts" / "research_export.py"
    spec = importlib.util.spec_from_file_location("research_export_mutation_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_returns_research_json_without_mutating_source_audits(tmp_path: Path) -> None:
    module = _research_module()
    audit = module.OPERATING_MARGIN_CORRECTED_REPRODUCTION_JSON
    before = hashlib.sha256(audit.read_bytes()).hexdigest()
    shutil.copyfile(module.OUT_DIR / "kill_log.json", tmp_path / "kill_log.json")
    written = module.main(tmp_path)
    assert written == tmp_path / module.OUT_FILE
    assert written.name == "research.json"
    assert hashlib.sha256(audit.read_bytes()).hexdigest() == before


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
    assert 'f"0.3 to 0.9 (the {TILT_PROSE} beta' in source


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
    assert audit["summary"]["lineage_families"] == atlas["summary"]["lineage_classifications"]
    assert audit["summary"]["overlap_review_required"] == 42
    assert audit["summary"]["identity_redesign_required"] == 12
    assert audit["summary"]["forward_only_monitoring"] == 6
    assert audit["summary"]["new_sleeves_admitted"] == 0
    assert audit["summary"]["return_hypotheses_spent"] == 0
    assert section["atlas_public_path"] == "/glassbox/sleeve_atlas.json"
    assert section["audit_public_path"] == "/glassbox/sleeve_atlas_audit.json"
    assert section["sleeve_family_lineage_audit"]["summary"]["decision"] == "PASS"
    assert section["sleeve_family_lineage_audit"]["summary"]["current_book_exact_match"] is True
    assert section["sleeve_family_lineage_audit"]["summary"]["family_failures"] == 0
    assert section["lineage_audit_public_path"] == "/glassbox/sleeve_family_lineage_audit.json"


@pytest.mark.workspace_evidence
def test_export_carries_shared_brutal_admission_contract(modules) -> None:
    _, research = modules
    section = research.build_research_export()["sleeve_admission_contract"]
    contract = section["contract"]

    # Compare against the contract ON DISK rather than a transcribed version string and a list of
    # threshold values. What this test is actually for is that the published bundle carries the
    # contract that is in force -- a copy that has drifted is the failure mode, and pinning
    # literals here cannot see it: they go stale in exactly the same direction as the export.
    import json as _json
    from pathlib import Path as _Path

    on_disk = _json.loads(
        (_Path(__file__).parents[2] / "config/sleeve_admission_contract.json").read_text()
    )
    assert contract == on_disk, "the published contract is not the contract in force"

    # Invariants that must hold of ANY contract this project publishes, whatever its version.
    assert contract["objective"]["targets_are_admission_evidence"] is False
    assert contract["schema"].startswith("canli.alphac-sleeve-admission-contract.")
    assert contract["evidence_checks_per_candidate"] > 0
    assert contract["diversification_evidence_policy"]["default_bootstrap_samples"] >= 2000
    assert section["public_path"] == "/glassbox/sleeve_admission_contract.json"
    assert len(section["source_sha256"]) == 64

    # The correlation gate and the portfolio objective must be published together WITH the
    # arithmetic relating them. Publishing a target beside a gate that forbids it, with nothing
    # saying so, is the specific defect this block was added to close.
    frontier = contract["frontier_arithmetic"]
    assert (
        frontier["incremental_candidate_average_correlation_gate"]
        == contract["thresholds"]["candidate_average_correlation_to_existing_book_max"]
    )
    assert (
        frontier["incremental_book_average_correlation_delta_gate_exclusive"]
        == contract["thresholds"]["book_average_pairwise_correlation_delta_max_exclusive"]
    )
    assert frontier["incremental_gates_alone_establish_objective_floor"] is False


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
    assert (
        sum(p["immutable_execution_records"] for p in ledger["profiles"])
        == ledger["immutable_execution_records"]
    )
    # Stated as the RELATIONSHIP between the count, the budget and the status rather than as the
    # three literals they happened to hold. Pinning the literals meant that authorizing a budget
    # broke this test for a reason that had nothing to do with what it is checking: that the
    # published ledger's status follows from its own numbers. It now fails on an inconsistent
    # ledger and passes on a consistent one at any budget.
    over_budget = ledger["distinct_hypothesis_identities"] > ledger["hypothesis_identity_budget"]
    assert ledger["budget_status"] == ("PAUSE_RESEARCH" if over_budget else "PASS")
    assert ledger["budget_remaining"] == (
        ledger["hypothesis_identity_budget"] - ledger["distinct_hypothesis_identities"]
    )
    assert ledger["research_status"].startswith("PAUSED_") == over_budget, (
        "a ledger that is over budget must say research is paused, and one that is not must not"
    )
    assert ledger["distinct_hypothesis_identities"] == 229, (
        "the observed identity count is a fact about work already done; it must not move when a "
        "budget is authorized"
    )
    assert ledger["ledger_scope_correction"]["recovered_legacy_hypothesis_identities"] == 12
    assert ledger["ledger_scope_correction"]["new_experiments_run"] == 0
    assert (
        ledger["summary_trial_debt_correction"]["recovered_historical_hypothesis_identities"] == 54
    )
    assert ledger["summary_trial_debt_correction"]["new_experiments_run"] == 0
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
def test_program_status_composes_targets_live_provenance_and_evidence_gaps(modules) -> None:
    _, research = modules
    status = research.build_research_export()["program_status"]

    assert status["schema"] == "canli.alphac-program-status.v2"
    assert status["owner"]["name"] == "Arhan Canli"
    assert status["achievement"]["forward_sharpe_status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert status["achievement"]["forward_sharpe_underlying_status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert status["achievement"]["overall"] == "TARGETS_NOT_YET_ACHIEVED"
    assert status["forward_record"]["capital_kind"] == "PAPER_ONLY"
    assert status["forward_record"]["normalized_starting_equity"] > 0
    assert status["forward_record"]["curve_points"] >= 2
    maturity = status["forward_record"]["evidence_maturity"]
    assert maturity["status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert maturity["underlying_status"] == "IMMATURE_RECORD_TOO_SHORT"
    assert maturity["provenance_passes"] is True
    assert maturity["failed_provenance_checks"] == []
    assert maturity["sharpe"]["annualized_point_estimate"] is None
    assert maturity["sharpe"]["target_statistically_established"] is False
    assert maturity["drawdown"]["realized_status"] == (
        "DESCRIPTIVE_TO_DATE_NOT_EXPECTED_MAX_DRAWDOWN"
    )
    assert maturity["drawdown"]["study_production_labelled_p95_max_drawdown"] > 0.11
    assert maturity["drawdown"]["production_equivalence_passes"] is False
    assert maturity["drawdown"]["objective_status"] == (
        "MODELED_CURRENT_COMPOSITION_WITHIN_OBJECTIVE_LIVE_EXPECTED_MAX_DRAWDOWN_NOT_ESTABLISHED"
    )
    assert maturity["drawdown"]["current_composition_conservative_expected_max_drawdown"] < 0.11
    assert maturity["drawdown"]["current_composition_conservative_p95_max_drawdown"] > 0.11
    assert maturity["drawdown_evidence_public_path"] == ("/glassbox/forward_drawdown_evidence.json")
    assert maturity["public_path"] == "/glassbox/forward_evidence_maturity.json"

    execution = status["execution_provenance"]
    assert set(execution["alpaca_broker_executed_sleeves"]) == {
        "alphamax",
        "managed_futures",
        "alphavintage",
    }
    by_key = {item["key"]: item for item in execution["all_sleeves"]}
    assert by_key["alphac"]["execution"]["record_kind"] == "DERIVED_PAPER_BOOK"
    assert by_key["alphaforge"]["execution"]["broker"] == "ALPHAFORGE_PAPERBROKER"
    assert all(
        item["execution"]["capital_kind"] == "PAPER_ONLY" for item in execution["all_sleeves"]
    )

    papers = status["research_governance"]["paper_corpus"]
    assert papers["published_markdown_papers"] > 0
    assert papers["trial_packet_coverage_status"] == (
        "INCOMPLETE_LEGACY_BACKFILL_PROSPECTIVE_SERIAL_COMPLETE"
    )
    assert papers["complete_trial_packets"] == 3
    assert papers["new_return_identity_gate"] == {
        "status": "OPEN_SERIAL_PACKET_COMPLETE",
        "enforced_before_return_compute": True,
        "incomplete_historical_packets": 226,
        "retired_historical_identities": 228,
        "historical_identities_eligible_for_admission": 0,
        "existing_identity_remeasurements_unaffected": True,
        "live_paper_execution_unaffected": True,
        "implementation": "src/alphaforge/validation/trial_reservation.py",
        "prior_forward_identity_packet_policy": (
            "SERIAL_COMPLETE_PACKET_BEFORE_NEXT_FORWARD_IDENTITY"
        ),
        "legacy_epoch_closure_public_path": ("/glassbox/legacy_research_epoch_closure.json"),
        "claim_boundary": (
            "The legacy epoch is retired fail-closed: no historical identity is "
            "admission-eligible or reusable, and missing packet sections remain missing. A "
            "genuinely new identity may run only after its exact pre-result reservation "
            "validates. Frozen live paper execution is unaffected. The first prospective "
            "identity now has a complete, hash-valid evidence-accounting packet and a final "
            "INCOMPLETE / NOT ADMITTED decision, so it no longer blocks the serial queue. Every "
            "later forward identity remains subject to the same rule before another can compute "
            "returns."
        ),
    }
    prospective = papers["prospective_epoch"]
    assert prospective["observed_identities"] == 1
    assert prospective["complete_identity_packets"] == 1
    assert prospective["candidate_evidence_complete_for_admission"] is False
    assert prospective["final_disposition"] == "INCOMPLETE"
    assert prospective["admitted"] is False
    assert papers["candidate_mapped_identities"] > 0
    assert papers["manifest_public_path"] == "/glassbox/trial_packet_manifest.json"
    assert len(papers["manifest_source_sha256"]) == 64
    assert (
        papers["required_trial_packets"]
        == status["research_governance"]["trial_accounting"]["distinct_hypothesis_identities"]
    )


@pytest.mark.workspace_evidence
def test_prospective_trial_projection_preserves_result_and_claim_boundaries(modules) -> None:
    _, research = modules
    record = research.build_research_export()["prospective_trial_record"]
    source = json.loads(research.CRYPTO_CARRY_PORTABLE_RESULT_JSON.read_text())

    assert record["identity"] == source["identity"]
    assert (
        record["metrics"]["annualized_daily_sharpe"]
        == source["immutable_primary_result"]["summary"]["sharpe"]
    )
    assert (
        record["metrics"]["candidate_simulation_max_drawdown"]
        == source["immutable_primary_result"]["summary"]["max_dd"]
    )
    assert record["classification"]["evidence_type"] == "HISTORICAL_WALK_FORWARD_SIMULATION"
    assert record["classification"]["forward_live_result"] is False
    assert record["classification"]["live_broker_result"] is False
    assert record["classification"]["independent_replication"] is False
    assert record["classification"]["peer_reviewed"] is False
    assert record["classification"]["external_submission_completed"] is False
    assert record["decision"]["disposition"] == "INCOMPLETE"
    assert record["decision"]["admitted"] is False
    assert record["decision"]["killed"] is False
    assert record["decision"]["identity_may_be_regraded_later"] is False
    assert record["packet"]["complete"] is True
    assert (
        record["packet"]["completion_assessment"]["candidate_evidence_complete_for_admission"]
        is False
    )
    assert record["future_protocol"]["status"] == ("TEMPLATE_NOT_IN_FORCE_NO_RETURN_AUTHORIZATION")


@pytest.mark.workspace_evidence
def test_program_status_is_published_identically_to_both_hosts(modules) -> None:
    _, research = modules
    expected = research.build_research_export()["program_status"]
    hosts = (
        REPO.parent / "meridian" / "public" / "glassbox" / "program_status.json",
        REPO.parent / "meridian-app" / "public" / "glassbox" / "program_status.json",
    )
    for path in hosts:
        assert path.exists(), f"program status is not published to {path}"
    assert hosts[0].read_bytes() == hosts[1].read_bytes()

    published = json.loads(hosts[0].read_text())
    assert published.pop("generated_at")
    assert published.pop("content_hash").startswith("sha256:")
    assert published == expected


@pytest.mark.workspace_evidence
def test_execution_realism_book_page_is_published_identically() -> None:
    source = REPO / "docs" / "research" / "EXECUTION_REALISM.md"
    legacy = REPO.parent / "meridian" / "public" / "research" / "execution-realism.md"
    app = REPO.parent / "meridian-app" / "public" / "research" / "execution-realism.md"

    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_execution_benchmark_is_honest_and_published_identically(modules) -> None:
    _, research = modules
    section = research.build_research_export()["engineering_benchmarks"]["execution_fill_models"]
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
    section = research.build_research_export()["engineering_capabilities"]["futures_execution"]
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
        REPO.parent / "meridian-app" / "public" / "research" / "futures-execution-foundation.md"
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
    section = research.build_research_export()["engineering_capabilities"]["options_execution"]
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
        REPO.parent / "meridian-app" / "public" / "research" / "options-execution-foundation.md"
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
        REPO.parent / "meridian-app" / "public" / "research" / "borrow-execution-foundation.md"
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
    section = research.build_research_export()["engineering_capabilities"]["market_status_replay"]
    contract = section["contract"]
    source = REPO / "artifacts" / "engineering" / "market_status_contract.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    book = REPO / "docs" / "research" / "MARKET_STATUS_REPLAY.md"
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "market-status-replay.md"
    app_book = REPO.parent / "meridian-app" / "public" / "research" / "market-status-replay.md"

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
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "crowding-risk-foundation.md"
    app_book = REPO.parent / "meridian-app" / "public" / "research" / "crowding-risk-foundation.md"

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
    legacy_book = REPO.parent / "meridian" / "public" / "research" / "corporate-action-lifecycle.md"
    app_book = (
        REPO.parent / "meridian-app" / "public" / "research" / "corporate-action-lifecycle.md"
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


@pytest.mark.workspace_evidence
def test_forward_evidence_standard_is_a_bound_first_class_publication(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    report = payload["forward_evidence_maturity"]
    contract = payload["forward_evidence_contract"]
    source = REPO / "docs" / "research" / "FORWARD_SHARPE_EVIDENCE_STANDARD.md"
    legacy = (
        REPO.parent / "meridian" / "public" / "research" / ("forward-sharpe-evidence-standard.md")
    )
    app = (
        REPO.parent
        / "meridian-app"
        / "public"
        / "research"
        / ("forward-sharpe-evidence-standard.md")
    )

    assert (
        report["source_bindings"]["methodology_paper"]["sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert contract["methodology_paper_public_path"] == (
        "/research/forward-sharpe-evidence-standard"
    )
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_forward_drawdown_evidence_is_public_and_byte_identical(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    source = research.FORWARD_DRAWDOWN_EVIDENCE_JSON
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    evidence = json.loads(source.read_text())

    assert payload["forward_drawdown_evidence"] == evidence
    assert evidence["schema"] == "canli.alphac-forward-drawdown-evidence.v1"
    assert evidence["production_equivalence"]["passes"] is False
    assert evidence["objective"]["live_expected_max_drawdown_established"] is False
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_current_book_drawdown_is_public_and_byte_identical(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    source = research.CURRENT_BOOK_DRAWDOWN_JSON
    public_name = "current_book_drawdown.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name
    evidence = json.loads(source.read_text())

    assert payload["current_book_drawdown"] == evidence
    assert evidence["schema"] == "canli.alphac-current-book-drawdown-study.v1"
    assert evidence["objective"]["conservative_modeled_expected_max_drawdown"] < 0.11
    assert evidence["objective"]["conservative_modeled_p95_max_drawdown"] > 0.11
    assert evidence["objective"]["live_expected_max_drawdown_established"] is False
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_current_book_diversification_is_public_and_byte_identical(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    source = research.CURRENT_BOOK_DIVERSIFICATION_JSON
    public_name = "current_book_diversification.json"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name
    evidence = json.loads(source.read_text())

    assert payload["current_book_diversification"] == evidence
    assert evidence["schema"] == "canli.alphac-current-book-diversification-study.v1"
    comparison = evidence["governing_comparison"]
    assert comparison["active_v7_has_no_global_average_correlation_point_gate"] is True
    assert comparison["historical_v6_global_average_correlation_point_check"] is False
    assert comparison["meets_active_correlation_objective"] is False
    assert comparison["checks"]["average_pairwise_upper_95"] is True
    assert comparison["live_forward_diversification_established"] is False
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
@pytest.mark.parametrize(
    ("source_name", "public_name"),
    [
        ("TRIAL_ACCOUNTING_POLICY_JSON", "trial_accounting.json"),
        ("ADMISSION_V7_PROMOTION_JSON", "admission_v7_promotion.json"),
    ],
)
def test_v7_governance_is_public_and_byte_identical(
    modules, source_name: str, public_name: str
) -> None:
    _, research = modules
    source = getattr(research, source_name)
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name

    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_crypto_attribution_rollout_evidence_is_public_and_byte_identical(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    source = research.CRYPTO_POSITION_ATTRIBUTION_ROLLOUT_JSON
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    evidence = json.loads(source.read_text())

    assert payload["crypto_position_attribution_rollout_verification"] == evidence
    assert evidence["schema"] == (
        "canli.alphac-crypto-position-attribution-rollout-verification.v1"
    )
    assert evidence["status"] == "VERIFIED_FIRST_NATURAL_MARKED_CYCLE"
    assert evidence["passes"] is True
    assert evidence["remote_query_performed"] is True
    assert evidence["natural_cycle_after_deployment"] is True
    assert evidence["attribution"]["latest_cycle"]["position_arithmetic_passes"] is True
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_crypto_attribution_preflight_is_public_current_and_non_authorizing(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    source = research.CRYPTO_POSITION_ATTRIBUTION_PREFLIGHT_OBSERVATION_JSON
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name
    evidence = json.loads(source.read_text())

    assert payload["crypto_position_attribution_preflight_observation"] == evidence
    assert payload["published_as"]["crypto_position_attribution_preflight_observation"] == (
        "crypto_position_attribution_vps_preflight_observation.json"
    )
    assert evidence["schema"] == (
        "canli.alphac-crypto-position-attribution-vps-preflight-observation.v1"
    )
    assert evidence["status"] == "PASS_READ_ONLY_PREFLIGHT_DEPLOYMENT_NOT_AUTHORIZED"
    assert evidence["passes_read_only_preflight"] is True
    assert evidence["remote_query_performed"] is True
    assert evidence["remote_mutations_performed"] is False
    assert evidence["deployment_authorized"] is False
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_active_ownership_handoff_is_hash_bound_and_identical_on_both_hosts(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    packet = next(
        item
        for item in payload["blind_review_packets"]
        if item["id"] == "active_ownership_item4_v3"
    )
    receipt = payload["active_ownership_blind_handoff_receipt"]
    source = REPO / "artifacts" / "handoffs" / "active_ownership_13d_item4_v3_blind.tar.gz"
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name

    assert packet["status"] == "WAITING_FOR_INDEPENDENT_REVIEW"
    assert packet["public_paths"]["archive"] == receipt["public_archive_path"]
    assert packet["public_paths"]["handoff_receipt"] == (
        "/glassbox/active_ownership_13d_item4_v3_blind.json"
    )
    assert receipt["labels_completed"] == 0
    assert receipt["prediction_blind"] is True
    assert receipt["archive_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()


@pytest.mark.workspace_evidence
def test_external_validation_audit_is_public_and_fail_closed(modules) -> None:
    _, research = modules
    payload = research.build_research_export()
    audit = payload["external_validation_opportunities"]
    source = research.EXTERNAL_VALIDATION_OPPORTUNITIES_JSON
    legacy = REPO.parent / "meridian" / "public" / "glassbox" / source.name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / source.name

    assert audit["schema"] == "canli.alphac-external-validation-opportunities.v2"
    assert audit["decision"] == "NO_EXTERNAL_ACTION_AUTHORIZED_ELIGIBILITY_FACTS_REMAIN"
    assert audit["counts"] == {
        "awarded": 0,
        "exact_future_deadlines": 1,
        "opportunities": 6,
        "registered": 0,
        "registration_authorized": 0,
        "submitted": 0,
    }
    assert len(audit["content_hash"]) == 71
    assert len(audit["opportunity_shortlist"]) == 6
    assert all(not row["registration_authorized"] for row in audit["opportunities"])
    assert all(not row["entry_claimed"] for row in audit["opportunities"])
    opportunities = {row["id"]: row for row in audit["opportunities"]}
    assert opportunities["regeneron_isef_2027"]["affiliated_fair_directory_query"][
        "result"
    ] == "NO_FAIRS_MATCH_YOUR_SEARCH_CRITERIA"
    assert opportunities["wharton_investment_2026_2027"]["eligibility"][
        "team_leader"
    ] == "at least 16 years old at the start of the competition"
    assert source.read_bytes() == legacy.read_bytes() == app.read_bytes()
