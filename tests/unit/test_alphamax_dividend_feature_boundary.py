"""Dividend corrections must not alter the retained split-only feature baseline."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow as pa
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.features.library.equity_price import eq_mom_252_21
from alphamax_share_ratio_service import substituted_specs
from alphamax_session_price_basis import session_close_panel
from alphamax_total_return_momentum import total_return_momentum


def world():
    cal = XNYSCalendar()
    grid = cal.expected_bar_opens(1577836800000, 1661990400000, Timeframe.D1)[:600]
    raw = pd.DataFrame({'SYNTH': 100 * np.exp(np.arange(len(grid)) * .001)},
                       index=pd.Index(grid, name='ts_open'))
    raw.iloc[300:] /= 4
    actions = pd.DataFrame([
        dict(instrument_id='SYNTH', action_type='split', ex_date=grid[300],
             available_at=grid[300], ratio=4., cash_amount=np.nan),
        dict(instrument_id='SYNTH', action_type='dividend', ex_date=grid[350],
             available_at=grid[350], ratio=np.nan, cash_amount=1.08),
        dict(instrument_id='SYNTH', action_type='dividend', ex_date=grid[400],
             available_at=grid[400], ratio=np.nan, cash_amount=.93),
    ])
    reviewed = actions.drop(index=1).copy()
    reviewed.loc[2, 'cash_amount'] = .925
    return cal, raw, actions, reviewed


class Context:
    def __init__(self, raw, actions):
        self.raw, self.actions = raw, actions
    def panel(self, field):
        assert field in {'open', 'close'}
        return self.raw.copy()
    def corporate_actions(self):
        return self.actions.copy()


def test_service_specs_ignore_cash_edits_but_total_return_control_detects_them():
    _, raw, original, reviewed = world()
    snapshots = [raw.copy(deep=True), original.copy(deep=True), reviewed.copy(deep=True)]
    specs = substituted_specs([eq_mom_252_21()], 'momentum_sigma')
    for spec in specs:
        before = spec.fn(Context(raw, original), spec)
        after = spec.fn(Context(raw, reviewed), spec)
        pd.testing.assert_series_equal(before, after, check_exact=True)
        assert before.notna().any()
    # Positive control: the same deletion/amendment must affect a dividend-aware
    # signal. Otherwise an inert fixture could falsely establish this boundary.
    before = total_return_momentum(raw, original)
    after = total_return_momentum(raw, reviewed)
    assert (before - after).abs().max().max() > .001
    for actual, expected in zip([raw, original, reviewed], snapshots):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_covariance_reader_path_ignores_cash_edits_and_preserves_split_returns():
    cal, raw, original, reviewed = world()
    ctx = SimpleNamespace(asset_class=AssetClass.EQUITY, calendar=cal,
                          tf=Timeframe.D1, ts=cal.next_bar_open(int(raw.index[-1]), Timeframe.D1))
    class Reader:
        def __init__(self, actions): self.actions = actions
        def ohlcv(self, ids, **kwargs):
            return pa.Table.from_pandas(raw.rename_axis(columns='instrument_id').stack()
                .rename('close').reset_index(), preserve_index=False)
        def corporate_actions(self, ids, **kwargs):
            return pa.Table.from_pandas(self.actions, preserve_index=False)
    a = session_close_panel(Reader(original), ctx, ['SYNTH'], len(raw), correct_splits=True)
    b = session_close_panel(Reader(reviewed), ctx, ['SYNTH'], len(raw), correct_splits=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    np.testing.assert_allclose(np.log(a).diff().iloc[1:], .001, atol=2e-15)
