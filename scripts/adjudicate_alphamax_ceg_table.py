"""Version specific issuer-supported CEG cash corrections, preserving frozen rows."""
import json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v3-20260913/unresolved.json'
issuer=json.loads((S/'CEG_issuer_table.json').read_text());iso=lambda x:datetime.strptime(x,'%B %d, %Y').date().isoformat()
rows=[{**x,**{k:iso(x[k]) for k in ['declared','ex_date','record_date','pay_date']}} for x in issuer['rows']]
index={x['ex_date']:x for x in rows};assert len(index)==len(rows)
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='CEG':continue
 i=index[x['ex_date']];assert len(x['vendor_records'])==1;v=x['vendor_records'][0]
 assert Decimal(i['amount'])==Decimal(str(v['cash_amount'])) and i['pay_date']==v['pay_date'] and i['record_date']==v['record_date']
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'CEG','ex_date':x['ex_date'],'amount':i['amount'],'pay_date':i['pay_date'],'record_date':i['record_date'],'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_table_cash_correction','vendor_id':v['id']})
assert len(resolved)==7
report={'status':'SEVEN_SPECIFIC_ISSUER_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Exact issuer/vendor amount and ex/record/pay-date agreement. Preserve original rounded amounts; use only in newly bound source version and registered replay. No general rounding tolerance or retrospective performance update. Current issuer table is not historical dissemination proof.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,S/'CEG_issuer_table.json']}}
with (S/'CEG_table_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
