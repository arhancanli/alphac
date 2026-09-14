from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from scripts.collect_alphabet_prospective import quote_diagnostic

from alphaforge.portfolio.trend_cost_policy import TrendCostPolicy, TrendCostRow


def policy(cost=0.005):
    return TrendCostPolicy((TrendCostRow("A", "long", 10, 30, 9, cost, "fixture"),), "modeled")


def frame():
    return pd.DataFrame(
        {"mu_ann": [0.08, np.nan]},
        index=pd.MultiIndex.from_tuples([(10, "A"), (20, "A")], names=["ts_open", "instrument_id"]),
    )


def test_signal_horizon_not_rebalance_cadence():
    f = frame()
    assert policy().apply(f, horizon_bars=21, periods_per_year=252).mu_ann.iloc[0] == 0.08
    assert policy().apply(f, horizon_bars=10, periods_per_year=252).mu_ann.iloc[0] == 0
    assert f.mu_ann.iloc[0] == 0.08
    assert np.isnan(policy().apply(f, horizon_bars=21, periods_per_year=252).mu_ann.iloc[1])


def test_cost_side_and_timestamp_coverage_fail_closed():
    f = frame()
    f.iloc[0, 0] = -0.08
    with pytest.raises(ValueError, match="coverage"):
        policy().apply(f, horizon_bars=21, periods_per_year=252)


def test_future_known_cost_and_overlaps_rejected():
    with pytest.raises(ValueError):
        TrendCostPolicy((TrendCostRow("A", "long", 10, 30, 11, 0.005, "fixture"),), "modeled")
    with pytest.raises(ValueError, match="Overlapping"):
        TrendCostPolicy(policy().rows * 2, "modeled")


def test_cost_and_horizon_change_trial_binding():
    assert (
        policy().binding(horizon_bars=21, periods_per_year=252)["sha256"]
        != policy(0.006).binding(horizon_bars=21, periods_per_year=252)["sha256"]
    )


@pytest.mark.parametrize("offset,expected", [(0, True), (2, False), (-1, False)])
def test_quote_staleness_and_future_source(offset, expected):
    q = {"bp": 100, "ap": 101, "bs": 1, "as": 1, "t": "2026-09-11T18:00:00Z"}
    from datetime import timedelta

    result = quote_diagnostic(
        {"GOOG": q, "GOOGL": q}, datetime(2026, 9, 11, 18, tzinfo=UTC) + timedelta(seconds=offset)
    )
    assert result["valid_pair"] is expected
    assert result["execution_eligible"] is False


def test_missing_leg_and_crossed_quote_rejected():
    assert not quote_diagnostic({}, datetime.now(UTC))["valid_pair"]
    q = {"bp": 102, "ap": 101, "bs": 1, "as": 1, "t": "2026-09-11T18:00:00Z"}
    assert not quote_diagnostic({"GOOG": q, "GOOGL": q}, datetime.now(UTC))["valid_pair"]


def test_cost_gate_cannot_hide_mu_units_error():
    f = frame()
    f.iloc[0, 0] = 10
    with pytest.raises(ValueError, match="contract"):
        policy(100).apply(f, horizon_bars=21, periods_per_year=252)


def test_cash_mode_keeps_original_mu_and_records_new_identity():
    from dataclasses import replace

    f = frame()
    original = policy(1)
    cash = replace(original, allocation_mode="retain_cash")
    filtered = original.apply(f, horizon_bars=21, periods_per_year=252)
    retained = cash.apply(f, horizon_bars=21, periods_per_year=252)
    assert filtered.mu_ann.iloc[0] == 0
    assert retained.mu_ann.iloc[0] == f.mu_ann.iloc[0]
    assert not retained.cash_retention_eligible.iloc[0]
    assert (
        cash.binding(horizon_bars=21, periods_per_year=252)["sha256"]
        != original.binding(horizon_bars=21, periods_per_year=252)["sha256"]
    )


def test_old_filter_redistributes_equal_vol_allocations():
    from alphaforge.portfolio.optimizer import PortfolioConstraints, TrendVolTarget

    solver = TrendVolTarget(PortfolioConstraints(w_max=1, gross_max=1))
    args = (np.eye(3) * 0.04, np.zeros(3), np.zeros(3), np.ones(3))
    base = solver.solve(np.array([0.1, 0.1, 0.1]), *args).weights
    filtered = solver.solve(np.array([0, 0.1, 0.1]), *args).weights
    assert filtered[1] > base[1]
    assert filtered[2] > base[2]
