"""What the site publishes as the admission gates must be what the contract enforces.

`config/sleeve_discovery.json` carried its own `admission_gates` block: a hand-transcribed summary
of the contract, published to canlicapital.com as the human-readable statement of the bar. By the
time the contract moved to v6 that copy had drifted, and it had drifted in the flattering
direction -- the site advertised an average-correlation ceiling of 0.15 and a 252-observation
minimum while the contract in force required 0.00 and 756.

Two files claiming the same fact is one file too many. The export now derives the summary from the
contract; this pins that it stays derived, and that the relationship between the gate and the
portfolio objective is published beside them rather than left for the reader to work out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
HOSTS = (
    REPO.parent / "meridian" / "public" / "glassbox" / "sleeve_discovery.json",
    REPO.parent / "meridian-app" / "public" / "glassbox" / "sleeve_discovery.json",
)

# published gate name -> contract threshold name
GATE_SOURCE = {
    "deflated_sharpe_min": "deflated_sharpe_min",
    "pbo_max": "pbo_max",
    "average_pairwise_correlation_max": "average_pairwise_correlation_max",
    "pairwise_correlation_max": "ordinary_pairwise_correlation_max",
    "stressed_pairwise_correlation_max": "stressed_pairwise_correlation_max",
    "minimum_oos_observations": "minimum_oos_observations",
}


def _published() -> list[tuple[Path, dict]]:
    found = [(path, json.loads(path.read_text())) for path in HOSTS if path.exists()]
    assert found, (
        "no published sleeve_discovery.json found on either host; this guard would pass "
        "vacuously, which is the failure mode it exists to prevent"
    )
    return found


@pytest.mark.workspace_evidence
def test_every_published_gate_equals_the_contract_threshold() -> None:
    thresholds = json.loads(CONTRACT.read_text())["thresholds"]
    for path, discovery in _published():
        gates = discovery["admission_gates"]
        for published_key, threshold_key in GATE_SOURCE.items():
            assert gates[published_key] == thresholds[threshold_key], (
                f"{path} publishes {published_key}={gates[published_key]!r} while the contract "
                f"enforces {threshold_key}={thresholds[threshold_key]!r}"
            )


@pytest.mark.workspace_evidence
def test_the_guard_covers_every_gate_the_site_publishes() -> None:
    """A guard that checks a subset reads as coverage while leaving gates unchecked."""
    thresholds = json.loads(CONTRACT.read_text())["thresholds"]
    for path, discovery in _published():
        numeric_published = {
            key
            for key, value in discovery["admission_gates"].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        unchecked = sorted(numeric_published - set(GATE_SOURCE))
        assert not unchecked, (
            f"{path} publishes numeric gates this guard never compares to the contract: "
            f"{unchecked}. Add them to GATE_SOURCE or stop publishing them."
        )
        for threshold_key in GATE_SOURCE.values():
            assert threshold_key in thresholds


@pytest.mark.workspace_evidence
def test_the_objective_is_published_with_the_arithmetic_that_bounds_it() -> None:
    for path, discovery in _published():
        assert "frontier_arithmetic" in discovery, (
            f"{path} publishes a portfolio objective and an admission gate with nothing stating "
            "the relationship between them"
        )
        frontier = discovery["frontier_arithmetic"]
        assert frontier["correlation_gate_in_force"] == (
            discovery["admission_gates"]["average_pairwise_correlation_max"]
        )
        assert isinstance(frontier["gate_permits_objective_floor"], bool)
        assert frontier["target_sleeve_count"] == discovery["objective"]["target_sleeve_count"]
