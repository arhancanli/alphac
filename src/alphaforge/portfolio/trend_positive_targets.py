"""Research-only positive-target mask for the confirmed-direction strategy."""

import numpy as np

from alphaforge.portfolio.trend_direction_confirmation import ConfirmedDirectionStrategy


class PositiveTargetsStrategy(ConfirmedDirectionStrategy):
    """Retain positive sized targets and leave rejected short allocations in cash.

    The parent calls this hook after volatility scaling and per-name clipping,
    before storing pre-ladder targets. Thus daily risk re-emission cannot revive
    a rejected short. No re-grossing follows the mask. Direction memory continues
    to track both signs. Parent volatility sizing still uses the unmasked book;
    this variant does not promise to attain its volatility target.
    """

    def _retain_cash(self, weights, ids, ctx):
        eligible = super()._retain_cash(weights, ids, ctx)
        if not np.isfinite(eligible).all():
            raise ValueError("Positive-target mask requires finite weights")
        return np.maximum(eligible, 0.0)
