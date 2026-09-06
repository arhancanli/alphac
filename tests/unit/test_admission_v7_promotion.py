from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/promote_admission_v7.py"


def _module():
    spec = importlib.util.spec_from_file_location("promote_admission_v7", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_contract_and_budget_match_the_promotion_receipt() -> None:
    module = _module()
    receipt = module.verify_current()
    contract = json.loads(module.ACTIVE_CONTRACT.read_text())
    policy = json.loads(module.ACTIVE_TRIAL_POLICY.read_text())

    assert contract["schema"] == "canli.alphac-sleeve-admission-contract.v7"
    assert contract["status"] == "IN_FORCE"
    assert contract["prospective_scope"]["effective"] is True
    assert contract["prospective_scope"]["effective_on_or_after_reservation_ordinal"] == 229
    assert policy["schema"] == "alphac.trial-accounting-policy.v2"
    assert policy["hypothesis_identity_budget"] == 400
    assert policy["prospective_v7_review"]["staged_hard_reviews"] == [320, 360, 400]
    assert receipt["legacy_identities_retired_without_regrading"] == 228
    assert receipt["assertions"]["known_results_regraded"] is False


def test_archives_preserve_the_exact_superseded_schemas() -> None:
    module = _module()
    archived_contract = json.loads(module.ARCHIVE_CONTRACT.read_text())
    archived_policy = json.loads(module.ARCHIVE_TRIAL_POLICY.read_text())
    assert archived_contract["schema"] == "canli.alphac-sleeve-admission-contract.v6"
    assert archived_policy["schema"] == "alphac.trial-accounting-policy.v1"
