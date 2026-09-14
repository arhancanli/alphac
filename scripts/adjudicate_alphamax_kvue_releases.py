"""Seven event-specific Kenvue cash corrections from dated issuer announcements."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v11-20260913/unresolved.json';P=S/'KVUE_issuer_releases.json'
rows=[];iso=lambda d:datetime.strptime(d,'%B %d, %Y').date().isoformat()
for t in json.loads(P.read_text())['sources']:
 assert 'https://investors.kenvue.com/financial-news/news-details/' in t
 amounts=set(re.findall(r'\$(0\.\d+) per share',t));assert len(amounts)==1
 pairs=set(re.findall(r'dividend is payable on ([A-Z][a-z]+ \d+, \d{4}), to shareholders of record as of the close of business on ([A-Z][a-z]+ \d+, \d{4})',t));assert len(pairs)==1
 p,r=pairs.pop();rows.append({'amount':amounts.pop(),'record_date':iso(r),'pay_date':iso(p)})
assert len(rows)==7
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='KVUE':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'KVUE','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_release_cash_correction'})
assert len(resolved)==7
report={'status':'SEVEN_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Exact issuer/vendor amounts and record/payment dates. Ex dates retained from frozen/vendor agreement, not independently specified in releases. Current retrieval of dated releases does not certify full historical dissemination or actual broker settlement. Preserve all original amounts; no generic rounding tolerance or historical returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'KVUE_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
