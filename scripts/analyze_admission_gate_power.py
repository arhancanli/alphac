#!/usr/bin/env python3
"""Audit admission-gate scope and prospective search power without reading candidate returns."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.dsr import deflated_sharpe_ratio

ROOT: Final = Path(__file__).resolve().parents[1]
CONTRACT: Final = (
    ROOT / "config" / "archive" / "sleeve_admission_contract_v6_superseded.json"
)
TRIALS: Final = ROOT / "config" / "archive" / "trial_accounting_v1_superseded.json"
DIVERSIFICATION: Final = (
    ROOT / "config" / "archive" / "admission_v7_power_audit_inputs.json"
)
PROTOCOL: Final = ROOT / "docs" / "design" / "ADMISSION_V7_POWER_AUDIT_PROTOCOL.md"
DSR_SOURCE: Final = ROOT / "src" / "alphaforge" / "validation" / "dsr.py"
OUTPUT: Final = ROOT / "artifacts" / "analysis" / "admission_gate_power_audit" / "result.json"
SCHEMA: Final = "canli.alphac-admission-gate-power-audit.v1"
ANNUALIZATION: Final = 252.0
POOLED_SHARPE_VARIANCE: Final = 7.96e-04
HISTORICAL_HITS: Final = 3
HISTORICAL_TRIALS: Final = 46
PROSPECTIVE_BUDGET_CEILING: Final = 400


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _minimum_annualized_sharpe_for_dsr(
    *, probability: float, observations: int, trials: int
) -> float:
    low, high = 0.0, 8.0
    for _ in range(100):
        mid = (low + high) / 2.0
        achieved = deflated_sharpe_ratio(
            sr=mid / math.sqrt(ANNUALIZATION),
            n_obs=observations,
            n_trials=trials,
            sr_trials_variance=POOLED_SHARPE_VARIANCE,
            skew=0.0,
            kurtosis=3.0,
        )
        if achieved < probability:
            low = mid
        else:
            high = mid
    return high


def _binomial_at_least(*, successes: int, trials: int, probability: float) -> float:
    return sum(
        math.comb(trials, count)
        * probability**count
        * (1.0 - probability) ** (trials - count)
        for count in range(successes, trials + 1)
    )


def build() -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text())
    trial_accounting = json.loads(TRIALS.read_text())
    diversification = json.loads(DIVERSIFICATION.read_text())
    thresholds = contract["thresholds"]
    objective = contract["objective"]
    observed = diversification["observed"]

    observed_trials = int(trial_accounting["observed_hypothesis_identities"])
    current_budget = int(trial_accounting["hypothesis_identity_budget"])
    minimum_new = int(objective["minimum_new_sleeves"])
    current_sleeves = int(objective["target_total_sleeves"]) - minimum_new
    current_rho = float(observed["average_pairwise_correlation"])
    current_pair_sum = math.comb(current_sleeves, 2) * current_rho
    first_candidate_pairs = current_sleeves
    first_candidate_average_for_global_zero = -current_pair_sum / first_candidate_pairs

    target_sleeves = int(objective["target_total_sleeves"])
    target_pairs = math.comb(target_sleeves, 2)
    new_pairs = target_pairs - math.comb(current_sleeves, 2)
    rho_objective = float(objective["average_pairwise_correlation_objective"])
    required_new_pair_average_for_objective = (
        rho_objective * target_pairs - current_pair_sum
    ) / new_pairs

    oos = int(thresholds["minimum_oos_observations"])
    dsr_floor = float(thresholds["book_deflated_sharpe_min"])
    current_research_sharpe = float(
        observed["full_book_sharpe_research_simulation_not_forward_evidence"]
    )
    required_book_sharpe_now = _minimum_annualized_sharpe_for_dsr(
        probability=dsr_floor,
        observations=oos,
        trials=observed_trials,
    )
    required_book_sharpe_at_current_ceiling = _minimum_annualized_sharpe_for_dsr(
        probability=dsr_floor,
        observations=oos,
        trials=current_budget,
    )
    required_book_sharpe_at_proposed_ceiling = _minimum_annualized_sharpe_for_dsr(
        probability=dsr_floor,
        observations=oos,
        trials=PROSPECTIVE_BUDGET_CEILING,
    )

    hit_rate = HISTORICAL_HITS / HISTORICAL_TRIALS
    current_headroom = current_budget - observed_trials
    proposed_headroom = PROSPECTIVE_BUDGET_CEILING - observed_trials

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "status": "PROSPECTIVE_RECALIBRATION_REQUIRED",
        "trial_accounting": {
            "hypothesis_identities_consumed": 0,
            "candidate_return_artifacts_read": 0,
            "legacy_identities_remain_retired": observed_trials,
        },
        "scope_boundary": {
            "known_data_audit": True,
            "applies_only_after_future_v7_contract_hash": True,
            "retroactive_candidate_rescue_permitted": False,
            "live_strategy_change": False,
        },
        "book_dsr_scope": {
            "minimum_oos_observations": oos,
            "book_dsr_probability_floor": dsr_floor,
            "current_union_trials": observed_trials,
            "current_book_research_sharpe_not_forward": current_research_sharpe,
            "minimum_book_sharpe_at_current_union": required_book_sharpe_now,
            "minimum_single_admission_jump_if_applied_now": (
                required_book_sharpe_now - current_research_sharpe
            ),
            "minimum_book_sharpe_at_320_trials": required_book_sharpe_at_current_ceiling,
            "minimum_book_sharpe_at_400_trials": required_book_sharpe_at_proposed_ceiling,
            "finding": "FINAL_PORTFOLIO_MATURITY_GATE_MISSCOPED_AS_INCREMENTAL_ADMISSION_GATE",
            "recommendation": (
                "Measure and publish full-union book DSR at every admission, but gate it at the "
                "portfolio-maturity claim. Incremental admission remains gated by the strictly "
                "positive bootstrap lower bound on book-Sharpe delta, PBO, leave-period-out "
                "robustness, costs, stress, execution and full trial accounting."
            ),
        },
        "correlation_path": {
            "current_sleeves": current_sleeves,
            "current_average_pairwise_correlation": current_rho,
            "current_pair_sum": current_pair_sum,
            "first_candidate_average_to_existing_required_for_immediate_global_zero": (
                first_candidate_average_for_global_zero
            ),
            "target_sleeves": target_sleeves,
            "target_average_pairwise_correlation": rho_objective,
            "new_pairs_to_create": new_pairs,
            "average_across_all_new_pairs_required_for_objective": (
                required_new_pair_average_for_objective
            ),
            "finding": "GLOBAL_LEVEL_GATE_IS_PATH_DEPENDENT_AT_INCREMENTAL_ADMISSION",
            "recommendation": (
                "Gate each new sleeve on a strictly negative change in the book's average "
                "pairwise correlation and a candidate-to-existing-book average no greater than "
                "zero, retain the 95% uncertainty ceiling and pair/stress ceilings, and publish "
                "the separate trajectory to -0.03. Do not require the first increment to finish "
                "the entire book's diversification objective."
            ),
        },
        "search_power": {
            "historical_planning_hit_rate": hit_rate,
            "historical_hit_rate_basis": "3 survivors / 46 tested candidates",
            "warning": (
                "Binomial values are planning arithmetic, not a forecast; future mechanism "
                "families differ and independence is not established."
            ),
            "current_identity_budget": current_budget,
            "current_remaining_identities": current_headroom,
            "expected_hits_at_current_remaining_budget": current_headroom * hit_rate,
            "probability_at_least_ten_at_current_remaining_budget": _binomial_at_least(
                successes=minimum_new,
                trials=current_headroom,
                probability=hit_rate,
            ),
            "prospective_identity_budget_recommendation": PROSPECTIVE_BUDGET_CEILING,
            "prospective_remaining_identities": proposed_headroom,
            "expected_hits_at_prospective_remaining_budget": proposed_headroom * hit_rate,
            "probability_at_least_ten_at_prospective_remaining_budget": _binomial_at_least(
                successes=minimum_new,
                trials=proposed_headroom,
                probability=hit_rate,
            ),
            "staged_reviews": [320, 360, 400],
            "family_tripwire_unchanged": 40,
            "multiplicity_accounting": "ALL_IDENTITIES_REMAIN_IN_COMPLETE_UNION",
        },
        "unchanged_rigor": [
            "POINT_IN_TIME_AND_SURVIVORSHIP_LINEAGE",
            "PURGED_WALK_FORWARD_AND_EMBARGO",
            "NET_OF_COST_EXECUTION_SCENARIOS",
            "PBO_AND_DSR_MEASUREMENT",
            "BOOTSTRAP_BOOK_SHARPE_DELTA_LOWER_BOUND",
            "LEAVE_PERIOD_OUT_ROBUSTNESS",
            "PAIRWISE_AND_STRESSED_CORRELATION_BOUNDS",
            "EXPECTED_SHORTFALL_AND_DRAWDOWN_COMPARISONS",
            "CAPACITY_CURVE_AND_STRESSED_FILL_RECONCILIATION",
            "PAPER_AND_MACHINE_READABLE_PACKET_BEFORE_NEXT_IDENTITY",
        ],
        "source_bindings": {
            "admission_contract": {
                "path": str(CONTRACT.relative_to(ROOT)),
                "sha256": _sha256(CONTRACT),
            },
            "trial_accounting": {"path": str(TRIALS.relative_to(ROOT)), "sha256": _sha256(TRIALS)},
            "current_book_diversification": {
                "path": str(DIVERSIFICATION.relative_to(ROOT)),
                "sha256": _sha256(DIVERSIFICATION),
            },
            "protocol": {"path": str(PROTOCOL.relative_to(ROOT)), "sha256": _sha256(PROTOCOL)},
            "dsr_implementation": {
                "path": str(DSR_SOURCE.relative_to(ROOT)),
                "sha256": _sha256(DSR_SOURCE),
            },
            "analysis_script": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": _sha256(Path(__file__).resolve()),
            },
        },
        "claim_boundary": (
            "Contract geometry and prospective planning only. This admits no sleeve, proves no "
            "alpha, changes no live strategy and does not predict ten admissions."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
