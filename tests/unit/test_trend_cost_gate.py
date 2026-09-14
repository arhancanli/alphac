import numpy as np
import pytest

from alphaforge.portfolio.optimizer import TrendVolTarget
from alphaforge.portfolio.trend_cost_gate import CostGatedTrendVolTarget


def inputs():
    return {
        "mu_ann": np.array([0.02, -0.20, 0.10]),
        "cov_ann": np.eye(3) * 0.04,
        "w_prev": np.zeros(3),
        "cost_frac_oneway": np.full(3, 0.001),
        "shortable": np.ones(3),
    }


def test_weak_signal_is_filtered_but_strong_short_survives():
    args = inputs()
    candidate = CostGatedTrendVolTarget(holding_years=10 / 252)
    result = candidate.solve(**args, all_in_round_trip_cost=np.full(3, 0.002))
    assert result.weights[0] == 0
    assert result.weights[1] < 0 < result.weights[2]


def test_zero_cost_reproduces_baseline_exactly():
    args = inputs()
    result = CostGatedTrendVolTarget(holding_years=10 / 252).solve(
        **args, all_in_round_trip_cost=np.zeros(3)
    )
    np.testing.assert_array_equal(result.weights, TrendVolTarget().solve(**args).weights)


def test_break_even_or_worse_stays_cash():
    args = inputs()
    result = CostGatedTrendVolTarget(holding_years=1).solve(
        **args, all_in_round_trip_cost=np.abs(args["mu_ann"])
    )
    np.testing.assert_array_equal(result.weights, np.zeros(3))


def test_borrow_cost_can_block_short_and_shortability_is_preserved():
    args = inputs()
    candidate = CostGatedTrendVolTarget(holding_years=10 / 252)
    costly = candidate.solve(**args, all_in_round_trip_cost=np.array([0, 0.1, 0]))
    assert costly.weights[1] == 0
    args["shortable"][1] = 0
    unavailable = candidate.solve(**args, all_in_round_trip_cost=np.zeros(3))
    assert unavailable.weights[1] == 0


@pytest.mark.parametrize("cost", [[0, np.nan, 0], [0, np.inf, 0], [0, -0.1, 0], [0]])
def test_missing_or_invalid_costs_fail_closed(cost):
    with pytest.raises(ValueError):
        CostGatedTrendVolTarget(holding_years=1).solve(
            **inputs(), all_in_round_trip_cost=np.array(cost)
        )


def test_nonfinite_signal_cannot_be_masked():
    args = inputs()
    args["mu_ann"][0] = np.nan
    with pytest.raises(ValueError):
        CostGatedTrendVolTarget(holding_years=1).solve(**args, all_in_round_trip_cost=np.ones(3))


@pytest.mark.parametrize("years", [0, -1, np.inf, np.nan, True])
def test_invalid_holding_period(years):
    with pytest.raises(ValueError):
        CostGatedTrendVolTarget(holding_years=years)
