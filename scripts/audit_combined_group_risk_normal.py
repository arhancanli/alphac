"""Independent scalar reconstruction and statistics of saved combined substitution."""
import csv,json,hashlib,math,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1];D=R/'artifacts/analysis/combined_group_risk_20260913/normal_v2';B=R/'artifacts/analysis/bil_cash_20260913/normal/daily.csv';C=R/'artifacts/analysis/trend_group_risk_20260913/baseline/calendar2023_2026_excess.csv'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
 with p.open() as f:return list(csv.DictReader(f))
def metrics(rows):
 r=[float(x['total']) for x in rows];e=[float(x['excess']) for x in rows];nav=high=1.;dd=0
 for x in r:nav*=1+x;high=max(high,nav);dd=max(dd,1-nav/high)
 return {'return':nav-1,'raw_sharpe':statistics.mean(r)/statistics.stdev(r)*math.sqrt(365),'excess_sharpe_proxy':statistics.mean(e)/statistics.stdev(e)*math.sqrt(365),'max_drawdown':dd,'observations':len(rows)}
def main():
 for p,h in json.loads((D/'input_manifest.json').read_text())['sha256'].items():assert sha(R/p)==h
 base=read(B);candidate=read(D/'daily.csv');trend={r['session'][:10]:float(r['return']) for r in read(C)}
 assert len(base)==len(candidate)==1248 and len(trend)==855
 for a,b in zip(base,candidate):
  assert a['day']==b['day']
  for k in ['max','crypto','cash_contribution','benchmark']:assert abs(float(a[k])-float(b[k]))<1e-14
  t=trend.get(a['day'],0.);assert abs(t-float(b['trend']))<1e-14
  total=.225*(float(a['max'])+float(a['crypto'])+t)+float(a['cash_contribution'])
  assert abs(total-float(b['total']))<1e-14
  assert abs(total-float(a['benchmark'])-float(b['excess']))<1e-14
 result=json.loads((D/'result.json').read_text())
 for rows,target in [(candidate,result),(base,result['baseline'])]+[( [r for r in candidate if r['day'].startswith(y)],v['candidate']) for y,v in result['annual'].items()]:
  for k,v in metrics(rows).items():assert abs(v-target[k])<1e-11
 assert not result['all_gates_pass'] and not result['gates']['excess_gain'] and not result['gates']['return_not_lower']
 paths=[B,C,D/'daily.csv',D/'result.json',Path(__file__)]
 report={'pass':True,'decision':'FAIL_NORMAL_COMBINED_GATE_STOP_GROUP_FAMILY','days':1248,'metric_tolerance':1e-11,'return_reconstruction_tolerance':1e-14,'sha256':{str(p.relative_to(R)):sha(p) for p in paths},'stress_allowed':False,'2022_allowed':False,'qualified':False}
 with (D/'independent_audit.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
 print(json.dumps(report))
if __name__=='__main__':main()
