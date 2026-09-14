"""Reconstruct bound feature context and independently audit path counts."""
from pathlib import Path
import json,hashlib
import numpy as np
from alphamax_path_service import PathMomentumSignalService,path_panels
from alphamax_share_ratio_features import share_ratio_close
from alphaforge.config.settings import Settings
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.features.context import FeatureContext
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore
from alphaforge.signals.service import _SIGMA_SPEC
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/analysis/alphamax_path_momentum_20260913';D=OUT/'candidate'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((OUT/'input_manifest.json').read_text())
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
trial=json.loads((D/'reservation.json').read_text())['trial_config'];start,end=trial['start'],trial['end']
settings=Settings(**json.loads((OUT/'state/settings.json').read_text()));paths=LakePaths(ROOT/'evidence/core-2023-2026-frozen-inputs-20260913/lake')
with InstrumentStore(OUT/'state/ops_cost1.sqlite') as store:
 reader=PITDataReader(paths);universe=UniverseStore(paths)
 engine=FeatureEngine(reader,store,universe,asset_class=settings.data.asset_class)
 service=PathMomentumSignalService(engine,universe,default_registry(),settings.signals,correction_mode='momentum_sigma',path_mode='candidate',sleeve=sleeve_for(settings.data.asset_class),alpha_names=trial['alpha_names'])
 ids=service._window_ids(start,end);spec=service._alpha_specs[0];tf=engine._anchor_tf;L=max(spec.lookback_bars,_SIGMA_SPEC.lookback_bars)
 warm=engine.calendar.expected_bar_opens(start-(2*L+8)*tf.ms,start+tf.ms,tf)
 ctx_start=warm[-(L+1)] if len(warm)>=L+1 else (warm[0] if warm else start-L*tf.ms)
 ctx=FeatureContext(reader=reader,instruments=store,universe=universe,instrument_ids=ids,start=ctx_start,end=end,calendar=engine.calendar,asset_class=settings.data.asset_class,anchor_tf=tf)
 panels,diagnostic=path_panels(ctx,spec)
 adjusted=share_ratio_close(ctx.panel('close'),ctx.corporate_actions())
 # Independent per-column NumPy windows, without the rolling kernel or sign-count frames.
 maximum=0.;checked=0
 for col in adjusted:
  values=adjusted[col].to_numpy(dtype=float)
  for i in range(252,len(values)):
   if adjusted.index[i]<start:continue
   window=values[i-252:i-20]
   valid=np.isfinite(window).all() and (window>0).all()
   actual=panels['candidate'].iloc[i][col]
   if not valid:assert np.isnan(actual);continue
   changes=window[1:]/window[:-1]-1
   m=np.log(window[-1]/window[0]);id_=np.sign(m)*(np.count_nonzero(changes<0)-np.count_nonzero(changes>0))/231
   expected=m*(1-id_)/2
   difference=abs(float(actual)-expected);maximum=max(maximum,difference);assert difference<1e-12
   checked+=1
 # Persist membership-conditioned extra exclusions by source day, not just all warmup cells.
 a=panels['control'];b=panels['candidate']
 from alphaforge.features.library.momentum import xs_momentum
 from alphaforge.features.context import long_series
 original=xs_momentum(adjusted,lookback=252,skip=21)
 original=original.loc[(original.index>=start)&(original.index<end)]
 candidate=b.reindex(original.index)
 raw=long_series(original,name='control');cand=long_series(candidate,name='candidate')
 membership=service._membership_mask(raw.index)
 exclusions=(raw.notna()&cand.isna()&membership).groupby(level='ts_open').sum()
 exclusions.to_csv(D/'feature_exclusions_by_session.csv',header=['extra_missing_member_cells'])
 report={'status':'BOUND_FEATURE_CONTEXT_RECONSTRUCTED','context_start':ctx_start,'context_end':end,'instrument_count':len(ids),'all_context_diagnostics':diagnostic,'eligible_scalar_cells_checked':checked,'maximum_scalar_difference':maximum,'extra_missing_member_cells':int(exclusions.sum()),'sessions_with_extra_missing_members':int(exclusions.gt(0).sum()),'saved_runtime_feature_snapshot_available':False,'limits':'Reconstruction from bound inputs/code, not comparison to a saved runtime feature snapshot. Price/metadata and historical adjustment limitations remain. No new return experiment.'}
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
report['sha256']={str(p.relative_to(ROOT)):h(p) for p in [Path(__file__),D/'feature_exclusions_by_session.csv',OUT/'input_manifest.json']}
with (D/'feature_audit.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
