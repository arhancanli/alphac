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


#: The fields that are a CLAIM. If one of these moves, something real changed.
_VERDICT_KEYS = ("status", "claim_boundary", "trial_accounting", "command")
#: The per-scope fields that are a claim, as opposed to a file count that moves whenever a script
#: is added.
_SCOPE_CLAIM_KEYS = ("violations", "files_with_violations")


def _verdict(contract: dict) -> dict:
    return {
        **{key: contract[key] for key in _VERDICT_KEYS if key in contract},
        "scopes": {
            name: {key: scope[key] for key in _SCOPE_CLAIM_KEYS if key in scope}
            for name, scope in contract["scopes"].items()
        },
    }


@pytest.mark.workspace_evidence
def test_the_published_verdict_is_what_the_builder_produces(exporter) -> None:
    """The half that is a claim: the status, the violation counts, the boundary.

    Split out from provenance on 2026-08-22. The single equality assertion this replaces failed
    after ANY source edit, because the contract records a sha256 of every file it covers — it was
    hand-resynced about ten times in one day. A test that routinely fails for a benign reason
    trains its reader to ignore a real one, which is the same defect as a warning that fires on
    every build. Nothing here is weaker: a production violation appearing still fails, and it now
    fails ALONE, so the message means something.
    """
    persisted = json.loads(exporter.OUTPUT.read_text())
    assert _verdict(persisted) == _verdict(exporter.build_contract())


@pytest.mark.workspace_evidence
def test_each_scope_still_scans_a_plausible_number_of_files(exporter) -> None:
    """The census is excluded from the verdict, so it needs its own floor.

    `python_files` moves by one every time a script is added, which is why comparing it exactly
    made the guard fail for nothing. But a scope whose count COLLAPSED would mean it had stopped
    matching files, and a clean result over zero files is the shape of the bug rather than the
    absence of it. So the count is floored rather than pinned.
    """
    persisted = json.loads(exporter.OUTPUT.read_text())
    floors = {"production": 100, "tests": 100, "historical_scripts": 100}
    for name, floor in floors.items():
        counted = persisted["scopes"][name]["python_files"]
        assert counted >= floor, (
            f"the {name} scope reports {counted} files, under a floor of {floor} — it has stopped "
            "matching, and a clean verdict over almost nothing means nothing"
        )


@pytest.mark.workspace_evidence
def test_the_content_hash_matches_the_bytes_it_was_published_with(exporter) -> None:
    """Catches the artifact being edited by hand, which no amount of regeneration would hide."""
    persisted = json.loads(exporter.OUTPUT.read_text())
    content_hash = persisted.pop("content_hash")
    canonical = json.dumps(persisted, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@pytest.mark.workspace_evidence
def test_provenance_staleness_is_named_rather_than_conflated(exporter) -> None:
    """The benign half, reported as benign and by name.

    When only the source hashes have drifted, this says so and names the files, so nobody has to
    diff two thousand-line JSON documents to learn that a script was edited. The pre-commit hook
    in scripts/hooks/ regenerates the contract for any commit touching Python, so on a clean
    checkout this does not fire at all.
    """
    persisted = json.loads(exporter.OUTPUT.read_text())
    fresh = exporter.build_contract()
    stale = sorted(
        name
        for name, digest in fresh.get("source_sha256", {}).items()
        if persisted.get("source_sha256", {}).get(name) != digest
    )
    added = sorted(set(fresh.get("source_sha256", {})) - set(persisted.get("source_sha256", {})))
    removed = sorted(set(persisted.get("source_sha256", {})) - set(fresh.get("source_sha256", {})))
    assert not (stale or added or removed), (
        "PROVENANCE ONLY — the published verdict is unchanged and only the source fingerprints "
        f"have drifted. Changed: {stale[:8]}{'…' if len(stale) > 8 else ''}. Added: {added[:5]}. "
        f"Removed: {removed[:5]}. Fix with "
        "`.venv/bin/python scripts/export_lint_debt_contract.py`, or run scripts/install_hooks.sh "
        "once so the pre-commit hook does it for you."
    )
