"""Specific MS/RF/O common cash corrections, preserving dates beyond horizon."""
import json,re,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v22-20260913/unresolved.json'
patterns={
'MS':('MS_cash',r'Common Stock Dividend Announcement Announcement date January 16, 2025 Amount per share \$([0-9.]+) Date paid ([A-Z][a-z]+ \d+, \d{4}) Shareholders of record as of ([A-Z][a-z]+ \d+, \d{4})'),
'RF':('RF_cash',r'A cash dividend of \$([0-9.]+) on each share of outstanding common stock of the Company, payable on ([A-Z][a-z]+ \d+, \d{4}), to stockholders of record at the close of business on ([A-Z][a-z]+ \d+, \d{4})'),
'O':('O_release_terms',r'common stock monthly cash dividend to \$([0-9.]+) per share from \$0.2570 per share\. The dividend is payable on ([A-Z][a-z]+ \d+, \d{4}), to stockholders of record as of ([A-Z][a-z]+ \d+, \d{4})')}
terms={};files=[]
for symbol,(name,pattern) in patterns.items():
 p=S/(name+'.web.json');files.append(p)
 t=re.sub(r'L\d+(?:@P[0-9-]+)?:','',json.loads(p.read_text())['result']);t=' '.join(t.split())
 m=re.search(pattern,t);assert m,symbol
 amount,pay,record=m.groups();iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
 terms[symbol]=(amount,iso(pay),iso(record),str(p.relative_to(R)))
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol'] not in terms:continue
 amount,pay,record,source=terms[x['symbol']];assert len(x['vendor_records'])==1;v=x['vendor_records'][0]
 assert Decimal(amount)==Decimal(str(v['cash_amount']))!=Decimal(str(x['cash_amount']))
 assert v['currency']=='USD' and v['pay_date']==pay and v['record_date']==record and v['ex_dividend_date']==x['ex_date']
 resolved.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'record_date':record,'source':source,'basis':'issuer_specific_MS_RF_O_common_cash_terms','amount_changed':True,'frozen_amount':str(x['cash_amount'])})
assert len(resolved)==3
assert next(x for x in resolved if x['symbol']=='RF')['pay_date']=='2026-07-01'
report={'status':'THREE_MS_RF_O_CASH_AMENDMENTS_CORROBORATED','resolved':resolved,'limits':'Current-vintage terms only; ex-dates vendor/frozen, no independent historical availability certification. MS retrospective 10K table reports paid. RF pay date after main replay end retained without acceleration; any held entitlement stays receivable until paid. O issuer webpage omitted body; issuer-authored PRNewswire release used. Preferred cash and annualized rates excluded. No lake mutation or returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*files,S/'O_2024cash.web.json']}}
with (S/'MS_RF_O_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
