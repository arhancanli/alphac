"""Calendar-aware equity-session reports; preserve elapsed-time CAGR.

The legacy summary assumes 365 observations/year after dropping empty days.
That overstates risk-adjusted metrics for a session-only equity series. This
additive entry point retains original cashflows and corrects annualization.
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from alphaforge.analytics.metrics import (
    PerfSummary,
    sharpe,
    sortino,
    summarize,
    to_returns,
    turnover,
)
from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass


def summarize_equity_sessions(
    equity: pd.Series,
    *,
    fills: pd.DataFrame | None = None,
    funding: pd.Series | None = None,
    positions: pd.DataFrame | None = None,
) -> PerfSummary:
    """Summarize one observation per XNYS session at 252 periods/year.

    Input timestamps follow the engine's midnight session-label convention.
    This is not suitable for intraday or calendar-day-filled equity curves.
    """
    calendar = calendar_for(AssetClass.EQUITY)
    expected = calendar.expected_bar_opens(
        int(equity.index.min()), int(equity.index.max()) + 1, Timeframe.D1
    )
    if list(equity.index) != expected:
        raise ValueError("Expected one equity observation per consecutive XNYS session")
    base = summarize(equity, fills=fills, funding=funding, positions=positions)
    annualization = calendar.periods_per_year(Timeframe.D1)
    returns = to_returns(equity)
    turnover_ann = base.turnover_ann
    if fills is not None:
        notionals = pd.Series(fills.notional.to_numpy(dtype=float), index=fills.ts.to_numpy())
        turnover_ann = turnover(notionals, equity, annualization)
    return replace(
        base,
        sharpe=sharpe(returns, annualization),
        sharpe_hourly=sharpe(returns, annualization),
        sortino=sortino(returns, annualization),
        sortino_hourly=sortino(returns, annualization),
        vol_ann=float(returns.std(ddof=1) * np.sqrt(annualization)),
        vol_ann_hourly=float(returns.std(ddof=1) * np.sqrt(annualization)),
        turnover_ann=turnover_ann,
    )
