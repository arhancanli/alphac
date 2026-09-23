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
REGISTER = REPO / "artifacts" / "research" / "prospective_epoch_register.json"
OUTPUT = REPO / "artifacts" / "analysis" / "trial_budget_cost" / "result.json"

# Pooled cross-trial Sharpe variance measured across the ledger. This is the honest V[SR] that
# replaced the ~80x-too-small value AlphaTrend had been graded against.
POOLED_V_SR = 7.96e-04
# Measured campaign hit rate: 3 survivors from 46 tested candidates.
HIT_RATE = 3 / 46
NEW_SLEEVES_WANTED = 10
DAYS_PER_YEAR = 252.0
# An admissible test is an identity batch of at least two selectable identities: the batch's PBO
# is defined only then (alphaforge.validation.trial_reservation: "pbo_defined": len(hashes) >= 2),
# and the contract gates on PBO. So one test spends two identities, never one.
MIN_IDENTITIES_PER_ADMISSIBLE_TEST = 2
# The staged ceilings priced for the v8 decision (owner, 2026-09-23: raise in steps).
V8_CEILINGS = (400, 500, 700, 1000)


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


def _binomial_at_least(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def governed_prospective_outcomes(register: dict) -> dict:
    """Admission outcomes of the governed prospective identities, read from the register.

    Development closures are excluded: they were closed by the author as exploration, never
    submitted to the admission evaluator, so they are not tests in the hit-rate sense.
    """
    governed = [i for i in register["identities"] if i.get("closure_kind") == "governed"]
    return {
        "governed_identities": len(governed),
        "admitted": sum(1 for i in governed if i.get("admitted") is True),
        "tests": math.ceil(len(governed) / MIN_IDENTITIES_PER_ADMISSIBLE_TEST),
    }


def _union_identities(register: dict, policy_observed: int) -> int:
    """Identities in the complete union: the highest governed reservation ordinal in the register.

    The policy's ``observed_hypothesis_identities`` is frozen at its last promotion (228) and the
    register has moved past it; ordinals are dense and never reused, so the highest is the count.
    """
    ordinals = [
        int(i["reservation_ordinal"])
        for i in register["identities"]
        if isinstance(i.get("reservation_ordinal"), int)
    ]
    return max([policy_observed, *ordinals])


def v8_ceiling_ladder(observed: int, prospective: dict) -> dict:
    """What each staged ceiling buys and costs, with the hit rate's uncertainty carried through.

    The hit rate is a Beta posterior on tests: Jeffreys prior, the legacy 3 of 46, and the
    governed prospective tests with their admissions. Its 5th and 95th percentiles bracket every
    probability, so an optimistic reading cannot hide behind a point estimate.
    """
    from scipy.stats import beta, binom  # scipy is a dev dependency of every analysis script

    hits = 3 + prospective["admitted"]
    tested = 46 + prospective["tests"]
    a, b = 0.5 + hits, 0.5 + tested - hits
    rates = {
        "p05": float(beta.ppf(0.05, a, b)),
        "mean": a / (a + b),
        "p95": float(beta.ppf(0.95, a, b)),
    }
    base = annualized_hurdle(observed, 3.0)
    ladder = {}
    for ceiling in V8_CEILINGS:
        tests = max(0, (ceiling - observed) // MIN_IDENTITIES_PER_ADMISSIBLE_TEST)
        hurdle3 = annualized_hurdle(ceiling, 3.0)
        ladder[str(ceiling)] = {
            "admissible_tests_remaining": tests,
            "hurdle_at_3y_sample": hurdle3,
            "hurdle_at_10y_sample": annualized_hurdle(ceiling, 10.0),
            "hurdle_increase_vs_now": hurdle3 / base - 1.0,
            "expected_new_sleeves": {k: tests * p for k, p in rates.items()},
            "probability_at_least_ten_new_sleeves": {
                k: float(binom.sf(NEW_SLEEVES_WANTED - 1, tests, p)) for k, p in rates.items()
            },
        }
    return {
        "identities_observed": observed,
        "min_identities_per_admissible_test": MIN_IDENTITIES_PER_ADMISSIBLE_TEST,
        "hit_rate_basis": {
            "legacy": "3 survivors from 46 tested candidates",
            "governed_prospective": prospective,
            "posterior": f"Beta({a}, {b}), Jeffreys prior",
            "rates": rates,
        },
        "ceilings": ladder,
    }


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

    register = json.loads(REGISTER.read_text())
    result["v8_staged_ceilings"] = v8_ceiling_ladder(
        _union_identities(register, observed), governed_prospective_outcomes(register)
    )
    v8 = result["v8_staged_ceilings"]
    for ceiling, row in v8["ceilings"].items():
        print(
            f"  ceiling {ceiling}: {row['admissible_tests_remaining']} tests, hurdle(3y) "
            f"{row['hurdle_at_3y_sample']:.3f} (+{row['hurdle_increase_vs_now']:.1%}), "
            f"P(>=10 new) p05/mean/p95 = "
            + "/".join(f"{v:.3f}" for v in row["probability_at_least_ten_new_sleeves"].values())
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(
        f"  {NEW_SLEEVES_WANTED} sleeves at a {HIT_RATE:.1%} hit rate "
        f"implies {trials_needed} trials"
    )
    print(
        f"  deflated benchmark {at_now['annualized_deflated_benchmark']:.4f} -> "
        f"{at_budget['annualized_deflated_benchmark']:.4f} annualized"
    )
    print(f"  hurdle at 3y sample:  {at_budget['hurdle_at_3y_sample']:.3f}")
    print(f"  hurdle at 20y sample: {at_budget['hurdle_at_20y_sample']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
