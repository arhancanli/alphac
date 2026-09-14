"""Fixed delayed trade-flow forecast screen; separately registered non-PnL evidence."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,zipfile
import numpy as np
import pandas as pd
from crypto_trade_flow import flow_blocks,delayed_flow_features,BAR,BLOCK
from crypto_trade_flow_model import fit_pair,CONTROLS
from crypto_oi_source_preflight import normalize_funding_slots
R=Path(__file__).resolve().parents[1];E=R/'evidence/crypto-trade-flow-design-20260913';O=R/'artifacts/analysis/crypto_trade_flow_diagnostic_20260913'
SYMBOLS=['BTCUSDT','ETHUSDT']
COLUMNS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,obj):
 with p.open('x') as f:json.dump(obj,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def ms(t):return int(pd.Timestamp(t).timestamp()*1000)

def build_symbol(symbol,items):
 parts=[]
 for item in items:
  if item['symbol']!=symbol:continue
  receipt=json.loads((R/'evidence/crypto-oi-full-source-20260913/receipts'/(item['name']+'.json')).read_text())
  p=R/receipt['path']
  with zipfile.ZipFile(p) as z:
   name=z.namelist()[0]
   with z.open(name) as f:first=f.readline().decode().split(',')[0]
   with z.open(name) as f:parts.append(pd.read_csv(f,header=0 if first=='open_time' else None,names=COLUMNS))
 raw=pd.concat(parts,ignore_index=True).sort_values('open_time').set_index('open_time')
 assert len(raw)==1613*288 and np.all(np.diff(raw.index)==BAR)
 b=flow_blocks(raw);f=delayed_flow_features(b)
 groups=raw.index.to_numpy()//BLOCK*BLOCK+BLOCK
 opening=raw.open.groupby(groups).first();closing=raw.close.groupby(groups).last()
 f['return_4h']=np.log(closing/opening)
 f['return_24h']=np.log(closing/closing.shift(6))
 f['return_7d']=np.log(closing/closing.shift(42))
 logs=np.log(raw.close/raw.close.shift(1))
 rv=np.sqrt(logs.pow(2).rolling(288,min_periods=288).sum())
 f['rv_24h']=rv.reindex(f.index-BAR).to_numpy()
 f['log_volume_4h']=np.log(b.quote_volume.where(b.quote_volume>0))
 paths=sorted((R/f'evidence/core-2023-2026-frozen-inputs-20260913/lake/funding/instrument_id=BINANCE:PERP:{symbol}').glob('year=*/data.parquet'))
 funding=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True).rename(columns={'ts_funding':'settled_at'})
 funding['symbol']=symbol;funding=normalize_funding_slots(funding)
 funding['day']=funding.settled_at.dt.normalize()
 daily=funding.groupby('day').agg(rate=('rate','mean'),count=('rate','size'),last_available=('available_at','max'))
 days=pd.date_range('2022-01-01','2026-06-01',tz='UTC');daily=daily.reindex(days)
 daily.loc[daily['count']!=3,'rate']=np.nan
 mean=daily.rate.rolling(21,min_periods=21).mean();mean.index=mean.index+pd.Timedelta(days=1)
 input_times=pd.to_datetime(f.index,unit='ms',utc=True)
 f['funding_mean_21d']=mean.reindex(input_times.normalize()).to_numpy()
 # The final complete source day's latest funding publication must precede t.
 last=daily.last_available.copy();last.index=last.index+pd.Timedelta(days=1)
 availability=last.reindex(input_times.normalize())
 valid=f.funding_mean_21d.notna().to_numpy()
 assert (availability.to_numpy()[valid]<=input_times.to_numpy()[valid]).all()
 f['eth_indicator']=float(symbol=='ETHUSDT');f['symbol']=symbol
 entry=raw.open.reindex(f.entry_reference).to_numpy();exit_=raw.open.reindex(f.exit_reference).to_numpy()
 f['target']=exit_/entry-1
 f['decision_at']=pd.to_datetime(f.available_at,unit='ms',utc=True)
 f['input_available_at']=f.decision_at
 f['label_available_at']=pd.to_datetime(f.label_available_at,unit='ms',utc=True)
 f['entry_at']=pd.to_datetime(f.entry_reference,unit='ms',utc=True)
 f['exit_at']=pd.to_datetime(f.exit_reference,unit='ms',utc=True)
 assert (f.entry_at>f.input_available_at).all() and (f.exit_at>f.entry_at).all()
 f=f.reset_index(drop=True)
 return f


def main():
 O.mkdir(exist_ok=False,parents=True)
 for p,h in json.loads((E/'closure.json').read_text())['sha256'].items():assert sha(R/p)==h
 bindings=dict(json.loads((E/'source_bindings.json').read_text())['sha256'])
 paths=[E/'DESIGN.json',E/'closure.json',Path(__file__),R/'scripts/crypto_trade_flow.py',R/'scripts/crypto_trade_flow_model.py',R/'scripts/crypto_oi_source_preflight.py',R/'tests/unit/test_crypto_trade_flow_model.py',R/'pyproject.toml',R/'uv.lock']
 for symbol in SYMBOLS:paths+=list((R/f'evidence/core-2023-2026-frozen-inputs-20260913/lake/funding/instrument_id=BINANCE:PERP:{symbol}').glob('year=*/data.parquet'))
 paths+=[R/'evidence/crypto-oi-full-source-20260913/plan.json']
 bindings.update({str(p.relative_to(R)):sha(p) for p in paths})
 for p,h in bindings.items():assert sha(R/p)==h
 write(O/'input_manifest.json',{'sha256':bindings})
 # Both diagnostic identities are bound before reading real price/feature pairs.
 register=R/'artifacts/research/forecast_diagnostics';register.mkdir(parents=True,exist_ok=True)
 registrations=[]
 for arm in ['control','trade_flow']:
  config={'family':'aggressive_trade_flow_4h','arm':arm,'design_sha256':sha(E/'DESIGN.json'),'manifest_sha256':sha(O/'input_manifest.json')}
  identity=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
  record={'schema':'alphac.forecast-diagnostic-reservation.v1','identity':identity,'config':config,'reserved_at':datetime.now(timezone.utc).isoformat(),'metric_type':'paired_forecast_loss_not_portfolio_return','performance_union_at_design':340,'selection_history':'Charge this distinct diagnostic to supplementary selection history; no synthetic Sharpe, no admission until combined selection accounting reconciled.','input_manifest':str((O/'input_manifest.json').relative_to(R)),'output_directory':str(O.relative_to(R))}
  write(register/(identity+'.reservation.json'),record);registrations.append(record)
 write(O/'diagnostic_reservations.json',registrations)
 items=[x for x in json.loads((R/'evidence/crypto-oi-full-source-20260913/plan.json').read_text())['items'] if x['kind']=='klines']
 full=pd.concat([build_symbol(s,items) for s in SYMBOLS],ignore_index=True)
 finite=np.isfinite(full[list(CONTROLS)+['flow','target']].to_numpy(dtype=float)).all(axis=1)
 eligible=full[finite].copy()
 # Matched evaluation/training rows; both symbols must be present at each decision.
 paired=eligible.groupby('decision_at').symbol.nunique();eligible=eligible[eligible.decision_at.isin(paired[paired==2].index)]
 expected=pd.date_range('2023-01-01 00:05','2026-06-01 16:05',freq='4h',tz='UTC')
 coverage={s:float(eligible[(eligible.symbol==s)&eligible.decision_at.isin(expected)].shape[0]/len(expected)) for s in SYMBOLS}
 write(O/'coverage.json',{'expected_per_symbol':len(expected),'fraction':coverage,'minimum':.95})
 if not all(x>=.95 for x in coverage.values()):raise ValueError('Frozen coverage failed')
 forecasts=[];models=[]
 for year in range(2023,2027):
  cutoff=pd.Timestamp(year=year,month=1,day=1,tz='UTC')
  control,candidate=fit_pair(eligible,cutoff)
  test=eligible[eligible.decision_at.isin(expected)&eligible.decision_at.dt.year.eq(year)].copy()
  test['control_prediction']=control.predict(test);test['candidate_prediction']=candidate.predict(test)
  forecasts.append(test)
  models.append({'year':year,'training_rows':control.training_rows,'last_label_available':str(control.last_label_available),'control_coefficients':control.coefficient.tolist(),'candidate_coefficients':candidate.coefficient.tolist(),'control_mean':control.mean.tolist(),'candidate_mean':candidate.mean.tolist(),'control_scale':control.scale.tolist(),'candidate_scale':candidate.scale.tolist(),'intercept':control.intercept})
 output=pd.concat(forecasts).sort_values(['decision_at','symbol'])
 output['control_loss']=(output.target-output.control_prediction)**2
 output['candidate_loss']=(output.target-output.candidate_prediction)**2
 output['improvement']=output.control_loss-output.candidate_loss
 output.to_parquet(O/'predictions.parquet',index=False);write(O/'models.json',models)
 group=lambda g:{'rows':len(g),'control_mse':float(g.control_loss.mean()),'candidate_mse':float(g.candidate_loss.mean()),'relative_reduction':float(g.improvement.mean()/g.control_loss.mean())}
 total=group(output);symbols={s:group(output[output.symbol==s]) for s in SYMBOLS}
 years={str(y):group(output[output.decision_at.dt.year==y]) for y in range(2023,2027)}
 daily=output.groupby(output.decision_at.dt.normalize()).improvement.mean().reindex(pd.date_range('2023-01-01','2026-06-01',tz='UTC'))
 daily.to_csv(O/'daily_loss_improvement.csv',header=['improvement'])
 values=daily.to_numpy();rng=np.random.default_rng(20260913);draws=[]
 for _ in range(10000):
  starts=rng.integers(0,len(values)-28+1,size=(len(values)+27)//28)
  sample=np.concatenate([values[j:j+28] for j in starts])[:len(values)]
  draws.append(float(np.nanmean(sample)))
 lower=float(np.quantile(draws,.05));np.save(O/'bootstrap_means.npy',draws)
 gates={'pooled_reduction_ge_1pct':total['relative_reduction']>=.01,'every_symbol_nonnegative':all(x['relative_reduction']>=0 for x in symbols.values()),'every_year_nonnegative':all(x['relative_reduction']>=0 for x in years.values()),'lower_bound_positive':lower>0}
 result={'status':'MEASURED_FORECAST_DIAGNOSTIC_NOT_TRADING_PERFORMANCE','pooled':total,'symbols':symbols,'years':years,'bootstrap_lower95':lower,'gates':gates,'all_gates_pass':all(gates.values()),'qualified':False,'performance_union_unchanged':340,'new_supplementary_diagnostic_identities':2,'limitations':'Retrospective current-vintage two-symbol price-target screen; no funding/cost-adjusted PnL, untouched OOS or live execution claim. Supplementary diagnostic selection debt must be included before future admission.'}
 for p,h in bindings.items():assert sha(R/p)==h
 write(O/'result.json',result)
 for r in registrations:
  write(register/(r['identity']+'.measurement.json'),{'identity':r['identity'],'measured_at':datetime.now(timezone.utc).isoformat(),'reservation_sha256':sha(register/(r['identity']+'.reservation.json')),'result_path':str((O/'result.json').relative_to(R)),'result_sha256':sha(O/'result.json'),'predictions_sha256':sha(O/'predictions.parquet'),'metric_type':'forecast_loss','qualified':False})
 print(json.dumps(result))
if __name__=='__main__':main()
