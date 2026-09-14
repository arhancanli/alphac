"""Compare archived curves only over identical, consecutive close intervals."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd

from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass


def session_intervals(equity: pd.Series, *, convention: str) -> tuple[pd.Series, dict]:
    """Map engine next-session labels or native close labels to economic intervals.

    Missing observations are never flat returns. Drop multi-session intervals
    rather than assigning their accumulated return to a one-session comparison.
    """
    if convention not in {"engine_next_session", "session_close"}:
        raise ValueError("Unknown timestamp convention")
    if len(equity) < 2 or not equity.index.is_unique or not equity.index.is_monotonic_increasing:
        raise ValueError("Expected at least two ordered unique equity observations")
    if not np.isfinite(equity).all() or not (equity > 0).all():
        raise ValueError("Equity must be positive and finite")
    cal = calendar_for(AssetClass.EQUITY)
    stamps = [int(t) for t in equity.index]
    if any(cal.floor_bar(t, Timeframe.D1) != t for t in stamps):
        raise ValueError("Expected midnight XNYS session labels")
    labels = (
        [cal.floor_bar(t - 1, Timeframe.D1) for t in stamps]
        if convention == "engine_next_session"
        else stamps
    )
    valid = np.array([cal.next_bar_open(a, Timeframe.D1) == b for a, b in pairwise(labels)])
    returns = equity.to_numpy()[1:] / equity.to_numpy()[:-1] - 1
    index = pd.MultiIndex.from_arrays([labels[:-1], labels[1:]], names=["start_close", "end_close"])
    result = pd.Series(returns, index=index).loc[valid]
    return result, {
        "observations": len(equity),
        "consecutive_intervals": len(result),
        "dropped_multi_session_intervals": int((~valid).sum()),
        "convention": convention,
    }
