"""Join issuer SW dividend table to specific frozen unresolved events."""
import json,re,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';P=S/'SW_history.json';U=R/'evidence/alphamax-payment-schedule-review-v15-20260913/unresolved.json'
t=json.loads(P.read_text())['result'];table={}
for line in t.splitlines():
 line=re.sub(r'^L\d+: ','',line)
 if not re.match(r'\d\d Dec \d{4}\s*\|',line):continue
 fields=[x.strip() for x in line.split('|')];assert len(fields)==5
 iso=lambda d:datetime.strptime(d.replace('Sept','Sep').replace('June','Jun'),'%d %b %Y').date().isoformat()
 ex,record,pay=[iso(x) for x in fields[1:4]];amount=fields[4].removeprefix('$');assert ex not in table
 table[ex]=(record,pay,amount)
assert len(table)==9
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='SW':continue
 assert len(x['vendor_records'])==1;v=x['vendor_records'][0];record,pay,amount=table[x['ex_date']]
 assert v['ex_dividend_date']==x['ex_date'] and v['record_date']==record and v['pay_date']==pay and v['currency']=='USD'
 assert Decimal(amount)==Decimal(str(v['cash_amount'])) and Decimal(amount)!=Decimal(str(x['cash_amount']))
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'SW','ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_SW_history_exact_ex_record_pay_amount','amount_changed':True,'frozen_amount':str(x['cash_amount']),'issuer_record_date':record})
assert len(resolved)==4
report={'status':'FOUR_SW_CASH_CONFLICTS_CORROBORATED','resolved':resolved,'limits':'Exact issuer table ex/record/pay and USD amount matches, current-vintage only. No historical publication, holder tax, lifecycle or qualified execution claim. No general rounding rule applied.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),P,U]}}
with (S/'SW_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
