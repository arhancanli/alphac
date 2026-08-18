"""Contract tests for the deterministic execution-model benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def benchmark_module():
    path = REPO / "scripts" / "benchmark_execution_models.py"
    spec = importlib.util.spec_from_file_location("benchmark_execution_models_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixed_workload_has_expected_full_and_capped_checksums(benchmark_module) -> None:
    module = benchmark_module
    workload = module.build_workload()
    cost_model = module.TransactionCostModel()
    full = module.execute_workload(module.NextOpenFill(cost_model), workload, 2)
    capped = module.execute_workload(
        module.ParticipationCappedFill(cost_model, max_bar_participation=0.10), workload, 2
    )

    assert full == pytest.approx(2 * (100.0 + 100.065 + 5.00325))
    assert capped == pytest.approx(2 * (50.0 + 100.05914213562373 + 2.5014785533905934))


def test_report_schema_and_trial_guardrails(benchmark_module) -> None:
    report = benchmark_module.build_report(calls=3, repeats=2, warmup=1)

    assert report["schema"] == "alphaforge.execution-model-benchmark.v1"
    assert report["classification"] == "local engineering microbenchmark; not return evidence"
    assert report["workload"]["market_data_opened"] is False
    assert report["workload"]["hypotheses_spent"] == 0
    assert [case["name"] for case in report["cases"]] == [
        "next_open_full_fill",
        "participation_capped_partial_fill",
    ]
    assert all(len(case["elapsed_ns_samples"]) == 2 for case in report["cases"])
    assert all(len(value) == 64 for value in report["source_sha256"].values())


@pytest.mark.parametrize("calls", [0, -1])
def test_execute_workload_rejects_nonpositive_calls(benchmark_module, calls: int) -> None:
    module = benchmark_module
    with pytest.raises(ValueError, match="calls must be > 0"):
        module.execute_workload(
            module.NextOpenFill(module.TransactionCostModel()), module.build_workload(), calls
        )
