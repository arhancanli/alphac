"""Specific P&G cash corrections supported by retained SEC filings."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v6-20260913/unresolved.json';P=S/'PG_SEC_review.json'
rows=[]
for s in json.loads(P.read_text())['sources']:
 t=s['result'].replace('\xa0',' ')
 m=re.search(r'declared a quarterly dividend of\s*\$(\d+\.\d+) per share on the Common Stock.*?payable on or after ([A-Z][a-z]+ \d+, \d{4}), to Common Stock shareholders of record at the close of business on ([A-Z][a-z]+ \d+, \d{4})',t)
 if m:
  amount,pay,record=m.groups();iso=lambda d:datetime.strptime(d,'%B %d, %Y').date().isoformat()
  rows.append({'amount':amount,'pay_date':iso(pay),'record_date':iso(record),'url':s['url']})
assert len(rows)==3
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='PG':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']]
 if not matches:continue
 assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'PG','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_SEC_cash_correction'})
assert len(resolved)==3
report={'status':'THREE_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Issuer amount and record date corroborate vendor. Issuer says payable on or after date; vendor pay date equals that date, not proof of actual broker settlement time. Ex date retained from frozen/vendor agreement. July remains unresolved. Current retrieval of dated filings, no claim of full point-in-time input certification.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'PG_SEC_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
