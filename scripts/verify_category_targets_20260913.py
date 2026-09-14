from pathlib import Path
import json,hashlib
import pandas as pd,numpy as np
r=Path('/Users/arhancanli/alphac-prospective-pause-20260911')
s=r/'artifacts/analysis/alphatrend_category_targets_20260913';c=r/'artifacts/analysis/alphac_category_targets_20260913'
arms=['baseline','baseline_stress','candidate','candidate_stress'];verification={};yearly=[];slices=[];exposure={}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
f=pd.read_csv(r/'evidence/alphac-algorithm-contributions-20260913/baseline_components.csv',index_col=0,parse_dates=True)
for arm in arms:
 d=s/arm;e=pd.read_parquet(d/'run/equity.parquet');p=pd.read_parquet(d/'run/positions.parquet');fills=pd.read_parquet(d/'run/fills.parquet');actions=pd.read_parquet(d/'run/corporate_actions.parquet');meta=json.loads((d/'run/run_meta.json').read_text())['config'];metrics=json.loads((d/'result.json').read_text())['metrics'];ret=e.equity.pct_change().dropna();sh=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252));dd=float((1-e.equity/e.equity.cummax()).max());assert abs(sh-metrics['sharpe'])<1e-12;assert abs(dd-metrics['max_dd'])<1e-12
 marked=p[p.ts==e.ts.iloc[-1]];value=(marked.qty*marked.mark).sum();cash=100000+(fills.notional.where(fills.side=='sell',-fills.notional)-fills.fee).sum()+actions.cashflow_quote.sum()+meta['borrow_total'];residual=float(e.equity.iloc[-1]-value-cash);assert abs(residual)<1e-6
 if arm.startswith('candidate'):
  assert (p.loc[p.instrument_id.isin([f'XUSE:CASH:{symbol}USD' for symbol in ['SPY','QQQ','IWM','EFA','EEM']]), 'qty']>=0).all()
  audit=json.loads((d/'direction_audit.json').read_text());assert all(w>=0 for row in audit for iid,w in row['targets'].items() if iid in [f'XUSE:CASH:{symbol}USD' for symbol in ['SPY','QQQ','IWM','EFA','EEM']])
 gross=p.assign(absw=p.weight.abs()).groupby('ts').absw.sum().reindex(e.ts,fill_value=0);net=p.groupby('ts').weight.sum().reindex(e.ts,fill_value=0)
 exposure[arm]={'mean_marked_gross':float(gross.mean()),'mean_marked_net':float(net.mean()),'mean_equity_minus_net_position_fraction':float((1-net).mean()),'borrow_signed_cashflow':meta['borrow_total'],'fees':float(fills.fee.sum())}
 dates=pd.to_datetime(e.ts,unit='ms');dated=pd.Series(e.equity.pct_change().to_numpy(),index=dates)
 for y,g in dated.dropna().groupby(dated.dropna().index.year):
  w=np.r_[1,np.cumprod(1+g.to_numpy())];yearly.append({'arm':arm,'year':int(y),'return':float(w[-1]-1),'maxdd':float((1-w/np.maximum.accumulate(w)).max())})
 for name,start,end in [('covid_Q1','2020-01-01','2020-03-31'),('year2022','2022-01-01','2022-12-31')]:
  g=dated.loc[start:end];w=np.r_[1,np.cumprod(1+g.to_numpy())];slices.append({'arm':arm,'slice':name,'return':float(w[-1]-1),'maxdd':float((1-w/np.maximum.accumulate(w)).max())})
 # Independent alignment: expand equity across every calendar day BEFORE differencing.
 series=pd.Series(e.equity.to_numpy(),index=dates);daily=series.reindex(pd.date_range(series.index.min(),series.index.max(),freq='D')).ffill().pct_change().reindex(f.index)
 assert daily.notna().all()
 expected=.225*sum(f[col]*4 for col in ['alphavintage_live','crypto_carry_wk','k30_dn_63'])+.225*daily+f.strategic_overlay
 actual=pd.read_csv(c/arm/'daily.csv',index_col=0,parse_dates=True);error=float(np.max(np.abs(expected-actual.total)));assert error<1e-12
 excess=actual.total-actual.benchmark;wealth=np.r_[1,np.cumprod(1+actual.total)];m=json.loads((c/arm/'result.json').read_text())['metrics'];assert abs(float(excess.mean()/excess.std(ddof=1)*np.sqrt(365))-m['sharpe'])<1e-11;assert abs(float(wealth[-1]**(365/len(actual))-1)-m['cagr'])<1e-12;assert abs(float((1-wealth/np.maximum.accumulate(wealth)).max())-m['maxdd'])<1e-12
 for directory in [d,c/arm]:
  reservation=json.loads((directory/'reservation.json').read_text())
  for bind in reservation['evidence'].values():assert sha(r/bind['path'])==bind['sha256']
  packet=json.loads((r/'artifacts/research/trial_packets'/f"{reservation['hypothesis_identity']}.json").read_text());digest=packet.pop('content_hash');assert 'sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()==digest
  for section in packet['required_sections'].values():
   for bind in section['evidence']:assert sha(r/bind['path'])==bind['sha256']
 verification[arm]={'standalone_sharpe_reproduced':sh,'terminal_cash_residual':residual,'combined_independent_calendar_path_max_error':error,'reservation_packet_bindings_verified':True}
for root in [s,c]:
 (root/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
pd.DataFrame(yearly).to_csv(s/'yearly.csv',index=False);pd.DataFrame(slices).to_csv(s/'crisis_slices.csv',index=False);(s/'exposure_and_costs.json').write_text(json.dumps(exposure,indent=2)+'\n')
print(json.dumps({'verification':verification,'exposure':exposure,'crisis_slices':slices},indent=2))
