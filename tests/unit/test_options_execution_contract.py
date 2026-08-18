"""Freshness and honesty checks for the options engineering capability artifact."""

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
    path = REPO / "scripts" / "export_options_execution_contract.py"
    spec = importlib.util.spec_from_file_location("options_contract_export_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_is_deterministic_source_bound_and_non_research(exporter) -> None:
    first = exporter.build_contract()
    assert first == exporter.build_contract()
    assert first["schema"] == "alphaforge.options-execution-contract.v12"
    assert first["status"] == "DOMAIN_PRIMITIVES_ONLY"
    assert first["trial_accounting"] == {
        "market_data_opened": False,
        "returns_evaluated": False,
        "hypotheses_spent": 0,
    }
    assert len(first["not_implemented"]) == 8
    assert "cross_strike_integrity" in first["invariants"]
    assert "adjusted_deliverables" in first["invariants"]
    assert "adjustment_ingest" in first["invariants"]
    assert "occ_source_archive" in first["invariants"]
    assert "displayed_package_execution" in first["invariants"]
    assert "option_market_status" in first["invariants"]
    assert "market_status_ingest" in first["invariants"]
    assert "market_status_coverage" in first["invariants"]
    assert "option_fee_assessment" in first["invariants"]
    assert "internal_scenario_margin" in first["invariants"]
    assert any("convexity" in item for item in first["implemented"])
    assert any("multi-asset" in item for item in first["implemented"])
    assert any("OCC-versus-vendor" in item for item in first["implemented"])
    assert any("content-addressed source archive" in item for item in first["implemented"])
    assert any("ratio-defined multi-leg" in item for item in first["implemented"])
    assert any("minimum-credit" in item for item in first["implemented"])
    assert any("AUCTION_ONLY" in item for item in first["implemented"])
    assert any("close-only package" in item for item in first["implemented"])
    assert any("official-exchange" in item for item in first["implemented"])
    assert any("coverage preflight" in item for item in first["implemented"])
    assert any("exact-decimal" in item for item in first["implemented"])
    assert any("assignment fees" in item for item in first["implemented"])
    assert any("scenario margin" in item for item in first["implemented"])
    assert any("concentration add-ons" in item for item in first["implemented"])
    assert "adjusted_deliverable_implementation" in first["source_sha256"]
    assert "adjusted_deliverable_tests" in first["source_sha256"]
    assert "adjustment_ingest_implementation" in first["source_sha256"]
    assert "adjustment_ingest_tests" in first["source_sha256"]
    assert "occ_archive_implementation" in first["source_sha256"]
    assert "occ_archive_tests" in first["source_sha256"]
    assert "package_execution_implementation" in first["source_sha256"]
    assert "package_execution_tests" in first["source_sha256"]
    assert "fee_assessment_implementation" in first["source_sha256"]
    assert "fee_assessment_tests" in first["source_sha256"]
    assert "scenario_margin_implementation" in first["source_sha256"]
    assert "scenario_margin_tests" in first["source_sha256"]
    assert "market_status_ingest_implementation" in first["source_sha256"]
    assert "market_status_ingest_tests" in first["source_sha256"]
    assert any("Cloudflare" in item for item in first["not_implemented"])
    assert "actual package fillability" in first["claim_boundary"]
    assert all(len(value) == 64 for value in first["source_sha256"].values())


def test_persisted_contract_matches_builder_and_content_hash(exporter) -> None:
    persisted = json.loads(exporter.OUTPUT.read_text())
    assert persisted == exporter.build_contract()
    content_hash = persisted.pop("content_hash")
    canonical = json.dumps(persisted, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
