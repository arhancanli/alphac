#!/usr/bin/env python3
"""Build the prospective staged trial-budget proposal authorized by the v7 power audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "config" / "archive" / "trial_accounting_v1_superseded.json"
AUDIT: Final = ROOT / "artifacts" / "analysis" / "admission_gate_power_audit" / "result.json"
TARGET: Final = ROOT / "config" / "trial_accounting_v7_proposed.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, Any]:
    policy: dict[str, Any] = json.loads(SOURCE.read_text())
    audit: dict[str, Any] = json.loads(AUDIT.read_text())
    power = audit["search_power"]
    if power["prospective_identity_budget_recommendation"] != 400:
        raise ValueError("frozen power audit no longer recommends the 400-identity ceiling")
    if policy["observed_hypothesis_identities"] != audit["trial_accounting"][
        "legacy_identities_remain_retired"
    ]:
        raise ValueError("trial ledger moved after the frozen power audit")

    policy["schema"] = "alphac.trial-accounting-policy.v2-proposed"
    policy["research_status"] = "PROPOSED_NOT_IN_FORCE"
    policy["hypothesis_identity_budget"] = 400
    policy["prospective_v7_review"] = {
        "authorized_by": "Arhan Canli, owner, 2026-08-23",
        "status": "PROPOSED_NOT_IN_FORCE",
        "reason": (
            "Ledger reconciliation raised the observed union from 162 to 228 without running new "
            "experiments, leaving only 92 identities under the 320 ceiling. At the previously "
            "declared planning rate of 3/46, that headroom has an exact binomial probability of "
            "only 7.70% of producing ten successes. A ceiling of 400 restores 172 prospective "
            "identities and a 69.04% planning probability under the same explicitly uncertain "
            "assumption."
        ),
        "staged_hard_reviews": [320, 360, 400],
        "single_family_tripwire": 40,
        "identities_are_permission_to_test_not_permission_to_admit": True,
        "all_new_identities_enter_complete_union_deflation": True,
        "no_legacy_identity_reopened": True,
        "promotion_requires_admission_v7_content_hash": True,
        "planning_probability_is_not_a_forecast": True,
        "current_remaining_identities": power["current_remaining_identities"],
        "prospective_remaining_identities": power["prospective_remaining_identities"],
        "current_probability_at_least_ten": power[
            "probability_at_least_ten_at_current_remaining_budget"
        ],
        "prospective_probability_at_least_ten": power[
            "probability_at_least_ten_at_prospective_remaining_budget"
        ],
        "book_dsr_required_at_400_and_756_rows": audit["book_dsr_scope"][
            "minimum_book_sharpe_at_400_trials"
        ],
    }
    policy["v7_power_audit_binding"] = {
        "path": str(AUDIT.relative_to(ROOT)),
        "sha256": _sha256(AUDIT),
        "content_hash": audit["content_hash"],
    }
    return policy


def main() -> int:
    policy = build()
    TARGET.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
    print(f"wrote {TARGET}")
    print(f"proposed_identity_ceiling: {policy['hypothesis_identity_budget']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
