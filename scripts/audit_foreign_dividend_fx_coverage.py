"""Current-vintage ECB reference coverage; never asserts historical availability."""
from pathlib import Path
from datetime import date,timedelta
from decimal import Decimal
from bisect import bisect_left
import xml.etree.ElementTree as ET
import json,hashlib
R=Path(__file__).resolve().parents[1];O=R/'evidence/foreign-dividend-fx-source-20260913'
root=ET.fromstring((O/'ecb_history.xml').read_bytes());rates={}
for node in root.iter():
 if 'time' not in node.attrib:continue
 day=date.fromisoformat(node.attrib['time']);usd=[c.attrib['rate'] for c in node if c.attrib.get('currency')=='USD'];assert len(usd)==1
 assert day not in rates and Decimal(usd[0])>0
 rates[day]=usd[0]
dates=sorted(rates)
notices=R/'evidence/alphamax-asml-jpm-gap-notices-20260913/coverage_checkpoint.json'
rows=json.loads(notices.read_text())['rows'];valuation=[]
for x in rows:
 start=date.fromisoformat(x['frozen_event']['ex_date']);end=date.fromisoformat(x['us_pay']);day=start
 while day<=end:
  index=bisect_left(dates,day)-1;assert index>=0
  prior=dates[index];assert prior<day
  valuation.append({'event_ex':str(start),'valuation_date':str(day),'reference_date':str(prior),'usd_per_eur':rates[prior],'reference_age_days':(day-prior).days,'convention':'STRICT_PRIOR_DATE_CURRENT_VINTAGE_REFERENCE_PROXY_NOT_PIT'})
  day+=timedelta(days=1)
report={'status':'REFERENCE_MARK_COVERAGE_AVAILABLE_HISTORICAL_AVAILABILITY_UNPROVEN','historical_usd_rows':len(rates),'first_date':str(dates[0]),'last_date':str(dates[-1]),'asml_events':len(rows),'event_calendar_day_marks':len(valuation),'max_reference_age_days':max(x['reference_age_days'] for x in valuation),'marks':valuation,'interpretation':'Strict prior calendar date avoids same-day reference use; it does not prove historical availability, revisions or publication delays. ECB reference is valuation proxy only, never ASML settlement fixing or executable conversion. No FX-age threshold tuned or historical return computed.','local_review':'Filename search of frozen core lake and alphaforge/data found ETF symbol suffixes containing EURUSD, not an identified spot FX series. Legacy FX scripts fetch Yahoo at run time; they are not retained vintage evidence. Search scope does not establish absence from every workspace.','remaining':['Historical EUR entitlement approval and availability for each event','Historical final-fixing availability and amendments','Independently evidenced short settlement obligations','FX reference publication/vintage policy explicitly frozen before integration'],'sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),notices,*sorted(O.glob('ecb*')),O/'request_plan.json']}}
with (O/'coverage.json').open('x') as f:json.dump(report,f,indent=2)
print({k:v for k,v in report.items() if k not in ['marks','sha256','remaining','interpretation','local_review']})
