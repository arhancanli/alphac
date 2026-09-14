"""Assemble reviewed cash schedule and explicit unresolved gate, never run returns."""
import json,hashlib
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';O=R/'evidence/alphamax-payment-schedule-review-v17-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=json.loads((S/'match_audit.json').read_text());components=json.loads((S/'component_reconciliation.json').read_text());dvn=json.loads((S/'DVN_adjudication.json').read_text());patch=json.loads((S/'issuer_cash_correction_overlay.json').read_text())
key=lambda x:(x['instrument_id'],x['ex_date'])
review={}
for x in source['matches']:
 if x['accepted']:review[key(x)]={'amount':str(x['cash_amount']),'pay_date':x['vendor_records'][0]['pay_date'],'basis':'single_vendor_exact_match','amount_changed':False}
for x in components['resolved']:
 assert key(x) not in review
 review[key(x)]={'amount':str(x['cash_amount']),'pay_date':x['component_reconciliation']['pay_date'],'basis':'same_date_component_sum','amount_changed':False}
assert key(dvn) not in review
review[key(dvn)]={'amount':str(dvn['cash_amount']),'pay_date':dvn['pay_date'],'basis':'issuer_DVN_adjudication','amount_changed':False}
for x in patch['patches']:
 assert key(x) not in review
 review[key(x)]={'amount':x['reviewed_cash_amount'],'pay_date':x['pay_date'],'basis':'issuer_explicit_cash_correction','amount_changed':True,'frozen_amount':x['frozen_cash_amount']}
for x in json.loads((S/'FCX_adjudication.json').read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed']}
G=R/'evidence/alphamax-gold-ticker-route-20260913/adjudication.json'
for x in json.loads(G.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed']}
C=S/'CEG_table_adjudication.json'
for x in json.loads(C.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
D=S/'O_2025_adjudication.json'
for x in json.loads(D.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
E=S/'D_NEE_T_adjudication.json'
for x in json.loads(E.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
F=S/'PG_SEC_adjudication.json'
for x in json.loads(F.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
H=S/'MET_adjudication.json'
for x in json.loads(H.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
J=S/'AON_adjudication.json';K=S/'WMT_adjudication.json'
for f in [J,K]:
 for x in json.loads(f.read_text())['resolved']:
  assert key(x) not in review
  review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
L=S/'VZ_CCI_adjudication.json'
for x in json.loads(L.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
M=S/'HPE_HPQ_adjudication.json'
for x in json.loads(M.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
N=S/'KVUE_adjudication.json'
for x in json.loads(N.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
Q=S/'SLB_adjudication.json'
for x in json.loads(Q.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
T=S/'DAL_adjudication.json'
for x in json.loads(T.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
V=S/'IP_VRT_adjudication.json'
for x in json.loads(V.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
W=S/'SW_adjudication.json';Y=S/'APO_adjudication.json'
for f in [W,Y]:
 for x in json.loads(f.read_text())['resolved']:
  assert key(x) not in review
  review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
Z=S/'PG_DELL_remaining_adjudication.json'
for x in json.loads(Z.read_text())['resolved']:
 assert key(x) not in review
 review[key(x)]={k:x[k] for k in ['amount','pay_date','basis','amount_changed','frozen_amount']}
accepted=[];unresolved=[]
for x in source['matches']:
 if key(x) in review:accepted.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],**review[key(x)]})
 else:unresolved.append(x)
assert len(accepted)==3371 and len(unresolved)==95 and len(review)==len(accepted)
O.mkdir(exist_ok=False)
files=[S/n for n in ['match_audit.json','component_reconciliation.json','DVN_adjudication.json','issuer_cash_correction_overlay.json','FCX_adjudication.json']]
files.extend([G,C,D,E,F,H,J,K,L,M,N,Q,T,V,W,Y,Z])
for f in files:
 a=json.loads(f.read_text())
 for name,h in a.get('sha256',{}).items():
  p=Path(name);p=p if p.is_absolute() else R/p
  assert sha(p)==h,name
(O/'reviewed_schedule.json').write_text(json.dumps(accepted,indent=2)+'\n');(O/'unresolved.json').write_text(json.dumps(unresolved,indent=2)+'\n')
report={'status':'INCOMPLETE_SOURCE_SCHEDULE_REPLAY_FORBIDDEN','total':3466,'reviewed':3371,'unchanged_amount':3279,'explicit_new_amounts':92,'unresolved':95,'unresolved_by_symbol':dict(Counter(x['symbol'] for x in unresolved)),'coverage_by_year':{str(y):{'reviewed':sum(x['ex_date'].startswith(str(y)) for x in accepted),'unresolved':sum(x['ex_date'].startswith(str(y)) for x in unresolved)} for y in range(2022,2027)},'qualification':False,'limitations':'Assembled vendor/issuer-reviewed current-vintage events, not complete security-identity/PIT certification. No input lake mutated or historical returns computed. Do not drop unresolved events or trade only reviewed names.','sha256':{str(p.relative_to(R)):sha(p) for p in [*files,Path(__file__),O/'reviewed_schedule.json',O/'unresolved.json']}}
(O/'gate.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['sha256','unresolved_by_symbol']},indent=2))
