"""Four event-specific APO ordinary cash corrections, excluding preferred stock."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v15-20260913/unresolved.json'
files=[Path(__file__),U];table={}
for name in ['May','Aug_release','Nov','Feb']:
 p=S/f'APO_{name}.web.json';files.append(p);r=json.loads(p.read_text());t=' '.join(re.sub(r'L\d+: ','',r['result']).split())
 m=re.search(r'Apollo Global Management, Inc\. has declared a cash dividend of \$([0-9.]+) per share of its Common Stock.{0,120}?This dividend will be paid on ([A-Z][a-z]+ \d{1,2}, \d{4}) to holders of record at the close of business on ([A-Z][a-z]+ \d{1,2}, \d{4})',t);assert m,p
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
 pay=iso(m.group(2));assert pay not in table;table[pay]=(m.group(1),iso(m.group(3)),r['url'])
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='APO':continue
 assert len(x['vendor_records'])==1;v=x['vendor_records'][0];amount,record,url=table[v['pay_date']]
 assert Decimal(amount)==Decimal(str(v['cash_amount'])) and record==v['record_date'] and v['currency']=='USD'
 assert v['ex_dividend_date']==x['ex_date'] and Decimal(amount)!=Decimal(str(x['cash_amount']))
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'APO','ex_date':x['ex_date'],'amount':amount,'pay_date':v['pay_date'],'basis':'issuer_APO_common_stock_explicit_terms','amount_changed':True,'frozen_amount':str(x['cash_amount']),'issuer_record_date':record,'source':url,'issuer_ex_date_verified':False})
assert len(resolved)==4
report={'status':'FOUR_APO_CASH_CONFLICTS_CORROBORATED','resolved':resolved,'limits':'Current-vintage issuer common-stock amounts and record/payment dates. Ex-date retained from vendor; no historical source availability, tax or execution certification. Preferred dividends and rounded summary tables not used. Failed August10Q web route retained; issuer press release used instead.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
with (S/'APO_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
