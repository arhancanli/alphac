"""Specific Verizon and Crown Castle cash corrections from issuer tables."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v9-20260913/unresolved.json'
files=[S/f'{s}_issuer_table.json' for s in ['VZ','CCI']]
iso=lambda d:datetime.strptime(d,'%m/%d/%Y').date().isoformat()
rows={}
for symbol,p in zip(['VZ','CCI'],files):
 t=json.loads(p.read_text())['result']
 raw=re.findall(r'(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*\$?(\d+\.\d+)',t)
 rows[symbol]=[dict(declared=iso(d),ex_date=iso(e),record_date=iso(r),pay_date=iso(pay),amount=a) for d,e,r,pay,a in raw]
 assert rows[symbol]
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol'] not in rows:continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows[x['symbol']] if r['ex_date']==x['ex_date']];assert len(matches)==1
 i=matches[0]
 assert i['pay_date']==v['pay_date'] and i['record_date']==v['record_date']
 assert Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_table_cash_correction'})
assert len(resolved)==5
report={'status':'FIVE_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Issuer ex/record/pay dates and amounts exactly corroborate vendor. Current-vintage issuer tables, not complete historical dissemination evidence. Original amounts preserved, no general rounding tolerance. No original input mutation or historical returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*files]}}
with (S/'VZ_CCI_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
