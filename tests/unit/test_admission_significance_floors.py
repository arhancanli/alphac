"""The contract's own significance floors must be satisfiable, and the new gates must bite.

Three things are pinned here, all of which were broken or absent in v4:

1. ``load_admission_contract`` refuses a contract whose Sharpe floor, t floor and minimum sample
   cannot all be met at once. v4 declared exactly such a triple and shipped for months: a
   candidate at its declared Sharpe floor of 0.40 needed 25 years of out-of-sample data to clear
   its t floor of 2.0, so the t floor -- invisible to anyone reading the config as a Sharpe
   requirement -- was the real gate. Nothing in the atlas could ever have passed it.
2. The Newey-West RATIO gate rejects a sleeve whose autocorrelation-corrected t falls far below
   the t its own reported Sharpe implies, which is the signature of stale or appraised pricing.
3. The average pairwise correlation is gated on its upper confidence bound, not only its point
   estimate, because the bound is what says the sample could resolve the effect at all.

Each gate carries a mutation: a case that must FAIL, so a gate that has quietly stopped biting
cannot pass this file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_sleeve_admission import passing_evidence

from alphaforge.validation.sleeve_admission import (
    evaluate_sleeve_evidence,
    load_admission_contract,
)

CONTRACT_PATH = Path(__file__).parents[2] / "config/sleeve_admission_contract.json"
ARCHIVE_DIR = Path(__file__).parents[2] / "config/archive"


def _contract() -> dict:
    return load_admission_contract(CONTRACT_PATH)


def _failure_paths(evidence: dict, contract: dict) -> list[str]:
    report = evaluate_sleeve_evidence(evidence, contract)
    return [failure.split(":")[1] for failure in report.failures]


# --------------------------------------------------------------------------------------------
# 1. the contract must be satisfiable by construction
# --------------------------------------------------------------------------------------------


def test_in_force_contract_significance_floors_agree() -> None:
    contract = _contract()
    thresholds = contract["thresholds"]
    years = thresholds["minimum_oos_observations"] / 252.0
    attainable = thresholds["net_sharpe_min"] * years**0.5
    assert thresholds["newey_west_t_min"] <= attainable, (
        "a candidate sitting exactly on the Sharpe floor, measured over exactly the minimum "
        "sample, cannot reach the declared t floor -- so the t floor is the real gate and the "
        "declared Sharpe floor is decoration"
    )


def test_loader_refuses_a_self_contradictory_contract(tmp_path: Path) -> None:
    """The mutation: push the t floor one notch above what the Sharpe floor can reach."""
    contract = json.loads(CONTRACT_PATH.read_text())
    thresholds = contract["thresholds"]
    years = thresholds["minimum_oos_observations"] / 252.0
    thresholds["newey_west_t_min"] = thresholds["net_sharpe_min"] * years**0.5 + 0.01
    path = tmp_path / "sleeve_admission_contract.json"
    path.write_text(json.dumps(contract))

    with pytest.raises(ValueError, match="self-contradictory significance floors"):
        load_admission_contract(path)


@pytest.mark.parametrize(
    ("name", "expected_years"),
    [("sleeve_admission_contract_v4_superseded.json", "25.0"),
     ("sleeve_admission_contract_v5_superseded.json", "177.8")],
)
def test_the_superseded_contracts_are_refused_with_their_real_cost(
    name: str, expected_years: str
) -> None:
    """The defect this validator exists for, pinned against the actual artifacts that carried it.

    These files are kept precisely so the claim 'v4 and v5 could not be satisfied' stays checkable
    rather than becoming a story in a commit message.
    """
    path = ARCHIVE_DIR / name
    if not path.exists():  # pragma: no cover - the archive is part of the change
        pytest.fail(f"missing superseded contract {name}; the defect record must remain auditable")
    with pytest.raises(ValueError) as excinfo:
        load_admission_contract(path)
    assert "self-contradictory significance floors" in str(excinfo.value)
    assert expected_years in str(excinfo.value)


# --------------------------------------------------------------------------------------------
# 2. the autocorrelation-inflation gate
# --------------------------------------------------------------------------------------------


def test_ratio_gate_is_declared_and_passes_on_honest_evidence() -> None:
    contract = _contract()
    assert "newey_west_t_ratio_min" in contract["thresholds"]
    assert evaluate_sleeve_evidence(passing_evidence(), contract).eligible


def test_ratio_gate_rejects_a_stale_priced_sleeve() -> None:
    """A high headline Sharpe whose Newey-West t collapses is smoothed pricing, not edge.

    Note the shape of the mutation: net_sharpe RISES. A flat t floor of the kind v4 used would
    have waved this through on the strength of the very number that is inflated, which is why the
    ratio -- not the level -- is the instrument.
    """
    contract = _contract()
    evidence = copy.deepcopy(passing_evidence())
    evidence["statistics"]["net_sharpe"] = 1.6
    evidence["statistics"]["newey_west_t"] = 0.9  # ratio 0.325 against an implied 2.771

    failures = evaluate_sleeve_evidence(evidence, contract).failures
    assert any("newey_west_t_ratio" in failure for failure in failures), failures
    assert evidence["statistics"]["net_sharpe"] > contract["thresholds"]["net_sharpe_min"]
    assert evidence["statistics"]["newey_west_t"] > contract["thresholds"]["newey_west_t_min"]


def test_ratio_gate_fails_closed_on_missing_evidence() -> None:
    contract = _contract()
    evidence = copy.deepcopy(passing_evidence())
    del evidence["statistics"]["newey_west_t"]
    assert not evaluate_sleeve_evidence(evidence, contract).eligible


# --------------------------------------------------------------------------------------------
# 3. the correlation-precision gate
# --------------------------------------------------------------------------------------------


def test_average_correlation_upper_bound_is_gated() -> None:
    contract = _contract()
    assert "average_pairwise_correlation_upper_95_max" in contract["thresholds"]

    evidence = copy.deepcopy(passing_evidence())
    # The point estimate still passes; only the bound moves. A candidate whose correlation cannot
    # be resolved by its own sample must not be admitted on the strength of a point estimate.
    evidence["diversification"]["average_pairwise_correlation_upper_95"] = 0.4
    assert evidence["diversification"]["average_pairwise_correlation"] <= (
        contract["thresholds"]["average_pairwise_correlation_max"]
    )

    failures = _failure_paths(evidence, contract)
    assert "diversification.average_pairwise_correlation_upper_95" in failures, failures


def test_correlation_gate_is_not_merely_looser_than_it_was() -> None:
    """The one gate in v6 that moved AGAINST the target being easier to reach."""
    contract = _contract()
    archived = ARCHIVE_DIR / "sleeve_admission_contract_v4_superseded.json"
    superseded = json.loads(archived.read_text())
    assert contract["thresholds"]["average_pairwise_correlation_max"] < (
        superseded["thresholds"]["average_pairwise_correlation_max"]
    )
