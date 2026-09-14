from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from test_alphamax_path_service import context
from alphamax_total_return_service import total_return_panels,total_return_specs,corrected_total_return_momentum
from alphamax_share_ratio_service import corrected_sigma,corrected_momentum
from alphaforge.features.library.equity_price import eq_mom_252_21
from alphaforge.signals.service import _OPEN_SPEC


def test_spec_only_changes_alpha_body():
    spec=eq_mom_252_21();c=total_return_specs([spec],'candidate');b=total_return_specs([spec],'control')
    assert c[0].fn is corrected_total_return_momentum and b[0].fn is corrected_momentum
    assert replace(c[0],fn=spec.fn)==spec
    assert c[1].fn is corrected_sigma and c[2] is _OPEN_SPEC


def test_forward_split_control_matches_parent_on_XNYS_grid():
    ctx,raw,actions=context(True);p,d=total_return_panels(ctx,eq_mom_252_21())
    assert d['maximum_shared_control_difference']<1e-12 and d['extra_missing_control_cells']==0
    np.testing.assert_allclose(p['candidate'],p['control'],atol=1e-12,equal_nan=True)


def test_control_only_mode_never_calls_dividend_candidate():
    ctx,raw,_=context();ex=raw.index[300]
    invalid=pd.DataFrame([dict(instrument_id='SYNTH',action_type='dividend',ex_date=ex,available_at=ex,ratio=np.nan,cash_amount=-1.)])
    ctx.corporate_actions=lambda:invalid
    p,d=total_return_panels(ctx,eq_mom_252_21(),include_candidate=False)
    assert not d['candidate_computed'] and 'candidate' not in p
    with pytest.raises(ValueError,match='dividend'):total_return_panels(ctx,eq_mom_252_21())


def test_dividend_changes_candidate_but_not_control():
    ctx,raw,_=context();ex=raw.index[300]
    div=pd.DataFrame([dict(instrument_id='SYNTH',action_type='dividend',ex_date=ex,available_at=ex,ratio=np.nan,cash_amount=1.)])
    ctx.corporate_actions=lambda:div
    p,d=total_return_panels(ctx,eq_mom_252_21())
    assert p['candidate'].iloc[330,0]>p['control'].iloc[330,0]
    np.testing.assert_allclose(p['candidate'].iloc[:321],p['control'].iloc[:321],atol=1e-12,equal_nan=True)


def test_incomplete_grid_rejected():
    ctx,raw,_=context();ctx.panel=lambda _:raw.drop(index=raw.index[300])
    with pytest.raises(ValueError,match='XNYS'):total_return_panels(ctx,eq_mom_252_21())
