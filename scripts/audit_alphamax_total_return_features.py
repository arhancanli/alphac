"""Reconstruct bound feature context and independently audit dividend-aware wealth returns."""
from pathlib import Path
import json,hashlib
import numpy as np
from alphamax_total_return_service import TotalReturnMomentumSignalService,total_return_panels
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
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/analysis/alphamax_total_return_momentum_20260913';D=OUT/'candidate'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((OUT/'input_manifest.json').read_text())
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
trial=json.loads((D/'reservation.json').read_text())['trial_config'];start,end=trial['start'],trial['end']
settings=Settings(**json.loads((OUT/'state/settings.json').read_text()));paths=LakePaths(ROOT/'evidence/core-2023-2026-frozen-inputs-20260913/lake')
with InstrumentStore(OUT/'state/ops_cost1.sqlite') as store:
 reader=PITDataReader(paths);universe=UniverseStore(paths)
 engine=FeatureEngine(reader,store,universe,asset_class=settings.data.asset_class)
 service=TotalReturnMomentumSignalService(engine,universe,default_registry(),settings.signals,correction_mode='momentum_sigma',total_return_mode='candidate',sleeve=sleeve_for(settings.data.asset_class),alpha_names=trial['alpha_names'])
 ids=service._window_ids(start,end);spec=service._alpha_specs[0];tf=engine._anchor_tf;L=max(spec.lookback_bars,_SIGMA_SPEC.lookback_bars)
 warm=engine.calendar.expected_bar_opens(start-(2*L+8)*tf.ms,start+tf.ms,tf)
 ctx_start=warm[-(L+1)] if len(warm)>=L+1 else (warm[0] if warm else start-L*tf.ms)
 ctx=FeatureContext(reader=reader,instruments=store,universe=universe,instrument_ids=ids,start=ctx_start,end=end,calendar=engine.calendar,asset_class=settings.data.asset_class,anchor_tf=tf)
 panels,diagnostic=total_return_panels(ctx,spec)
 adjusted=share_ratio_close(ctx.panel('close'),ctx.corporate_actions())
 # Independent scalar action lookup and direct products over each formation window.
 raw_prices=ctx.panel('close');actions=ctx.corporate_actions()
 events={}
 for row in actions.itertuples():
  key=(row.instrument_id,int(row.ex_date))
  assert key not in events
  events[key]=row
 maximum=0.;checked=0
 for col in raw_prices:
  values=raw_prices[col].to_numpy(dtype=float); dates=raw_prices.index
  gross=np.full(len(values),np.nan)
  for j in range(1,len(values)):
   previous,current=values[j-1],values[j]
   if not(np.isfinite(previous) and np.isfinite(current) and previous>0 and current>0):continue
   event=events.get((col,int(dates[j])))
   shares=1.;distribution=0.
   if event is not None:
    if event.action_type=='split':shares=float(event.ratio)
    elif event.action_type=='dividend':distribution=float(event.cash_amount)
    else:raise AssertionError(event.action_type)
   gross[j]=(shares*current+distribution)/previous
  actuals=panels['candidate'][col].to_numpy()
  for i in range(252,len(values)):
   if dates[i]<start:continue
   window=gross[i-251:i-20]
   assert len(window)==231
   actual=actuals[i]
   if not np.isfinite(window).all():assert np.isnan(actual);continue
   expected=np.log(np.prod(window))
   difference=abs(float(actual)-expected)
   assert np.isfinite(actual) and difference<1e-12,(col,int(dates[i]),actual,expected)
   maximum=max(maximum,difference);checked+=1
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
 report={'status':'BOUND_FEATURE_CONTEXT_RECONSTRUCTED','context_start':ctx_start,'context_end':end,'instrument_count':len(ids),'all_context_diagnostics':diagnostic,'eligible_scalar_cells_checked':checked,'maximum_scalar_difference':maximum,'extra_missing_member_cells':int(exclusions.sum()),'sessions_with_extra_missing_members':int(exclusions.gt(0).sum()),'saved_runtime_feature_snapshot_available':False,'limits':'Reconstruction from bound inputs/code, not comparison to a saved runtime feature snapshot. Stored action availability is not independently verified historical publication or source completeness. Synthetic ex-date reinvestment is a signal index, not spendable cash. Price/metadata limitations remain. No new return experiment.'}
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
report['sha256']={str(p.relative_to(ROOT)):h(p) for p in [Path(__file__),D/'feature_exclusions_by_session.csv',OUT/'input_manifest.json']}
with (D/'feature_audit.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
