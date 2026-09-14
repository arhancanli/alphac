"""Replay quantities/average costs from fills independently of saved PnL fields."""
from pathlib import Path
import json,hashlib
import pandas as pd
R=Path(__file__).resolve().parents[1];O=R/'artifacts/analysis/crypto_funded_reference_20260913/baseline'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
wf=json.loads((O/'run/walkforward.json').read_text());initial=22500.;legs=[]
for leg in wf['legs']:
 d=O/f"run/legs/leg_{leg['leg']:02d}"
 fills=pd.read_parquet(d/'fills.parquet');funding=pd.read_parquet(d/'funding.parquet')
 positions=pd.read_parquet(d/'positions.parquet');equity=pd.read_parquet(d/'equity.parquet')
 events=[]
 for row in fills.to_dict('records'):
  terminal=row['reason'] in ['administrative_terminal_settlement','forced_flat']
  events.append((int(row['ts']),1 if terminal else 3,'fill',row))
 for row in funding.to_dict('records'):events.append((int(row['ts_funding']),0,'funding',row))
 for row in equity.to_dict('records'):events.append((int(row['ts']),2,'mark',row))
 events.sort(key=lambda x:(x[0],x[1]))
 book={};cash=initial;maximum=0.;realized_error=0.;funding_error=0.
 snapshots={int(t):g for t,g in positions.groupby('ts')}
 for ts,priority,kind,row in events:
  if kind=='fill':
   iid=row['instrument_id'];q,avg=book.get(iid,(0.,0.));amount=float(row['qty'])*(1 if row['side']=='buy' else -1);price=float(row['price'])
   assert abs(row['notional']-abs(amount)*price)<1e-6
   realized=0.
   if q==0 or q*amount>0:newavg=(abs(q)*avg+abs(amount)*price)/(abs(q)+abs(amount))
   else:
    realized=min(abs(q),abs(amount))*(price-avg)*(1 if q>0 else -1)
    newavg=price if abs(amount)>abs(q) else avg
   newq=q+amount
   if newq==0:book.pop(iid,None)
   else:book[iid]=(newq,newavg)
   realized_error=max(realized_error,abs(realized-row['realized_pnl_quote']))
   assert realized_error<1e-6
   cash+=realized-float(row['fee'])
  elif kind=='funding':
   q=book.get(row['instrument_id'],(0.,0.))[0]
   assert abs(q-row['position_qty'])<1e-8
   payment=-q*row['mark_price']*row['rate'];funding_error=max(funding_error,abs(payment-row['payment_quote']))
   assert funding_error<1e-7;cash+=payment
  else:
   snap=snapshots.get(ts,positions.iloc[:0]);observed=set(snap.instrument_id)
   assert observed==set(book),(leg['leg'],ts,observed^set(book))
   unrealized=0.
   for pos in snap.itertuples():
    q,avg=book[pos.instrument_id];assert abs(q-pos.qty)<1e-8
    value=q*(pos.mark-avg);assert abs(value-pos.unreal_pnl)<1e-6;unrealized+=value
   maximum=max(maximum,abs(cash+unrealized-row['equity']));assert maximum<1e-6
 assert not book,'Leg must end flat before funded capital continuity'
 initial=cash
 legs.append({'leg':leg['leg'],'fills':len(fills),'funding_events':len(funding),'marks':len(equity),'nav_residual_max':maximum,'realized_pnl_residual_max':realized_error,'funding_residual_max':funding_error,'ending_cash':cash})
report={'status':'INDEPENDENT_FILL_QUANTITY_COST_BASIS_AND_NAV_REPLAY_PASSED','initial_cash':22500,'final_cash':initial,'legs':legs,'limits':'Recorded execution prices/fees and mark prices are inputs. This independently checks quantities, cost basis, realized/unrealized PnL, funding position quantities and account conservation; it does not certify market impact, quotes, actual collateral or price-source availability.','sha256':{str(p.relative_to(R)):sha(p) for p in [Path(__file__),O/'run/walkforward.json',O/'run/fills.parquet',O/'run/positions.parquet',O/'run/funding.parquet',O/'run/equity.parquet']}}
with (O/'quantity_audit.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps({k:v for k,v in report.items() if k not in ['sha256','legs']}));print('maximum_nav_residual',max(x['nav_residual_max'] for x in legs))
