"""Two issuer-supported SLB corrections; no generalized rounding tolerance."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v12-20260913/unresolved.json';P=S/'SLB_issuer_review.json'
z=json.loads(P.read_text());iso=lambda d,fmt:datetime.strptime(d,fmt).date().isoformat()
t=z['table'];rows=[]
for d,e,r,p,a in re.findall(r'(\d{2} [A-Z][a-z]+ \d{4})\s*\|\s*(\d{2} [A-Z][a-z]+ \d{4})\s*\|\s*(\d{2} [A-Z][a-z]+ \d{4})\s*\|\s*(\d{2} [A-Z][a-z]+ \d{4})\s*\|\s*(\d+\.\d+)',t):
 rows.append(dict(ex_date=iso(e,'%d %B %Y'),record_date=iso(r,'%d %B %Y'),pay_date=iso(p,'%d %B %Y'),amount=a))
m=re.search(r'quarterly cash dividend of \$(\d+\.\d+) per share of outstanding common stock, payable on ([A-Z][a-z]+ \d+, \d{4}), to stockholders of record on ([A-Z][a-z]+ \d+, \d{4})',z['release_2024']);assert m
a,p,r=m.groups();rows.append(dict(record_date=iso(r,'%B %d, %Y'),pay_date=iso(p,'%B %d, %Y'),amount=a))
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='SLB':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 if 'ex_date' in i:assert i['ex_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'SLB','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_cash_correction','issuer_ex_date_verified':'ex_date' in i})
assert len(resolved)==2
report={'status':'TWO_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Exact issuer/vendor cash, record and payment dates. 2025 issuer table corroborates ex date; 2024 release lacks ex date, retained from frozen/vendor agreement. Current search extracts, not full PIT certification. Frozen input unchanged.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'SLB_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
