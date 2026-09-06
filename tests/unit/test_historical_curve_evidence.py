from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "build_historical_curve_evidence.py"
    spec = importlib.util.spec_from_file_location("historical_curve_evidence_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_unique_legacy_curves_recompute_without_claiming_packet_completion() -> None:
    evidence, index = _module().build_evidence()
    assert index["summary"] == {
        "unique_exact_artifact_bindings": 37,
        "sharpe_recomputations_matched": 37,
        "complete_trial_packets_created": 0,
    }
    assert len(evidence) == len(index["curves"]) == 37
    assert all(
        item["verification"]["annualized_sharpe_matches_within_1e_12"]
        for item in evidence.values()
    )
    assert all(
        item["verification"]["full_packet_section_verified"] is False
        for item in evidence.values()
    )
    assert all(
        item["curve_structure"]["return_observations"] > 0
        and item["measurement"]["maximum_drawdown"] <= 0
        and item["measurement"]["maximum_drawdown_magnitude"] >= 0
        for item in evidence.values()
    )


def test_published_historical_curve_trees_are_byte_identical_and_index_bound() -> None:
    artifact = REPO / "artifacts" / "research" / "historical_curve_evidence"
    left = REPO.parent / "meridian" / "public" / "glassbox" / "historical-curves"
    right = REPO.parent / "meridian-app" / "public" / "glassbox" / "historical-curves"
    artifact_files = {
        str(path.relative_to(artifact)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifact.rglob("*")
        if path.is_file()
    }
    left_files = {
        str(path.relative_to(left)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in left.rglob("*")
        if path.is_file()
    }
    right_files = {
        str(path.relative_to(right)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in right.rglob("*")
        if path.is_file()
    }
    assert len(artifact_files) == 112
    assert artifact_files == left_files == right_files
