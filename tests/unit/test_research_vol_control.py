import numpy as np
import pandas as pd

from alphaforge.portfolio.research_vol_control import apply_control, scales


def test_future_returns_cannot_change_current_scale():
    days = pd.date_range("2020-01-01", periods=200).weekday.to_numpy()
    returns = np.sin(np.arange(200)) * 0.02
    base = scales(returns, days)
    for cut in [63, 80, 150]:
        changed = returns.copy()
        changed[cut:] = 0.2
        assert np.array_equal(scales(changed, days)[: cut + 1], base[: cut + 1])


def test_warmup_monday_updates_and_cost():
    days = pd.date_range("2020-01-01", periods=100).weekday.to_numpy()
    returns = np.sin(np.arange(100)) * 0.02
    net, factor, cost = apply_control(returns, days, 0.0001)
    assert np.all(factor[:63] == 1)
    assert all(days[i] == 0 for i in range(1, 100) if factor[i] != factor[i - 1])
    assert np.all((factor > 0) & (factor <= 1))
    assert np.allclose(cost, 0.0001 * np.abs(np.diff(np.r_[1.0, factor])))
    assert np.allclose(net + cost, factor * returns)


def test_zero_vol_and_stress_same_positions():
    days = np.arange(100) % 7
    assert np.array_equal(scales(np.zeros(100), days), np.ones(100))
    returns = np.sin(np.arange(100)) * 0.02
    net, scale, cost = apply_control(returns, days, 0.0001)
    stress, stressed_scale, stressed_cost = apply_control(returns, days, 0.0005)
    assert np.array_equal(scale, stressed_scale)
    assert np.all(stress <= net)
    assert np.allclose(stressed_cost, 5 * cost)
