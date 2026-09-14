"""Reconstruct bound feature context and independently audit path counts."""
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
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/analysis/alphamax_session_cooldown_20260913';D=OUT/'candidate'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((OUT/'input_manifest.json').read_text())
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
trial=json.loads((D/'reservation.json').read_text())['trial_config'];start,end=trial['start'],trial['end']
settings=Settings(**json.loads((OUT/'state/settings.json').read_text()));paths=LakePaths(ROOT/'evidence/core-2023-2026-frozen-inputs-20260913/lake')
with InstrumentStore(OUT/'state/ops_cost1.sqlite') as store:
 reader=PITDataReader(paths);universe=UniverseStore(paths)
 engine=FeatureEngine(reader,store,universe,asset_class=settings.data.asset_class)
 service=TotalReturnMomentumSignalService(engine,universe,default_registry(),settings.signals,correction_mode='momentum_sigma',total_return_mode='control',sleeve=sleeve_for(settings.data.asset_class),alpha_names=trial['alpha_names'])
 ids=service._window_ids(start,end);spec=service._alpha_specs[0];tf=engine._anchor_tf;L=max(spec.lookback_bars,_SIGMA_SPEC.lookback_bars)
 warm=engine.calendar.expected_bar_opens(start-(2*L+8)*tf.ms,start+tf.ms,tf)
 ctx_start=warm[-(L+1)] if len(warm)>=L+1 else (warm[0] if warm else start-L*tf.ms)
 ctx=FeatureContext(reader=reader,instruments=store,universe=universe,instrument_ids=ids,start=ctx_start,end=end,calendar=engine.calendar,asset_class=settings.data.asset_class,anchor_tf=tf)
 panels,diagnostic=total_return_panels(ctx,spec,include_candidate=False)
 report={'status':'HISTORICAL_CONTROL_PARITY_VERIFIED_NO_DIVIDEND_CANDIDATE_COMPUTED','context_start':ctx_start,'context_end':end,'instrument_count':len(ids),'diagnostics':diagnostic,'limits':'Same frozen source and modeled timing; not independent historical source verification. No dividend candidate scores, labels, fitting or portfolio returns.'}
for p,v in manifest['sha256'].items():assert h(ROOT/p)==v
E=ROOT/'evidence/alphamax-total-return-integration-20260913'
report['sha256']={str(p.relative_to(ROOT)):h(p) for p in [Path(__file__),OUT/'input_manifest.json',ROOT/'scripts/alphamax_total_return_service.py',ROOT/'scripts/alphamax_total_return_momentum.py']}
with (E/'control_parity.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
