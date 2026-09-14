"""Classify missing exact-date events without accepting neighboring dates."""
import json,hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v3-20260913/unresolved.json'
rows=[];bindings={};sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for x in json.loads(U.read_text()):
 if x['vendor_records']:continue
 p=S/f"{x['symbol']}_dividends.bin";receipt=json.loads((S/f"{x['symbol']}_dividends_receipt.json").read_text());assert sha(p)==receipt['sha256'];bindings[str(p.relative_to(R))]=sha(p)
 body=json.loads(p.read_bytes());assert not body.get('next_url') and body['status']=='OK'
 nearby=[]
 for v in body['results']:
  delta=(date.fromisoformat(v['ex_dividend_date'])-date.fromisoformat(x['ex_date'])).days
  if abs(delta)<=12:
   nearby.append({'vendor_event':v,'calendar_day_offset':delta,'amount_equal':abs(Decimal(str(v['cash_amount']))-Decimal(str(x['cash_amount'])))<=Decimal('0.00000001')})
 rows.append({'frozen_event':x,'nearby_candidates':nearby,'accepted':False})
issuer=S/'AMC_issuer_distribution_review.json';e=json.loads(issuer.read_text());assert any('August' in x and '22, 2022' in x for x in e['lines'])
amc=next(x for x in rows if x['frozen_event']['symbol']=='AMC')
report={'status':'MISSING_EVENTS_CLASSIFIED_NOT_AUTOMATICALLY_REPAIRED','missing_events':len(rows),'neighbor_date_candidates':sum(bool(x['nearby_candidates']) for x in rows),'rows':rows,'AMC':{'status':'UNSUPPORTED_CASH_EVENT_AND_NONCASH_LIFECYCLE_REQUIRED','frozen_date':'2022-08-12','frozen_cash_amount':amc['frozen_event']['cash_amount'],'issuer_ex_date':'2022-08-22','issuer_record_date':'2022-08-15','issuer_expected_distribution_date':'2022-08-19','issuer_distribution':'one APE depositary unit per AMC common share','decision':'Do not map0.01 to a cash pay date or delete entitlement. Affected2022account requires unit entitlement, marks, due-bill timing and later lifecycle accounting before executable qualification. Main2023freshinception doesnotinherit2022units, but source-history/feature implications need separate assessment.','inference_limit':'Issuer source contradicts interpretation as this cash dividend; it does not establish how provider generated its0.01row or exhaustively rule out every separate cash event.'},'accepted_new_events':0,'limits':'Nearby date/amount matches are diagnostic leads, not identity/exdate corrections. No source modified, no returns measured.','sha256':{**bindings,str(U.relative_to(R)):sha(U),str(issuer.relative_to(R)):sha(issuer),str(Path(__file__).relative_to(R)):sha(Path(__file__))}}
with (S/'missing_event_classification.json').open('x') as f:json.dump(report,f,indent=2)
print(report['missing_events'],report['neighbor_date_candidates'])
