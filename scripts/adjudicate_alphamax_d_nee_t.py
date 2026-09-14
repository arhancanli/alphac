"""Exact event-specific cash corrections from three issuer histories."""
import re, json, hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1]
S=R/'evidence/alphamax-payment-source-full-20260913'
U=R/'evidence/alphamax-payment-schedule-review-v5-20260913/unresolved.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files=[S/f'{s}_issuer_table_extract.json' for s in ['D','NEE','T']]
texts={s:json.loads(p.read_text())['result'].split('--------------------------------------------------------------------------------')[0] for s,p in zip(['D','NEE','T'],files)}
rows={}
for symbol in ['D','NEE','T']:
 t=texts[symbol]
 if symbol=='D':
  raw=re.findall(r'^(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*\$(\d+\.\d+)',t,re.M)
  fmt='%m/%d/%Y'
 elif symbol=='NEE':
  raw=[r[1:] for r in re.findall(r'^(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*(\d{2}/\d{2}/\d{2})\s*\|\s*\$(\d+\.\d+)',t,re.M)]
  fmt='%m/%d/%y'
 else:
  raw=[(None,r,p,a) for p,r,a in re.findall(r'(\d{2}-\d{2}-\d{2})\s*\|\s*(\d{2}-\d{2}-\d{2})\s*\|\s*\$(\d+\.\d+)',t)]
  fmt='%m-%d-%y'
 iso=lambda d:datetime.strptime(d,fmt).date().isoformat() if d else None
 rows[symbol]=[{'ex_date':iso(e),'record_date':iso(r),'pay_date':iso(p),'amount':a} for e,r,p,a in raw]
 assert len(rows[symbol])>=18,(symbol,len(rows[symbol]))
resolved=[]
for x in json.loads(U.read_text()):
 s=x['symbol']
 if s not in rows:continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0]
 matches=[r for r in rows[s] if (r['ex_date']==x['ex_date'] if s!='T' else r['record_date']==v['record_date']) and r['pay_date']==v['pay_date']]
 assert len(matches)==1,(s,x['ex_date'],matches)
 i=matches[0]
 assert i['record_date']==v['record_date']
 assert Decimal(i['amount'])==Decimal(str(v['cash_amount'])) and v['currency']=='USD'
 assert v['ex_dividend_date']==x['ex_date']
 assert Decimal(i['amount'])!=Decimal(str(x['cash_amount']))
 resolved.append({'instrument_id':x['instrument_id'],'symbol':s,'ex_date':x['ex_date'],'record_date':i['record_date'],'pay_date':i['pay_date'],'amount':i['amount'],'frozen_amount':str(x['cash_amount']),'amount_changed':True,'basis':'specific_issuer_table_cash_correction','issuer_ex_date_verified':s!='T','vendor_id':v['id']})
assert {s:sum(x['symbol']==s for x in resolved) for s in rows}=={'D':6,'NEE':6,'T':5}
report={'status':'SEVENTEEN_SPECIFIC_CORRECTIONS_REVIEWED_NOT_APPLIED','resolved':resolved,'issuer_rows':rows,'limits':'D and NEE issuer ex/record/pay dates and amount agree with vendor. T issuer provides record/pay dates and amount; ex date retained from exact frozen/vendor agreement, not independently supplied by issuer. Current table/search extraction is not historical publication evidence. Explicit new source version needed; no lake mutation or performance computed.','sha256':{str(p.relative_to(R)):sha(p) for p in [Path(__file__),U,*files]}}
with (S/'D_NEE_T_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print('Reviewed',len(resolved))
