import numpy as np
import pandas as pd
import pytest
from combined_2022_alignment import DAY, END, PREDECESSOR, START, crypto_daily, equity_daily

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe


def fixture_frame():
    cal = XNYSCalendar()
    sessions = cal.expected_bar_opens(PREDECESSOR, END, Timeframe.D1)
    return sessions, pd.DataFrame(
        {
            "ts": [cal.next_bar_open(t, Timeframe.D1) for t in sessions],
            "equity": 100.0 * 1.001 ** np.arange(len(sessions)),
        }
    )


def test_source_session_friday_return_not_monday_and_final_session_retained():
    sessions, frame = fixture_frame()
    r = equity_daily(frame, next_session_label=True)
    assert len(r) == 365
    assert np.count_nonzero(r) == 251
    # Jan7 Friday return; Jan8/9 weekend zero, Dec30 included, Dec31 zero.
    assert r[6] == pytest.approx(0.001)
    assert r[7] == r[8] == r[-1] == 0
    assert r[-2] == pytest.approx(0.001)
    source = frame.assign(ts=sessions)
    np.testing.assert_array_equal(r, equity_daily(source, next_session_label=False))


def test_missing_session_rejected_instead_of_padding():
    _, f = fixture_frame()
    with pytest.raises(ValueError, match="missing required"):
        equity_daily(f.drop(index=4), next_session_label=True)


def test_crypto_full_utc_day_boundary():
    f = pd.DataFrame(
        {"ts": np.arange(START, END + DAY, DAY), "equity": 100.0 * 1.001 ** np.arange(366)}
    )
    r = crypto_daily(f)
    assert len(r) == 365
    np.testing.assert_allclose(r, 0.001)
    with pytest.raises(KeyError):
        crypto_daily(f.iloc[:-1])
