"""Review four event-specific MetLife common stock distributions."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v7-20260913/unresolved.json';P=S/'MET_issuer_releases.json'
def iso(d):
 d=d.replace('Sept.','Sep.').replace('.','')
 for fmt in ['%B %d, %Y','%b %d, %Y']:
  try:return datetime.strptime(d,fmt).date().isoformat()
  except ValueError:pass
 raise ValueError(d)
rows=[]
for s in json.loads(P.read_text())['sources']:
 t=s['result'];m=re.search(r'common stock dividend of \$(\d+\.\d+) per share\. The dividend will be payable on ([A-Z][a-z.]+ \d+, \d{4}), to shareholders of record as of ([A-Z][a-z.]+ \d+, \d{4})',t)
 assert m,s['url']
 amount,pay,record=m.groups();rows.append({'amount':amount,'pay_date':iso(pay),'record_date':iso(record),'url':s['url']})
assert len(rows)==4
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='MET':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'MET','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_release_cash_correction'})
assert len(resolved)==4
report={'status':'FOUR_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'Common shares only, not preferred shares. Issuer amounts and record/pay dates corroborate vendor; ex dates retained from frozen/vendor agreement, not supplied by issuer. Current retrieval of dated releases is not full historical dissemination or actual broker settlement proof. Original lake unchanged.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'MET_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
