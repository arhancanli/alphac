from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphaforge.validation.prereg import load_prereg

PROGRAM = Path(__file__).resolve().parents[2] / "config" / "sleeve_discovery.json"
INSIDER_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "probe"
    / "insider_purchase_clusters"
    / "result.json"
)
INVENTORY_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "probe"
    / "eia_petroleum_inventory"
    / "result.json"
)
TREASURY_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "result.json"
)
CFTC_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "cftc_hedging_pressure"
    / "result.json"
)
TREASURY_TIMING_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "identity_timing.json"
)
TREASURY_REVISION_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "calendar_revision_audit.json"
)
PRE_FOMC_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "result.json"
)
PRE_FOMC_SCHEDULE_LINEAGE_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "annual_schedule_lineage.json"
)
PRE_FOMC_PREREG = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "design"
    / "PREREG_PRE_FOMC_ANNOUNCEMENT_DRIFT.md"
)
PRE_FOMC_MARKET_DATA_READINESS_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "market_data_readiness.json"
)
SPIN_OFF_LINEAGE_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "spin_off_dislocation"
    / "result.json"
)
SPIN_OFF_DOCUMENT_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "spin_off_dislocation"
    / "document_schema_result.json"
)
NATURAL_GAS_FEASIBILITY_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "natural_gas_storage_weather"
    / "result.json"
)
CUSTOMER_SUPPLIER_FEASIBILITY_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "customer_supplier_propagation"
    / "result.json"
)
BOND_ETF_NAV_FEASIBILITY_RESULT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "bond_etf_nav_dislocation"
    / "result.json"
)


def test_discovery_program_has_bounded_distinct_candidates() -> None:
    data = json.loads(PROGRAM.read_text())
    candidates = data["candidates"]
    ids = [candidate["id"] for candidate in candidates]

    assert data["schema"] == "canli.sleeve-discovery.v2"
    assert 8 <= len(candidates) <= 14
    assert len(ids) == len(set(ids))
    assert sum(candidate["hypothesis_budget"] for candidate in candidates) <= 24
    assert len({candidate["mechanism"] for candidate in candidates}) == len(candidates)


def test_every_candidate_is_governed_and_credentials_are_not_embedded() -> None:
    data = json.loads(PROGRAM.read_text())
    serialized = json.dumps(data).lower()

    assert "api_key" not in serialized
    assert "secret_key" not in serialized
    for candidate in data["candidates"]:
        assert candidate["hypothesis_budget"] > 0
        assert candidate["kill"].startswith("Kill if")
        assert candidate["provider_options"]
        assert candidate["execution"]
        assert candidate["status"] in {
            "data-gated",
            "selected-key-free-probe",
            "key-free-feasibility",
            "manual-blind-label-gate",
            "calendar-lineage-pending",
            "identity-redesign-required",
            "return-preregistration-pending",
            "return-preregistered-ingest-pending",
            "return-killed",
        }


def test_repurchase_issuance_stays_no_return_and_completion_based() -> None:
    data = json.loads(PROGRAM.read_text())
    candidate = next(
        row for row in data["candidates"] if row["id"] == "repurchase_issuance_flow"
    )

    assert candidate["status"] == "manual-blind-label-gate"
    assert candidate["hypothesis_budget"] == 1
    assert candidate["return_hypotheses_spent"] == 0
    assert candidate["feasibility"]["decision"] == "BLIND_ITEM703_LABELING_REQUIRED"
    assert candidate["feasibility"]["return_hypotheses_spent"] == 0
    assert (
        candidate["feasibility"]["pipeline_status"]
        == "SEC_COLLECTION_AND_SEMANTICS_COMPLETE_AWAITING_BLIND_LABELS"
    )
    assert candidate["feasibility"]["pipeline_tests"] == 48
    commands = candidate["feasibility"]["implemented_commands"]
    assert len(commands) == 11
    assert any("audit_repurchase_issuance_semantics.py" in command for command in commands)
    assert any("seal_repurchase_item703_labels.py" in command for command in commands)
    assert any("parse_repurchase_item703_documents.py" in command for command in commands)
    assert any("audit_repurchase_item703_extraction.py" in command for command in commands)
    assert any("audit_repurchase_issuance_feasibility.py" in command for command in commands)
    assert "without viewing parser output" in candidate["feasibility"]["manual_gate"]
    assert "exits nonzero" in candidate["feasibility"]["fail_closed_state"]
    assert "completed" in candidate["mechanism"].lower()
    assert "never authorization" in candidate["mechanism"].lower()


def test_options_dispersion_is_source_bound_and_return_gated() -> None:
    data = json.loads(PROGRAM.read_text())
    candidate = next(
        row for row in data["candidates"] if row["id"] == "options_dispersion"
    )

    assert candidate["status"] == "data-gated"
    assert candidate["literature_review"].endswith("LITERATURE_OPTIONS_DISPERSION.md")
    feasibility = candidate["feasibility"]
    assert feasibility["decision"] == "DATA_GATED"
    assert feasibility["return_hypotheses_spent"] == 0
    assert feasibility["minimum_history_years"] == 15
    assert feasibility["alpaca_history_start"] == "2024-02"
    assert feasibility["credential_state"] == "INSTITUTIONAL_HISTORY_NOT_CONFIGURED"


def test_stablecoin_review_is_source_bound_and_outside_return_queue() -> None:
    data = json.loads(PROGRAM.read_text())
    review = next(
        row
        for row in data["feasibility_reviews"]
        if row["id"] == "stablecoin_dislocation"
    )

    assert review["queue_state"] == "outside-active-return-queue"
    assert review["decision"] == "DATA_GATED"
    assert review["return_hypotheses_spent"] == 0
    assert review["frozen_token"] == "native issuer-supported USDC only"
    assert "algorithmic stablecoins" in review["excluded_identities"]
    assert "production_entity_circle_mint_eligibility" in review["blocking_reasons"]
    assert review["credential_state"] == "INSTITUTIONAL_REDEMPTION_AND_L2_NOT_CONFIGURED"
    assert "public candles cannot pass" in review["claim_boundary"]


@pytest.mark.workspace_evidence
def test_spin_off_review_preserves_failed_initial_document_identity() -> None:
    data = json.loads(PROGRAM.read_text())
    lineage = json.loads(SPIN_OFF_LINEAGE_RESULT.read_text())
    documents = json.loads(SPIN_OFF_DOCUMENT_RESULT.read_text())
    review = next(
        row for row in data["feasibility_reviews"] if row["id"] == "spin_off_dislocation"
    )

    assert review["queue_state"] == "outside-active-return-queue"
    assert review["lineage_decision"] == lineage["decision"] == (
        "PASS_TO_DOCUMENT_SCHEMA_AUDIT"
    )
    assert review["decision"] == documents["decision"] == "DATA_GATED"
    assert review["lineage_quarter_indexes"] == lineage["quarter_indexes"] == 40
    assert review["lineage_initial_registrations"] == (
        lineage["initial_10_12b_registrations"]
    )
    assert review["document_sample_rows"] == documents["sample_rows"] == 98
    assert review["document_successful_rows"] == documents["successful_rows"] == 98
    assert review["pro_rata_language_rate"] == documents[
        "pro_rata_distribution_language_rate"
    ]
    assert review["ratio_mentions"] == documents["ratio_mentions"] == 8
    assert review["distribution_date_mentions"] == documents["distribution_date_mentions"] == 0
    assert review["market_data_opened"] is documents["market_data_opened"] is False
    assert review["return_hypotheses_spent"] == documents["return_hypotheses_spent"] == 0


@pytest.mark.workspace_evidence
def test_natural_gas_review_inherits_prior_inventory_trial_and_source_gate() -> None:
    data = json.loads(PROGRAM.read_text())
    result = json.loads(NATURAL_GAS_FEASIBILITY_RESULT.read_text())
    review = next(
        row
        for row in data["feasibility_reviews"]
        if row["id"] == "natural_gas_storage_weather"
    )

    assert review["queue_state"] == "outside-active-return-queue"
    assert review["decision"] == result["decision"] == "DATA_GATED"
    assert review["family_trial_account"] == result["family_trial_account"]
    assert review["prior_family_return_trials"] == result["prior_family_return_trials"] == 1
    assert review["minimum_family_trials_if_returns_open"] == (
        result["minimum_family_trials_if_returns_open"]
    )
    assert review["expected_eia_periods"] == result["expected_eia_periods"] == 469
    assert review["wayback_first_release_periods"] == result[
        "unique_first_release_periods_bound"
    ]
    assert review["wayback_first_release_coverage"] == result[
        "first_release_capture_coverage"
    ]
    assert review["official_original_data_coverage"] == result[
        "official_original_data_coverage"
    ]
    assert review["noaa_endpoint_coverage"] == result["noaa_endpoint_coverage"]
    assert review["market_data_opened"] is result["market_data_opened"] is False
    assert review["return_hypotheses_spent"] == result["return_hypotheses_spent"] == 0


@pytest.mark.workspace_evidence
def test_customer_supplier_review_preserves_failed_named_relationship_gate() -> None:
    data = json.loads(PROGRAM.read_text())
    result = json.loads(CUSTOMER_SUPPLIER_FEASIBILITY_RESULT.read_text())
    review = next(
        row
        for row in data["feasibility_reviews"]
        if row["id"] == "customer_supplier_propagation"
    )

    assert review["queue_state"] == "outside-active-return-queue"
    assert review["decision"] == result["decision"] == "DATA_GATED"
    assert review["manifest_rows_in_period"] == result["manifest"]["rows_in_period"]
    assert review["source_documents_valid"] == result["source_audit"][
        "documents_present_and_decompressible"
    ]
    assert review["source_coverage"] == result["source_audit"]["source_coverage"]
    assert review["concentration_candidates"] == result["source_audit"][
        "concentration_candidates"
    ]
    assert review["sample_rows"] == result["sample_audit"]["rows"] == 300
    assert review["documents_with_machine_name_candidate"] == result["sample_audit"][
        "documents_with_strict_name_candidate"
    ]
    assert review["machine_name_candidate_rate"] == result["sample_audit"][
        "strict_named_document_rate"
    ]
    assert review["market_data_opened"] is result["market_data_opened"] is False
    assert review["return_hypotheses_spent"] == result["return_hypotheses_spent"] == 0


@pytest.mark.workspace_evidence
def test_bond_etf_nav_review_preserves_stale_mark_and_source_gates() -> None:
    data = json.loads(PROGRAM.read_text())
    result = json.loads(BOND_ETF_NAV_FEASIBILITY_RESULT.read_text())
    review = next(
        row
        for row in data["feasibility_reviews"]
        if row["id"] == "bond_etf_nav_dislocation"
    )

    assert review["queue_state"] == "outside-active-return-queue"
    assert review["decision"] == result["decision"] == "DATA_GATED"
    for ticker in review["funds"]:
        coverage = result["premium_discount_coverage"][ticker]
        assert review["expected_xnys_sessions_each"] == coverage[
            "expected_xnys_sessions"
        ]
        assert review["issuer_dates_in_period_each"] == coverage[
            "issuer_dates_in_period"
        ]
        assert review["issuer_coverage_each"] == coverage["coverage"]
        assert review["historical_holdings_snapshots_each"] == result[
            "historical_holdings_snapshots"
        ][ticker]
    assert review["required_historical_holdings_snapshots_each"] == result[
        "required_historical_holdings_snapshots_each"
    ]
    assert review["market_records_opened"] == result["market_records_opened"] == 0
    assert review["return_hypotheses_spent"] == result["return_hypotheses_spent"] == 0


def test_retired_candidates_are_not_relisted_as_fresh_research() -> None:
    data = json.loads(PROGRAM.read_text())
    active = {candidate["id"] for candidate in data["candidates"]}
    retired = {candidate["id"] for candidate in data["retired_candidates"]}

    assert len(retired) >= 9
    assert active.isdisjoint(retired)
    assert all(candidate["verdict"] == "KILLED" for candidate in data["retired_candidates"])


@pytest.mark.workspace_evidence
def test_treasury_feasibility_matches_the_sealed_result() -> None:
    program = json.loads(PROGRAM.read_text())
    result = json.loads(TREASURY_RESULT.read_text())
    candidate = next(
        item for item in program["candidates"] if item["id"] == "treasury_auction_concession"
    )
    feasibility = candidate["feasibility"]

    assert candidate["status"] == "identity-redesign-required"
    assert result["decision"] == "PASS_TO_RETURN_PREREGISTRATION"
    assert feasibility["decision"] == result["decision"]
    assert feasibility["return_hypotheses_spent"] == result["return_hypotheses_spent"] == 0
    assert feasibility["coupon_auction_events"] == result["coupon_auction_events"]
    assert feasibility["post_2013_events"] == result["post_2013_events"]
    assert feasibility["raw_sha256"] == result["raw_sha256"]
    assert feasibility["manifest_sha256"] == result["manifest_sha256"]

    timing_result = json.loads(TREASURY_TIMING_RESULT.read_text())
    timing = candidate["identity_timing"]
    assert timing["decision"] == timing_result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert timing["return_hypotheses_spent"] == timing_result["return_hypotheses_spent"] == 0
    assert timing["two_year_note_auctions"] == timing_result["two_year_note_auctions"]
    assert (
        timing["formal_announcements_with_at_least_ten_calendar_days"]
        == timing_result["formal_announcements_with_at_least_ten_calendar_days"]
        == 0
    )
    assert timing["source_manifest_sha256"] == timing_result["source_manifest_sha256"]

    revision_result = json.loads(TREASURY_REVISION_RESULT.read_text())
    revision = candidate["calendar_revision_audit"]
    assert (
        revision["decision"]
        == revision_result["decision"]
        == "IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED"
    )
    assert revision["unresolved_auction_dates"] == revision_result["unresolved_auction_dates"]
    assert revision["return_hypotheses_spent"] == 0


@pytest.mark.workspace_evidence
def test_cftc_feasibility_matches_the_sealed_data_gate() -> None:
    program = json.loads(PROGRAM.read_text())
    result = json.loads(CFTC_RESULT.read_text())
    candidate = next(
        item for item in program["candidates"] if item["id"] == "cftc_hedging_pressure"
    )
    feasibility = candidate["feasibility"]

    assert candidate["status"] == "data-gated"
    assert result["decision"] == "DATA_GATED"
    assert feasibility["decision"] == result["decision"]
    assert feasibility["return_hypotheses_spent"] == result["return_hypotheses_spent"] == 0
    assert feasibility["metadata_rows"] == result["metadata_rows"]
    assert feasibility["blocking_reasons"] == result["blocking_reasons"]
    assert feasibility["raw_sha256"] == result["raw_sha256"]
    assert feasibility["manifest_sha256"] == result["manifest_sha256"]


@pytest.mark.workspace_evidence
def test_pre_fomc_discovery_state_matches_lineage_and_preregistration() -> None:
    program = json.loads(PROGRAM.read_text())
    feasibility_result = json.loads(PRE_FOMC_RESULT.read_text())
    lineage_result = json.loads(PRE_FOMC_SCHEDULE_LINEAGE_RESULT.read_text())
    prereg = load_prereg(PRE_FOMC_PREREG)
    candidate = next(
        item for item in program["candidates"] if item["id"] == "pre_fomc_announcement_drift"
    )
    feasibility = candidate["feasibility"]
    lineage = candidate["schedule_lineage"]
    registration = candidate["return_preregistration"]

    # Preserve the first-stage finding rather than rewriting history after lineage recovery.
    assert candidate["status"] == "data-gated"
    assert feasibility["decision"] == feasibility_result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert feasibility["scheduled_events"] == feasibility_result["scheduled_events"] == 79
    assert feasibility["blocking_reasons"] == feasibility_result["blockers"]
    assert feasibility["source_manifest_sha256"] == feasibility_result["source_manifest_sha256"]
    assert feasibility["events_sha256"] == feasibility_result["events_sha256"]

    # The second-stage artifact resolves that gate and seals the full scheduled universe,
    # including the cancellation that a statement-only join would silently omit.
    assert lineage["decision"] == lineage_result["decision"] == "PASS_TO_RETURN_PREREGISTRATION"
    assert lineage["annual_schedule_sources"] == lineage_result["annual_schedule_sources"] == 10
    assert lineage["scheduled_slots"] == lineage_result["scheduled_slots"] == 80
    assert (
        lineage["completed_regular_decisions"]
        == lineage_result["completed_regular_decisions"]
        == 79
    )
    assert lineage["explicit_cancellations"] == lineage_result["explicit_cancellations"] == 1
    assert lineage["events_sha256"] == lineage_result["events_sha256"]
    assert lineage["return_hypotheses_spent"] == lineage_result["return_hypotheses_spent"] == 0

    assert registration["identity"] == prereg["profile"] == "pre_fomc_announcement_drift_v1"
    assert registration["direction"] == prereg["direction"] == "long"
    assert registration["scheduled_slots"] == int(prereg["scheduled_slots"]) == 80
    assert registration["completed_events"] == int(prereg["completed_events"]) == 79
    assert registration["cancelled_slot"] == prereg["cancelled_slot"] == "2020-03-18"
    assert lineage_result["cancellation"]["scheduled_decision_date"] == prereg["cancelled_slot"]
    assert registration["return_data_opened"] is lineage_result["return_data_opened"] is False
    assert (
        candidate["return_hypotheses_spent"]
        == registration["return_hypotheses_spent"]
        == lineage_result["return_hypotheses_spent"]
        == 0
    )

    readiness_result = json.loads(PRE_FOMC_MARKET_DATA_READINESS_RESULT.read_text())
    readiness = candidate["market_data_readiness"]
    assert readiness["decision"] == readiness_result["decision"] == "DATA_GATED"
    assert (
        readiness["required_control_windows"]
        == readiness_result["required_control_windows"]
    )
    assert (
        readiness["minimum_controls_per_completed_event"]
        == readiness_result["minimum_controls_per_completed_event"]
        == 3
    )
    assert readiness["required_unique_session_files"] == readiness_result[
        "required_unique_session_files"
    ]
    assert (
        readiness["missing_session_files"]
        == len(readiness_result["missing_session_files"])
        == 0
    )
    assert readiness["full_day_flatfile_compressed_gib"] == readiness_result[
        "compressed_gib_if_all_required_full_day_files_downloaded"
    ]
    assert readiness["credential_state"] == readiness_result["credential_state"]
    assert readiness["quote_records_opened"] is False
    assert readiness_result["gates"]["quote_records_not_decompressed_or_parsed"] is True


def test_admission_gates_preserve_statistical_honesty() -> None:
    gates = json.loads(PROGRAM.read_text())["admission_gates"]

    assert gates["point_in_time_data"] is True
    assert gates["net_of_costs"] is True
    assert gates["walk_forward_only"] is True
    assert gates["deflated_sharpe_must_be_measured"] is True
    assert gates["book_deflated_sharpe_must_be_measured"] is True
    assert gates["pbo_max"] <= 0.20
    assert gates["candidate_average_correlation_to_existing_book_max"] <= 0.0
    assert gates["book_average_pairwise_correlation_delta_max_exclusive"] == 0.0
    assert gates["stressed_pairwise_correlation_max"] <= 0.50


@pytest.mark.workspace_evidence
def test_retired_insider_metrics_match_the_preserved_result() -> None:
    program = json.loads(PROGRAM.read_text())
    result = json.loads(INSIDER_RESULT.read_text())
    retired = next(
        candidate
        for candidate in program["retired_candidates"]
        if candidate["id"] == "insider_purchase_clusters"
    )

    assert result["schema"] == "canli.insider-cluster-probe.v3"
    assert result["verdict"] == "KILL"
    assert retired["net_sharpe"] == result["metrics"]["net_sharpe"]
    assert retired["dsr"] == result["metrics"]["dsr"]
    assert retired["newey_west_t"] == result["metrics"]["newey_west_t"]
    assert retired["average_correlation"] == result["correlation"]["average"]


@pytest.mark.workspace_evidence
def test_retired_inventory_metrics_match_the_preserved_result() -> None:
    program = json.loads(PROGRAM.read_text())
    result = json.loads(INVENTORY_RESULT.read_text())
    retired = next(
        candidate
        for candidate in program["retired_candidates"]
        if candidate["id"] == "commodity_inventory_seasonal"
    )

    assert result["schema"] == "canli.eia-petroleum-inventory-probe.v1"
    assert result["verdict"] == "KILL"
    assert retired["net_sharpe"] == result["metrics"]["net_sharpe"]
    assert retired["dsr"] == result["metrics"]["dsr"]
    assert retired["newey_west_t"] == result["metrics"]["newey_west_t"]
    assert retired["average_correlation"] == result["correlation"]["average"]
    assert (
        retired["capacity_p05_usd_at_1pct_adv"]
        == result["metrics"]["capacity"]["p05_usd_at_1pct_adv"]
    )
