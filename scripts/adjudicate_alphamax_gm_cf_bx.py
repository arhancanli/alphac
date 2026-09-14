"""Recover three issuer payment dates, retaining frozen ex-dates as uncertified."""
import json,re,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v23-20260913/unresolved.json'
patterns={
'GM':r'common stock of \$([0-9.]+) per share payable ([A-Z][a-z]+ \d+, \d{4}), to all common shareholders of record as of the close of trading on ([A-Z][a-z]+ \d+, \d{4})',
'CF':r'quarterly dividend of \$([0-9.]+) per common share\. The dividend will be paid on ([A-Z][a-z]+ \d+, \d{4}) to stockholders of record as of ([A-Z][a-z]+ \d+, \d{4})',
'BX':r'quarterly dividend of \$([0-9.]+) per share to record holders of common stock at the close of business on ([A-Z][a-z]+ \d+, \d{4})\. This dividend will be paid on ([A-Z][a-z]+ \d+, \d{4})'}
expected={'GM':('2024-02-29','2024-03-01'),'CF':('2024-05-14','2024-05-15'),'BX':('2024-04-26','2024-04-29')}
resolved=[];files=[]
for symbol,pattern in patterns.items():
 p=S/(symbol+'_recovery.web.json');files.append(p)
 t=re.sub(r'L\d+(?:@P[0-9-]+)?:','',json.loads(p.read_text())['result']);t=' '.join(t.split());m=re.search(pattern,t);assert m,symbol
 amount,d1,d2=m.groups();pay,record=(d2,d1) if symbol=='BX' else (d1,d2)
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat();pay=iso(pay);record=iso(record)
 x,=[x for x in json.loads(U.read_text()) if x['symbol']==symbol]
 assert not x['vendor_records'] and (x['ex_date'],record)==expected[symbol]
 assert Decimal(amount)==Decimal(str(x['cash_amount']))
 resolved.append({'instrument_id':x['instrument_id'],'symbol':symbol,'ex_date':x['ex_date'],'amount':str(x['cash_amount']),'pay_date':pay,'record_date':record,'basis':'issuer_specific_missing_payment_recovery','amount_changed':False,'source':str(p.relative_to(R))})
assert len(resolved)==3
report={'status':'THREE_MISSING_PAYMENT_DATES_RECOVERED_ORIGINAL_AMOUNTS','resolved':resolved,'limits':'Cash terms only, specific frozen event to issuer record-date mapping retained explicitly. Issuer bodies do not independently certify ex-dates; no automatic date shift or blanket settlement rule. No vendor agreement claimed for missing rows. Current-vintage sources do not certify historic availability. No original lake mutation or historical returns. AMC classification already exists and was not repeated.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*files]}}
with (S/'GM_CF_BX_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
