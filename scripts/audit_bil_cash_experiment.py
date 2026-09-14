"""Reconstruct cash/receivables from cumulative purchases and issuer events."""
import csv,json,hashlib,argparse
from pathlib import Path
from datetime import date
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/bil_cash_20260913'
def read(p):
 with p.open() as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(arm):
 directory=OUT/arm
 manifest=json.loads((OUT/'input_manifest.json').read_text())['sha256']
 for p,h in manifest.items():assert sha(ROOT/p)==h,p
 ledger=read(directory/'ledger.csv');combined=read(directory/'daily.csv')
 baseline=read(ROOT/'artifacts/analysis/combined_session_cooldown_20260913'/('candidate' if arm=='normal' else 'candidate_stress')/'daily.csv')
 prices={x['date']:x for x in read(ROOT/'evidence/bil-source-capture-20260913/funds_BIL.csv')}
 events=read(ROOT/'evidence/bil-issuer-distributions-20260913/BIL_distributions.csv')
 qty=0;spent=D(0);entitlements=[];mark=D(0);previous=D(100000);month=None;max_error=D(0)
 rate=D(6 if arm=='normal' else 12)/10000
 assert len(ledger)==len(combined)==len(baseline)==1248
 for row,output,base in zip(ledger,combined,baseline):
  day=row['day'];assert day==output['day']==base['day']
  assert int(row['carried_quantity'])==qty
  for event in events:
   if event['ex_date']==day:entitlements.append((event['pay_date'],qty*D(event['total'])))
  paid_before=sum((amount for pay,amount in entitlements if pay<day),D(0))
  available=D(100000)-spent+paid_before
  assert D(row['available_at_open'])==available
  buy=0
  if day in prices:
   price=prices[day];mark=D(price['closeunadj'])
   if month!=day[:7]:
    buy=int(available//(D(price['open'])*(1+rate)));month=day[:7]
   expected_notional=buy*D(price['open'])
  else:expected_notional=D(0)
  assert int(row['bought'])==buy and D(row['notional'])==expected_notional
  assert D(row['fee'])==expected_notional*rate
  spent+=expected_notional*(1+rate);qty+=buy
  paid_to_date=sum((amount for pay,amount in entitlements if pay<=day),D(0))
  pending=sum((amount for pay,amount in entitlements if pay>day),D(0))
  cash=D(100000)-spent+paid_to_date
  nav=D(100000)+qty*mark-spent+sum((amount for _,amount in entitlements),D(0))
  assert int(row['quantity'])==qty and D(row['mark'])==mark
  assert D(row['pending'])==pending and D(row['cash'])==cash and cash>=0
  error=abs(D(row['nav'])-nav);max_error=max(error,max_error);assert error<D('1e-18')
  cash_return=nav/previous-1;assert abs(cash_return-D(row['net_return']))<D('1e-18');previous=nav
  for k in ['day','max','trend','crypto','benchmark']:assert output[k]==base[k],k
  expected=float(base['total'])+.325*float(cash_return)
  assert abs(float(output['total'])-expected)<1e-15
  assert abs(float(output['excess'])-(expected-float(base['benchmark'])))<1e-15
 result=json.loads((directory/'result.json').read_text())
 gate={'excess_gain':result['excess_sharpe_proxy']-result['baseline']['excess_sharpe_proxy']>=.10,
       'return_not_lower':result['return']>=result['baseline']['return'],
       'full_drawdown':result['max_drawdown']<=.11,
       'annual_drawdowns':all(v['candidate']['max_drawdown']<=.11 for v in result['annual'].values()),
       'annual_excess_floor':all(v['candidate']['excess_sharpe_proxy']-v['baseline']['excess_sharpe_proxy']>=-.25 for v in result['annual'].values())}
 report={'pass':True,'arm':arm,'days':len(ledger),'source_bindings_verified':len(manifest),'max_nav_error':str(max_error),
         'terminal_pending':str(pending),'terminal_cash':str(cash),'quantity':qty,'gates':gate,'all_arm_gates_pass':all(gate.values()),
         'method':'Independent cumulative purchase/debit and issuer-entitlement reconstruction; matched baseline columns and combined returns checked.',
         'limitations':'Synthetic cost assumptions and current-vintage sources; not broker settlement verification or untouched OOS.',
         'sha256':{str(p.relative_to(ROOT)):sha(p) for p in [directory/'ledger.csv',directory/'daily.csv',directory/'result.json',Path(__file__)]}}
 with (directory/'independent_audit.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
 print(json.dumps(report))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--arm',required=True,choices=['normal','stress']);run(parser.parse_args().arm)
