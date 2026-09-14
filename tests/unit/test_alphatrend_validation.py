"""Independent arithmetic and timing guards for validation diagnostics."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_hac_zero_lag_matches_direct_sandwich():
    analysis = module("analyze_alphatrend_validation_corrected")
    rng = np.random.default_rng(18)
    x = rng.normal(size=(200, 2))
    y = 0.001 + x @ np.array([0.2, 0.4]) + rng.normal(size=200) * 0.01
    observed = analysis.hac_ols(y, x, lags=0)
    design = np.column_stack([np.ones(len(y)), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ coef
    pinv = np.linalg.pinv(design)
    covariance = pinv @ np.diag(residual**2) @ pinv.T * 200 / 197
    np.testing.assert_allclose(observed["coefficients"], coef)
    np.testing.assert_allclose(observed["standard_errors"], np.sqrt(np.diag(covariance)))
    with pytest.raises(ValueError, match="Rank-deficient"):
        analysis.hac_ols(y, np.ones((200, 2)))


def test_paired_bootstrap_identical_paths_have_zero_difference():
    analysis = module("analyze_alphatrend_validation_corrected")
    returns = np.random.default_rng(41).normal(0.0002, 0.01, size=200)
    assert analysis.paired_interval(np.column_stack([returns, returns]), draws=100) == [0.0, 0.0]


def test_factor_close_is_not_available_in_same_midnight_equity_and_no_gap_fill():
    analysis = module("analyze_alphatrend_validation_corrected")
    friday, monday, tuesday = [
        int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)
        for d in ["2024-01-05", "2024-01-08", "2024-01-09"]
    ]
    wednesday = int(pd.Timestamp("2024-01-10", tz="UTC").timestamp() * 1000)
    bars = pd.DataFrame(
        {
            "ts_open": [friday, monday, tuesday],
            "instrument_id": ["A"] * 3,
            "close": [100.0, 110.0, 121.0],
        }
    )
    returns = analysis.align_factors(bars)
    assert returns.index.tolist() == [monday, tuesday, wednesday]
    assert np.isnan(returns.loc[monday, "A"])
    assert np.isclose(returns.loc[tuesday, "A"], 0.1)
    bars.loc[1, "close"] = np.nan
    assert analysis.align_factors(bars).isna().all().all()


def test_cost_stress_does_not_mutate_base_or_other_settings():
    from alphaforge.config.settings import load_settings

    stress = module("validate_alphatrend_directional")
    root = Path(__file__).resolve().parents[2]
    original = load_settings("managed_futures", root=root)
    before = original.model_dump(mode="json")
    scenario = stress.stressed_settings(original).model_dump(mode="json")
    assert original.model_dump(mode="json") == before
    for key in stress.COST_KEYS:
        assert scenario["costs"][key] == 2 * before["costs"][key]
        scenario["costs"][key] = before["costs"][key]
    assert scenario == before
