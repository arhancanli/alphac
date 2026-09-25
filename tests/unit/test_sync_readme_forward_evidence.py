from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_readme_forward_evidence.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_readme_forward_evidence_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence(failed_checks: list[str]) -> dict:
    return {
        "generated_at": "2026-08-26T00:00:00+00:00",
        "provenance_gate": {"passes": not failed_checks, "failed_checks": failed_checks},
        "record": {
            "daily_return_observations": 17,
            "first_mark": "2026-08-07",
            "last_mark": "2026-08-26",
            "cumulative_return": -0.02,
        },
        "sharpe_evidence": {
            "target": 2.0,
            "target_history": [
                {"target": 1.5, "in_force_from": "2026-08-21", "superseded_on": "2026-09-14"},
                {"target": 2.0, "in_force_from": "2026-09-14"},
            ],
            "estimate_minimum": 252,
            "establishment_minimum": 756,
            "annualized_point_estimate": None,
            "status": "IMMATURE_RECORD_TOO_SHORT",
        },
        "drawdown_evidence": {
            "realized_live_max_drawdown": 0.024,
            "realized_max_drawdown_bound": 0.10,
            "current_composition_conservative_expected_max_drawdown": 0.09,
            "current_composition_conservative_p95_max_drawdown": 0.16,
        },
        "diversification_evidence": {
            "current_sleeves": 3,
            "target_total_sleeves": 14,
            "average_pairwise_correlation": 0.02,
            "marginal_book_sharpe_research_diagnostics": {
                "k30_dn_63": {},
                "managed_futures": {},
                "alphavintage_live": {},
            },
        },
    }


README_TEMPLATE = """**Evidence snapshot:** 2026-08-25. Later marks follow.

| Paper sleeves | old |
| Forward record | old |
| Forward Sharpe | old |
| Drawdown | old |
| Diversification | old |

No forward Sharpe is established. The 16-return record is too short, and its provenance gate
currently passes.
Historical simulations, modeled risk and broker-derived paper marks remain separately labelled.
"""


def test_sync_names_stale_crypto_cycle_instead_of_claiming_rollout_is_missing() -> None:
    updated = _module().synchronize(
        _evidence(["crypto_position_attribution_covers_last_mark"]), README_TEMPLATE
    )

    assert "crypto attribution does not cover the latest mark" in updated
    assert "latest composite mark is newer than the last attributed crypto cycle" in updated
    assert "until crypto position attribution is deployed" not in updated


def test_sync_reports_a_passing_provenance_gate_directly() -> None:
    updated = _module().synchronize(_evidence([]), README_TEMPLATE)

    assert "provenance currently passes the publication gate" in updated
    assert "its provenance gate currently passes" in updated


def test_sync_derives_the_governing_target_and_the_realized_bound_from_the_evidence() -> None:
    updated = _module().synchronize(_evidence([]), README_TEMPLATE)

    assert "| Paper sleeves | **3 / 14 planned**" in updated
    assert (
        "| Forward Sharpe | **Not reportable** — 252 observations are required for an estimate "
        "and 756 for the project's establishment test; the governing forward target is **2.0** "
        "(owner goal, in force from 2026-09-14) |"
    ) in updated
    assert "against the owner's realized bound of **10%**" in updated


def test_sync_publishes_a_point_estimate_only_once_the_evidence_carries_one() -> None:
    evidence = _evidence([])
    evidence["sharpe_evidence"].update(
        {
            "annualized_point_estimate": 1.234,
            "probability_true_sharpe_exceeds_target": 0.235,
            "status": "ESTIMATE_ELIGIBLE_TARGET_NOT_OBSERVED",
        }
    )
    updated = _module().synchronize(evidence, README_TEMPLATE)

    assert (
        "| Forward Sharpe | Point estimate **1.23** against the governing target **2.0**; "
        "probability the true Sharpe exceeds it **23.5%**; status "
        "ESTIMATE_ELIGIBLE_TARGET_NOT_OBSERVED, not a real-money result |"
    ) in updated
    assert "Not reportable" not in updated


def test_sleeve_names_come_from_the_book_so_a_suspended_sleeve_is_not_named() -> None:
    updated = _module().synchronize(_evidence([]), README_TEMPLATE)

    assert (
        "| Paper sleeves | **3 / 14 planned** — equity momentum, managed-futures trend, "
        "PIT macro surprise |"
    ) in updated
    assert "funding carry" not in updated


def test_an_unreviewed_sleeve_key_or_a_count_mismatch_fails_closed() -> None:
    evidence = _evidence([])
    diversification = evidence["diversification_evidence"]
    diversification["marginal_book_sharpe_research_diagnostics"]["new_sleeve"] = {}
    diversification["current_sleeves"] = 4
    with pytest.raises(RuntimeError, match="no reviewed name"):
        _module().synchronize(evidence, README_TEMPLATE)

    del diversification["marginal_book_sharpe_research_diagnostics"]["new_sleeve"]
    with pytest.raises(RuntimeError, match="names 3 sleeves but reports 4"):
        _module().synchronize(evidence, README_TEMPLATE)
