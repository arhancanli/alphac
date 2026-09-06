from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "clean_checkout_workspace_evidence_policy.json"


def test_clean_checkout_workspace_policy_is_explicit_and_current() -> None:
    policy = json.loads(POLICY.read_text())
    modules = policy["test_modules"]

    assert policy["schema"] == (
        "canli.alphac-clean-checkout-workspace-evidence-policy.v1"
    )
    assert modules == sorted(set(modules))
    assert modules
    assert all(path.startswith("tests/") and path.endswith(".py") for path in modules)
    assert all((ROOT / path).is_file() for path in modules)
    assert "does not convert a skipped workstation evidence check into a pass" in policy[
        "claim_boundary"
    ]
