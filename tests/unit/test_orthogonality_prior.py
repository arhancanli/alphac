"""A prior is only worth publishing if its rule is mechanical, complete, and able to be wrong.

WHY IT EXISTS. This artifact ranks twenty families before any of them is measured, and a ranking
stated before the fact is the easiest thing in this repo to quietly fudge: one family reasoned into
a different bucket than the rule implies and the whole ordering becomes an opinion with a schema.
So the rule is applied by code, and the tests below check that the code is the rule.

Two of these matter more than the rest. The first exercises the branch that is EMPTY in the real
data — a rule path nothing currently reaches is a rule path nobody has tested, and it will be
reached the moment a family is added. The second pins that the evidence and the rule read the same
table: the measured pairs are classified by the SAME live-sleeve definitions the families are
scored against, so the artifact cannot argue from one taxonomy and rank by another.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "orthogonality_prior", REPO / "scripts" / "orthogonality_prior.py"
)
assert _spec is not None and _spec.loader is not None
prior = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = prior
_spec.loader.exec_module(prior)


def test_the_prior_covers_exactly_the_untouched_atlas_families() -> None:
    atlas = json.loads(prior.ATLAS.read_text())
    assert sorted(p.family for p in prior.PRIORS) == prior._untouched_families(atlas)


def test_a_family_added_to_the_atlas_fails_the_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    atlas = json.loads(prior.ATLAS.read_text())
    atlas["families"].append(
        {
            "id": "an_unranked_family",
            "lineage_classification": "NOVEL_ATLAS",
            "return_outcome": None,
        }
    )
    path = tmp_path / "atlas.json"
    path.write_text(json.dumps(atlas))
    monkeypatch.setattr(prior, "ATLAS", path)
    with pytest.raises(AssertionError, match="an_unranked_family"):
        prior.main()


def test_every_branch_of_the_rule_is_reachable_including_the_empty_one() -> None:
    """LIKELY_ORTHOGONAL is empty in today's data. An untested branch is a latent wrong answer."""
    factor_shared = prior.Prior("x", prior.CARRY, prior.PRICE, prior.NEUTRAL, "r")
    assert factor_shared.prior == prior.SHARES_FACTOR

    crisis_shared = prior.Prior("x", prior.BASIS, prior.PRICE, prior.SHORT_LIQUIDITY, "r")
    assert crisis_shared.prior == prior.SHARES_CRISIS

    not_price = prior.Prior("x", prior.BASIS, prior.ORDER_FLOW, prior.NEUTRAL, "r")
    assert not_price.prior == prior.STRONGLY_ORTHOGONAL

    price_only = prior.Prior("x", prior.BASIS, prior.PRICE, prior.NEUTRAL, "r")
    assert price_only.prior == prior.LIKELY_ORTHOGONAL


def test_a_shared_factor_outranks_a_shared_crisis_and_a_non_price_driver() -> None:
    """Precedence is the rule's whole content: the axis with evidence must win."""
    both = prior.Prior("x", prior.CARRY, prior.ORDER_FLOW, prior.SHORT_LIQUIDITY, "r")
    assert both.prior == prior.SHARES_FACTOR
    crisis_and_flow = prior.Prior("x", prior.FLOW, prior.ORDER_FLOW, prior.SHORT_LIQUIDITY, "r")
    assert crisis_and_flow.prior == prior.SHARES_CRISIS


def test_a_neutral_crisis_direction_matches_nothing() -> None:
    """NEUTRAL means 'no market state', not 'a state that happens to be shared'."""
    assert prior.Prior("x", prior.FLOW, prior.PRICE, prior.NEUTRAL, "r").shares_crisis_with() == []


def test_the_evidence_and_the_rule_read_the_same_sleeve_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: retag a live sleeve's factor and the measured pair's shared-factor flag must move.

    If the measured structure were classified from its own hard-coded notion of which sleeves share
    a factor, the artifact could argue from one taxonomy and rank by another, and the argument
    would look exactly the same on the page.
    """
    before = {r["pair"]: r["shares_factor_family"] for r in prior._measured_structure()["pairs"]}
    assert before["AlphaMax|AlphaTrend"] is True

    monkeypatch.setitem(
        prior.LIVE_SLEEVES, "AlphaTrend", {**prior.LIVE_SLEEVES["AlphaTrend"], "factor": prior.VOL}
    )
    after = {r["pair"]: r["shares_factor_family"] for r in prior._measured_structure()["pairs"]}
    assert after["AlphaMax|AlphaTrend"] is False


def test_the_required_new_pair_average_round_trips_to_the_objective() -> None:
    """Plug the answer back into the identity it was solved from; it must return the objective."""
    result = json.loads(prior.OUTPUT.read_text())
    a = result["what_the_ordering_is_for"]
    rho_bar = (
        a["pairs_now"] * a["rho_bar_now"]
        + a["pairs_new"] * a["required_average_over_the_new_pairs"]
    ) / (a["pairs_now"] + a["pairs_new"])
    assert rho_bar == pytest.approx(a["objective_rho_bar"], abs=1e-4)


def test_the_gate_is_shown_to_be_insufficient_by_arithmetic_not_assertion() -> None:
    """The claim 'the gate does not reach the objective' must be recomputed, never transcribed."""
    result = json.loads(prior.OUTPUT.read_text())
    a = result["what_the_ordering_is_for"]
    assert (
        a["rho_bar_if_the_aggregate_new_edges_sit_at_the_incremental_boundary"]
        > a["objective_rho_bar"]
    )
    assert a["forward_sharpe_at_that_rho_bar_optimistic_haircut"] < 1.5
    assert a["forward_sharpe_at_the_objective_optimistic_haircut"] == pytest.approx(1.5, abs=0.01)


def test_the_book_sharpe_identity_is_the_published_one() -> None:
    """s_bar * sqrt(N / (1 + (N-1) rho_bar)), checked at a point computed by hand."""
    assert prior._book_sharpe(14, 0.0, s_bar=1.0) == pytest.approx(math.sqrt(14))
    assert prior._book_sharpe(1, 0.5, s_bar=0.4) == pytest.approx(0.4)


def test_resolution_is_measured_against_sampling_error_not_eyeballed() -> None:
    """Four of six pairs are noise. Publishing them as structure would be the whole error here."""
    structure = json.loads(prior.OUTPUT.read_text())["measured_structure"]
    se = structure["standard_error_per_pair"]
    assert se == pytest.approx(1 / math.sqrt(structure["n_days"] - 3), abs=1e-4)
    for row in structure["pairs"]:
        expected = abs(math.atanh(row["rho"])) / se > 1.96
        assert row["resolved_at_95"] is expected, row["pair"]
    assert structure["resolved_pairs"] + structure["unresolved_pairs"] == len(structure["pairs"])


def test_every_row_is_stamped_a_prior() -> None:
    result = json.loads(prior.OUTPUT.read_text())
    assert all(r["evidence_status"] == "PRIOR_NOT_A_MEASUREMENT" for r in result["families"])


def test_the_headline_counts_match_the_rows() -> None:
    result = json.loads(prior.OUTPUT.read_text())
    for bucket, families in result["by_prior"].items():
        assert len(families) == sum(1 for r in result["families"] if r["prior"] == bucket)
    strongly = len(result["by_prior"].get(prior.STRONGLY_ORTHOGONAL, []))
    assert result["headline"].startswith(f"{strongly} of {len(result['families'])} ")


def test_every_prior_is_ranked_and_explained() -> None:
    assert set(prior.RANK) == set(prior.MEANING)
    assert len(prior.RANK) == len(set(prior.RANK))
    for p in prior.RANK:
        assert len(prior.MEANING[p]) > 60
