"""Compare fixed policy inputs and realized fee arithmetic across cost arms."""
from pathlib import Path
from dataclasses import asdict
import json,hashlib
import numpy as np
import pandas as pd
from alphaforge.core.instruments import InstrumentStore
R=Path(__file__).resolve().parents[1];O=R/'artifacts/analysis/crypto_continuous_account_20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
reports={};sources=[Path(__file__)];metadata={};policies={}
for arm,mult in [('baseline',1),('baseline_stress',2)]:
 D=O/arm;assert (D/'execution_complete.json').exists()
 reservation=json.loads((D/'reservation.json').read_text());config=reservation['trial_config'];policies[arm]=json.loads(json.dumps(config))
 scenario=policies[arm]['research_engine']['scenario'];assert scenario.pop('execution_cost_multiplier')==mult
 scenario.pop('id');assert abs(scenario.pop('fee_fraction')-.0005*mult)<1e-15
 with InstrumentStore(O/f'state/ops_cost{mult}.sqlite') as store:instruments={x.instrument_id:x for x in store.all_known(as_of=1780358400000)}
 metadata[arm]={k:asdict(v) for k,v in instruments.items()}
 P=D/'run/legs/leg_00';fills=pd.read_parquet(P/'fills.parquet');positions=pd.read_parquet(P/'positions.parquet');funding=pd.read_parquet(P/'funding.parquet')
 max_error=0.
 for fill in fills.itertuples():
  inst=instruments[fill.instrument_id]
  bps=inst.maker_fee_bps if fill.liquidity=='maker' else inst.taker_fee_bps
  expected=fill.notional*bps*1e-4
  max_error=max(max_error,abs(fill.fee-expected));assert max_error<1e-7
 daily=pd.read_csv(D/'calendar2023_2026.csv')
 hourly=pd.read_parquet(D/'run/equity.parquet').equity.to_numpy();nav=np.r_[22500.,hourly]
 annual={}
 for year in range(2023,2027):
  g=daily[daily.day.str.startswith(str(year))];r=g['return'].to_numpy();e=g.excess.to_numpy();curve=np.r_[1.,np.cumprod(1+r)]
  annual[str(year)]={'observations':len(g),'return':float(curve[-1]-1),'raw_sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(365)),'excess_sharpe':float(e.mean()/e.std(ddof=1)*np.sqrt(365)),'within_year_daily_maxdd':float((1-curve/np.maximum.accumulate(curve)).max())}
 reports[arm]={'fills':len(fills),'fees_paid':float(fills.fee.sum()),'funding_cashflows':float(funding.payment_quote.sum()),'maximum_fee_arithmetic_error':max_error,'hourly_max_drawdown':float((1-nav/np.maximum.accumulate(nav)).max()),'annual':annual}
 sources += [D/'reservation.json',D/'calendar2023_2026.csv',P/'fills.parquet',P/'funding.parquet',P/'positions.parquet',P/'run_meta.json',D/'run/equity.parquet',O/f'state/ops_cost{mult}.sqlite']
assert policies['baseline']==policies['baseline_stress']
assert metadata['baseline'].keys()==metadata['baseline_stress'].keys()
for iid,normal in metadata['baseline'].items():
 stressed=metadata['baseline_stress'][iid].copy();normal=normal.copy()
 for key in ['maker_fee_bps','taker_fee_bps']:assert stressed.pop(key)==normal.pop(key)*2
 assert normal==stressed
m=lambda arm:json.loads((O/arm/'run/legs/leg_00/run_meta.json').read_text())['config']
assert m('baseline')['model_schedule']==m('baseline_stress')['model_schedule']
result={'status':'FIXED_POLICY_AND_DOUBLED_METADATA_FEES_VERIFIED','arms':reports,'qualified':False,'limits':'Same policy/signal schedule and source bindings; realized fees match doubled instrument schedules. Slippage/impact multiplier is bound runner code, not independently reconstructed quote execution. Funding rates are not doubled. Annual DD uses within-year normalized curves; full-hourly DD includes original cash deposit. No combined qualification.','sha256':{str(p.relative_to(R)):sha(p) for p in sources}}
with (O/'cost_stress_audit.json').open('x') as f:json.dump(result,f,indent=2)
print(json.dumps({k:v for k,v in result.items() if k!='sha256'}))
