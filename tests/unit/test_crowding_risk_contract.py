"""Freshness and honesty checks for the crowding capability artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def exporter():
    path = REPO / "scripts" / "export_crowding_risk_contract.py"
    spec = importlib.util.spec_from_file_location("crowding_contract_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_is_deterministic_and_confesses_missing_coverage(exporter) -> None:
    first = exporter.build_contract()
    assert first == exporter.build_contract()
    assert first["status"] == "PRETRADE_INTEGRATED_NO_HISTORICAL_COVERAGE"
    assert first["trial_accounting"]["hypotheses_spent"] == 0
    statuses = {row["name"]: row["status"] for row in first["deterministic_stress_scenarios"]}
    assert statuses == {
        "liquid_uncrowded_long": "pass",
        "missing_required_flow": "unassessable",
        "ownership_saturation": "block",
        "short_squeeze": "block",
        "stressed_liquidation": "block",
    }


def test_persisted_contract_matches_builder_and_content_hash(exporter) -> None:
    persisted = json.loads(exporter.OUTPUT.read_text())
    assert persisted == exporter.build_contract()
    content_hash = persisted.pop("content_hash")
    canonical = json.dumps(persisted, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
