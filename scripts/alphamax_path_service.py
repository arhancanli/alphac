"""Isolated AlphaMax forecast substitution; parent source and registry unchanged."""
from dataclasses import replace
import numpy as np
from alphamax_path_momentum import path_momentum
from alphamax_share_ratio_features import share_ratio_close
from alphamax_share_ratio_service import ShareRatioSignalService, substituted_specs
from alphaforge.core.calendar import calendar_for
from alphaforge.core.types import AssetClass
from alphaforge.core.time import Timeframe
from alphaforge.features.context import long_series
from alphaforge.features.library.momentum import xs_momentum


def path_panels(ctx, spec):
    if spec.name!='eq_mom_252_21' or spec.params.get('lookback')!=252 or spec.params.get('skip')!=21 or spec.lookback_bars!=253:
        raise ValueError('Frozen252/21AlphaMaxspec required')
    raw=ctx.panel('close')
    expected=calendar_for(AssetClass.EQUITY).expected_bar_opens(ctx.start,ctx.end,Timeframe.D1)
    if not np.array_equal(raw.index.to_numpy(),np.asarray(expected)):
        raise ValueError('Input is not the complete frozen XNYS session grid')
    adjusted=share_ratio_close(raw,ctx.corporate_actions())
    panels=path_momentum(adjusted,raw.index)
    original=xs_momentum(adjusted,lookback=252,skip=21)
    mask=panels['control'].notna()
    differences=(panels['control']-original).where(mask)
    if not np.allclose(panels['control'].to_numpy()[mask],original.to_numpy()[mask],rtol=0,atol=1e-12):
        raise ValueError('Retained control feature mismatch on shared eligible rows')
    diagnostics={'control_finite_cells':int(original.notna().sum().sum()),
                 'candidate_finite_cells':int(panels['candidate'].notna().sum().sum()),
                 'extra_missing_cells':int((original.notna()&panels['candidate'].isna()).sum().sum()),
                 'maximum_shared_control_difference':float(differences.abs().max().max()) if mask.any().any() else None}
    return panels,diagnostics


def corrected_path_momentum(ctx,spec):
    panels,_=path_panels(ctx,spec)
    return long_series(panels['candidate'],name=spec.name)


def path_specs(alpha_specs,mode):
    specs=substituted_specs(alpha_specs,'momentum_sigma')
    if mode=='control':return specs
    if mode!='candidate':raise ValueError('Unknown path mode')
    if specs[0].params.get('lookback')!=252 or specs[0].params.get('skip')!=21:
        raise ValueError('Frozen parameters required')
    return [replace(specs[0],fn=corrected_path_momentum),*specs[1:]]


class PathMomentumSignalService(ShareRatioSignalService):
    def __init__(self,*args,path_mode,**kwargs):
        if kwargs.get('correction_mode')!='momentum_sigma':
            raise ValueError('Preserve corrected momentum and sigma baseline')
        super().__init__(*args,**kwargs)
        self._path_mode=path_mode
        path_specs(self._alpha_specs,path_mode)

    def _panel(self,start,end):
        ids=self._window_ids(start,end)
        if not ids:raise ValueError('No members in path window')
        specs=path_specs(self._alpha_specs,self._path_mode)
        frame=self._engine.compute_history(specs,ids,start=start,end=end)
        mask=self._membership_mask(frame.index)
        return frame,mask,self._directional_zs(frame,mask)
