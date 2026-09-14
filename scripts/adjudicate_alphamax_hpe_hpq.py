"""Specific HPE and HP Inc. payment corrections; retain distinct issuer identities."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v10-20260913/unresolved.json'
files=[S/'HPE_issuer_table.json',S/'HPQ_issuer_releases.json'];rows={'HPE':[],'HPQ':[]}
iso=lambda d,fmt:datetime.strptime(d,fmt).date().isoformat()
t=json.loads(files[0].read_text())['result']
for d,e,r,p,a in re.findall(r'(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*(\d+\.\d+) USD',t):
 rows['HPE'].append(dict(ex_date=iso(e,'%m/%d/%y'),record_date=iso(r,'%m/%d/%y'),pay_date=iso(p,'%m/%d/%y'),amount=a))
for t in json.loads(files[1].read_text())['results']:
 assert '(NYSE: HPQ)' in t
 amount=re.search(r'cash dividend of \$(\d+\.\d+) per share',t).group(1)
 p,r=re.search(r'is payable on ([A-Z][a-z]+ \d+, \d{4}), to stockholders of record as of the close of business on ([A-Z][a-z]+ \d+, \d{4})',t).groups()
 rows['HPQ'].append(dict(record_date=iso(r,'%B %d, %Y'),pay_date=iso(p,'%B %d, %Y'),amount=amount))
resolved=[]
for x in json.loads(U.read_text()):
 s=x['symbol']
 if s not in rows:continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows[s] if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 if s=='HPE':assert i['ex_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':s,'ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_cash_correction','issuer_ex_date_verified':s=='HPE'})
assert len(resolved)==3
report={'status':'THREE_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'HPE and HPQ are separate issuers. Exact issuer/vendor cash, record/pay dates; HPE issuer also supplies ex date, HPQ ex date retained from frozen/vendor agreement. HPE table labels amounts split adjusted; this review corroborates the specific recent event, not all historical share bases. Current-vintage evidence only. Frozen lake unchanged.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*files]}}
with (S/'HPE_HPQ_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
