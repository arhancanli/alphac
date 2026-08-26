from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analyze_admission_gate_power.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("admission_gate_power_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_is_deterministic_and_reads_no_candidate_returns() -> None:
    module = _module()
    first = module.build()
    second = module.build()

    assert first == second
    assert first["content_hash"] == module._content_hash(first)
    assert first["trial_accounting"]["hypothesis_identities_consumed"] == 0
    assert first["trial_accounting"]["candidate_return_artifacts_read"] == 0
    bound_paths = {item["path"] for item in first["source_bindings"].values()}
    assert not any("walkforward" in path or "candidate" in path for path in bound_paths)


def test_correlation_path_arithmetic_is_independently_reproduced() -> None:
    report = _module().build()
    path = report["correlation_path"]
    current_pairs = math.comb(path["current_sleeves"], 2)
    current_sum = current_pairs * path["current_average_pairwise_correlation"]

    assert path["current_pair_sum"] == pytest.approx(current_sum)
    assert path[
        "first_candidate_average_to_existing_required_for_immediate_global_zero"
    ] == pytest.approx(-current_sum / path["current_sleeves"])
    target_pairs = math.comb(path["target_sleeves"], 2)
    new_pairs = target_pairs - current_pairs
    expected_new_average = (
        path["target_average_pairwise_correlation"] * target_pairs - current_sum
    ) / new_pairs
    assert path["average_across_all_new_pairs_required_for_objective"] == pytest.approx(
        expected_new_average
    )


def test_search_budget_probability_is_exact_binomial_planning_arithmetic() -> None:
    module = _module()
    report = module.build()["search_power"]
    probability = report["historical_planning_hit_rate"]

    for trials, key in (
        (
            report["current_remaining_identities"],
            "probability_at_least_ten_at_current_remaining_budget",
        ),
        (
            report["prospective_remaining_identities"],
            "probability_at_least_ten_at_prospective_remaining_budget",
        ),
    ):
        expected = sum(
            math.comb(trials, count)
            * probability**count
            * (1.0 - probability) ** (trials - count)
            for count in range(10, trials + 1)
        )
        assert report[key] == pytest.approx(expected)


def test_published_artifact_matches_current_bound_sources() -> None:
    module = _module()
    published = json.loads(module.OUTPUT.read_text())

    assert published == module.build()
    for binding in published["source_bindings"].values():
        path = ROOT / binding["path"]
        assert module._sha256(path) == binding["sha256"]
