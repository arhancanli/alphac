"""Specific remaining PG/DELL corrections; retain payment wording limitations."""
import json,re,hashlib
from datetime import datetime
from pathlib import Path
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v16-20260913/unresolved.json'
D=S/'DELL_remaining.web.json';P=S/'PG_July.web.json';table={}
for line in json.loads(D.read_text())['result'].splitlines():
 line=re.sub(r'^L\d+: ','',line)
 if not re.match(r'\d+/\d+/\d{4}\s*\|',line):continue
 f=[v.strip() for v in line.split('|')];assert len(f)==7
 iso=lambda s:datetime.strptime(s,'%m/%d/%Y').date().isoformat()
 declared,ex,record,pay=map(iso,f[:4]);assert ex not in table
 table[ex]=(declared,record,pay,f[4],f[6])
t=' '.join(json.loads(P.read_text())['result'].split())
m=re.search(r'declared a quarterly dividend of \$([0-9.]+) per share on the Common Stock.{0,170}?payable on or after ([A-Z][a-z]+ \d{1,2}, \d{4}) to Common Stock shareowners of record at the close of business on ([A-Z][a-z]+ \d{1,2}, \d{4})',t);assert m
iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat();resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol'] not in ('DELL','PG'):continue
 assert len(x['vendor_records'])==1;v=x['vendor_records'][0]
 if x['symbol']=='DELL':
  declared,record,pay,amount,currency=table[x['ex_date']];assert currency=='U.S. Currency' and declared==v['declaration_date'];basis='issuer_hosted_DELL_table_exact_terms';wording='payable_date'
 else:
  amount=m.group(1);pay=iso(m.group(2));record=iso(m.group(3));basis='issuer_PG_July_common_stock_terms';wording='on_or_after_date_vendor_scheduled_pay_date'
 assert record==v['record_date'] and pay==v['pay_date'] and Decimal(amount)==Decimal(str(v['cash_amount'])) and v['currency']=='USD'
 assert Decimal(amount)!=Decimal(str(x['cash_amount'])) and v['ex_dividend_date']==x['ex_date']
 resolved.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':basis,'amount_changed':True,'frozen_amount':str(x['cash_amount']),'payment_wording':wording})
assert len(resolved)==3
report={'status':'THREE_SPECIFIC_PG_DELL_AMOUNTS_CORROBORATED','resolved':resolved,'limits':'Current-vintage terms only. Dell issuer-hosted table, not independently captured historic notices. PG source says on or after August15; vendor scheduled date is retained, not proof of exact settlement. PG ex-date remains vendor. No original lake mutation or historical returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,D,P]}}
with (S/'PG_DELL_remaining_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
