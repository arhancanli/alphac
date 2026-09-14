from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from alphamax_path_service import path_specs,path_panels,corrected_path_momentum
from alphamax_share_ratio_service import corrected_momentum,corrected_sigma
from alphaforge.features.library.equity_price import eq_mom_252_21
from alphaforge.core.calendar import calendar_for
from alphaforge.core.types import AssetClass
from alphaforge.core.time import Timeframe
from alphaforge.signals.service import _OPEN_SPEC


def context(split=False):
    start=int(pd.Timestamp('2020-01-01',tz='UTC').timestamp()*1000)
    end=int(pd.Timestamp('2022-06-01',tz='UTC').timestamp()*1000)
    grid=calendar_for(AssetClass.EQUITY).expected_bar_opens(start,end,Timeframe.D1)
    raw=pd.DataFrame({'SYNTH':100*np.exp(np.arange(len(grid))*.001)},index=grid)
    actions=pd.DataFrame()
    if split:
        raw.iloc[300:]/=4
        actions=pd.DataFrame([dict(instrument_id='SYNTH',action_type='split',ex_date=grid[300],available_at=grid[300],ratio=4.,cash_amount=np.nan)])
    ctx=SimpleNamespace(start=start,end=end,panel=lambda _:raw,corporate_actions=lambda:actions)
    return ctx,raw,actions


def test_exact_spec_changes_and_metadata_preserved():
    s=eq_mom_252_21();before=s.fn
    control=path_specs([s],'control');candidate=path_specs([s],'candidate')
    assert control[0].fn is corrected_momentum and candidate[0].fn is corrected_path_momentum
    assert candidate[1].fn is corrected_sigma and candidate[2] is _OPEN_SPEC
    assert replace(candidate[0],fn=s.fn)==s and s.fn is before


def test_split_conservation_and_control_parity_on_real_session_grid():
    a,raw,actions=context(True);b,_,_=context(False)
    before=raw.copy();ca=actions.copy()
    p,d=path_panels(a,eq_mom_252_21());q,_=path_panels(b,eq_mom_252_21())
    for key in p:np.testing.assert_allclose(p[key],q[key],atol=1e-12,equal_nan=True)
    assert d['extra_missing_cells']==0 and d['maximum_shared_control_difference']<=1e-12
    pd.testing.assert_frame_equal(raw,before);pd.testing.assert_frame_equal(actions,ca)


def test_gap_is_reported_not_bridged_and_incomplete_grid_rejected():
    ctx,raw,_=context();raw.iloc[300]=np.nan
    _,d=path_panels(ctx,eq_mom_252_21())
    assert d['extra_missing_cells']>0
    ctx.panel=lambda _:raw.drop(index=raw.index[300])
    with pytest.raises(ValueError,match='XNYS'):path_panels(ctx,eq_mom_252_21())


def test_wrong_parameters_rejected_and_long_index_matches_parent():
    ctx,_,_=context();spec=eq_mom_252_21()
    out=corrected_path_momentum(ctx,spec);baseline=corrected_momentum(ctx,spec)
    assert out.index.equals(baseline.index) and out.name==baseline.name
    with pytest.raises(ValueError):path_panels(ctx,replace(spec,params={'lookback':126,'skip':21}))
