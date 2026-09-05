from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType

from test_sleeve_admission import passing_evidence

from alphaforge.validation.sleeve_admission import (
    evaluate_sleeve_evidence,
    load_admission_contract,
)

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "build_admission_contract_v7.py"
PROPOSAL = ROOT / "config" / "sleeve_admission_contract_v7_proposed.json"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("admission_v7_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_proposal_is_exact_builder_output_and_not_in_force() -> None:
    built = _builder().build()
    loaded = load_admission_contract(PROPOSAL)

    assert loaded == built
    assert loaded["status"] == "PROPOSED_NOT_IN_FORCE"
    assert loaded["prospective_scope"]["effective"] is False
    assert loaded["prospective_scope"]["known_candidates_may_not_be_regraded"] is True
    assert loaded["evidence_checks_per_candidate"] == 86


def test_v7_replaces_two_final_level_gates_with_incremental_decisions() -> None:
    contract = load_admission_contract(PROPOSAL)
    thresholds = contract["thresholds"]

    assert "average_pairwise_correlation_max" not in thresholds
    assert "book_deflated_sharpe_min" not in thresholds
    assert thresholds["candidate_average_correlation_to_existing_book_max"] == 0.0
    assert thresholds["book_average_pairwise_correlation_delta_max_exclusive"] == 0.0
    assert thresholds["book_deflated_sharpe_must_be_measured"] is True


def test_both_incremental_correlation_gates_can_fail() -> None:
    contract = load_admission_contract(PROPOSAL)
    evidence = passing_evidence()
    assert evaluate_sleeve_evidence(evidence, contract).eligible

    candidate_worsens = copy.deepcopy(evidence)
    candidate_worsens["diversification"][
        "candidate_average_correlation_to_existing_book"
    ] = 0.001
    failures = evaluate_sleeve_evidence(candidate_worsens, contract).failures
    assert any("candidate_average_correlation_to_existing_book" in item for item in failures)

    book_does_not_improve = copy.deepcopy(evidence)
    book_does_not_improve["diversification"]["book_average_pairwise_correlation_delta"] = 0.0
    failures = evaluate_sleeve_evidence(book_does_not_improve, contract).failures
    assert any("book_average_pairwise_correlation_delta" in item for item in failures)


def test_book_dsr_remains_mandatory_but_is_not_an_incremental_cutoff() -> None:
    contract = load_admission_contract(PROPOSAL)
    evidence = passing_evidence()
    evidence["statistics"]["book_deflated_sharpe"] = 0.10
    assert evaluate_sleeve_evidence(evidence, contract).eligible

    del evidence["statistics"]["book_deflated_sharpe"]
    failures = evaluate_sleeve_evidence(evidence, contract).failures
    assert "missing_numeric:statistics.book_deflated_sharpe" in failures
