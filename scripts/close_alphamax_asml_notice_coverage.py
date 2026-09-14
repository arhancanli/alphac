"""Close bounded notice discovery; do not authorize historical cash accounting."""
import hashlib,json
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[1]
O=R/'evidence/alphamax-asml-jpm-gap-notices-20260913'
reports=[R/'evidence/alphamax-asml-jpm-notices-20260913/reconciliation.json',O/'reconciliation.json']
rows=[]
for p in reports:
 report=json.loads(p.read_text())
 for name,digest in report['sha256'].items():
  assert hashlib.sha256((R/name).read_bytes()).hexdigest()==digest,name
 rows.extend(report['rows'])
unresolved=R/'evidence/alphamax-payment-schedule-review-v14-20260913/unresolved.json'
source=[x for x in json.loads(unresolved.read_text()) if x['symbol']=='ASML']
key=lambda x:(x['instrument_id'],x['ex_date'])
assert len(rows)==17 and len({key(x['frozen_event']) for x in rows})==17
assert {key(x['frozen_event']) for x in rows}=={key(x) for x in source}
api=json.loads((O/'public_dividends.json').read_text())['data']['items']
for x in rows:
 matches=[i for i in api if i.get('paymentDate','')[:10]==x['us_pay'] and i.get('notices',{}).get('pdf')]
 assert len(matches)==1
 i=matches[0];u=i['underlying']
 for field,v in [('gross',i['ratePerDr']),('withheld',i['withHoldingAmount']),('net',i['finalDivRatePerDr']),('fee',i['dividendFee']),('eur',u['currencyPerDr']),('fx',u['finalExchangeRate'])]:
  assert Decimal(x[field])==Decimal(str(v)),(x['us_pay'],field)
 assert x['us_record']==i['recordDate'][:10]
 assert x['foreign_record']==u['recordDate'][:10]
 x['api_fx_date']=u['exchangeDate'][:10]
 x['api_pdf_fx_date_exact']=x['fx_date']==x['api_fx_date']
 assert x['vendor_gross_exact'] and x['vendor_record_exact']
 x['notice_status']=i['status']
summary={'status':'ALL_17_ASML_CONFLICTS_HAVE_RECONCILED_FINAL_NOTICES_NOT_REPLAY_READY','covered_conflicts':17,'new_notices':10,'api_pdf_fx_date_conflicts':[{'notice_date':x['notice_date'],'pdf_fx_date':x['fx_date'],'api_fx_date':x['api_fx_date']} for x in rows if not x['api_pdf_fx_date_exact']],'amended_final_notices':sum(x['notice_status']=='Amended Final' for x in rows),'notice_date_after_ex_count':sum(x['notice_after_ex_date'] for x in rows),'rows':rows,'checks':['Input hashes verified','Exact frozen conflict identity coverage, no duplicate events','PDF EUR times FX equals gross USD','PDF gross minus printed withholding and fees equals net USD','All cash terms and record dates match API; FX dates checked with conflicts retained','All 17 vendor gross amounts and US record dates match'],'remaining':['Resolve August 2022 PDF/API FX-date discrepancy (August 4 versus August 5)','Specify causal EUR entitlement valuation until FX fixing becomes available; final USD notice is not proof of ex-date availability','Explicitly distinguish pretax research gross amounts from settled cash and any withholding/reclaim assumptions','Resolve remaining issuer cash conflicts and lifecycle events before full funded replay'],'reviewed_schedule_count_unchanged':3353,'unresolved_schedule_count_unchanged':113,'performance_computed':False,'sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*reports,unresolved,O/'public_dividends.json',O/'public_dividends.receipt.json']}}
with (O/'coverage_checkpoint.json').open('x') as f:json.dump(summary,f,indent=2)
print({k:v for k,v in summary.items() if k not in ('rows','sha256','remaining','checks')})
