"""Synthetic integration evidence for raw covariance and forward-label defects."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from alphamax_share_ratio_features import share_ratio_close

from alphaforge.backtest.engine import StrategyContext
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.labeling import forward_returns
from alphaforge.portfolio.strategy import BlendStrategy


def world():
    cal = XNYSCalendar()
    start = int(pd.Timestamp("2018-01-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
    grid = cal.expected_bar_opens(start, end, Timeframe.D1)
    economic = pd.DataFrame({"SYNTH": 100 * np.exp(np.arange(len(grid)) * 0.001)}, index=grid)
    raw = economic.copy()
    ex = grid[-40]
    raw.loc[ex:] /= 4
    actions = pd.DataFrame(
        [
            {
                "instrument_id": "SYNTH",
                "action_type": "split",
                "ex_date": ex,
                "available_at": ex,
                "ratio": 4.0,
                "cash_amount": np.nan,
            }
        ]
    )
    return cal, economic, raw, actions


def test_raw_covariance_has_artificial_split_shock():
    _, economic, raw, actions = world()
    original = raw.pct_change(fill_method=None)
    fixed = share_ratio_close(raw, actions).pct_change(fill_method=None)
    ex = actions.ex_date.iloc[0]
    assert original.loc[ex, "SYNTH"] == pytest.approx(np.exp(0.001) / 4 - 1)
    assert fixed.loc[ex, "SYNTH"] == pytest.approx(np.exp(0.001) - 1)
    np.testing.assert_allclose(
        fixed, economic.pct_change(fill_method=None), atol=2e-15, equal_nan=True
    )


def test_raw_open_holding_label_invents_split_loss():
    cal, economic, raw, actions = world()

    def label(panel):
        bars = panel.rename_axis("ts_open").reset_index().rename(columns={"SYNTH": "open"})
        bars["instrument_id"] = "SYNTH"
        return forward_returns(bars, 21, timeframe=Timeframe.D1, calendar=cal)

    original = label(raw)
    corrected = label(share_ratio_close(raw, actions))
    reference = label(economic)
    decision = raw.index[-50]
    assert original.loc[(decision, "SYNTH")] == pytest.approx(0.021 - np.log(4))
    assert corrected.loc[(decision, "SYNTH")] == pytest.approx(0.021)
    np.testing.assert_allclose(corrected, reference, atol=2e-15, equal_nan=True)


def test_real_context_underfetches_covariance_session_window():
    cal, _, raw, _ = world()
    rows = pd.DataFrame(
        {"instrument_id": "SYNTH", "ts_open": raw.index, "close": raw.SYNTH.to_numpy()}
    )

    class Reader:
        def ohlcv(self, ids, *, start, end, as_of, tf):
            assert end == as_of
            return pa.Table.from_pandas(
                rows[(rows.ts_open >= start) & (rows.ts_open < end)], preserve_index=False
            )

    ts = cal.next_bar_open(int(raw.index[-1]), Timeframe.D1)
    ctx = StrategyContext(
        reader=Reader(),
        tf=Timeframe.D1,
        ts=ts,
        equity=100000,
        positions={},
        instruments={},
        asset_class=AssetClass.EQUITY,
    )
    panel = BlendStrategy._close_panel(SimpleNamespace(_cov_window_bars=300), ctx, ["SYNTH"])
    assert len(panel) == 301
    # Full source has all301 requested sessions; context requests301calendar days.
    assert 190 < int(panel.SYNTH.notna().sum()) < 230
    assert panel.iloc[:70].SYNTH.isna().all()
    assert raw.loc[panel.index].SYNTH.notna().all()


def test_session_reader_recovers_complete_window_and_preserves_real_gaps():
    from alphamax_session_price_basis import session_close_panel

    cal, economic, raw, actions = world()
    rows = pd.DataFrame(
        {"instrument_id": "SYNTH", "ts_open": raw.index, "close": raw.SYNTH.to_numpy()}
    )
    missing = int(raw.index[-10])

    class Reader:
        def __init__(self, drop=False):
            self.drop = drop

        def ohlcv(self, ids, *, start, end, as_of, tf):
            assert as_of == end
            f = rows[(rows.ts_open >= start) & (rows.ts_open < end)]
            if self.drop:
                f = f[f.ts_open != missing]
            return pa.Table.from_pandas(f, preserve_index=False)

        def corporate_actions(self, ids, *, start, end, as_of):
            f = actions[
                (actions.ex_date >= start)
                & (actions.ex_date < end)
                & (actions.available_at <= as_of)
            ]
            return pa.Table.from_pandas(f, preserve_index=False)

    ts = cal.next_bar_open(int(raw.index[-1]), Timeframe.D1)
    ctx = StrategyContext(
        reader=Reader(),
        tf=Timeframe.D1,
        ts=ts,
        equity=100000,
        positions={},
        instruments={},
        asset_class=AssetClass.EQUITY,
    )
    panel = session_close_panel(Reader(), ctx, ["SYNTH"], 301, correct_splits=False)
    assert panel.SYNTH.notna().sum() == 301
    np.testing.assert_array_equal(panel.SYNTH, raw.loc[panel.index].SYNTH)
    fixed = session_close_panel(Reader(), ctx, ["SYNTH"], 301, correct_splits=True)
    np.testing.assert_allclose(
        fixed.pct_change(fill_method=None),
        economic.loc[fixed.index].pct_change(fill_method=None),
        atol=2e-15,
        equal_nan=True,
    )
    gapped = session_close_panel(Reader(True), ctx, ["SYNTH"], 301, correct_splits=True)
    assert gapped.loc[missing].isna().all()
    assert gapped.SYNTH.notna().sum() == 300
