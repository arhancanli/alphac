"""Prospective statistics and frozen-evidence checks for the Active Ownership label gate."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "active_ownership_human_gate_audit", ROOT / "scripts/audit_active_ownership_human_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_audit = MODULE.build_audit
exact_one_sided_lower_bound = MODULE.exact_one_sided_lower_bound
minimum_perfect_trials = MODULE.minimum_perfect_trials


def test_exact_lower_bound_matches_closed_form_for_all_successes() -> None:
    observed = exact_one_sided_lower_bound(8, 8)
    assert observed == pytest.approx(0.05 ** (1 / 8), abs=1e-12)


def test_minimum_perfect_denominators_are_exactly_reachable() -> None:
    for target, expected in ((0.95, 59), (0.80, 14), (0.90, 29)):
        assert minimum_perfect_trials(target) == expected
        assert exact_one_sided_lower_bound(expected, expected) >= target
        assert exact_one_sided_lower_bound(expected - 1, expected - 1) < target


def test_invalid_exact_interval_inputs_fail_closed() -> None:
    with pytest.raises(ValueError):
        exact_one_sided_lower_bound(2, 1)
    with pytest.raises(ValueError):
        exact_one_sided_lower_bound(0, 0)
    with pytest.raises(ValueError):
        minimum_perfect_trials(math.inf)


@pytest.mark.workspace_evidence
def test_current_frozen_gate_audit_is_prospective_and_honest() -> None:
    payload = build_audit()
    assert payload["governance"] == {
        "labels_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "existing_point_thresholds_changed": False,
        "audit_may_rescue_known_outcome": False,
    }
    assert payload["frozen_design"]["rows"] == 48
    assert payload["frozen_design"]["machine_predicted_positive"] == 8
    assert payload["point_gate_reachability"]["precision"]["maximum_false_positives"] == 0
    assert (
        payload["statistical_establishment_audit"]["best_case_precision"]["establishes_threshold"]
        is False
    )
    assert payload["decision"].startswith("KEEP_FROZEN_48_ROW_POINT_GATE")
    assert payload["content_hash"].startswith("sha256:")
