from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "seal_active_ownership_confirmatory_design.py"
SPEC = importlib.util.spec_from_file_location("active_ownership_confirmatory_design", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
INPUT_SCRIPT = ROOT / "scripts" / "seal_active_ownership_confirmatory_inputs.py"
INPUT_SPEC = importlib.util.spec_from_file_location(
    "active_ownership_confirmatory_inputs", INPUT_SCRIPT
)
assert INPUT_SPEC is not None and INPUT_SPEC.loader is not None
INPUT_MODULE = importlib.util.module_from_spec(INPUT_SPEC)
INPUT_SPEC.loader.exec_module(INPUT_MODULE)


def test_confirmatory_design_is_disjoint_large_and_fail_closed() -> None:
    payload = MODULE.build()
    assert payload["content_hash"] == MODULE.content_hash(payload)
    assert payload["stage"] == "PROSPECTIVE_PRE_LABEL_PRE_RETURN_CONFIRMATORY_DESIGN"
    assert payload["project_owner"] == "Arhan Canli"
    assert payload["technical_authorship_approved"] is False
    assert payload["authorship_disclosure"].startswith("AI-assisted technical draft")
    assert payload["protocol_frozen"] is True
    assert payload["corpus_acquired"] is False
    assert payload["corpus_frozen"] is False
    assert payload["independent_labels_completed"] == 0
    assert payload["return_data_opened"] is False
    assert payload["return_hypotheses_spent"] == 0
    assert payload["execution_authorized"] is False
    assert payload["selection"]["rows_per_year"] == 40
    assert payload["selection"]["target_rows"] == 640
    assert payload["population"]["original_accessions_excluded"] == 160
    assert payload["selection"]["selection_uses_machine_prediction"] is False
    assert payload["selection"]["selection_uses_human_labels"] is False
    assert payload["selection"]["selection_uses_prices_or_returns"] is False
    assert payload["activation"]["condition"].startswith("ORIGINAL_48_ROW_POINT_GATE_PASSES")


def test_confirmatory_design_records_power_without_promising_a_pass() -> None:
    payload = MODULE.build()
    gates = payload["confidence_gates"]
    assert gates["precision"]["minimum_perfect_denominator"] == 59
    assert gates["recall"]["minimum_perfect_denominator"] == 14
    assert gates["ownership_exact"]["minimum_perfect_denominator"] == 29
    assert gates["precision"]["lower_bound_threshold"] == 0.95
    assert gates["recall"]["lower_bound_threshold"] == 0.80
    assert gates["ownership_exact"]["lower_bound_threshold"] == 0.90
    planning = payload["planning_power_not_outcome"]
    assert planning["observed_feasibility_machine_positive_rate"] == 0.20
    assert planning["expected_predicted_positives_at_640"] == 128
    assert planning["expected_denominator_max_false_positives_while_precision_lb_passes"] == 2
    assert planning["guarantees_actual_denominator_or_pass"] is False
    assert planning["underpowered_actual_denominator_blocks_admission"] is True


def test_current_cache_is_explicitly_insufficient() -> None:
    cache = MODULE.build()["current_cache"]
    assert cache["headers"] == 800
    assert cache["eligible_disjoint_rows"] == 218
    assert cache["minimum_year_count"] == 5
    assert cache["sufficient_for_design"] is False
    assert cache["additional_header_acquisition_required"] is True
    assert cache["confirmation_submissions_acquired"] == 0


def test_compact_input_receipt_is_tracked_self_hashing_and_source_bound() -> None:
    snapshot = json.loads(MODULE.INPUT_SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["content_hash"] == MODULE.content_hash(snapshot)
    assert snapshot["status"] == (
        "SEALED_COMPACT_INPUT_RECEIPT_RAW_WORKSPACE_SOURCES_NOT_INCLUDED"
    )
    assert snapshot["governed_values"]["header_audit"]["eligible_disjoint_rows"] == 218
    assert snapshot["governed_values"]["original_document_sample"]["unique_accessions"] == 160
    assert set(snapshot["raw_source_bindings"]) == {
        "metadata_result",
        "header_audit",
        "original_document_sample",
        "feasibility_result",
        "point_gate_audit",
    }


@pytest.mark.workspace_evidence
def test_checked_in_compact_input_receipt_matches_raw_workspace_sources() -> None:
    assert json.loads(INPUT_MODULE.OUTPUT.read_text(encoding="utf-8")) == INPUT_MODULE.build()


@pytest.mark.workspace_evidence
def test_checked_in_confirmatory_design_matches_sources() -> None:
    assert json.loads(MODULE.OUTPUT.read_text(encoding="utf-8")) == MODULE.build()
