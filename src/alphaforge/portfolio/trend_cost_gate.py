"""Opt-in research candidate: suppress trends below an explicit cost break-even hurdle.

Not selected by any live profile. This is a new construction hypothesis, not a
validated improvement. Expected return calibration and cost inputs are caller evidence.
"""

from __future__ import annotations

import numpy as np

from alphaforge.portfolio.optimizer import (
    OptResult,
    PortfolioConstraints,
    TrendVolTarget,
    winsorize_mu_ann,
)


class CostGatedTrendVolTarget:
    """Filter the baseline's directional signals before inverse-vol allocation.

    Keep a signal only when abs(expected annual return) * holding_years exceeds
    its supplied all-in round-trip cost fraction. Cost includes commission,
    spread, impact and applicable borrow/financing; unknown cost blocks evaluation.
    There is no fitted multiplier or added lookback. The caller must specify the
    expected holding period and the annualization convention of mu explicitly.

    The hurdle is reapplied at every rebalance, including existing positions.
    It is deliberately conservative about costs for held positions; it is not a
    turnover optimizer. Remaining names use the baseline allocation and caps, so
    concentration can increase. An empty eligible set remains cash.
    """

    def __init__(self, *, holding_years: float, constraints: PortfolioConstraints | None = None):
        if isinstance(holding_years, bool) or not np.isfinite(holding_years) or holding_years <= 0:
            raise ValueError("holding_years must be finite and positive")
        self.holding_years = holding_years
        self.baseline = TrendVolTarget(constraints)

    def solve(
        self,
        mu_ann: np.ndarray,
        cov_ann: np.ndarray,
        w_prev: np.ndarray,
        cost_frac_oneway: np.ndarray,
        shortable: np.ndarray,
        *,
        all_in_round_trip_cost: np.ndarray,
    ) -> OptResult:
        # Validate unmasked signals and the original optimizer inputs first: NaN mu
        # must not be silently turned into a zero signal by the comparison below.
        self.baseline.solve(mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable)
        mu, _ = winsorize_mu_ann(np.asarray(mu_ann, dtype=float))
        costs = np.asarray(all_in_round_trip_cost, dtype=float)
        if costs.shape != mu.shape or not np.isfinite(costs).all() or (costs < 0).any():
            raise ValueError("Complete finite nonnegative per-asset round-trip costs required")
        expected = np.abs(mu) * self.holding_years
        if not np.isfinite(expected).all():
            raise ValueError("Non-finite expected holding return")
        filtered = np.where(expected > costs, mu, 0.0)
        return self.baseline.solve(filtered, cov_ann, w_prev, cost_frac_oneway, shortable)
