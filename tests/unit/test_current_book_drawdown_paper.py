"""The drawdown paper is rendered from the study result, so its prose cannot outlive the book."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _renderer() -> Any:
    path = ROOT / "scripts/render_current_book_drawdown_paper.py"
    spec = importlib.util.spec_from_file_location("render_current_book_drawdown_paper_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arm(expected: float, median: float, p95: float) -> dict[str, float]:
    return {
        "expected_max_drawdown": expected,
        "median_max_drawdown": median,
        "p95_max_drawdown": p95,
        "max_drawdown_stderr": 0.0003,
    }


def _result() -> dict[str, Any]:
    third = 1 / 3
    return {
        "author": "Arhan Canli",
        "status": (
            "CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_HISTORICAL_TAIL_COVERAGE_INCOMPLETE"
        ),
        "configuration": {
            "sleeves": ["alphavintage_live", "k30_dn_63", "managed_futures"],
            "weights": {"alphavintage_live": third, "k30_dn_63": third, "managed_futures": third},
            "strategic_tilt_pct": 0.1,
            "strategic_tilt_mix": {"BTC": 0.5, "SPY": 0.5},
            "aggregation": {
                "book_level_drawdown_ladder": {
                    "activated_on": "2026-09-15",
                    "dd_half_frac": 0.05,
                    "dd_flat_frac": 0.1,
                }
            },
        },
        "calibration": {
            "calendar_days": 1061,
            "start": "2023-07-07",
            "end": "2026-06-01",
            "component_order": [
                "alphavintage_live",
                "k30_dn_63",
                "managed_futures",
                "strategic_overlay",
            ],
            "exact_component_reconstruction_max_abs_error": 1.7e-18,
            "observed_book_annualized_volatility": 0.0511,
            "observed_book_max_drawdown": 0.0463,
            "observed_book_sharpe_simulation_not_forward_evidence": 1.1746,
        },
        "design": {
            "paths_per_model": 10000,
            "bootstrap_primary_block_days": 63,
            "bootstrap_sensitivity_block_days": [21, 63, 126],
            "regime_stress_correlation": 0.5,
            "regime_stress_share": 0.12,
            "regime_mean_stress_run_days": 40.0,
        },
        "models": {
            "circular_moving_block_bootstrap": {
                "21": _arm(0.0845, 0.0785, 0.1489),
                "63": _arm(0.0879, 0.0819, 0.1547),
                "126": _arm(0.0862, 0.0810, 0.1436),
            },
            "correlation_regime": _arm(0.0899, 0.0835, 0.1586),
        },
        "objective": {
            "conservative_modeled_expected_max_drawdown": 0.0899,
            "conservative_modeled_expected_within_target": True,
            "conservative_modeled_p95_max_drawdown": 0.1586,
            "conservative_modeled_p95_within_target": False,
            "expected_max_drawdown_target": 0.11,
        },
        "source_bindings": {
            name: {} for name in ("protocol", "book_implementation", "sleeve_equity_inputs")
        },
        "failed_establishment_dimensions": [
            "COMMON_WINDOW_BEGINS_AFTER_COVID_AND_2022",
            "CONSTITUENT_INSTRUMENT_AND_LADDER_STATE_NOT_REPLAYED",
        ],
    }


def test_the_paper_states_the_composition_and_figures_of_the_result() -> None:
    paper = _renderer().render(_result())
    assert (
        "three constituent sleeves (AlphaMax, AlphaTrend and AlphaVintage) "
        "at equal weights of one third each" in paper
    )
    assert "four constituent" not in paper and "AlphaForge" not in paper
    assert "**8.99%**" in paper and "**15.86%**" in paper
    assert "1.17 Sharpe" in paper and "5.11% annualized volatility" in paper
    assert "active since 2026-09-15" in paper and "do not replay the ladder's state" in paper
    assert (
        "| p95 | 15.47% |" in paper and "the 126-day arm gives 8.62% expected / 14.36% p95" in paper
    )
    assert "The expected result is therefore encouraging; the tail result is not." in paper


def test_a_changed_book_changes_the_paper() -> None:
    renderer = _renderer()
    four = _result()
    quarter = 0.25
    four["configuration"]["sleeves"].append("crypto_carry_wk")
    four["configuration"]["weights"] = dict.fromkeys(four["configuration"]["sleeves"], quarter)
    paper = renderer.render(four)
    assert (
        "four constituent sleeves (AlphaForge, AlphaMax, AlphaTrend and AlphaVintage) "
        "at equal weights of one quarter each" in paper
    )


def test_unknown_sleeves_and_inconsistent_objectives_are_refused() -> None:
    renderer = _renderer()
    unknown = _result()
    unknown["configuration"]["sleeves"].append("mystery_sleeve")
    with pytest.raises(ValueError, match="no public name"):
        renderer.render(unknown)
    inconsistent = copy.deepcopy(_result())
    inconsistent["objective"]["conservative_modeled_expected_max_drawdown"] = 0.05
    with pytest.raises(ValueError, match="larger of the two model expectations"):
        renderer.render(inconsistent)


@pytest.mark.workspace_evidence
def test_the_committed_paper_is_the_render_of_the_current_study() -> None:
    renderer = _renderer()
    if not renderer.RESULT.is_file():
        pytest.skip("no current drawdown study result in this workspace")
    rendered = renderer.render(json.loads(renderer.RESULT.read_text()))
    assert renderer.PAPER.read_text() == rendered, (
        "run: uv run python scripts/render_current_book_drawdown_paper.py"
    )
