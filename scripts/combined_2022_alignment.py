"""Explicit source-session/UTC-day alignment for frozen combined diagnostics."""

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

DAY = 86400000
START = 1640995200000
END = 1672531200000
PREDECESSOR = START - DAY


def equity_daily(frame, *, next_session_label):
    cal = XNYSCalendar()
    sessions = cal.expected_bar_opens(PREDECESSOR, END, Timeframe.D1)
    marks = [cal.next_bar_open(t, Timeframe.D1) if next_session_label else t for t in sessions]
    if frame.ts.duplicated().any():
        raise ValueError("duplicate equity marks")
    saved = frame.set_index("ts").equity
    if not set(marks).issubset(saved.index):
        raise ValueError("missing required session or predecessor")
    values = saved.loc[marks].to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("invalid equity values")
    returns = pd.Series(values, index=sessions).pct_change().iloc[1:]
    daily = returns.reindex(np.arange(START, END, DAY))
    expected = set(sessions[1:])
    if any(pd.isna(v) and day in expected for day, v in daily.items()):
        raise ValueError("missing trading session cannot become zero")
    return daily.fillna(0.0).to_numpy()


def crypto_daily(frame):
    # Full UTC-day endpoints, including Jan1 2023 midnight. Unlike prior
    # standalone23UTC diagnostic, this matches the overlay's complete daily bar.
    marks = np.arange(START, END + DAY, DAY)
    if frame.ts.duplicated().any():
        raise ValueError("duplicate crypto marks")
    values = frame.set_index("ts").equity.loc[marks]
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("invalid crypto equity")
    return values.pct_change().iloc[1:].to_numpy()
