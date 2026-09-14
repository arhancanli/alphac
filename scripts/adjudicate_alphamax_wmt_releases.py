"""Walmart cash terms on the share basis at each event, without tolerance changes."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v8-20260913/unresolved.json';P=S/'WMT_issuer_releases.json'
def iso(d):
 d=d.replace('Sept.','Sep.').replace('.','')
 for fmt in ['%B %d, %Y','%b %d, %Y']:
  try:return datetime.strptime(d,fmt).date().isoformat()
  except ValueError:pass
 raise ValueError(d)
rows=[]
for s in json.loads(P.read_text())['sources']:
 t=s['result'];m=re.search(r'four quarterly installments of \$(\d+\.\d+) per share',t);assert m
 amount=m.group(1)
 table=t.split('Record Dates  | Payable Dates')[1]
 pairs=re.findall(r'([A-Z][a-z.]+ \d+, \d{4})\s*\|\s*([A-Z][a-z.]+ \d+, \d{4})',table)
 assert len(pairs)==4
 rows.extend({'record_date':iso(r),'pay_date':iso(p),'amount':amount,'issuer_year':s['year']} for r,p in pairs)
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='WMT':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'WMT','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_release_cash_correction'})
assert len(resolved)==5
report={'status':'FIVE_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'2022 issuer amount .56 on contemporaneous share basis, not a later split-adjusted annual report amount. Frozen .56001 explicitly amended, no widened rounding tolerance. 2026 amount .2475. Issuer record/pay dates and cash agree with vendor; ex dates retained from frozen/vendor agreement. Current retrieval, not complete PIT certification. No original input mutation.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'WMT_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
