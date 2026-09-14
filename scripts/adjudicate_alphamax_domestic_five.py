"""Five issuer-specific common dividend corrections; no rounding rule inferred."""
import json,re,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';U=R/'evidence/alphamax-payment-schedule-review-v21-20260913/unresolved.json'
patterns={
'APH':('APH_release',r'Common Stock in the amount of \$([0-9.]+) per share at its meeting held on January 29, 2025\. The Company will pay this first quarter 2025 dividend on ([A-Z][a-z]+ \d+, \d{4}) to shareholders of record as of ([A-Z][a-z]+ \d+, \d{4})'),
'DUK':('DUK',r'common stock of \$([0-9.]+) per share\. This dividend is payable on ([A-Z][a-z]+ \d+, \d{4}), to shareholders of record at the close of business on (Feb\. \d+, \d{4})'),
'HBAN':('HBAN',r'common stock of \$([0-9.]+) per common share, unchanged from the prior quarter\. The common stock cash dividend is payable on ([A-Z][a-z]+ \d+, \d{4}), to shareholders of record on ([A-Z][a-z]+ \d+, \d{4})'),
'TJX':('TJX',r'common stock of \$([0-9.]+) per share payable ([A-Z][a-z]+ \d+, \d{4}), to shareholders of record on ([A-Z][a-z]+ \d+, \d{4})'),
'VICI':('VICI',r'On June 5, 2025, the Company declared a regular quarterly cash dividend of \$([0-9.]+) per share\. The Q2 2025 dividend was paid on ([A-Z][a-z]+ \d+, \d{4}) to stockholders of record as of the close of business on ([A-Z][a-z]+ \d+, \d{4})')}
terms={};files=[]
for symbol,(name,pattern) in patterns.items():
 p=S/(name+'_single.web.json');files.append(p)
 t=' '.join(json.loads(p.read_text())['result'].split());m=re.search(pattern,t);assert m,symbol
 amount,pay,record=m.groups();iso=lambda s:datetime.strptime(s.replace('Feb.','February'),'%B %d, %Y').date().isoformat()
 terms[symbol]=(amount,iso(pay),iso(record),str(p.relative_to(R)))
resolved=[]
for x in json.loads(U.read_text()):
 if x['symbol'] not in terms:continue
 amount,pay,record,source=terms[x['symbol']];assert len(x['vendor_records'])==1
 v=x['vendor_records'][0]
 assert Decimal(amount)==Decimal(str(v['cash_amount']))!=Decimal(str(x['cash_amount']))
 assert v['currency']=='USD' and v['pay_date']==pay and v['record_date']==record and v['ex_dividend_date']==x['ex_date']
 resolved.append({'instrument_id':x['instrument_id'],'symbol':x['symbol'],'ex_date':x['ex_date'],'amount':str(Decimal(amount)),'pay_date':pay,'record_date':record,'source':source,'basis':'issuer_specific_common_stock_cash_terms','amount_changed':True,'frozen_amount':str(x['cash_amount'])})
assert len(resolved)==5
report={'status':'FIVE_DOMESTIC_COMMON_DIVIDEND_AMENDMENTS_CORROBORATED','resolved':resolved,'limits':'Current-vintage issuer terms only; ex-dates retained from frozen/vendor events, not independently certified. APH current table body omitted dividends; use dated release with unadjusted declared amount. APH board approval January29 and release January30 differ; vendor lists January30. VICI retrospective results say paid, but no historical availability inferred from page date. DUK/HBAN preferred distributions excluded. No general rounding rule, lake mutation, historical returns, or qualification.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*files,S/'APH_single.web.json']}}
with (S/'domestic_five_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
