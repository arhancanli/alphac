"""Synthetic dependency probes for the unchanged AlphaMax momentum input window."""

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.features.library.equity_price import adjusted_close
from alphaforge.features.library.momentum import xs_momentum


def ts(value):
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def panel():
    grid = calendar_for(AssetClass.EQUITY).expected_bar_opens(
        ts("2010-12-27"), ts("2023-01-01"), Timeframe.D1
    )
    return pd.DataFrame({"SYNTHETIC": 100 * np.exp(np.arange(len(grid)) * 0.0001)}, index=grid)


def actions(date, ratio):
    return pd.DataFrame(
        [
            {
                "instrument_id": "SYNTHETIC",
                "ex_date": ts(date),
                "available_at": ts(date),
                "action_type": "split",
                "ratio": ratio,
                "cash_amount": np.nan,
            }
        ]
    )


def momentum(raw, events):
    return xs_momentum(
        adjusted_close(raw, events, tf_ms=Timeframe.D1.ms, include_dividends=False),
        lookback=252,
        skip=21,
    )


@pytest.mark.parametrize("ratio", [0.0256, 0.1, 0.33333, 100000.0])
def test_old_action_can_change_earlier_features_but_not_replay_window(ratio):
    raw = panel()
    baseline = momentum(raw, actions("2019-12-11", 1.0))
    altered = momentum(raw, actions("2019-12-11", ratio))
    target = raw.index >= ts("2020-12-30")
    pd.testing.assert_frame_equal(baseline.loc[target], altered.loc[target], check_exact=True)
    # Positive control: this is a real perturbation, not an ignored action record.
    earlier = (raw.index >= ts("2020-01-15")) & (raw.index < ts("2020-03-01"))
    assert not baseline.loc[earlier].equals(altered.loc[earlier])


def test_action_inside_endpoint_window_is_not_declared_irrelevant():
    raw = panel()
    baseline = momentum(raw, actions("2020-06-01", 1.0))
    altered = momentum(raw, actions("2020-06-01", 4.0))
    first = ts("2020-12-30")
    assert abs(altered.loc[first, "SYNTHETIC"] - baseline.loc[first, "SYNTHETIC"]) > 1.0
