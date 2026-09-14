"""Resolve seven specific cash-amount conflicts from captured issuer releases."""
import json,re,hashlib
from decimal import Decimal
from datetime import datetime
from pathlib import Path
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-ip-vrt-sources-20260913';S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v14-20260913/unresolved.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
resolved=[];files=[Path(__file__),U,O/'request_plan.json']
for x in json.loads(U.read_text()):
 if x['symbol'] not in ('IP','VRT'):continue
 p=O/(x['symbol']+'_'+x['ex_date']+'.web.json');r=json.loads(p.read_text());t=' '.join(re.sub(r'L[0-9]+: ', '', r['result']).split())
 files.append(p)
 assert len(x['vendor_records'])==1;v=x['vendor_records'][0]
 if x['symbol']=='IP':
  assert 'SOURCE International Paper' in t
  m=re.search(r'quarterly dividend of \$([0-9.]+) per share.{0,180}?on the common stock.{0,100}?payable on ([A-Z][a-z]+ \d{1,2}, \d{4}), to holders of record at the close of business on ([A-Z][a-z]+ \d{1,2}, \d{4})',t)
 else:
  assert 'SOURCE Vertiv Holdings Co' in t
  m=re.search(r'(?:quarterly|fourth-quarter) cash dividend of \$([0-9.]+) per share.{0,350}?payable on ([A-Z][a-z]+ \d{1,2}, \d{4}), to shareholders of record of Class A common stock at the close of business on ([A-Z][a-z]+ \d{1,2}, \d{4})',t)
 assert m,(p,'Specific common-stock cash terms not found')
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
 amount=m.group(1);pay=iso(m.group(2));record=iso(m.group(3))
 assert Decimal(amount)==Decimal(str(v['cash_amount'])) and pay==v['pay_date'] and record==v['record_date']
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(amount)!=Decimal(str(x['cash_amount']))
 resolved.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_specific_IP_VRT_common_dividend','amount_changed':True,'frozen_amount':str(x['cash_amount']),'issuer_record_date':record,'source':r['url'],'issuer_ex_date_verified':False})
assert len(resolved)==7
report={'status':'SEVEN_SPECIFIC_COMMON_DIVIDEND_AMOUNTS_CORROBORATED','resolved':resolved,'limits':'Issuer amount/record/payment terms match vendor. Ex-date retained from vendor, not relabeled issuer verified. IP preferred distribution excluded by common-stock clause. VRT November board date November13 differs from release November14; no intraday availability inference. Current-vintage correction only, no original lake mutation or historical returns.','sha256':{str(p.relative_to(R)):sha(p) for p in files}}
with (S/'IP_VRT_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
