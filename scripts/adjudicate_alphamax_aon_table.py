"""Four specific Aon corrections, including one discrepancy beyond rounding."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v8-20260913/unresolved.json';P=S/'AON_issuer_table.json'
t=json.loads(P.read_text())['result'].split('FY2024')[1].split('FY2023')[0]
raw=re.findall(r'(\d{2}/\d{2}/2024)\s*\|\s*(\d{2}/\d{2}/2024)\s*\|\s*(\d{2}/\d{2}/2024)\s*\|\s*\$(\d+\.\d+)',t)
assert len(raw)==4
iso=lambda d:datetime.strptime(d,'%m/%d/%Y').date().isoformat()
rows=[{'declared':iso(d),'record_date':iso(r),'pay_date':iso(p),'amount':a} for d,r,p,a in raw]
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='AON':continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];matches=[r for r in rows if r['record_date']==v['record_date']];assert len(matches)==1
 i=matches[0];assert i['pay_date']==v['pay_date'] and Decimal(i['amount'])==Decimal(str(v['cash_amount']))
 assert i['declared']==v['declaration_date']
 assert v['currency']=='USD' and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))!=Decimal(i['amount'])
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'AON','ex_date':x['ex_date'],**i,'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_table_cash_correction'})
assert len(resolved)==4
report={'status':'FOUR_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'limits':'January 2024 frozen .68 versus issuer .615 is not mere cent rounding; no generic tolerance or cause inferred. Issuer declaration/record/payment dates and amounts agree with vendor. Ex dates retained from frozen/vendor agreement, not supplied in issuer table. Current-vintage evidence; original lake unchanged, no historical performance computed.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,P]}}
with (S/'AON_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
