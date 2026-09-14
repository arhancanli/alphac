"""Linde event-specific gross dividend terms, no ex-date or net-cash inference."""
import json,re,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';P=S/'LIN_history.web.json';U=R/'evidence/alphamax-payment-schedule-review-v18-20260913/unresolved.json'
t=json.loads(P.read_text())['result'];t=t.split('##### 2022 Dividends',1)[1].split('##### 2024 Dividends',1)[0];table={}
for line in t.splitlines():
 line=re.sub(r'^L\d+:','',line).strip()
 if not re.match(r'\d+/\d+/\d{4}\s*\|',line):continue
 f=[s.strip() for s in line.split('|')];assert len(f)==4
 iso=lambda s:datetime.strptime(s,'%m/%d/%Y').date().isoformat()
 declared,record,pay=map(iso,f[:3]);assert record not in table;table[record]=(declared,pay,f[3].removeprefix('$'))
assert len(table)==8
route={'2022-03-10':'2022-03-11','2022-06-02':'2022-06-03','2022-09-01':'2022-09-02','2022-12-01':'2022-12-02','2023-12-01':'2023-12-04'}
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='LIN':continue
 record=route[x['ex_date']];declared,pay,amount=table[record];assert declared<x['ex_date']<record<pay
 if x['vendor_records']:
  assert len(x['vendor_records'])==1;v=x['vendor_records'][0];assert (v['record_date'],v['pay_date'],v['declaration_date'],v['currency'])==(record,pay,declared,'USD');assert Decimal(str(v['cash_amount']))==Decimal(amount)
 else:assert Decimal(str(x['cash_amount']))==Decimal(amount)
 changed=Decimal(str(x['cash_amount']))!=Decimal(amount)
 row={'instrument_id':x['instrument_id'],'symbol':'LIN','ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_LIN_gross_dividend_table_explicit_record_mapping','amount_changed':changed,'issuer_record_date':record,'issuer_ex_date_verified':False}
 if changed:row['frozen_amount']=str(x['cash_amount'])
 resolved.append(row)
assert len(resolved)==5 and sum(x['amount_changed'] for x in resolved)==1
report={'status':'FIVE_LIN_GROSS_CASH_TERMS_CORROBORATED','resolved':resolved,'limits':'Four missing2022 payment dates explicitly mapped to issuer record-date rows and exact original amounts; one2023 vendor conflict matched by record/pay/declaration and amount. Ex-dates retained from frozen schedule, not inferred as issuer-certified. Gross USD terms only: no holder withholding, net settlement, historic availability or corporate reorganization identity certification. No historical returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),P,U]}}
with (S/'LIN_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
