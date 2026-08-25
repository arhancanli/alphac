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

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
HOSTS = (
    REPO.parent / "meridian" / "public" / "glassbox" / "sleeve_discovery.json",
    REPO.parent / "meridian-app" / "public" / "glassbox" / "sleeve_discovery.json",
)

# Imported from the exporter, NOT transcribed. A guard against drift that keeps its own copy of
# the mapping has the defect it is guarding against: when the contract retired the per-sleeve
# deflation gate, a duplicated map here failed for a reason that had nothing to do with the site
# being wrong.
_EXPORT = importlib.util.spec_from_file_location(
    "research_export_gate_map", REPO / "scripts" / "research_export.py"
)
assert _EXPORT is not None and _EXPORT.loader is not None
_export_module = importlib.util.module_from_spec(_EXPORT)
_EXPORT.loader.exec_module(_export_module)
GATE_SOURCE = _export_module._DISCOVERY_GATE_SOURCE
RETIRED = _export_module._DISCOVERY_GATE_RETIRED


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
def test_a_retired_gate_is_not_still_published_as_a_live_one() -> None:
    """A bar that no longer applies must not sit on the page looking like it does."""
    thresholds = json.loads(CONTRACT.read_text())["thresholds"]
    for path, discovery in _published():
        for retired in RETIRED:
            if retired in thresholds:
                continue
            assert retired not in discovery["admission_gates"], (
                f"{path} still publishes {retired} as an admission gate after the contract "
                "retired it"
            )
            assert retired in discovery.get("retired_admission_gates", {}), (
                f"{path} dropped {retired} without saying so; a bar that disappears between "
                "deploys reads as a bar that was quietly relaxed"
            )


@pytest.mark.workspace_evidence
def test_the_objective_is_published_with_the_arithmetic_that_bounds_it() -> None:
    contract_objective = json.loads(CONTRACT.read_text())["objective"]
    for path, discovery in _published():
        for key, value in contract_objective.items():
            assert discovery["objective"][key] == value, (
                f"{path} publishes objective.{key}={discovery['objective'][key]!r} while the "
                f"contract in force declares {value!r}"
            )
        assert (
            discovery["objective"]["target_sleeve_count"]
            == (contract_objective["target_total_sleeves"])
        )
        assert "frontier_arithmetic" in discovery, (
            f"{path} publishes a portfolio objective and an admission gate with nothing stating "
            "the relationship between them"
        )
        frontier = discovery["frontier_arithmetic"]
        assert frontier["incremental_candidate_average_correlation_gate"] == discovery[
            "admission_gates"
        ]["candidate_average_correlation_to_existing_book_max"]
        assert frontier["incremental_book_average_correlation_delta_gate_exclusive"] == discovery[
            "admission_gates"
        ]["book_average_pairwise_correlation_delta_max_exclusive"]
        assert frontier["incremental_gates_alone_establish_objective_floor"] is False
        assert frontier["target_sleeve_count"] == discovery["objective"]["target_sleeve_count"]
