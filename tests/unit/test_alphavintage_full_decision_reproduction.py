from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/run_alphavintage_full_decision_clean_workspace.py"
LEDGER = ROOT / "scripts/seal_alphavintage_full_decision_attempt_ledger.py"
MANUSCRIPT = ROOT / "docs/research/ALPHAVINTAGE_MACRO_SURPRISE_LINEAGE.md"
RECEIPT = ROOT / "artifacts/publication/alphavintage_full_decision_clean_workspace.json"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_full_decision_receipt_is_bound_and_honest() -> None:
    module = _module(RUNNER, "alphavintage_full_decision_runner")
    receipt = module.validate_published()
    assert receipt["passes"] is True
    assert receipt["receipt_integrity_passes"] is True
    assert all(receipt["exact_decision_checks"].values())
    assert receipt["fresh_result"]["checks"] == {
        "a_clears_bar": True,
        "b_nw_t_ge_1p5": False,
        "c_benefit_is_the_mean": True,
        "d_placebo_dead": True,
    }
    assert receipt["fresh_result"]["verdict"] == "KILLED"
    assert receipt["full_alphavintage_decision_clean_workspace_reproduction_completed"] is True
    assert receipt["full_pipeline_clean_environment_reproduction_completed"] is False
    assert receipt["portable_reviewer_replay_completed"] is False
    assert receipt["independent_human_reproduction_completed"] is False
    assert all(
        item["values_exact"]
        for item in receipt["fresh_vs_sealed_input_comparisons"]["macro"]
    )
    assert all(
        item["dates_exact"] and not item["values_exact"]
        for item in receipt["fresh_vs_sealed_input_comparisons"]["market"]
    )


def test_attempt_ledger_preserves_failure_before_success() -> None:
    module = _module(LEDGER, "alphavintage_full_decision_attempt_ledger")
    ledger = module.build()
    assert ledger["counts"] == {
        "attempts_disclosed": 2,
        "numeric_equivalence_acceptance_passes": 1,
        "all_four_gate_values_stable": 2,
        "verdicts_killed": 2,
    }
    assert ledger["attempts"][0]["numeric_equivalence_acceptance_passes"] is False
    assert ledger["attempts"][1]["numeric_equivalence_acceptance_passes"] is True
    assert ledger["acceptance_tolerance_changed_between_attempts"] is False
    assert ledger["first_failed_attempt_disclosed"] is True
    assert ledger["content_hash"] == module._content_hash(ledger)


def test_persisted_attempt_ledger_matches_recoverable_evidence() -> None:
    module = _module(LEDGER, "alphavintage_full_decision_attempt_ledger_persisted")
    assert json.loads(module.OUTPUT.read_text()) == module.build()


def test_manuscript_replay_differences_are_bound_to_current_receipt() -> None:
    """Prevent unsupported precision claims or a stale replay paragraph from publishing."""
    manuscript = MANUSCRIPT.read_text()
    receipt = json.loads(RECEIPT.read_text(), parse_float=Decimal)
    comparisons = {item["metric"]: item for item in receipt["metric_comparisons"]}

    net_sharpe_delta = format(comparisons["net_sharpe"]["absolute_delta"], "f")
    nw_t_delta = format(comparisons["nw_t"]["absolute_delta"], "f")
    maximum_delta = format(
        max(item["absolute_delta"] for item in receipt["metric_comparisons"]), "f"
    )

    assert net_sharpe_delta in manuscript
    assert nw_t_delta in manuscript
    assert maximum_delta in manuscript
    assert "0.000001735861554830187" not in manuscript
    assert "0.0000040497554956164805" not in manuscript
    assert "0.0000235133439796531" not in manuscript
