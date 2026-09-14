"""The 2026-09-14 reconciliation record beside the trial-accounting policy must agree with the
import receipt it cites, and the 320 staged review it records must be the one the external-ledger
audit treats as held. A record that could drift from its evidence is a typed number. It lives in
config/trial_accounting_reviews.json, not in the policy: the policy is embedded byte-for-byte in
the admission v7 promotion receipt and hash-bound by every v2 reservation, so an event recorded
inside it drifts every sealed binding without changing one rule."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "config" / "trial_accounting.json"
REVIEWS = REPO / "config" / "trial_accounting_reviews.json"
AUDIT = REPO / "scripts" / "audit_external_experiment_ledgers.py"


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _reviews() -> dict:
    return json.loads(REVIEWS.read_text(encoding="utf-8"))


def test_the_record_names_a_receipt_and_the_review_it_triggered() -> None:
    reviews = _reviews()
    record = reviews["external_ledger_reconciliation"]
    assert reviews["policy_path"] == "config/trial_accounting.json"
    assert "staged_reviews_held" not in _policy(), (
        "events are recorded beside the policy, never in it"
    )
    assert "external_ledger_reconciliation" not in _policy()
    assert record["status"] == "IMPORTED"
    assert record["new_experiments_run"] == 0
    assert (
        record["canonical_identities_after"] - record["canonical_identities_before"]
        == record["identities_imported"]
    )
    assert reviews["accounting_last_reconciled"] == record["recorded_at"]
    held = reviews["staged_reviews_held"]
    assert "320" in held
    assert held["320"]["reviewed_on"] >= held["320"]["reached_on"]
    assert record["evidence"] in held["320"]["evidence"]


@pytest.mark.workspace_evidence
def test_the_record_matches_the_import_receipt_it_cites() -> None:
    record = _reviews()["external_ledger_reconciliation"]
    receipt_path = REPO / record["evidence"]
    if not receipt_path.exists():
        pytest.skip("import receipt lives in the working tree, not the clean checkout")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["dry_run"] is False
    assert receipt["union_identities_before"] == record["canonical_identities_before"]
    assert receipt["union_identities_after"] == record["canonical_identities_after"]
    assert receipt["union_identities_added"] == record["identities_imported"]
    assert len(receipt["directories_imported"]) == record["ledger_directories_imported"]


def test_the_audit_reads_the_held_review_from_beside_the_policy() -> None:
    spec = importlib.util.spec_from_file_location("audit_external_ledgers_policy", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = module.load_policy(POLICY)
    assert 320 in loaded["staged_reviews_held"]
    assert 360 not in loaded["staged_reviews_held"]
    assert loaded["staged_hard_reviews"] == [320, 360, 400]
