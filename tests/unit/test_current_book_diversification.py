from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/analyze_current_book_diversification.py"
SPEC = importlib.util.spec_from_file_location("current_book_diversification_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_circular_block_correlation_bootstrap_is_deterministic() -> None:
    rng = np.random.default_rng(7)
    source = rng.multivariate_normal(
        np.zeros(4),
        np.asarray(
            [
                [1.0, 0.1, 0.0, -0.1],
                [0.1, 1.0, 0.2, 0.0],
                [0.0, 0.2, 1.0, 0.05],
                [-0.1, 0.0, 0.05, 1.0],
            ]
        ),
        size=300,
    )
    first = MODULE.circular_block_correlation_bootstrap(
        source, samples=250, block_days=21, seed=11
    )
    second = MODULE.circular_block_correlation_bootstrap(
        source, samples=250, block_days=21, seed=11
    )
    assert first == second
    assert len(first["pairs"]) == 6
    assert first["average_pairwise_correlation"]["upper_95"] > -1.0
    assert first["maximum_pairwise_upper_95"] < 1.0


@pytest.mark.workspace_evidence
def test_current_book_diversification_build_is_exact_and_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "BOOTSTRAP_SAMPLES", 200)
    document = MODULE.build()
    assert document["content_hash"] == MODULE._content_hash(document)
    assert document["configuration"]["sleeves"] == [
        "alphavintage_live",
        "crypto_carry_wk",
        "k30_dn_63",
        "managed_futures",
    ]
    assert document["observed"]["exact_component_reconstruction_max_abs_error"] == 0.0
    assert document["observed"]["average_pairwise_correlation"] > 0.0
    comparison = document["governing_comparison"]
    assert comparison["active_v7_has_no_global_average_correlation_point_gate"] is True
    assert comparison["historical_v6_global_average_correlation_point_check"] is False
    assert comparison["meets_active_correlation_objective"] is False
    assert document["governing_comparison"]["live_forward_diversification_established"] is False
    assert document["trial_accounting"]["hypothesis_identities_spent"] == 0
    assert document["trial_accounting"]["return_data_were_known_before_protocol"] is True


def test_build_rejects_mutated_drawdown_binding(tmp_path: Path, monkeypatch) -> None:
    source = json.loads(MODULE.DRAWDOWN_RESULT.read_text())
    source["configuration"]["sleeves"] = list(reversed(source["configuration"]["sleeves"]))
    path = tmp_path / "drawdown.json"
    path.write_text(json.dumps(source))
    monkeypatch.setattr(MODULE, "DRAWDOWN_RESULT", path)
    monkeypatch.setattr(MODULE, "BOOTSTRAP_SAMPLES", 10)
    with pytest.raises(ValueError, match="source binding is invalid"):
        MODULE.build()


@pytest.mark.parametrize(
    "source",
    [np.ones((20, 1)), np.full((20, 2), np.nan), np.ones((5, 2))],
)
def test_bootstrap_rejects_invalid_inputs(source: np.ndarray) -> None:
    with pytest.raises(ValueError):
        MODULE.circular_block_correlation_bootstrap(
            source, samples=10, block_days=10, seed=1
        )
