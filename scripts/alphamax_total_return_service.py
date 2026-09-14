"""Isolated AlphaMax forecast substitution; parent source and registry unchanged."""
from dataclasses import replace
import numpy as np
from alphamax_total_return_momentum import total_return_momentum
from alphamax_share_ratio_features import share_ratio_close
from alphamax_share_ratio_service import ShareRatioSignalService, substituted_specs
from alphaforge.core.calendar import calendar_for
from alphaforge.core.types import AssetClass
from alphaforge.core.time import Timeframe
from alphaforge.features.context import long_series
from alphaforge.features.library.momentum import xs_momentum


def total_return_panels(ctx, spec, *, include_candidate=True):
    if spec.name!='eq_mom_252_21' or spec.params.get('lookback')!=252 or spec.params.get('skip')!=21 or spec.lookback_bars!=253:
        raise ValueError('Frozen252/21AlphaMaxspec required')
    raw=ctx.panel('close')
    expected=calendar_for(AssetClass.EQUITY).expected_bar_opens(ctx.start,ctx.end,Timeframe.D1)
    if not np.array_equal(raw.index.to_numpy(),np.asarray(expected)):
        raise ValueError('Input is not the complete frozen XNYS session grid')
    actions=ctx.corporate_actions()
    split_actions=actions[actions.action_type=='split'] if not actions.empty else actions
    forward_control=total_return_momentum(raw,split_actions)
    legacy=xs_momentum(share_ratio_close(raw,actions),lookback=252,skip=21)
    valid=forward_control.notna()
    difference=(forward_control-legacy).where(valid)
    if not np.allclose(forward_control.to_numpy()[valid],legacy.to_numpy()[valid],rtol=0,atol=1e-12):
        raise ValueError('Forward split-only control differs from retained momentum')
    panels={'control':forward_control,'legacy':legacy}
    if include_candidate:panels['candidate']=total_return_momentum(raw,actions)
    diagnostics={'legacy_finite_cells':int(legacy.notna().sum().sum()),
                 'forward_control_finite_cells':int(forward_control.notna().sum().sum()),
                 'extra_missing_control_cells':int((legacy.notna()&forward_control.isna()).sum().sum()),
                 'maximum_shared_control_difference':float(difference.abs().max().max()) if valid.any().any() else None,
                 'candidate_computed':include_candidate}
    return panels,diagnostics


def corrected_total_return_momentum(ctx,spec):
    panels,_=total_return_panels(ctx,spec)
    return long_series(panels['candidate'],name=spec.name)


def total_return_specs(alpha_specs,mode):
    specs=substituted_specs(alpha_specs,'momentum_sigma')
    if mode=='control':return specs
    if mode!='candidate':raise ValueError('Unknown path mode')
    if specs[0].params.get('lookback')!=252 or specs[0].params.get('skip')!=21:
        raise ValueError('Frozen parameters required')
    return [replace(specs[0],fn=corrected_total_return_momentum),*specs[1:]]


class TotalReturnMomentumSignalService(ShareRatioSignalService):
    def __init__(self,*args,total_return_mode,**kwargs):
        if kwargs.get('correction_mode')!='momentum_sigma':
            raise ValueError('Preserve corrected momentum and sigma baseline')
        super().__init__(*args,**kwargs)
        self._total_return_mode=total_return_mode
        total_return_specs(self._alpha_specs,total_return_mode)

    def _panel(self,start,end):
        ids=self._window_ids(start,end)
        if not ids:raise ValueError('No members in path window')
        specs=total_return_specs(self._alpha_specs,self._total_return_mode)
        frame=self._engine.compute_history(specs,ids,start=start,end=end)
        mask=self._membership_mask(frame.index)
        return frame,mask,self._directional_zs(frame,mask)
