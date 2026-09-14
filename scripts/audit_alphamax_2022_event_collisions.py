"""Identify source-event collisions without silently repairing frozen events."""
import json,re,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913'
A=S/'match_audit.json';U=R/'evidence/alphamax-payment-schedule-review-v24-20260913/unresolved.json'
a=json.loads(A.read_text())['matches'];u=json.loads(U.read_text());files=[]
def body(sym):
 p=S/(sym+'_2022_exception.web.json');files.append(p)
 return ' '.join(re.sub(r'L\d+(?:@P[0-9-]+)?:','',json.loads(p.read_text())['result']).split())
iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
t=body('TGT');rows=re.findall(r'2022 ([1-4]) ([A-Z][a-z]+ \d+, 2022) ([A-Z][a-z]+ \d+, 2022) Cash \$([0-9.]+)',t)
assert len(rows)==4
issuer=[{'quarter':int(q),'record_date':iso(rec),'pay_date':iso(pay),'amount':amt} for q,rec,pay,amt in rows]
orig=[x for x in a if x['symbol']=='TGT' and x['ex_date'].startswith('2022')]
assert len(orig)==5
for term in issuer:
 matches=[x for x in orig if x['accepted'] and any(v['record_date']==term['record_date'] and v['pay_date']==term['pay_date'] and Decimal(str(v['cash_amount']))==Decimal(term['amount']) for v in x['vendor_records'])]
 assert len(matches)==1
frozen_sum=sum(Decimal(str(x['cash_amount'])) for x in orig);issuer_sum=sum(Decimal(x['amount']) for x in issuer)
assert issuer_sum==Decimal('3.96') and frozen_sum-issuer_sum==Decimal('1.08')
m=body('MCO');assert 'dividend of $0.70 per share of MCO Common Stock. The dividend will be payable on December 14, 2022, to stockholders of record at the close of business on November 23, 2022' in m
mco_existing=[x for x in a if x['symbol']=='MCO' and x['ex_date']=='2022-11-22'];assert len(mco_existing)==1 and mco_existing[0]['accepted']
v=mco_existing[0]['vendor_records'][0];assert v['pay_date']=='2022-12-14' and v['record_date']=='2022-11-23'
h=body('HON');assert 'fourth-quarter dividend of $1.03 per share' in h and 'payable on December 2, 2022' in h and 'November 11, 2022' in h
classification=S/'missing_event_classification.json';prior=json.loads(classification.read_text())
hon=next(x for x in prior['rows'] if x['frozen_event']['symbol']=='HON')
assert len(hon['nearby_candidates'])==1
vendor=hon['nearby_candidates'][0]['vendor_event'];assert vendor['ex_dividend_date']=='2022-11-09' and vendor['pay_date']=='2022-12-02'
report={'status':'EVENT_COLLISIONS_AND_DATE_CONFLICT_RETAINED_NO_CASH_ACCEPTANCE','TGT':{'issuer_rows':issuer,'frozen_total':str(frozen_sum),'issuer_total':str(issuer_sum),'extra_frozen_event':next(x for x in orig if not x['accepted']),'finding':'Every issuer2022 dividend already represented by one accepted frozen event. Extra September15 event cannot receive a second copy of an existing payment. Provider-origin audit needed before explicit quarantine decision.'},'MCO':{'unresolved':next(x for x in u if x['symbol']=='MCO'),'issuer_terms_already_bound_to':mco_existing[0],'finding':'October24 announced November23-record December14-payment event already represented by November22 frozen event. Do not assign it to October26 as well; separate cash event remains unsupported.'},'HON':{'frozen_event':hon['frozen_event'],'vendor_event':vendor,'issuer_terms':{'amount':'1.03','record_date':'2022-11-11','pay_date':'2022-12-02'},'finding':'Amount/pay corroborated, exdate conflict November10 versus November9 persists. Verify market entitlement boundary, including settlement holiday treatment, before date amendment. No generic prior-weekday rule.'},'accepted_events':0,'next_action':'Inspect retained original-provider action records for TGT/MCO/HL anomalous extra events and design explicit reviewed quarantine if supported; inspect issuer/exchange exdates for HON/COP. Do not repeat issuer cash searches for these same notices.','limits':'Current-vintage sources. Source absence alone is not proof no separate event occurred. No source row deleted/shifted, no schedule change, no returns or qualification.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),A,U,classification,*files]}}
with (S/'event_collision_audit_2022.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status']);print('TGT totals',frozen_sum,issuer_sum)
