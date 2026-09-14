"""Fixed causal allocation diagnostic; no production or admission use."""

import numpy as np


def bounded_weights(vol):
    """Normalize inverse volatility with 10%/40% limits, no mean-return input."""
    vol = np.asarray(vol, dtype=float)
    if vol.shape != (4,) or not np.isfinite(vol).all() or np.any(vol < 0):
        raise ValueError("Expected four finite nonnegative volatilities")
    if np.any(vol == 0):
        return np.full(4, 0.25)
    score = vol.min() / vol
    lo, hi = 0.0, 1.0 / score.min()
    for _ in range(100):
        mid = (lo + hi) / 2
        if np.clip(mid * score, 0.1, 0.4).sum() > 1:
            hi = mid
        else:
            lo = mid
    return np.clip((lo + hi) / 2 * score, 0.1, 0.4)


def allocate(components, weekdays, cost_rate):
    """Use preceding 126 rows on Mondays; charge changes in target weights.

    Input four 25% sleeve contributions followed by the additive overlay.
    Costs proxy incremental allocation changes, not all underlying turnover.
    """
    c = np.asarray(components, dtype=float)
    weekdays = np.asarray(weekdays)
    if c.ndim != 2 or c.shape[1] != 5 or len(weekdays) != len(c):
        raise ValueError("Expected five components and aligned weekdays")
    if not np.isfinite(c).all() or not np.isfinite(cost_rate) or cost_rate < 0:
        raise ValueError("Inputs and cost must be finite; cost nonnegative")
    sleeves = c[:, :4] * 4
    weights = np.empty((len(c), 4))
    costs = np.zeros(len(c))
    previous = np.full(4, 0.25)
    for t in range(len(c)):
        target = previous.copy()
        if t >= 126 and weekdays[t] == 0:
            target = bounded_weights(sleeves[t - 126 : t].std(axis=0, ddof=1))
        costs[t] = cost_rate * np.abs(target - previous).sum()
        weights[t] = target
        previous = target
    gross = (weights * sleeves).sum(axis=1) + c[:, 4]
    return gross - costs, weights, costs
