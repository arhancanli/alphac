"""Independent saved-model prediction/loss/timing and raw-price/flow checks."""
from pathlib import Path
import json,hashlib,zipfile
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parents[1];O=R/'artifacts/analysis/crypto_trade_flow_diagnostic_20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((O/'input_manifest.json').read_text())['sha256']
for p,h in manifest.items():assert sha(R/p)==h
f=pd.read_parquet(O/'predictions.parquet');models=json.loads((O/'models.json').read_text());result=json.loads((O/'result.json').read_text())
controls=['return_4h','return_24h','return_7d','rv_24h','log_volume_4h','funding_mean_21d','eth_indicator']
assert len(f)==14974 and not f.duplicated(['symbol','decision_at']).any()
assert (f.input_available_at==f.decision_at).all()
assert (f.entry_at==f.decision_at+pd.Timedelta(minutes=5)).all()
assert (f.exit_at==f.entry_at+pd.Timedelta(hours=4)).all()
assert (f.label_available_at==f.exit_at+pd.Timedelta(minutes=5)).all()
maximum=0.
for model in models:
 year=model['year'];g=f[f.decision_at.dt.year==year]
 assert pd.Timestamp(model['last_label_available'])<pd.Timestamp(year=year,month=1,day=1,tz='UTC')-pd.Timedelta(hours=24)
 for arm,columns in [('control',controls),('candidate',controls+['flow'])]:
  x=g[columns].to_numpy();mean=np.array(model[arm+'_mean']);scale=np.array(model[arm+'_scale']);coef=np.array(model[arm+'_coefficients'])
  expected=model['intercept']+np.sum(((x-mean)/scale)*coef,axis=1)
  error=float(np.max(np.abs(expected-g[arm+'_prediction'].to_numpy())))
  assert error<1e-12;maximum=max(maximum,error)
 assert model['candidate_coefficients'][-1]>=0
for symbol in ['BTCUSDT','ETHUSDT']:
 files=sorted([R/p for p in manifest if p.endswith('.zip') and f'{symbol}-5m-' in p]);assert len(files)==54
 frames=[]
 for p in files:
  with zipfile.ZipFile(p) as z:
   with z.open(z.namelist()[0]) as stream:frames.append(pd.read_csv(stream))
 raw=pd.concat(frames).sort_values('open_time').set_index('open_time');assert len(raw)==1613*288
 g=f[f.symbol==symbol];entry=(g.entry_at.astype('int64')//1000).to_numpy() if g.entry_at.dtype.unit=='us' else np.array([int(t.timestamp()*1000) for t in g.entry_at])
 exit_=np.array([int(t.timestamp()*1000) for t in g.exit_at])
 expected=raw.open.reindex(exit_).to_numpy()/raw.open.reindex(entry).to_numpy()-1
 np.testing.assert_allclose(expected,g.target,atol=1e-14,rtol=0)
 # Independent direct NumPy windows, no rolling/grouping feature helper.
 for row in g.itertuples():
  end=int(row.input_end);pos=(end-int(raw.index[0]))//300000
  window=raw.iloc[pos-48:pos];history=raw.iloc[pos-2016:pos]
  assert len(window)==48 and len(history)==2016
  denominator=history.quote_volume.to_numpy().sum()/42
  signed=2*window.taker_buy_quote_volume.to_numpy().sum()-window.quote_volume.to_numpy().sum()
  assert abs(signed/denominator-row.flow)<1e-12
  assert abs(np.log(window.close.iloc[-1]/window.open.iloc[0])-row.return_4h)<1e-12
  assert abs(np.log(raw.close.iloc[pos-1]/raw.close.iloc[pos-1-288])-row.return_24h)<1e-12
  assert abs(np.log(raw.close.iloc[pos-1]/raw.close.iloc[pos-1-2016])-row.return_7d)<1e-12
  closes=raw.close.iloc[pos-289:pos].to_numpy()
  assert abs(np.sqrt(np.sum(np.log(closes[1:]/closes[:-1])**2))-row.rv_24h)<1e-12
  assert abs(np.log(window.quote_volume.sum())-row.log_volume_4h)<1e-12
  assert row.eth_indicator==float(symbol=='ETHUSDT')
 # All source funding publications obey observed +5minute convention; daily control direct slice.
 funding_paths=[R/p for p in manifest if '/funding/' in p and f'PERP:{symbol}/' in p]
 funding=pd.concat([pd.read_parquet(p) for p in funding_paths]).sort_values('ts_funding')
 assert ((funding.available_at-funding.ts_funding)==pd.Timedelta(minutes=5)).all()
 for day,dg in g.groupby(g.decision_at.dt.normalize()):
  source=funding[(funding.ts_funding>=day-pd.Timedelta(days=21))&(funding.ts_funding<day)]
  assert len(source)==63 and source.available_at.max()<dg.decision_at.min()
  np.testing.assert_allclose(dg.funding_mean_21d,source.rate.mean(),atol=1e-15,rtol=0)
control=(f.target-f.control_prediction)**2;candidate=(f.target-f.candidate_prediction)**2
np.testing.assert_allclose(f.control_loss,control,rtol=0,atol=1e-16)
np.testing.assert_allclose(f.candidate_loss,candidate,rtol=0,atol=1e-16)
relative=lambda mask:float((control[mask].mean()-candidate[mask].mean())/control[mask].mean())
pooled=relative(np.ones(len(f),dtype=bool));assert abs(pooled-result['pooled']['relative_reduction'])<1e-12
symbols={s:relative(f.symbol==s) for s in ['BTCUSDT','ETHUSDT']};years={str(y):relative(f.decision_at.dt.year==y) for y in range(2023,2027)}
for s,v in symbols.items():assert abs(v-result['symbols'][s]['relative_reduction'])<1e-12
for y,v in years.items():assert abs(v-result['years'][y]['relative_reduction'])<1e-12
values=pd.read_csv(O/'daily_loss_improvement.csv').improvement.to_numpy()
assert len(values)==1248 and np.isfinite(values).all()
rng=np.random.default_rng(20260913);offset=np.arange(28);replicates=[]
for _ in range(10000):
 starts=rng.integers(0,len(values)-27,size=(len(values)+27)//28)
 indices=(starts[:,None]+offset).ravel()[:len(values)];replicates.append(values[indices].mean())
np.testing.assert_allclose(replicates,np.load(O/'bootstrap_means.npy'),rtol=0,atol=1e-18)
lower=float(np.quantile(replicates,.05));assert abs(lower-result['bootstrap_lower95'])<1e-18
checks={'pooled_reduction_ge_1pct':pooled>=.01,'every_symbol_nonnegative':all(v>=0 for v in symbols.values()),'every_year_nonnegative':all(v>=0 for v in years.values()),'lower_bound_positive':lower>0}
assert checks==result['gates'] and not any(checks.values()) and not result['all_gates_pass']
for p,h in manifest.items():assert sha(R/p)==h
refs=[O/'predictions.parquet',O/'models.json',O/'result.json',O/'bootstrap_means.npy',O/'daily_loss_improvement.csv',Path(__file__)]
audit={'status':'SAVED_PREDICTIONS_SOURCE_FEATURES_LABELS_LOSSES_AND_GATES_VERIFIED','rows':len(f),'maximum_model_reconstruction_error':maximum,'all_gates_fail':True,'execution_trial_allowed':False,'limits':'Independent saved-coefficient evaluation and raw source-window/timing checks. This audit does not independently refit training coefficients; training separation additionally covered by unit tests and retained cutoff metadata. No trading performance or independent historical dissemination certification.','sha256':{str(p.relative_to(R)):sha(p) for p in refs}}
with (O/'independent_audit.json').open('x') as stream:json.dump(audit,stream,indent=2)
print(json.dumps(audit))
