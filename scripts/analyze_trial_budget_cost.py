"""Price a prospective trial budget before it is authorized.

Every hypothesis identity raises the deflation hurdle for EVERY sleeve already in the book, not
only for the new candidate. A budget decision is therefore a decision about the whole book's
evidence standard, and it should be made with that cost on the table rather than inferred later.

Reads the trial-accounting policy and the production DSR implementation. Opens no return data,
runs no backtest, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from alphaforge.validation.dsr import expected_max_sharpe

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "config" / "trial_accounting.json"
OUTPUT = REPO / "artifacts" / "analysis" / "trial_budget_cost" / "result.json"

# Pooled cross-trial Sharpe variance measured across the ledger. This is the honest V[SR] that
# replaced the ~80x-too-small value AlphaTrend had been graded against.
POOLED_V_SR = 7.96e-04
# Measured campaign hit rate: 3 survivors from 46 tested candidates.
HIT_RATE = 3 / 46
NEW_SLEEVES_WANTED = 10
DAYS_PER_YEAR = 252.0


def annualized_hurdle(n_trials: int, years: float) -> float:
    """Annualized Sharpe a candidate must beat, at `n_trials` selection and `years` of sample.

    ``expected_max_sharpe`` returns a PER-PERIOD benchmark, so it is annualized by sqrt(252) the
    same way the analytics harness annualizes any per-period Sharpe. The sample length enters
    because the PSR converts to a standard-error-scaled statistic over the observation count: a
    longer record defeats deflation that a shorter one cannot.
    """
    per_period = expected_max_sharpe(n_trials, POOLED_V_SR)
    hurdle = per_period * math.sqrt(DAYS_PER_YEAR)
    # 1.96 standard errors of an annualized Sharpe over `years`, added to the deflated benchmark.
    return hurdle + 1.96 / math.sqrt(years)


def main() -> int:
    policy = json.loads(POLICY.read_text())
    observed = policy["observed_hypothesis_identities"]
    trials_needed = math.ceil(NEW_SLEEVES_WANTED / HIT_RATE)

    ladder = {}
    for extra in (0, 50, 100, trials_needed, 200, 300):
        total = observed + extra
        ladder[str(total)] = {
            "extra_trials": extra,
            "expected_max_sharpe_per_period": expected_max_sharpe(total, POOLED_V_SR),
            "annualized_deflated_benchmark": expected_max_sharpe(total, POOLED_V_SR)
            * math.sqrt(DAYS_PER_YEAR),
            "hurdle_at_3y_sample": annualized_hurdle(total, 3.0),
            "hurdle_at_10y_sample": annualized_hurdle(total, 10.0),
            "hurdle_at_20y_sample": annualized_hurdle(total, 20.0),
        }

    at_now = ladder[str(observed)]
    at_budget = ladder[str(observed + trials_needed)]

    result = {
        "schema": "canli.alphac-trial-budget-cost.v1",
        "claim_boundary": (
            "Derived from the trial-accounting policy and the production DSR implementation. "
            "Opens no return data, runs no backtest, registers no hypothesis. 0 trials."
        ),
        "observed_hypothesis_identities": observed,
        "measured_hit_rate": HIT_RATE,
        "hit_rate_basis": "3 survivors from 46 tested candidates",
        "new_sleeves_wanted": NEW_SLEEVES_WANTED,
        "trials_implied_at_measured_hit_rate": trials_needed,
        "pooled_cross_trial_sharpe_variance": POOLED_V_SR,
        "hurdle_ladder": ladder,
        "cost_of_the_budget": {
            "deflated_benchmark_now": at_now["annualized_deflated_benchmark"],
            "deflated_benchmark_after": at_budget["annualized_deflated_benchmark"],
            "increase": at_budget["annualized_deflated_benchmark"]
            - at_now["annualized_deflated_benchmark"],
            "applies_to": (
                "every sleeve in the book, not only the new candidates. Deflation is a property "
                "of the search, and the search is the book's."
            ),
        },
        "honest_reading": (
            "The deflated benchmark rises with the LOGARITHM of the trial count, so a budget of "
            f"{trials_needed} on top of {observed} costs less than intuition suggests: the "
            f"benchmark moves from {at_now['annualized_deflated_benchmark']:.3f} to "
            f"{at_budget['annualized_deflated_benchmark']:.3f} annualized. Sample length is the "
            "stronger lever in both directions -- at three years the hurdle is "
            f"{at_budget['hurdle_at_3y_sample']:.2f} and at twenty it is "
            f"{at_budget['hurdle_at_20y_sample']:.2f}. This is why the contract's raised "
            "three-year minimum matters more to admissibility than the budget does, and why a "
            "pre-registered forward record remains the only thing that defeats deflation "
            "outright: it is N=1 by construction."
        ),
        "what_this_does_not_say": (
            "It does not say the budget is affordable in research TIME, only in evidence. It "
            "also assumes the measured 6.5% hit rate holds for families that have never been "
            "tested, which is an assumption and not a measurement -- the atlas families are "
            "deliberately unlike the ones that produced that rate."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(
        f"  {NEW_SLEEVES_WANTED} sleeves at a {HIT_RATE:.1%} hit rate "
        f"implies {trials_needed} trials"
    )
    print(f"  deflated benchmark {at_now['annualized_deflated_benchmark']:.4f} -> "
          f"{at_budget['annualized_deflated_benchmark']:.4f} annualized")
    print(f"  hurdle at 3y sample:  {at_budget['hurdle_at_3y_sample']:.3f}")
    print(f"  hurdle at 20y sample: {at_budget['hurdle_at_20y_sample']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
