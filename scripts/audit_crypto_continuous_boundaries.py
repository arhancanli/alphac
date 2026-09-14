"""Verify all model transitions against one uninterrupted saved account."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parents[1];D=R/'artifacts/analysis/crypto_continuous_account_20260913/baseline'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
wf=json.loads((D/'run/walkforward.json').read_text());assert len(wf['legs'])==1
P=D/'run/legs/leg_00';meta=json.loads((P/'run_meta.json').read_text())['config']
schedules=meta['model_schedule'];transitions=meta['model_boundary_transitions'];assert len(schedules)==20 and len(transitions)==19
assert meta['continuous_accounting'] and meta['physical_account_segments']==1
assert schedules[0]['test_start']==1672531200000 and schedules[-1]['test_end']==1780358400000
for a,b in zip(schedules,schedules[1:]):assert a['test_end']==b['test_start']
eq=pd.read_parquet(P/'equity.parquet').set_index('ts').equity
np.testing.assert_array_equal(eq.index.to_numpy(),np.arange(1672534800000,1780358400000+1,3600000))
positions=pd.read_parquet(P/'positions.parquet');funding=pd.read_parquet(P/'funding.parquet');fills=pd.read_parquet(P/'fills.parquet')
assert not funding.duplicated(['instrument_id','ts_funding']).any()
records=[]
for s,t in zip(schedules[1:],transitions):
 assert t['model_interval']==s['model_interval'] and t['actual_decision_ts']==t['scheduled_decision_start']==s['test_start']+3600000
 ts=t['actual_decision_ts'];saved=positions[positions.ts==ts].set_index('instrument_id').qty.to_dict()
 assert saved.keys()==t['positions_before_model_swap'].keys()
 for iid,q in saved.items():assert abs(q-t['positions_before_model_swap'][iid])<1e-10
 assert abs(eq.loc[ts]-t['equity_before_model_swap'])<1e-10
 records.append({'model_interval':s['model_interval'],'test_start':s['test_start'],'switch_decision':ts,'positions_at_switch':len(saved),'fills_at_boundary_open':int(fills.ts.eq(s['test_start']).sum()),'funding_during_first_interval':int(((funding.ts_funding>s['test_start'])&(funding.ts_funding<=ts)).sum())})
quantity=json.loads((D/'quantity_audit.json').read_text());assert quantity['funded_continuity_pass'] and quantity['material_flat_restart_boundaries']==0
for p,h in quantity['sha256'].items():assert sha(R/p)==h
refs=[Path(__file__),D/'quantity_audit.json',P/'run_meta.json',P/'positions.parquet',P/'funding.parquet',P/'fills.parquet',P/'equity.parquet']
r={'status':'ALL_19_SIGNAL_SWAPS_VERIFIED_WITH_ONE_PHYSICAL_LEDGER','model_intervals':20,'hourly_marks':len(eq),'transitions':records,'physical_account_continuity_pass':True,'qualification':False,'limits':'Verifies saved positions/equity at signal swaps plus independent continuous quantity/NAV replay. Synthetic engine tests prove pending-order crossing; source/impact/collateral/publication assumptions remain unqualified.','sha256':{str(p.relative_to(R)):sha(p) for p in refs}}
with (D/'boundary_audit.json').open('x') as f:json.dump(r,f,indent=2)
print(json.dumps({k:v for k,v in r.items() if k not in ['sha256','transitions']}))
