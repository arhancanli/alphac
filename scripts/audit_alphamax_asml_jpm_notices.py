"""Reconcile seven retained JPMorgan notices without admitting cash corrections."""
import re,json,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-asml-jpm-notices-20260913';U=R/'evidence/alphamax-payment-schedule-review-v14-20260913/unresolved.json'
source=[x for x in json.loads(U.read_text()) if x['symbol']=='ASML'];date=r'([A-Z][a-z]+ \d{2}, \d{4})';iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat();rows=[]
for p in sorted(O.glob('*.txt')):
 t=p.read_text();receipt=json.loads(p.with_suffix('.receipt.json').read_text());assert hashlib.sha256(p.with_suffix('.bin').read_bytes()).hexdigest()==receipt['sha256'];assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['text_sha256']
 assert 'CUSIP: N07059210' in t and 'DR Ratio 1:1' in t and 'Final Announcement' in t
 def amount(label):
  m=re.search(r'^'+re.escape(label)+r'(?: ¹)?\s+([0-9.]+)\s*$',t,re.M);assert m,label;return m.group(1)
 record=re.search('Record Date '+date+' '+date,t);pay=re.search('Payment/Value Date '+date+' '+date,t);assert record and pay
 us_record=iso(record.group(2));us_pay=iso(pay.group(2));fx_date=iso(re.search('Foreign Exchange Date '+date,t).group(1))
 fields={k:amount(label) for k,label in [('eur','Euro per DR'),('fx','Final Foreign Exchange Rate'),('gross','Rate per DR'),('withheld','Withholding Amount'),('net','Final Dividend Rate per DR'),('fee','Dividend Fee'),('dsc','DSC'),('other','Other')]}
 d={k:Decimal(v) for k,v in fields.items()};assert d['eur']*d['fx']==d['gross']
 assert d['gross']-d['withheld']-d['fee']-d['dsc']-d['other']==d['net']
 assert 'Withholding Tax Rate 15%' in t
 matches=[x for x in source if x['vendor_records'][0]['pay_date']==us_pay];assert len(matches)==1
 x=matches[0];v=x['vendor_records'][0]
 rows.append({'notice_date':p.stem,'foreign_record':iso(record.group(1)),'us_record':us_record,'us_pay':us_pay,'fx_date':fx_date,**fields,'tax_rounding_residual':str(d['withheld']-d['gross']*Decimal('.15')),'frozen_event':x,'vendor_gross_exact':Decimal(str(v['cash_amount']))==d['gross'],'vendor_record_exact':v['record_date']==us_record,'notice_after_ex_date':p.stem>x['ex_date'],'status':'SOURCE_TERMS_ONLY_NOT_REPLAY_READY'})
assert len(rows)==7
report={'status':'SEVEN_NOTICE_CASH_IDENTITIES_RECONCILED_NOT_REPLAY_READY','rows':rows,'vendor_gross_exact_count':sum(x['vendor_gross_exact'] for x in rows),'vendor_record_exact_count':sum(x['vendor_record_exact'] for x in rows),'limits':'EUR times FX and gross minus reported withholding/fees equal net exactly in each notice. Report printed tax rounding residual, do not replace reported amount. Joined by unique USD payment date; explicit record mismatches remain unresolved. USD ex-entitlement availability, withheld cash, holder tax/reclaims, and remaining notice coverage need policy/evidence. No correction applied, no historical performance.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),U,*sorted(O.glob('*.bin')),*sorted(O.glob('*.txt')),*sorted(O.glob('*.receipt.json')),O/'request_plan.json']}}
with (O/'reconciliation.json').open('x') as f:json.dump(report,f,indent=2)
print({k:v for k,v in report.items() if k not in ['rows','sha256','limits']})
for x in rows:print(x['notice_date'],x['vendor_gross_exact'],x['vendor_record_exact'],x['tax_rounding_residual'])
