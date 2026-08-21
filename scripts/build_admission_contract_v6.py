"""Build the v6 ALPHAC sleeve-admission contract with its arithmetic derived, not typed.

Every number in the ``frontier_arithmetic`` block is computed here from the governing identity
``S_book = s_bar * sqrt(N / (1 + (N - 1) * rho_bar))`` so that the published contract cannot drift
from the arithmetic it claims to rest on. Reads no data, runs no backtest, spends no hypothesis.

Run: ``python scripts/build_admission_contract_v6.py``
(writes config/sleeve_admission_contract.json)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "config" / "archive" / "sleeve_admission_contract_v5_superseded.json"
TARGET = REPO / "config" / "sleeve_admission_contract.json"

TARGET_N = 14
ANNUALIZATION_DAYS = 252.0
# Measured per-sleeve quality, both bases published side by side because they differ and the
# difference matters: 0.529 is the three traded sleeves, 0.464 the four-curve basis that included
# an untraded curve. See artifacts/analysis/sleeve_scaling and frontier_14.
S_BAR_TRADED = 0.529
S_BAR_FOUR_CURVE = 0.464


def book_sharpe(s_bar: float, rho_bar: float, n: int = TARGET_N) -> float:
    return s_bar * math.sqrt(n / (1.0 + (n - 1) * rho_bar))


def required_rho(s_bar: float, target: float, n: int = TARGET_N) -> float:
    return ((s_bar**2 * n) / target**2 - 1.0) / (n - 1)


def required_s_bar(rho_bar: float, target: float, n: int = TARGET_N) -> float:
    return target / math.sqrt(n / (1.0 + (n - 1) * rho_bar))


def main() -> int:
    contract: dict[str, Any] = json.loads(SOURCE.read_text())
    contract["schema"] = "canli.alphac-sleeve-admission-contract.v6"
    contract["status"] = "IN_FORCE"
    contract["derived_from"] = "canli.alphac-sleeve-admission-contract.v5-proposed"
    contract["rationale"] = "docs/design/ADMISSION_V6.md"

    thresholds = contract["thresholds"]
    thresholds["minimum_oos_observations"] = 756
    thresholds["newey_west_t_min"] = 0.25
    thresholds["newey_west_t_ratio_min"] = 0.60
    thresholds["average_pairwise_correlation_upper_95_max"] = 0.10
    thresholds["capacity_usd_min"] = 500_000

    correlation_gate = thresholds["average_pairwise_correlation_max"]
    low, high = contract["objective"]["portfolio_sharpe_target"]
    psd_floor = -1.0 / (TARGET_N - 1)

    contract["frontier_arithmetic"] = {
        "claim_boundary": (
            "Derived from the governing identity alone. Reads no data, runs no backtest, spends no "
            "hypothesis, and claims no candidate's correlation, sign or return."
        ),
        "identity": "S_book = s_bar * sqrt(N / (1 + (N - 1) * rho_bar))",
        "target_sleeve_count": TARGET_N,
        "psd_floor_at_target_n": psd_floor,
        "psd_floor_note": (
            "Average pairwise correlation cannot fall below -1/(N-1) for any real correlation "
            "matrix. At fourteen sleeves that floor is far from binding, which is why a negative "
            "average is arithmetically available here and is not at 250 sleeves."
        ),
        "correlation_gate_in_force": correlation_gate,
        "book_sharpe_ceiling_at_the_gate": {
            "s_bar_traded_basis": book_sharpe(S_BAR_TRADED, correlation_gate),
            "s_bar_four_curve_basis": book_sharpe(S_BAR_FOUR_CURVE, correlation_gate),
        },
        "gate_permits_objective_floor": book_sharpe(S_BAR_TRADED, correlation_gate) >= low,
        "gate_permits_objective_ceiling": book_sharpe(S_BAR_TRADED, correlation_gate) >= high,
        "quality_precondition_at_the_gate": {
            "note": (
                "What the tightened correlation gate alone does NOT buy. At the gate exactly, "
                "reaching each end of the objective band requires at least this average "
                "standalone Sharpe across fourteen sleeves."
            ),
            f"s_bar_required_for_{low}": required_s_bar(correlation_gate, low),
            f"s_bar_required_for_{high}": required_s_bar(correlation_gate, high),
            "s_bar_measured_traded_basis": S_BAR_TRADED,
            "s_bar_measured_four_curve_basis": S_BAR_FOUR_CURVE,
        },
        "correlation_required_at_measured_quality": {
            "note": (
                "The other route to the same place: hold quality where it is measured today and "
                "read off the average pairwise correlation each end of the band demands."
            ),
            "traded_basis": {
                f"rho_bar_required_for_{low}": required_rho(S_BAR_TRADED, low),
                f"rho_bar_required_for_{high}": required_rho(S_BAR_TRADED, high),
            },
            "four_curve_basis": {
                f"rho_bar_required_for_{low}": required_rho(S_BAR_FOUR_CURVE, low),
                f"rho_bar_required_for_{high}": required_rho(S_BAR_FOUR_CURVE, high),
            },
        },
        "honest_reading": (
            "Tightening the correlation ceiling from 0.15 to 0.00 removes a ceiling that sat "
            "BELOW the objective at every plausible quality, which is why the v4 gate could not "
            "have produced the objective at any sleeve count. It does not on its own deliver the "
            "objective. At the gate exactly, fourteen sleeves of today's measured quality reach "
            "the figure recorded above, and the remaining distance has to be bought with "
            "per-sleeve quality, genuinely negative correlation, or both. Publishing this is the "
            "point: a target sitting beside a gate that forbids it is not a stretch goal."
        ),
    }

    contract["capacity_policy"] = {
        "capacity_usd_min_previous": 5_000_000,
        "capacity_usd_min": thresholds["capacity_usd_min"],
        "reason": (
            "A 5,000,000 USD floor per sleeve implies a 70,000,000 USD book at fourteen sleeves. "
            "It was written for a fund that does not exist yet, and it did not reject candidates "
            "uniformly: the return sources most likely to be genuinely anti-correlated with a "
            "momentum-and-carry book -- catastrophe bonds, municipal basis, freight, power, "
            "sovereign dislocation -- are structurally thin. The floor therefore selected AGAINST "
            "the diversification the objective depends on, which is the opposite of what a "
            "capacity gate is for."
        ),
        "what_this_does_not_relax": (
            "The capacity CURVE, its monotonicity reconciliation, and the stressed fill-ratio "
            "floor are unchanged. A candidate must still show Sharpe decaying and cost rising "
            "with capital, and must still reconcile its reported capacity to that curve."
        ),
        "review_trigger": (
            "Re-raise per sleeve when deployed capital per sleeve exceeds one fifth of this "
            "floor. Capacity is a property of the strategy, but the FLOOR is a property of the "
            "book, and a floor that outruns the book is a constraint that costs edge for nothing."
        ),
    }

    contract["significance_policy"] = {
        "newey_west_t_min": thresholds["newey_west_t_min"],
        "newey_west_t_min_role": "sign gate",
        "newey_west_t_ratio_min": thresholds["newey_west_t_ratio_min"],
        "newey_west_t_ratio_role": "autocorrelation-inflation gate",
        "primary_significance_gate": "book_sharpe_delta_lower_95_min_exclusive",
        "reason": (
            "v4 declared net_sharpe_min 0.40, newey_west_t_min 2.0 and minimum_oos_observations "
            "252 together. Because t is approximately Sharpe * sqrt(years), a candidate at the "
            "declared Sharpe floor needed 25 years of out-of-sample data to clear the t floor, and "
            "at the declared 252-observation minimum the pair demanded a standalone Sharpe of 2.0 "
            "-- five times the floor a reader of the config would see. v5 lowered the Sharpe floor "
            "to 0.15 and left the t floor at 2.0, raising the hidden requirement to 178 years. The "
            "t floor, not the Sharpe floor, had been doing the rejecting all along. It is now set "
            "where it does what it is for -- excluding wrong-signed and indistinguishable-from-"
            "zero results -- and load_admission_contract refuses any contract whose three "
            "significance floors cannot all be met at once, so this class of error cannot recur."
        ),
        "why_a_standalone_bar_is_the_wrong_instrument": (
            "When correlation binds, standalone Sharpe does not rank a candidate's portfolio "
            "value: a Sharpe 0.25 sleeve at correlation -0.05 beats a Sharpe 0.60 sleeve at "
            "+0.30. The gate that decides admission is therefore the bootstrap LOWER bound on the "
            "book-Sharpe improvement, which prices edge and correlation together, and it is "
            "strictly harder to game than either input alone."
        ),
        "minimum_oos_observations_raised_from": 252,
        "minimum_oos_observations_reason": (
            "Raised to three years because the binding constraint of this whole programme is an "
            "average pairwise correlation, and a correlation measured over 252 observations "
            "carries a sampling error near 0.063 -- twice the size of the -0.03 effect the "
            "objective turns on. Gating a number the sample cannot resolve is not a strict gate. "
            "Paired with average_pairwise_correlation_upper_95_max, which gates the bound rather "
            "than the point estimate."
        ),
    }

    overlay = contract["overlay_policy"]
    overlay["known_defect"] = {
        "site": "src/alphaforge/portfolio/strategy.py (_realized_vol_ann)",
        "description": (
            "The realized leg was measured on the post-overlay account equity curve while the "
            "ex-ante leg used pre-overlay optimizer weights. The book runs de-levered, so the "
            "realized leg lost max() essentially always and the fast regime detector never fired."
        ),
        "measured_bind_fraction_as_shipped": 0.000193,
        "measured_bind_fraction_if_fixed": 0.817626,
        "expected_max_drawdown_cost_at_permitted_stressed_rho": 0.0217,
        "status": (
            "RESOLVED in production. The realized leg is now de-levered per bar before "
            "comparison, and tests/unit/test_overlay_realized_leg_scale.py pins the caller's "
            "value rather than the function's intention."
        ),
    }
    overlay["remaining_gap_to_the_drawdown_objective"] = (
        "Production still runs cov_halflife_bars=720. The measured study holds expected maximum "
        "drawdown at 10.2% only with BOTH the realized-leg scale correction (shipped) and the "
        "covariance halflife shortened to 21 (not shipped). Either alone is insufficient. The "
        "objective is an EXPECTED maximum drawdown; no tested configuration held the 95th "
        "percentile at or under 11%, and the best was 13.8%. Both figures are published."
    )

    contract["claim_boundary"] = (
        "Passing this contract makes a result technically eligible for an explicit admission "
        "decision. It does not guarantee a sleeve, future performance, the target Sharpe, or the "
        "target drawdown. Point estimates cannot override confidence-bound, crisis-conditional, "
        "tail-loss, execution-evidence, or capacity-reconciliation failures. v6 additionally "
        "refuses to load if its own significance floors cannot all be satisfied at once, gates "
        "the average pairwise correlation on its upper confidence bound as well as its point "
        "estimate, and publishes the arithmetic relating the correlation gate to the portfolio "
        "objective -- including the distance the gate does not close."
    )

    base = 21
    contract["evidence_checks_per_candidate"] = (
        len(contract["required_lineage"])
        + len(contract["required_robustness"])
        + len(contract["execution_dimensions"])
        + base
        + 8
    )

    TARGET.write_text(json.dumps(contract, indent=2, sort_keys=False) + "\n")
    print(f"wrote {TARGET.relative_to(REPO)}")
    print(f"  evidence_checks_per_candidate = {contract['evidence_checks_per_candidate']}")
    fa = contract["frontier_arithmetic"]
    print(f"  ceiling at the gate (traded basis) = "
          f"{fa['book_sharpe_ceiling_at_the_gate']['s_bar_traded_basis']:.4f}")
    print(f"  gate_permits_objective_floor = {fa['gate_permits_objective_floor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
