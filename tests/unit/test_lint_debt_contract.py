"""Freshness and honesty checks for the lint-debt capability artifact."""

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
    path = REPO / "scripts" / "export_lint_debt_contract.py"
    spec = importlib.util.spec_from_file_location("lint_debt_contract_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_proves_clean_boundaries_and_confesses_script_debt(exporter) -> None:
    contract = exporter.build_contract()
    scopes = contract["scopes"]

    assert contract["status"] == "PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT"
    assert scopes["production"]["violations"] == 0
    assert scopes["tests"]["violations"] == 0
    assert scopes["historical_scripts"]["violations"] > 0
    assert contract["trial_accounting"] == {
        "hypotheses_spent": 0,
        "returns_evaluated": False,
    }


@pytest.mark.workspace_evidence
def test_persisted_contract_matches_builder_and_content_hash(exporter) -> None:
    persisted = json.loads(exporter.OUTPUT.read_text())
    assert persisted == exporter.build_contract()
    content_hash = persisted.pop("content_hash")
    canonical = json.dumps(persisted, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
