"""The owner's goals are the one source every published objective derives from.

WHY. On 2026-09-14 the owner corrected the operator: the forward Sharpe target is 2, not the 1.5
the admission contract wrote down in August. Two files had been claiming to state "the objective"
(the sealed admission contract and the forward-evidence contract) and a third (the discovery
config) carried a typed copy. One governing file, projected by code, is the only arrangement in
which the number the site shows, the number the evaluator tests against, and the number the owner
set cannot be three different numbers. These tests pin that arrangement:

- the goals file says what the owner said, in the owner's document's own words;
- the forward-evidence contract evaluates against exactly that target and carries its history;
- the sealed admission contract has not moved (its bytes are pinned) and its objective is published
  as dated history inside the governing objective, never as a second target;
- the frontier arithmetic is the sealed identity at the owner's N and target, and round-trips.

Reads no return data, spends no hypothesis, establishes nothing.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from alphaforge.research import owner_goals as og

REPO = Path(__file__).resolve().parents[2]
GOALS_DOC = REPO / "docs" / "design" / "ALPHAC_OWNER_GOALS_2026-09-12.md"
FORWARD_CONTRACT = REPO / "config" / "forward_evidence_contract.json"
DISCOVERY = REPO / "config" / "sleeve_discovery.json"
REGISTRY_POINTERS = (
    "honest_forward_sharpe_target",
    "portfolio_max_drawdown_target",
    "target_total_sleeves",
    "average_pairwise_correlation_objective",
)


@pytest.fixture(scope="module")
def goals() -> dict[str, Any]:
    return og.load_owner_goals()


@pytest.fixture(scope="module")
def forward_contract() -> dict[str, Any]:
    return json.loads(FORWARD_CONTRACT.read_text(encoding="utf-8"))


def test_the_goals_are_the_owners_words_from_the_owners_document(goals: dict[str, Any]) -> None:
    document = GOALS_DOC.read_text(encoding="utf-8")
    # The owner's words sit in the document as a wrapped blockquote; compare on collapsed text.
    flattened = re.sub(r"\s+", " ", document.replace("\n> ", " "))
    assert goals["source_document"] == str(GOALS_DOC.relative_to(REPO))
    for outcome in goals["goals"].values():
        assert outcome["quoted_outcome"] in document, outcome["quoted_outcome"]
    assert goals["goals"]["combined_forward_sharpe"]["target"] == 2.0
    assert goals["goals"]["combined_forward_sharpe"]["comparison"] == "ABOVE"
    assert goals["goals"]["combined_max_drawdown"]["bound"] == 0.10
    assert goals["goals"]["combined_max_drawdown"]["comparison"] == "AT_MOST"
    assert goals["goals"]["qualified_economically_distinct_sleeves"]["minimum"] == 14
    assert "2 sharpe ratio 14 plus sleeves 10 percent max dd" in goals["decision"]["words"]
    assert goals["decision"]["words"] in flattened
    for key in ("open_glassbox", "developer_platform", "real_life_costs_on_paper_live"):
        assert goals["program"][key]["quoted"] in goals["decision"]["words"], key
    restated = goals["supersedes"]["owner_goals_document_2026_09_12"]["restated_outcomes"]
    assert restated == {
        "combined_forward_sharpe_above": 2.0,
        "combined_max_drawdown_at_most": 0.10,
        "qualified_sleeves_at_least": 14,
    }
    assert goals["status"] == "IN_FORCE_NOT_ACHIEVED"
    assert goals["recorded_on"] <= goals["in_force_from"]


def test_the_forward_evidence_contract_evaluates_against_the_owners_target(
    goals: dict[str, Any], forward_contract: dict[str, Any]
) -> None:
    target = goals["goals"]["combined_forward_sharpe"]["target"]
    assert forward_contract["forward_sharpe_target"] == target
    assert forward_contract["forward_sharpe_target_source"] == "config/owner_goals.json"
    history = forward_contract["forward_sharpe_target_history"]
    assert history[-1]["target"] == target
    assert history[-1]["in_force_from"] == goals["in_force_from"]
    supersession = goals["supersedes"]["forward_evidence_contract_target"]
    assert history[-2]["target"] == supersession["previous"]
    assert history[-1]["target"] == supersession["current"]
    assert history[-2]["superseded_on"] == history[-1]["in_force_from"]
    assert all(a["in_force_from"] < b["in_force_from"] for a, b in itertools.pairwise(history))
    assert "target_change" in forward_contract["rules"]
    assert "1.5" not in forward_contract["rules"]["target_observed"]
    assert "1.5" not in forward_contract["rules"]["target_statistically_established"]


def test_the_forward_evidence_contract_carries_the_realized_bound_beside_the_expected_target(
    goals: dict[str, Any], forward_contract: dict[str, Any]
) -> None:
    bound = goals["goals"]["combined_max_drawdown"]["bound"]
    assert forward_contract["realized_max_drawdown_bound"] == bound
    assert forward_contract["realized_max_drawdown_bound_statistic"] == "REALIZED_MAXIMUM_DRAWDOWN"
    # The modeled objective is the sealed contract's and is NOT the owner's bound.
    sealed = og.sealed_admission_objective(goals)
    assert (
        forward_contract["expected_max_drawdown_target"]
        == (sealed["portfolio_max_drawdown_target"])
    )
    assert forward_contract["expected_max_drawdown_target"] != bound
    assert "realized_drawdown_bound" in forward_contract["rules"]
    # The declared brake goes flat ABOVE the bound; the goals file must say so, not hide it.
    control = json.loads(
        (REPO / "config" / "drawdown_control_contract.json").read_text(encoding="utf-8")
    )
    if float(control["ladder"]["dd_flat_frac"]) > bound:
        assert (
            "INCONSISTENT_WITH_BOUND" in goals["goals"]["combined_max_drawdown"]["mechanism_status"]
        )


def test_the_sealed_admission_contract_has_not_moved_and_is_history_not_a_target(
    goals: dict[str, Any],
) -> None:
    pin = goals["supersedes"]["sleeve_admission_contract_objective"]
    raw = (REPO / pin["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
    sealed = og.sealed_admission_objective(goals)
    assert sealed["honest_forward_sharpe_target"] == 1.5
    assert sealed["target_total_sleeves"] == 14
    assert sealed["targets_are_admission_evidence"] is False
    objective = og.governing_objective(goals)
    inner = objective["superseded_admission_contract_objective"]
    assert inner["superseded_on"] == goals["in_force_from"]
    assert inner["sealed_sha256"] == pin["sha256"]
    assert {key: inner[key] for key in sealed} == sealed
    assert objective["honest_forward_sharpe_target"] != inner["honest_forward_sharpe_target"]


def test_a_moved_seal_fails_closed(goals: dict[str, Any], tmp_path: Path) -> None:
    contract = json.loads(og.ADMISSION_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["objective"]["honest_forward_sharpe_target"] = 2.0  # "helpfully" edited in place
    moved = tmp_path / "sleeve_admission_contract.json"
    moved.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="moved under the owner-goals pin"):
        og.governing_objective(goals, moved)


def test_the_governing_objective_keeps_every_registry_pointer_and_derives_the_rest(
    goals: dict[str, Any],
) -> None:
    objective = og.governing_objective(goals, current_sleeves=4)
    for key in REGISTRY_POINTERS:
        assert key in objective, key
    assert objective["honest_forward_sharpe_target"] == 2.0
    assert objective["portfolio_max_drawdown_target"] == 0.10
    assert objective["portfolio_max_drawdown_statistic"] == "REALIZED_MAXIMUM_DRAWDOWN_BOUND"
    assert objective["expected_max_drawdown_objective"] == 0.11
    assert objective["expected_max_drawdown_objective_statistic"] == "expected_maximum_drawdown"
    assert objective["target_total_sleeves"] == objective["target_sleeve_count"] == 14
    assert objective["minimum_new_sleeves"] == 10
    assert objective["current_sleeves"] == 4
    assert objective["targets_are_admission_evidence"] is False
    assert objective["source"] == "config/owner_goals.json"
    assert "minimum_new_sleeves" not in og.governing_objective(goals)
    band = objective["portfolio_sharpe_target"]
    haircut_low = objective["backtest_to_forward_haircut"]["range"][0]
    assert band[0] == pytest.approx(2.0 * haircut_low)
    assert objective["implied_in_sample_target"]["at_1_5x_haircut"] == pytest.approx(3.0)


def test_the_frontier_is_the_sealed_identity_at_the_owners_n_and_round_trips(
    goals: dict[str, Any],
) -> None:
    frontier = og.goal_frontier(goals)
    contract = json.loads(og.ADMISSION_CONTRACT_PATH.read_text(encoding="utf-8"))
    sealed = contract["frontier_arithmetic"]
    assert frontier["identity"] == sealed["identity"]
    n = frontier["target_sleeve_count"]
    assert n == 14
    assert frontier["psd_floor_at_target_n"] == pytest.approx(-1.0 / (n - 1))
    quality = frontier["quality_precondition_at_the_gate"]
    assert (
        quality["s_bar_measured_four_curve_basis"]
        == (sealed["quality_precondition_at_the_gate"]["s_bar_measured_four_curve_basis"])
    )
    gate = frontier["incremental_candidate_average_correlation_gate"]
    assert gate == contract["thresholds"]["candidate_average_correlation_to_existing_book_max"]
    low, high = frontier["in_sample_support_band"]
    # Plug each answer back into the identity it was solved from.
    for basis in ("four_curve_basis", "traded_basis"):
        s_bar = quality[f"s_bar_measured_{basis}"]
        rho = frontier["correlation_required_at_measured_quality"][basis][
            f"rho_bar_required_for_{low:g}"
        ]
        assert og.book_sharpe(n, rho, s_bar) == pytest.approx(low)
        rho_high = frontier["correlation_required_at_measured_quality"][basis][
            f"rho_bar_required_for_{high:g}"
        ]
        assert og.book_sharpe(n, rho_high, s_bar) == pytest.approx(high)
    assert og.book_sharpe(n, gate, quality[f"s_bar_required_for_{low:g}"]) == pytest.approx(low)
    assert og.book_sharpe(14, 0.0, 1.0) == pytest.approx(math.sqrt(14))
    # Same N as the sealed frontier, so the sealed rho for 3.0 in-sample must reappear exactly.
    assert frontier["correlation_required_at_measured_quality"]["four_curve_basis"][
        f"rho_bar_required_for_{low:g}"
    ] == pytest.approx(
        sealed["correlation_required_at_measured_quality"]["four_curve_basis"][
            "rho_bar_required_for_3.0"
        ]
    )
    # The objective correlation published on the site IS the low-end four-curve requirement.
    objective = og.governing_objective(goals)
    assert (
        objective["average_pairwise_correlation_objective"]
        == (
            frontier["correlation_required_at_measured_quality"]["four_curve_basis"][
                f"rho_bar_required_for_{low:g}"
            ]
        )
    )
    assert frontier["incremental_gates_alone_establish_objective_floor"] is False
    assert "unreachable" not in frontier["honest_reading"] or (
        objective["average_pairwise_correlation_objective"] < frontier["psd_floor_at_target_n"]
    )


def test_the_discovery_config_no_longer_types_a_target() -> None:
    objective = json.loads(DISCOVERY.read_text(encoding="utf-8"))["objective"]
    for key in (
        "honest_forward_sharpe_target",
        "portfolio_sharpe_target",
        "portfolio_max_drawdown_target",
        "target_sleeve_count",
        "minimum_new_sleeves",
    ):
        assert key not in objective, f"discovery config types {key}; derive it from owner goals"
    assert "config/owner_goals.json" in objective["source_of_truth"]


def test_a_malformed_goals_file_fails_closed(tmp_path: Path, goals: dict[str, Any]) -> None:
    bad = json.loads(json.dumps(goals))
    bad["goals"]["combined_forward_sharpe"]["comparison"] = "AT_LEAST"
    path = tmp_path / "owner_goals.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="ABOVE"):
        og.load_owner_goals(path)
    bad = json.loads(json.dumps(goals))
    bad["goals"]["combined_max_drawdown"]["bound"] = 11
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="fraction"):
        og.load_owner_goals(path)
    bad = json.loads(json.dumps(goals))
    bad["schema"] = "canli.alphac-owner-goals.v0"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        og.load_owner_goals(path)


@pytest.mark.workspace_evidence
def test_the_published_program_status_carries_the_owners_objective(goals: dict[str, Any]) -> None:
    published = REPO.parent / "meridian" / "public" / "glassbox" / "program_status.json"
    if not published.exists():
        pytest.skip("the publication host is not checked out beside this repository")
    status = json.loads(published.read_text(encoding="utf-8"))
    expected = og.governing_objective(
        goals, current_sleeves=status["achievement"]["current_sleeves"]
    )
    if status["objective"].get("source") != "config/owner_goals.json":
        pytest.xfail("the host has not been republished since the owner goals took force")
    for key in REGISTRY_POINTERS:
        assert status["objective"][key] == expected[key], key
    assert (
        status["achievement"]["forward_sharpe_target"] == expected["honest_forward_sharpe_target"]
    )
    assert status["achievement"]["target_sleeves"] == expected["target_total_sleeves"]
    assert status["governing_goals"]["path"] == "config/owner_goals.json"
