"""Reconcile KKR common dividends; frozen ex dates are not issuer-certified."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';O=R/'evidence/alphamax-kkr-pdfs-20260913';U=R/'evidence/alphamax-payment-schedule-review-v17-20260913/unresolved.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source=[x for x in json.loads(U.read_text()) if x['symbol']=='KKR'];resolved=[];pending=[];files=[Path(__file__),U,O/'request_plan.json']
# Explicit event-to-release identity mapping, not nearest-date guessing.
route={'2022-02-17':89,'2022-05-13':74,'2023-11-16':62,'2024-02-15':63,'2024-05-10':44,'2024-08-12':45,'2024-11-04':46,'2025-02-14':47}
for x in source:
 p=O/f"KKR_terms_{route[x['ex_date']]}.web.txt"
 if not p.exists():pending.append(x);continue
 receipt=p.with_suffix('.receipt.json');r=json.loads(receipt.read_text());assert r['status']==200 and sha(p)==r['text_sha256'] and sha(p.with_suffix('.pdf'))==r['sha256'];files.extend([p,receipt,p.with_suffix('.pdf')])
 t=' '.join(p.read_text().split());m=re.search(r'A dividend of \$([0-9.]+) per share of common stock(?: of KKR & Co\. Inc\.)? has been declared for the (first|second|third|fourth) quarter of (\d{4}), which will be paid on ([A-Z][a-z]+ \d{1,2}, \d{4}) to holders of record of common stock as of the close of business on ([A-Z][a-z]+ \d{1,2}, \d{4})',t);assert m,p
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat();amount=m.group(1);pay=iso(m.group(4));record=iso(m.group(5));assert x['ex_date']<=record<pay
 if x['vendor_records']:
  assert len(x['vendor_records'])==1;v=x['vendor_records'][0]
  assert v['pay_date']==pay and v['record_date']==record and v['currency']=='USD' and Decimal(str(v['cash_amount']))==Decimal(amount)
 else:
  assert x['ex_date'] in ('2022-02-17','2022-05-13') and Decimal(str(x['cash_amount']))==Decimal(amount)
 changed=Decimal(str(x['cash_amount']))!=Decimal(amount)
 out={'instrument_id':x['instrument_id'],'symbol':'KKR','ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_KKR_common_dividend_release','amount_changed':changed,'issuer_record_date':record,'issuer_ex_date_verified':False,'vendor_payment_missing':not bool(x['vendor_records']),'fiscal_quarter':m.group(2)+' '+m.group(3)}
 if changed:out['frozen_amount']=str(x['cash_amount'])
 resolved.append(out)
assert len(resolved)+len(pending)==8
report={'status':'KKR_COMMON_DIVIDEND_TERMS_REVIEWED','resolved':resolved,'pending':pending,'limits':'Issuer amount/record/pay terms. Six conflicts joined to vendor payment records when available; two2022 payments recover from explicitly mapped issuer quarters with exact frozen amount. Frozen ex-dates retained, not independently certified. Current-vintage cash schedule only; no holder settlement/PIT/lifecycle certification or returns.','sha256':{str(p.relative_to(R)):sha(p) for p in files}}
with (S/'KKR_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('resolved',len(resolved),'pending',len(pending),'changed',sum(x['amount_changed'] for x in resolved))
