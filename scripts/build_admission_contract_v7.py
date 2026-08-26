#!/usr/bin/env python3
"""Build the prospective v7 admission proposal from the in-force v6 contract and power audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "config" / "archive" / "sleeve_admission_contract_v6_superseded.json"
AUDIT: Final = ROOT / "artifacts" / "analysis" / "admission_gate_power_audit" / "result.json"
TARGET: Final = ROOT / "config" / "sleeve_admission_contract_v7_proposed.json"
EXPECTED_SOURCE_SCHEMA: Final = "canli.alphac-sleeve-admission-contract.v6"
EXPECTED_AUDIT_SCHEMA: Final = "canli.alphac-admission-gate-power-audit.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, Any]:
    contract: dict[str, Any] = json.loads(SOURCE.read_text())
    audit: dict[str, Any] = json.loads(AUDIT.read_text())
    if contract.get("schema") != EXPECTED_SOURCE_SCHEMA:
        raise ValueError("v7 proposal must be derived from the exact in-force v6 schema")
    if audit.get("schema") != EXPECTED_AUDIT_SCHEMA:
        raise ValueError("v7 proposal requires the frozen power-audit schema")
    if audit.get("status") != "PROSPECTIVE_RECALIBRATION_REQUIRED":
        raise ValueError("power audit does not authorize prospective recalibration")

    contract["schema"] = "canli.alphac-sleeve-admission-contract.v7-proposed"
    contract["status"] = "PROPOSED_NOT_IN_FORCE"
    contract["derived_from"] = EXPECTED_SOURCE_SCHEMA
    contract["rationale"] = "docs/design/ADMISSION_V7.md"
    contract["evidence_checks_per_candidate"] = 86

    thresholds = contract["thresholds"]
    thresholds.pop("average_pairwise_correlation_max")
    thresholds["candidate_average_correlation_to_existing_book_max"] = 0.0
    thresholds["book_average_pairwise_correlation_delta_max_exclusive"] = 0.0
    thresholds.pop("book_deflated_sharpe_min")
    thresholds["book_deflated_sharpe_must_be_measured"] = True
    frontier = contract["frontier_arithmetic"]
    frontier["legacy_global_zero_correlation_reference"] = frontier.pop(
        "correlation_gate_in_force"
    )
    frontier["book_sharpe_ceiling_at_zero_global_correlation"] = frontier.pop(
        "book_sharpe_ceiling_at_the_gate"
    )
    frontier["incremental_candidate_average_correlation_gate"] = 0.0
    frontier["incremental_book_average_correlation_delta_gate_exclusive"] = 0.0
    frontier["incremental_gates_alone_establish_objective_floor"] = False
    frontier["incremental_gates_alone_establish_objective_ceiling"] = False
    frontier.pop("gate_permits_objective_floor")
    frontier.pop("gate_permits_objective_ceiling")
    contract["deflation_policy"]["book_threshold_key"] = None
    contract["deflation_policy"]["book_measurement_key"] = (
        "book_deflated_sharpe_must_be_measured"
    )
    contract["deflation_policy"]["book_maturity_threshold"] = 0.95
    contract["deflation_policy"]["book_deflation_is_strictly_additional"] = False
    contract["deflation_policy"]["book_deflation_is_mandatory_for_maturity"] = True
    contract["deflation_policy"]["per_sleeve_gate_removed_reason"] = (
        "The per-sleeve 0.95 DSR gate was already removed in v6 because it measured the wrong "
        "object and silently required about eight times the declared standalone Sharpe floor. "
        "Per-sleeve DSR remains mandatory to measure and publish. V7 additionally re-scopes the "
        "full-union book DSR threshold: it remains mandatory to measure at every admission and "
        "becomes a 0.95 gate at portfolio maturity, while incremental admission is decided by "
        "the positive bootstrap lower bound on book-Sharpe improvement and the other unchanged "
        "robustness, execution, stress, capacity, and trial-accounting gates."
    )

    contract["prospective_scope"] = {
        "effective": False,
        "effective_contract_content_hash": None,
        "applies_only_to_identity_reservations_after_effective_hash": True,
        "legacy_identities_retired_and_ineligible": 228,
        "known_candidates_may_not_be_regraded": True,
        "promotion_requirements": [
            "INDEPENDENT_TEST_SUITE_PASSES",
            "PUBLIC_GATE_PROJECTION_RECONCILES",
            "TRIAL_BUDGET_V7_IS_HASH_BOUND",
            "OWNER_PROMOTION_RECORDED",
        ],
    }
    contract["incremental_gate_scope_policy"] = {
        "book_deflated_sharpe": {
            "admission_role": "MANDATORY_MEASUREMENT_AND_PUBLICATION",
            "portfolio_maturity_role": "GATE_AT_0.95",
            "reason": audit["book_dsr_scope"]["recommendation"],
            "full_union_trial_count_remains_mandatory": True,
            "maturity_threshold": 0.95,
        },
        "correlation": {
            "candidate_average_to_existing_book_max": 0.0,
            "book_average_pairwise_correlation_delta_must_be_strictly_negative": True,
            "global_average_pairwise_correlation": "MANDATORY_MEASUREMENT_AND_TRAJECTORY",
            "global_objective": contract["objective"][
                "average_pairwise_correlation_objective"
            ],
            "average_upper_95_gate_unchanged": thresholds[
                "average_pairwise_correlation_upper_95_max"
            ],
            "ordinary_pair_and_stress_gates_unchanged": True,
            "reason": audit["correlation_path"]["recommendation"],
        },
    }
    contract["gate_power_audit"] = {
        "path": str(AUDIT.relative_to(ROOT)),
        "sha256": _sha256(AUDIT),
        "content_hash": audit["content_hash"],
        "candidate_return_artifacts_read": audit["trial_accounting"][
            "candidate_return_artifacts_read"
        ],
        "hypothesis_identities_consumed": audit["trial_accounting"][
            "hypothesis_identities_consumed"
        ],
    }
    retired = contract.setdefault("retired_admission_gates", {})
    retired["average_pairwise_correlation_max"] = {
        "value": 0.0,
        "retired_in": "v7-proposed",
        "reason": (
            "A final global level was path-dependent when applied to the first incremental sleeve. "
            "Replaced by strict candidate-to-book and global-improvement gates while the -0.03 "
            "portfolio objective remains published."
        ),
    }
    retired["book_deflated_sharpe_min"] = {
        "value": 0.95,
        "retired_in": "v7-proposed",
        "reason": (
            "Re-scoped to portfolio maturity. It remains a mandatory full-union measurement at "
            "every admission and remains the 0.95 gate before a mature portfolio claim."
        ),
    }
    contract["claim_boundary"] = (
        "This is a prospective proposal, not an in-force gate change. It can apply only to new "
        "identities reserved after a promoted v7 content hash. It cannot rescue any known or "
        "retired candidate. Passing v7 would establish technical eligibility only, never alpha, "
        "future returns, the 1.5 forward Sharpe target, the 11% expected-drawdown objective, or "
        "the -0.03 diversification objective."
    )
    return contract


def main() -> int:
    contract = build()
    TARGET.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    print(f"wrote {TARGET}")
    print(f"checks_per_candidate: {contract['evidence_checks_per_candidate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
