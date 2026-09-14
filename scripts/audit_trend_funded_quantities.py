"""Independent equity quantities, cost basis and cash conservation from saved events."""
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
R=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('arm',choices=['baseline','baseline_stress']);arm=p.parse_args().arm
D=R/'artifacts/analysis/trend_funded_account_20260913'/arm
config=json.loads((D/'reservation.json').read_text())['trial_config']
meta=json.loads((D/'run/run_meta.json').read_text())['config']
frames={n:pd.read_parquet(D/'run'/f'{n}.parquet') for n in ['fills','positions','equity','corporate_actions']}
fills,positions,equity,actions=[frames[n] for n in ['fills','positions','equity','corporate_actions']]
cal=XNYSCalendar();opens=cal.expected_bar_opens(config['start'],config['end'],Timeframe.D1)
source=R/'evidence/alphatrend-retrospective-execution-20260912'
raw=pd.read_parquet(source/'paired_prices.parquet').set_index(['symbol','session_ms'])
mapping=json.loads((source/'schedule.json').read_text())['instrument_symbols']
rate=config['resolved_settings']['costs']['equity_borrow_bps_annual']*1e-4/365
book={};cash=22500.;pending=0.;paid_events=meta['dividend_settlements'];paid_index=0
errors={'nav':0.,'realized':0.,'unrealized':0.,'quantity':0.};calendar=[];last_nav=22500.
for session,row in zip(opens,equity.itertuples(),strict=True):
 assert row.ts==cal.next_bar_open(session,Timeframe.D1)
 for a in actions[actions.action_ts.eq(session)].itertuples():
  q,avg=book.get(a.instrument_id,(0.,0.));assert abs(q-a.position_qty_before)<1e-8
  if a.action_type=='split':book[a.instrument_id]=(q*a.ratio,avg/a.ratio)
  else:
   assert a.action_type=='dividend';amount=q*a.cash_amount
   assert abs(amount-a.cashflow_quote)<1e-8;pending+=amount
 for f in fills[fills.ts.eq(session)].itertuples():
  q,avg=book.get(f.instrument_id,(0.,0.));delta=f.qty*(1 if f.side=='buy' else -1)
  assert abs(abs(delta)*f.price-f.notional)<1e-7
  realized=0.
  if q==0 or q*delta>0:newavg=(abs(q)*avg+abs(delta)*f.price)/(abs(q)+abs(delta))
  else:
   realized=min(abs(q),abs(delta))*(f.price-avg)*(1 if q>0 else -1)
   newavg=f.price if abs(delta)>abs(q) else avg
  errors['realized']=max(errors['realized'],abs(realized-f.realized_pnl_quote))
  if q+delta==0:book.pop(f.instrument_id,None)
  else:book[f.instrument_id]=(q+delta,newavg)
  cash-=delta*f.price+f.fee
 daily_borrow=sum(q*float(raw.loc[(mapping[iid],session),'raw_open'])*rate for iid,(q,avg) in book.items() if q<0)
 days=(row.ts-session)/86400000;cash+=daily_borrow*days
 while paid_index<len(paid_events) and paid_events[paid_index]['ts']<=row.ts:
  amount=paid_events[paid_index]['cashflow_quote'];cash+=amount;pending-=amount;paid_index+=1
 snap=positions[positions.ts.eq(row.ts)];assert set(snap.instrument_id)==set(book)
 value=0.
 for pos in snap.itertuples():
  q,avg=book[pos.instrument_id];errors['quantity']=max(errors['quantity'],abs(q-pos.qty))
  errors['unrealized']=max(errors['unrealized'],abs(q*(pos.mark-avg)-pos.unreal_pnl));value+=q*pos.mark
 nav=cash+pending+value;errors['nav']=max(errors['nav'],abs(nav-row.equity))
 # Close price applies to source day. Remove borrow attributable to later days
 # then accrue it linearly through non-session days. Payment moves cash vs
 # receivables but does not alter NAV. Intraday cash availability not certified.
 for day in range(session,row.ts,86400000):
  if day>=config['end']:break
  remaining=(row.ts-day-86400000)/86400000
  calendar.append({'day':pd.Timestamp(day,unit='ms',tz='UTC').strftime('%Y-%m-%d'),'equity':nav-daily_borrow*remaining})
 last_nav=nav
assert max(errors.values())<1e-6,errors
assert abs(cash-meta['terminal_settled_cash'])<1e-6
assert abs(pending-meta['terminal_pending_dividends'])<1e-6
assert paid_index==len(paid_events)
benchpath=R/'artifacts/analysis/crypto_continuous_account_20260913/baseline/calendar2023_2026.csv'
bench=pd.read_csv(benchpath)
assert sha(benchpath)==json.loads((benchpath.parent/'calendar2023_2026_audit.json').read_text())['daily_csv_sha256']
f=pd.DataFrame(calendar).set_index('day').reindex(bench.day)
assert f.equity.iloc[2:].notna().all();f.loc[bench.day.iloc[:2],'equity']=22500.
f['return']=np.r_[f.equity.iloc[0]/22500-1,f.equity.pct_change().iloc[1:]]
f['benchmark']=bench.benchmark.to_numpy();f['excess']=f['return']-f.benchmark
assert len(f)==1248 and f.index.is_unique
f.to_csv(D/'funded_calendar.csv')
nav=np.r_[22500,f.equity.to_numpy()]
report={'status':'QUANTITIES_COST_BASIS_NAV_AND_CALENDAR_RECONCILED','initial_cash':22500,'final_nav':last_nav,'residuals':errors,'calendar_days':len(f),'total_return':last_nav/22500-1,'raw_sharpe':float(f['return'].mean()/f['return'].std(ddof=1)*np.sqrt(365)),'net_excess_sharpe_DFF_proxy':float(f.excess.mean()/f.excess.std(ddof=1)*np.sqrt(365)),'daily_max_drawdown':float((1-nav/np.maximum.accumulate(nav)).max()),'qualified':False,'limits':'Saved fills, fees, action events, settlement amounts and marks are inputs. Source-session close applied on source calendar day, borrow spread over modeled calendar interval. Settlement transfers NAV-neutral; intraday settled cash availability, quote/impact and point-in-time sources not certified.'}
report['sha256']={str(p.relative_to(R)):sha(p) for p in [Path(__file__),benchpath,source/'paired_prices.parquet',source/'schedule.json',D/'run/run_meta.json',D/'funded_calendar.csv',*sorted((D/'run').glob('*.parquet'))]}
with (D/'quantity_calendar_audit.json').open('x') as out:json.dump(report,out,indent=2)
print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2))
