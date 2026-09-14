"""Three specific Delta cash corrections from issuer dividend history."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v13-20260913/unresolved.json';P=S/'DAL_issuer_table.json'
t=json.loads(P.read_text())['result'].split('## Dividend History')[1];iso=lambda d:datetime.strptime(d,'%m/%d/%Y').date().isoformat()
rows=[dict(ex_date=iso(e),record_date=iso(r),pay_date=iso(p),amount=a) for e,r,p,a in re.findall(r'(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*\$(\d+\.\d+)',t)]
assert rows
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='DAL':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['ex_date']==x['ex_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and i['record_date']==v['record_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'DAL',**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_table_cash_correction'})
assert len(resolved)==3
report={'status':'THREE_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Exact issuer/vendor amounts and ex/record/payment dates. Retained issuer table search extraction is current-vintage evidence, not full PIT certification or broker settlement proof. Original frozen inputs preserved.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'DAL_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
