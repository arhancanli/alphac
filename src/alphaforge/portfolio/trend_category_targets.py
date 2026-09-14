"""Fixed research category mask; no production selection or learned exclusions."""

import numpy as np

from alphaforge.portfolio.trend_direction_confirmation import ConfirmedDirectionStrategy

EQUITY_IDS = frozenset(f"XUSE:CASH:{s}USD" for s in ("SPY", "QQQ", "IWM", "EFA", "EEM"))
OTHER_IDS = frozenset(
    f"XUSE:CASH:{s}USD"
    for s in ("SHY", "IEF", "TLT", "DBA", "DBC", "GLD", "SLV", "UNG", "USO", "FXE", "FXY", "UUP")
)


class CategoryTargetsStrategy(ConfirmedDirectionStrategy):
    """Mask only equity-ETF shorts after sizing, retaining every non-equity sign."""

    def _retain_cash(self, weights, ids, ctx):
        if not set(ids) <= EQUITY_IDS | OTHER_IDS:
            raise ValueError("Unclassified research instrument")
        eligible = super()._retain_cash(weights, ids, ctx)
        if not np.isfinite(eligible).all():
            raise ValueError("Category targets require finite weights")
        mask = np.array([iid in EQUITY_IDS for iid in ids])
        return np.where(mask, np.maximum(eligible, 0.0), eligible)
