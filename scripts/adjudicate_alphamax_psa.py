"""Recover seven explicitly mapped PSA common-dividend payment records."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v19-20260913/unresolved.json';files=[Path(__file__),U];resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='PSA':continue
 assert not x['vendor_records'];p=S/('PSA_'+x['ex_date']+'.web.json');files.append(p);t=' '.join(re.sub(r'L\d+:','',json.loads(p.read_text())['result']).split())
 if x['ex_date']=='2022-07-29':
  m=re.search(r'one-time dividend of \$([0-9.]+) per common share, payable on ([A-Z][a-z]+ \d{1,2}, \d{4}) to shareholders of record on ([A-Z][a-z]+ \d{1,2}, \d{4})',t);kind='special'
 else:
  if x['ex_date']=='2023-03-14':
   pattern=r'regular common quarterly dividend from \$2.00 to \$([0-9.]+) per share\.'
  else:pattern=r'regular common quarterly dividend of \$([0-9.]+) per common share\.'
  m=re.search(pattern+r'.{0,450}?All the dividends are payable on ([A-Z][a-z]+ \d{1,2}, \d{4}) to shareholders of record as of ([A-Z][a-z]+ \d{1,2}, \d{4})',t);kind='regular'
 assert m,p
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat();amount=m.group(1);pay=iso(m.group(2));record=iso(m.group(3))
 assert Decimal(amount)==Decimal(str(x['cash_amount'])) and x['ex_date']<record<pay
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'PSA','ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_PSA_explicit_common_'+kind+'_dividend','amount_changed':False,'issuer_record_date':record,'issuer_ex_date_verified':False,'distribution_kind':kind})
assert len(resolved)==7 and sum(x['distribution_kind']=='special' for x in resolved)==1
report={'status':'SEVEN_PSA_MISSING_PAYMENT_TERMS_RECOVERED','resolved':resolved,'limits':'Explicit event-to-release mapping, exact original amounts retained, issuer record/payment dates. Frozen ex-dates not independently verified; no due-bill conclusion inferred from special status alone. Source cash-schedule review only; economic lifecycle and exchange ex-date checks remain needed for qualified replay. No tax-classification substitution, no preferred dividend included, no returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
with (S/'PSA_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
