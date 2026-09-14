"""Frozen unlevered volatility-control research rule; no deployment interface."""

import numpy as np


def scales(returns, weekdays):
    returns = np.asarray(returns, dtype=float)
    weekdays = np.asarray(weekdays)
    if returns.ndim != 1 or weekdays.shape != returns.shape or not np.isfinite(returns).all():
        raise ValueError("finite aligned daily observations required")
    output = np.ones(len(returns))
    current = 1.0
    for i in range(len(returns)):
        if i >= 63 and weekdays[i] == 0:
            volatility = returns[i - 63 : i].std(ddof=1) * np.sqrt(365)
            current = min(1.0, 0.05 / volatility) if volatility else 1.0
        output[i] = current
    return output


def apply_control(returns, weekdays, cost_rate):
    factor = scales(returns, weekdays)
    cost = cost_rate * np.abs(np.diff(np.r_[1.0, factor]))
    return factor * np.asarray(returns) - cost, factor, cost
