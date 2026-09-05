from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_trial_accounting_v7.py"
PROPOSAL = ROOT / "config" / "trial_accounting_v7_proposed.json"


def _module():
    spec = importlib.util.spec_from_file_location("trial_accounting_v7", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trial_budget_proposal_is_exact_builder_output() -> None:
    module = _module()
    assert json.loads(PROPOSAL.read_text()) == module.build()


def test_budget_increase_preserves_trial_debt_and_staged_stops() -> None:
    proposal = json.loads(PROPOSAL.read_text())
    review = proposal["prospective_v7_review"]

    assert proposal["research_status"] == "PROPOSED_NOT_IN_FORCE"
    assert proposal["observed_hypothesis_identities"] == 228
    assert proposal["hypothesis_identity_budget"] == 400
    assert review["staged_hard_reviews"] == [320, 360, 400]
    assert review["single_family_tripwire"] == 40
    assert review["all_new_identities_enter_complete_union_deflation"] is True
    assert review["no_legacy_identity_reopened"] is True
    assert review["planning_probability_is_not_a_forecast"] is True
