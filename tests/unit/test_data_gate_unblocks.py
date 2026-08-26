from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "analyze_data_gate_unblocks.py"
SPEC = importlib.util.spec_from_file_location("data_gate_unblocks_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_active_ownership_v3_is_not_reported_as_parser_blocked() -> None:
    result = json.loads(MODULE.OUTPUT.read_text())
    rows = {row["family"]: row for row in result["families"]}
    v3 = rows["active_ownership_13d_item4_v3"]
    assert v3["decision"] == "HUMAN_AUDIT_REQUIRED"
    assert v3["classification"] == "BLOCKED_ON_HUMAN_ACCURACY_AUDIT"
    assert v3["failing_gate_count"] == 0
    assert v3["passing_gate_count"] == 5
    assert "active_ownership_13d_item4_v3" not in result["by_classification"].get(
        "BLOCKED_ON_EXTRACTION_QUALITY", []
    )
    assert result["content_hash"] == MODULE.content_hash(result)


def test_measured_unreachable_or_blended_gates_are_not_called_nearest() -> None:
    result = json.loads(MODULE.OUTPUT.read_text())
    nearest = {row["family"] for row in result["nearest_to_passing"]}
    assert nearest.isdisjoint(
        {
            "spin_off_dislocation",
            "customer_supplier_propagation",
            "merger_arbitrage",
            "cftc_hedging_pressure",
            "bond_etf_nav_dislocation",
        }
    )
    rows = {row["family"]: row for row in result["families"]}
    assert rows["spin_off_dislocation"]["reachability_verdict"] == (
        "GATE_UNREACHABLE_BY_DETECTOR_REPAIR"
    )
    assert rows["merger_arbitrage"]["reachability_verdict"] == "GATE_BLENDS_TWO_POPULATIONS"
    assert rows["tender_offer_spread"]["atlas_obtainability_verdict"] == (
        "HELD_BUT_REACHABILITY_CEILING_NOT_MEASURED"
    )
    assert rows["inflation_breakeven_relative_value"]["atlas_obtainability_verdict"] == (
        "VENDOR_ONLY_AN_OWNER_SPENDING_DECISION"
    )
    assert rows["active_ownership_13d_item4_v2"]["superseded"] is True
    assert rows["active_ownership_13d_item4_v2"]["classification"] == (
        "SUPERSEDED_HISTORICAL_RESULT"
    )
    assert rows["active_ownership_13d_schema_v2"]["classification"] == (
        "SUPERSEDED_HISTORICAL_RESULT"
    )
    assert rows["cftc_hedging_pressure"]["classification"] == (
        "BLOCKED_ON_UNRECOVERABLE_RELEASE_LINEAGE"
    )
    assert rows["cftc_hedging_pressure"]["release_reachability_verdict"] == (
        "HISTORICAL_RELEASE_LINEAGE_CEILING_BELOW_GATE"
    )
    assert rows["bond_etf_nav_dislocation"]["classification"] == (
        "BLOCKED_ON_PAID_ARCHIVAL_AND_EXECUTABLE_DATA"
    )
    assert rows["bond_etf_nav_dislocation"]["source_reachability_verdict"] == (
        "PAID_ARCHIVAL_AND_EXECUTABLE_DATA_REQUIRED"
    )


def test_staged_families_use_declared_current_artifacts_and_blockers() -> None:
    result = json.loads(MODULE.OUTPUT.read_text())
    rows = {row["family"]: row for row in result["families"]}

    pre_fomc = rows["pre_fomc_announcement_drift"]
    assert pre_fomc["source_artifact"].endswith("/market_data_readiness.json")
    assert pre_fomc["decision"] == "DATA_GATED"
    assert pre_fomc["classification"] == (
        "BLOCKED_ON_PAID_OR_BOUNDED_MARKET_DATA_ROUTE"
    )
    assert "practical_server_filtered_or_bounded_download_route" in pre_fomc[
        "failing_gates"
    ]

    repurchase = rows["repurchase_issuance_flow"]
    assert repurchase["source_artifact"].endswith("/item703/documents_result.json")
    assert repurchase["decision"] == "READY_FOR_BLIND_LABELING"
    assert repurchase["classification"] == "BLOCKED_ON_HUMAN_BLIND_LABELING"

    spin_off = rows["spin_off_dislocation"]
    assert spin_off["source_artifact"].endswith("/document_schema_result.json")
    assert spin_off["classification"] == "BLOCKED_ON_MEASURED_REACHABILITY_CEILING"

    treasury = rows["treasury_auction_concession"]
    assert treasury["source_artifact"].endswith("/schedule_state_machine_audit.json")
    assert treasury["decision"] == "AUTHOR_APPROVAL_REQUIRED"
    assert treasury["classification"] == "BLOCKED_ON_AUTHOR_TECHNICAL_APPROVAL"

    for row in (pre_fomc, repurchase, spin_off, treasury):
        assert row["source_artifact"] in row["artifacts_considered"]

    polygon_actions = [
        action for action in result["owner_actions"] if "POLYGON_API_KEY" in action["action"]
    ]
    assert all(
        "pre_fomc_announcement_drift" not in action["unblocks"]
        for action in polygon_actions
    )
    manual_actions = {
        tuple(action["unblocks"]): action
        for action in result["owner_actions"]
        if "packet" in action
    }
    for family in (
        "repurchase_issuance_flow",
        "active_ownership_13d_item4_v3",
    ):
        action = manual_actions[(family,)]
        packet = REPO / action["packet"]
        assert packet.is_file()
        assert json.loads(packet.read_text())["content_hash"] == action["packet_content_hash"]
    assert result["content_hash"] == MODULE.content_hash(result)


def test_script_discovery_does_not_match_only_the_first_family_token() -> None:
    paths = {path.name for path in MODULE._scripts_for("treasury_auction_concession")}
    assert "audit_treasury_auction_feasibility.py" in paths
    assert "audit_treasury_calendar_revisions.py" in paths
    assert "audit_treasury_schedule_state_machine.py" in paths
    assert "audit_treasury_futures_basis_feasibility.py" not in paths


def test_a_completed_return_kill_is_never_reported_as_actionable() -> None:
    """A passing feasibility artifact must not resurrect a family after its return trial KILL."""
    result = json.loads(MODULE.OUTPUT.read_text())
    rows = {row["family"]: row for row in result["families"]}
    narrative = rows["earnings_narrative_change"]
    assert narrative["decision"] == "PASS_TO_RETURN_PREREGISTRATION"
    assert narrative["return_outcome"]["verdict"] == "KILL"
    assert narrative["classification"] == "RETURN_OUTCOME_ALREADY_RECORDED"
    assert narrative["actionable_unblock"] is False
    assert "earnings_narrative_change" not in result["by_classification"].get(
        "NOT_BLOCKED", []
    )
