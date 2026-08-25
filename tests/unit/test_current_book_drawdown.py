from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts/analyze_current_book_drawdown.py"
    spec = importlib.util.spec_from_file_location("current_book_drawdown_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analyzer():
    return _module()


def test_circular_bootstrap_is_deterministic_and_ordered(analyzer) -> None:
    source = np.array([0.01, -0.02, 0.005, -0.01, 0.015, -0.003])
    left = analyzer.circular_block_bootstrap(
        source, paths=200, horizon_days=30, block_days=3, seed=7
    )
    right = analyzer.circular_block_bootstrap(
        source, paths=200, horizon_days=30, block_days=3, seed=7
    )
    assert left == right
    assert 0.0 <= left["median_max_drawdown"] <= left["p95_max_drawdown"] < 1.0
    assert left["max_drawdown_stderr"] > 0.0


def test_regime_model_is_deterministic_and_exercises_stress(analyzer) -> None:
    rng = np.random.default_rng(4)
    contributions = rng.normal(0.0, [0.002, 0.003, 0.001], size=(400, 3))
    kwargs = {
        "paths": 200,
        "horizon_days": 60,
        "stress_correlation": 0.5,
        "stress_share": 0.12,
        "mean_stress_run_days": 10.0,
        "seed": 8,
    }
    left = analyzer.correlation_regime_drawdown(contributions, **kwargs)
    right = analyzer.correlation_regime_drawdown(contributions, **kwargs)
    assert left == right
    assert left[0]["p95_max_drawdown"] >= left[0]["expected_max_drawdown"]
    assert 0.0 < left[1]["simulated_stress_day_fraction"] < 1.0


def test_current_artifact_is_integral_and_fail_closed(analyzer) -> None:
    payload = json.loads(analyzer.OUTPUT.read_text())
    assert payload["content_hash"] == analyzer._content_hash(payload)
    assert payload["trial_accounting"]["hypothesis_identities_spent"] == 0
    assert payload["configuration"]["aggregation"]["book_level_vol_target_ann"] is None
    assert payload["calibration"]["sample_mean_removed_before_modeling"] is True
    assert payload["calibration"]["exact_component_reconstruction_max_abs_error"] <= 1e-15
    assert payload["objective"]["conservative_modeled_expected_max_drawdown"] < 0.11
    assert payload["objective"]["conservative_modeled_p95_max_drawdown"] > 0.11
    assert payload["objective"]["conservative_modeled_expected_within_target"] is True
    assert payload["objective"]["conservative_modeled_p95_within_target"] is False
    assert payload["objective"]["live_expected_max_drawdown_established"] is False
    assert len(payload["failed_establishment_dimensions"]) >= 5


def test_live_aggregation_drift_fails_before_modeling(analyzer, monkeypatch) -> None:
    original = json.loads(analyzer.LIVE_CONTRACT.read_text())
    mutated = copy.deepcopy(original)
    mutated["declared_surface"]["book_aggregation_settings"][
        "book_level_vol_target_ann"
    ] = 0.10

    class ContractPath:
        def read_text(self, **_kwargs):
            return json.dumps(mutated)

    monkeypatch.setattr(analyzer, "LIVE_CONTRACT", ContractPath())
    with pytest.raises(ValueError, match="declared aggregation"):
        analyzer.build()
