"""Freshness and honesty checks for the market-status capability artifact."""

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
    path = REPO / "scripts" / "export_market_status_contract.py"
    spec = importlib.util.spec_from_file_location("market_status_contract_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_is_deterministic_source_bound_and_non_research(exporter) -> None:
    first = exporter.build_contract()
    assert first == exporter.build_contract()
    assert first["schema"] == "alphaforge.market-status-contract.v4"
    assert first["status"] == "EVENT_DRIVEN_BACKTEST_INTEGRATED"
    assert (
        first["coverage_status"]
        == "REVIEWED_INGEST_AND_BOUND_PREFLIGHT_NO_BUNDLED_CORPUS"
    )
    assert first["trial_accounting"]["hypotheses_spent"] == 0
    assert first["trial_accounting"]["returns_evaluated"] is False
    assert "source_lineage" in first["invariants"]
    assert "historical_availability" in first["invariants"]
    assert "independent_confirmation" in first["invariants"]
    assert "coverage_preflight" in first["invariants"]
    assert "ingest_implementation" in first["source_sha256"]
    assert "ingest_tests" in first["source_sha256"]
    assert any("official-exchange" in item for item in first["implemented"])
    assert any("pre-run coverage audit" in item for item in first["implemented"])
    assert any("historical exchange-status corpus" in item for item in first["not_implemented"])
    assert all(len(value) == 64 for value in first["source_sha256"].values())


def test_persisted_contract_matches_builder_and_content_hash(exporter) -> None:
    persisted = json.loads(exporter.OUTPUT.read_text())
    assert persisted == exporter.build_contract()
    content_hash = persisted.pop("content_hash")
    canonical = json.dumps(persisted, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
