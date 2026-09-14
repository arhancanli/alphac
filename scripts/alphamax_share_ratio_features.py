"""Opt-in equity feature math using stored new-shares/old-shares split ratios.

This module does not change the frozen legacy feature path. Only timely actions
are supported; delayed publication requires a separate causal revision model.
"""

import numpy as np

from alphaforge.core.time import Timeframe
from alphaforge.features.library.equity_price import adjusted_close
from alphaforge.features.library.vol import ewma_vol


def share_ratio_close(raw, actions):
    normalized = actions.copy(deep=True)
    splits = (
        normalized.action_type.eq("split") if not normalized.empty else np.array([], dtype=bool)
    )
    if splits.any():
        rows = normalized.loc[splits]
        applicable = (
            rows.instrument_id.isin(raw.columns)
            & (rows.ex_date > raw.index.min())
            & (rows.ex_date <= raw.index.max())
        )
        if (
            rows.loc[applicable, "available_at"] > rows.loc[applicable, "ex_date"] + Timeframe.D1.ms
        ).any():
            raise ValueError("late split publication requires causal revision model")
        ratios = rows.ratio.to_numpy(dtype=float)
        if not np.isfinite(ratios).all() or (ratios <= 0).any():
            raise ValueError("split share ratio must be finite and positive")
        normalized.loc[splits, "ratio"] = 1.0 / ratios
    return adjusted_close(raw, normalized, tf_ms=Timeframe.D1.ms, include_dividends=False)


def share_ratio_sigma(raw, actions, span=168):
    return ewma_vol(share_ratio_close(raw, actions), span=span)
