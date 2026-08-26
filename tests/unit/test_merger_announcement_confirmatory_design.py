from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INPUT_SCRIPT = ROOT / "scripts" / "seal_merger_announcement_confirmatory_inputs.py"
INPUT_SPEC = importlib.util.spec_from_file_location("merger_confirmation_inputs", INPUT_SCRIPT)
assert INPUT_SPEC is not None and INPUT_SPEC.loader is not None
INPUT_MODULE = importlib.util.module_from_spec(INPUT_SPEC)
INPUT_SPEC.loader.exec_module(INPUT_MODULE)

DESIGN_SCRIPT = ROOT / "scripts" / "seal_merger_announcement_confirmatory_design.py"
DESIGN_SPEC = importlib.util.spec_from_file_location("merger_confirmation_design", DESIGN_SCRIPT)
assert DESIGN_SPEC is not None and DESIGN_SPEC.loader is not None
DESIGN_MODULE = importlib.util.module_from_spec(DESIGN_SPEC)
DESIGN_SPEC.loader.exec_module(DESIGN_MODULE)


def test_redesign_preserves_failure_and_uses_a_disjoint_unopened_period() -> None:
    payload = DESIGN_MODULE.build()
    assert payload["content_hash"] == DESIGN_MODULE.content_hash(payload)
    assert payload["exploratory_result_preserved_as_failed"] is True
    assert payload["exploration_period"] == {"start": "2016-01-01", "end": "2025-12-31"}
    assert payload["confirmation_period"] == {"start": "2006-01-01", "end": "2015-12-31"}
    assert payload["periods_disjoint"] is True
    assert payload["corpus_acquired"] is False
    assert payload["corpus_frozen"] is False
    assert payload["independent_labels_completed"] == 0
    assert payload["return_data_opened"] is False
    assert payload["return_hypotheses_spent"] == 0
    assert payload["execution_authorized"] is False


def test_both_filing_strata_must_pass_without_aggregate_rescue() -> None:
    payload = DESIGN_MODULE.build()
    assert payload["strata"]["values"] == ["DEFM14A", "SC 14D9"]
    assert payload["strata"]["reported_and_gated_separately"] is True
    assert payload["strata"]["aggregate_cannot_rescue_failed_stratum"] is True
    assert payload["selection"]["rows_per_year_stratum_cell"] == 20
    assert payload["selection"]["rows_per_stratum"] == 200
    assert payload["selection"]["target_rows"] == 400
    assert payload["selection"]["insufficient_cell_policy"] == (
        "DATA_GATED_NO_CROSS_CELL_SUBSTITUTION"
    )


def test_selection_and_resolver_fail_closed_before_returns() -> None:
    payload = DESIGN_MODULE.build()
    selection = payload["selection"]
    assert selection["selection_uses_document_text"] is False
    assert selection["selection_uses_machine_prediction"] is False
    assert selection["selection_uses_human_labels"] is False
    assert selection["selection_uses_prices_or_returns"] is False
    assert selection["selection_uses_realized_deal_outcome"] is False
    resolver = payload["resolver"]
    assert resolver["selection_rule"] == "EARLIEST_QUALIFYING_SEC_ACCEPTANCE_TIMESTAMP"
    assert resolver["later_confirmation_may_backdate"] is False
    assert resolver["conflict_policy"] == "UNRESOLVED_CONFLICT"
    assert "UNRESOLVED_NO_QUALIFYING_SOURCE" in resolver["states"]


def test_confidence_gates_are_powered_and_not_descriptive_only() -> None:
    gates = DESIGN_MODULE.build()["confidence_gates_per_stratum"]
    expected = {
        "announcement_coverage": (0.80, 0.75),
        "same_transaction_link_accuracy": (0.95, 0.95),
        "acceptance_timestamp_accuracy": (0.90, 0.90),
        "outcome_marker_coverage": (0.70, 0.65),
    }
    for key, (point, lower) in expected.items():
        gate = gates[key]
        assert gate["point_threshold"] == point
        assert gate["one_sided_exact_lower_95_threshold"] == lower
        assert gate["target_denominator"] == 200
        successes = gate["minimum_successes_at_target_denominator"]
        assert successes / 200 >= point
        assert DESIGN_MODULE.exact_one_sided_lower_bound(successes, 200) >= lower
        if successes:
            previous = successes - 1
            assert (
                previous / 200 < point
                or DESIGN_MODULE.exact_one_sided_lower_bound(previous, 200) < lower
            )


def test_technical_pass_does_not_supply_arhans_approval() -> None:
    payload = DESIGN_MODULE.build()
    assert payload["project_owner"] == "Arhan Canli"
    assert payload["technical_authorship_approved"] is False
    assert payload["authorship_disclosure"].startswith("AI-assisted technical draft")
    assert payload["technical_decision"] == (
        "PASS_PROSPECTIVE_NO_RETURN_CONFIRMATORY_DESIGN"
    )
    assert payload["governance_decision"] == "AUTHOR_APPROVAL_REQUIRED"
    assert payload["decision"] == "AUTHOR_APPROVAL_REQUIRED"
    assert payload["technical_gates"]["author_technical_approval_recorded"] is False


def test_compact_input_receipt_is_self_hashing_and_confirmation_unopened() -> None:
    inputs = json.loads(DESIGN_MODULE.INPUTS.read_text(encoding="utf-8"))
    assert inputs["content_hash"] == DESIGN_MODULE.content_hash(inputs)
    assert inputs["governed_values"]["confirmation_corpus_opened"] is False
    assert inputs["governed_values"]["confirmation_documents_acquired"] == 0
    assert inputs["governed_values"]["confirmation_labels_completed"] == 0
    assert inputs["governed_values"]["forbidden_market_columns"] == []


@pytest.mark.workspace_evidence
def test_checked_in_input_receipt_matches_raw_workspace_sources() -> None:
    assert json.loads(INPUT_MODULE.OUTPUT.read_text(encoding="utf-8")) == INPUT_MODULE.build()


@pytest.mark.workspace_evidence
def test_checked_in_design_matches_sources() -> None:
    assert json.loads(DESIGN_MODULE.OUTPUT.read_text(encoding="utf-8")) == DESIGN_MODULE.build()
