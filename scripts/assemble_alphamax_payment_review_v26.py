"""Add evidenced Moody's duplicate-cash exclusion without modifying prior reviews."""
import json,re,hashlib
from decimal import Decimal
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';P=R/'evidence/alphamax-payment-schedule-review-v25-20260913';O=R/'evidence/alphamax-payment-schedule-review-v26-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=S/'MCO_annual_2022.web.json';t=' '.join(re.sub(r'L\d+:','',json.loads(source.read_text())['result']).split())
assert '2022 2021 2020 Declared Paid Declared Paid Declared Paid' in t
for quarter in ['First','Second','Third','Fourth']:
 assert re.search(quarter+r' quarter\s*\$?0.70\s*\$?0.70',t)
assert 'Total$2.80 $2.80' in t
original=json.loads((S/'match_audit.json').read_text())['matches'];year=[x for x in original if x['symbol']=='MCO' and x['ex_date'].startswith('2022')]
assert len(year)==5 and sum(Decimal(str(x['cash_amount'])) for x in year)==Decimal('3.5')
valid=[x for x in year if x['accepted']];assert len(valid)==4
assert sum(Decimal(str(x['cash_amount'])) for x in valid)==Decimal('2.8')
assert all(x['vendor_records'][0]['pay_date'].startswith('2022') for x in valid)
accepted=json.loads((P/'reviewed_schedule.json').read_text());pending=json.loads((P/'unresolved.json').read_text());excluded=json.loads((P/'excluded.json').read_text())
x,=[x for x in pending if x['symbol']=='MCO'];assert x['ex_date']=='2022-10-26' and x['cash_amount']==0.7
collision=json.loads((S/'event_collision_audit_2022.json').read_text());assert collision['MCO']['unresolved']==x
O.mkdir(exist_ok=False);D=O/'MCO_exclusion_decision.json'
decision={'status':'EXCLUDE_INVALID_CASH_EVENT','original_event':x,'rationale':'Reviewed data-quality inference: issuer2022 annual capital-stock note reports four quarterly cash dividends0.70 declared/paid each,total2.80. Four accepted frozen/vendor events already total2.80 and pay within2022. Extra October26 0.70 raises total3.50; October24 announcement maps to already represented November22 event (November23record,December14pay). Exact extra cash event excluded; this is not a provider-issued correction.','comparison':{'issuer_declared_and_paid':'2.80','frozen_total':'3.50','matched_events':valid},'sha256':{str(p.relative_to(R)):sha(p) for p in [source,S/'event_collision_audit_2022.json',S/'collision_origin_audit.json',S/'match_audit.json']}}
D.write_text(json.dumps(decision,indent=2)+'\n');excluded.append({'instrument_id':x['instrument_id'],'ex_date':x['ex_date'],'original_event':x,'decision_file':str(D.relative_to(R))})
pending=[v for v in pending if v!=x]
for n,v in [('reviewed_schedule.json',accepted),('unresolved.json',pending),('excluded.json',excluded)]: (O/n).write_text(json.dumps(v,indent=2)+'\n')
assert len(accepted)==3405 and len(pending)==59 and len(excluded)==2
files=[P/'gate.json',S/'match_audit.json',D,Path(__file__),R/'scripts/alphamax_payment_source_guard_v2.py',*[O/n for n in ['reviewed_schedule.json','unresolved.json','excluded.json']]]
files.extend(R/v['decision_file'] for v in excluded)
gate={'status':'INCOMPLETE_SOURCE_SCHEDULE_REPLAY_FORBIDDEN','total':3466,'reviewed':3405,'unresolved':59,'excluded':2,'unchanged_amount':3295,'explicit_new_amounts':110,'unresolved_by_symbol':dict(Counter(v['symbol'] for v in pending)),'qualification':False,'limitations':'Source guardv2 required. Cash partition only, not exdate/PIT/lifecycle certification. Feature inputs must use same exclusions before registered replay. No original lake mutation or returns.','sha256':{str(p.relative_to(R)):sha(p) for p in files}}
(O/'gate.json').write_text(json.dumps(gate,indent=2)+'\n');print(gate['status'],gate['unresolved'],gate['excluded'])
