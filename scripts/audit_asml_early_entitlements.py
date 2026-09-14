"""Retain dated issuer entitlement evidence; proposals do not imply approval."""
import re,json,hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal
R=Path(__file__).resolve().parents[1];O=R/'evidence/foreign-dividend-fx-source-20260913'
N=R/'evidence/alphamax-asml-jpm-gap-notices-20260913/coverage_checkpoint.json'
notices=json.loads(N.read_text())['rows'];rows=[]
for quarter in ['q2-2022','q3-2022','q4-2022']:
 p=O/f'asml_{quarter}-financial-results.txt';t=p.read_text()
 stamp=re.search(r'Press release - Veldhoven, the Netherlands, ([A-Z][a-z]+ \d{1,2}, \d{4})',t);assert stamp
 statement=re.search(r'(?:an|An) interim dividend of €([0-9.]+) per ordinary share that? ?will be made payable on ([A-Z][a-z]+ \d{1,2}, \d{4})',t)
 if statement is None:
  statement=re.search(r'(?:an|An) interim dividend of €([0-9.]+) per ordinary share will be made payable on ([A-Z][a-z]+ \d{1,2}, \d{4})',t)
 assert statement
 iso=lambda s:datetime.strptime(s,'%B %d, %Y').date().isoformat()
 pay=iso(statement.group(2));matches=[x for x in notices if x['us_pay']==pay];assert len(matches)==1
 x=matches[0];assert Decimal(statement.group(1))==Decimal(x['eur']);assert iso(stamp.group(1))<x['frozen_event']['ex_date']
 rows.append({'source':str(p.relative_to(R)),'release_date':iso(stamp.group(1)),'pay_date':pay,'eur_per_share':statement.group(1),'ex_date':x['frozen_event']['ex_date'],'release_precedes_ex':True,'exact_notice_entitlement_match':True,'historical_capture_proven':False})
p=O/'asml_q1-2023-financial-results.txt';assert 'final dividend proposal to the Annual General Meeting of €1.69' in p.read_text()
report={'status':'THREE_DATED_INTERIM_ENTITLEMENTS_CORROBORATED_ONE_FINAL_PROPOSAL_NOT_APPROVAL','rows':rows,'proposal_only':{'eur':'1.69','source':str(p.relative_to(R)),'needed':'Dated AGM approval and applicable entitlement timetable'},'limits':'Retained current issuer pages corroborate dated statements before ex. Not original capture evidence or full ex/record-calendar verification. No source schedule admission, no historical replay, no estimated short tax terms.','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),N,*sorted(O.glob('asml*'))]}}
for p in O.glob('asml*.receipt.json'):
 receipt=json.loads(p.read_text());stem=p.name.removesuffix('.receipt.json')
 assert receipt['status']==200
 assert hashlib.sha256((O/(stem+'.html')).read_bytes()).hexdigest()==receipt['sha256']
 assert hashlib.sha256((O/(stem+'.txt')).read_bytes()).hexdigest()==receipt['text_sha256']
with (O/'entitlements.json').open('x') as f:json.dump(report,f,indent=2)
print(report['status'])
