"""Adjudicate missing vendor components against issuer record/pay-date table."""
import json,hashlib
from pathlib import Path
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-20260913/unresolved.json'
issuer=json.loads((S/'FCX_issuer_components.json').read_text());unresolved=json.loads(U.read_text());resolved=[]
for x in unresolved:
 if x['symbol']!='FCX':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0]
 rows=[r for r in issuer['rows'] if r['record_date']==v['record_date'] and r['pay_date']==v['pay_date']]
 assert len(rows)==2 and {r['type'] for r in rows}=={'Base Cash','Variable Cash'}
 total=sum((Decimal(r['amount']) for r in rows),Decimal(0))
 assert abs(total-Decimal(str(x['cash_amount'])))<=Decimal('0.00000001')
 assert v['ex_dividend_date']==x['ex_date'] and v['currency']=='USD'
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'FCX','ex_date':x['ex_date'],'amount':str(total),'pay_date':v['pay_date'],'record_date':v['record_date'],'issuer_components':rows,'basis':'issuer_missing_variable_component_adjudication','amount_changed':False})
assert len(resolved)==15
out={'status':'FIFTEEN_MISSING_COMPONENTS_ADJUDICATED','resolved':resolved,'limits':'Issuer total/paydate/recorddate corroborated; exdate from existing matched frozen/vendor event. Current website table extraction, not historical publication proof. No generic doubling rule and no other issuer affected.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,S/'FCX_issuer_components.json']}}
with (S/'FCX_adjudication.json').open('x') as f:json.dump(out,f,indent=2)
print('Adjudicated',len(resolved))
