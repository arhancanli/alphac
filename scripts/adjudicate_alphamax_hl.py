"""Corroborate three HL amounts, retaining announcement and event discrepancies."""
import json,re,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1]; S=R/'evidence/alphamax-payment-source-full-20260913'
U=R/'evidence/alphamax-payment-schedule-review-v20-20260913/unresolved.json'
files=[S/('HL_'+n+'.web.json') for n in ['May','Aug','Nov_8k']]
terms={}
iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
for p in files:
 t=' '.join(json.loads(p.read_text())['result'].split())
 m=re.search(r'On ([A-Z][a-z]+ \d+, \d{4}), the Company announced it would pay a dividend on its shares of common stock in the amount of \$([0-9.]+), to shareholders of record as of ([A-Z][a-z]+ \d+, \d{4}), payable on or about ([A-Z][a-z]+ \d+, \d{4})',t)
 assert m,p
 announcement,amount,record,pay=m.groups();record=iso(record)
 assert record not in terms
 terms[record]=(iso(announcement),amount,iso(pay),str(p.relative_to(R)))
resolved=[];discrepancies=[]
for x in json.loads(U.read_text()):
 if x['symbol']!='HL' or not x['ex_date'].startswith('2025'):continue
 assert len(x['vendor_records'])==1
 v=x['vendor_records'][0];announcement,amount,pay,source=terms[v['record_date']]
 assert Decimal(amount)==Decimal(str(v['cash_amount']))==Decimal('.00375')
 assert v['currency']=='USD' and pay==v['pay_date'] and v['ex_dividend_date']==x['ex_date']
 assert Decimal(str(x['cash_amount']))==Decimal('.004')
 resolved.append({'instrument_id':x['instrument_id'],'symbol':'HL','ex_date':x['ex_date'],'amount':amount,'pay_date':pay,'basis':'issuer_HL_SEC_common_stock_cash_terms','amount_changed':True,'frozen_amount':str(x['cash_amount']),'source':source,'record_date':v['record_date'],'issuer_announcement_date':announcement,'vendor_declaration_date':v['declaration_date'],'payment_wording':'on_or_about_vendor_scheduled_date'})
 if announcement!=v['declaration_date']:discrepancies.append({'ex_date':x['ex_date'],'issuer_announcement_date':announcement,'vendor_declaration_date':v['declaration_date'],'resolution':'Retain both; announcement and board declaration are not necessarily identical. No historical availability inferred.'})
assert len(resolved)==3 and len(discrepancies)==1
baseline=json.loads((S/'match_audit.json').read_text())['matches']
nearby=[x for x in baseline if x['symbol']=='HL' and '2023-05-01'<=x['ex_date']<='2023-06-30']
assert len(nearby)==2 and any(x['ex_date']=='2023-05-19' and x['accepted'] for x in nearby)
report={'status':'THREE_HL_CASH_AMENDMENTS_CORROBORATED_ONE_EVENT_UNRESOLVED','resolved':resolved,'announcement_discrepancies':discrepancies,'unresolved_2023':{'nearby_frozen_events':nearby,'finding':'May19 event already has June9 payment. June14 .006 has no matching vendor event. No reassignment, deletion, or duplicate conclusion authorized by available evidence.','failed_source_capture':'HL_2023_Q1.web.json'},'limits':'Current-vintage cash terms only; issuer sources do not certify ex-dates or historical intraday availability. On-or-about wording does not prove settlement. Preferred dividends excluded. Original lake unchanged; no historical returns.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,S/'match_audit.json',*files,S/'HL_Nov.web.json',S/'HL_2023_Q1.web.json']}}
with (S/'HL_adjudication.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
