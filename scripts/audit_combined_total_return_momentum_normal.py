"""Independent scalar return, annual-statistic and gate reconstruction."""
import csv,json,hashlib
from pathlib import Path
from audit_combined_group_risk_normal import metrics
R=Path(__file__).resolve().parents[1];D=R/'artifacts/analysis/combined_total_return_momentum_20260913/normal';B=R/'artifacts/analysis/bil_cash_20260913/normal/daily.csv';C=R/'artifacts/analysis/alphamax_total_return_momentum_20260913/candidate/calendar2023_2026_excess.csv'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
 with p.open() as f:return list(csv.DictReader(f))
for p,h in json.loads((D/'input_manifest.json').read_text())['sha256'].items():assert sha(R/p)==h
base=read(B);candidate=read(D/'daily.csv');stock={r['session'][:10]:float(r['return']) for r in read(C)}
assert len(base)==len(candidate)==1248 and len(stock)==855
for a,b in zip(base,candidate):
 assert a['day']==b['day']
 for k in ['trend','crypto','cash_contribution','benchmark']:assert abs(float(a[k])-float(b[k]))<1e-14
 t=stock.get(a['day'],0.);assert abs(t-float(b['max']))<1e-14
 total=.225*(float(a['trend'])+float(a['crypto'])+t)+float(a['cash_contribution'])
 assert abs(total-float(b['total']))<1e-14
 assert abs(total-float(a['benchmark'])-float(b['excess']))<1e-14
result=json.loads((D/'result.json').read_text());cm=metrics(candidate);bm=metrics(base)
pairs=[(cm,result),(bm,result['baseline'])]
years={}
for y,stored in result['annual'].items():
 c=metrics([r for r in candidate if r['day'].startswith(y)]);b=metrics([r for r in base if r['day'].startswith(y)])
 pairs.extend([(c,stored['candidate']),(b,stored['baseline'])]);years[y]=(c,b)
for actual,stored in pairs:
 for k,v in actual.items():assert abs(v-stored[k])<1e-11
checks={'excess_gain':cm['excess_sharpe_proxy']-bm['excess_sharpe_proxy']>=.1,'return_not_lower':cm['return']>=bm['return'],'full_drawdown':cm['max_drawdown']<=.11,'annual_drawdowns':all(c['max_drawdown']<=.11 for c,b in years.values()),'annual_excess_floor':all(c['excess_sharpe_proxy']-b['excess_sharpe_proxy']>=-.25 for c,b in years.values())}
assert checks==result['gates'] and all(checks.values())==result['all_gates_pass']
assert not checks['excess_gain'] and not checks['return_not_lower']
paths=[B,C,D/'daily.csv',D/'result.json',Path(__file__),R/'scripts/audit_combined_group_risk_normal.py']
report={'pass':True,'decision':'FAIL_NORMAL_COMBINED_GATE_STOP_TOTAL_RETURN_CANDIDATE','days':1248,'excess_sharpe_change':cm['excess_sharpe_proxy']-bm['excess_sharpe_proxy'],'gates':checks,'metric_tolerance':1e-11,'return_reconstruction_tolerance':1e-14,'sha256':{str(p.relative_to(R)):sha(p) for p in paths},'stress_allowed':False,'2022_allowed':False,'qualified':False}
with (D/'independent_audit.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report))
