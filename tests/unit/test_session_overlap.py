import pandas as pd
import pytest

from alphaforge.analytics.session_overlap import session_intervals


def curve(dates, values):
    return pd.Series(
        values, index=[int(pd.Timestamp(d, tz="UTC").timestamp() * 1000) for d in dates]
    )


def test_same_economic_interval_despite_weekend_holiday_labels():
    engine = curve(["2026-01-16", "2026-01-20", "2026-01-21"], [100.0, 110.0, 99.0])
    closes = curve(["2026-01-15", "2026-01-16", "2026-01-20"], [100.0, 110.0, 99.0])
    a, _ = session_intervals(engine, convention="engine_next_session")
    b, _ = session_intervals(closes, convention="session_close")
    pd.testing.assert_series_equal(a, b)


def test_missing_session_is_dropped_but_known_flat_is_retained():
    equity = curve(["2026-01-15", "2026-01-20", "2026-01-21"], [100.0, 110.0, 110.0])
    returns, audit = session_intervals(equity, convention="session_close")
    assert audit["dropped_multi_session_intervals"] == 1
    assert len(returns) == 1 and returns.iloc[0] == 0


def test_non_session_and_unsorted_inputs_fail():
    for equity in [
        curve(["2026-01-16", "2026-01-17"], [100.0, 110.0]),
        curve(["2026-01-20", "2026-01-16"], [100.0, 110.0]),
    ]:
        with pytest.raises(ValueError):
            session_intervals(equity, convention="session_close")
