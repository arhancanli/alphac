import numpy as np
import pandas as pd
import pytest

from alphaforge.analytics.metrics import summarize
from alphaforge.analytics.session_metrics import summarize_equity_sessions


def sample():
    dates = pd.to_datetime(["2026-01-15", "2026-01-16", "2026-01-20", "2026-01-21"], utc=True)
    index = pd.Index([int(d.timestamp() * 1000) for d in dates], name="ts")
    return pd.Series([100, 102, 101, 104], index=index, dtype=float)


def test_session_annualization_and_cashflow_metrics():
    equity = sample()
    fills = pd.DataFrame({"ts": [equity.index[1]], "notional": [10.0], "fee": [0.1]})
    corrected = summarize_equity_sessions(equity, fills=fills)
    original = summarize(equity, fills=fills)
    returns = np.array([102 / 100 - 1, 101 / 102 - 1, 104 / 101 - 1])
    assert corrected.sharpe == pytest.approx(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
    assert corrected.vol_ann == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert corrected.turnover_ann == pytest.approx(10 / 102 / 4 * 252)
    assert corrected.cagr == original.cagr
    assert corrected.max_dd == original.max_dd
    assert corrected.final_equity == original.final_equity
    assert corrected.fees_paid == original.fees_paid


def test_calendar_day_padding_rejected():
    equity = sample()
    padded = equity.copy()
    padded.loc[int(pd.Timestamp("2026-01-17", tz="UTC").timestamp() * 1000)] = 102
    with pytest.raises(ValueError, match="consecutive XNYS"):
        summarize_equity_sessions(padded.sort_index())


def test_missing_session_rejected():
    with pytest.raises(ValueError, match="consecutive XNYS"):
        summarize_equity_sessions(sample().drop(sample().index[1]))
