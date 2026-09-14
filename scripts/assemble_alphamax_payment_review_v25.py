"""Preserve v24 and add one explicitly evidenced invalid-cash exclusion."""
import json,hashlib
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[1];S=R/'evidence/alphamax-payment-source-full-20260913';P=R/'evidence/alphamax-payment-schedule-review-v24-20260913';O=R/'evidence/alphamax-payment-schedule-review-v25-20260913'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
accepted=json.loads((P/'reviewed_schedule.json').read_text());unresolved=json.loads((P/'unresolved.json').read_text())
x,=[v for v in unresolved if v['symbol']=='TGT'];assert x['ex_date']=='2022-09-15' and x['cash_amount']==1.08
collision=json.loads((S/'event_collision_audit_2022.json').read_text())
assert collision['TGT']['extra_frozen_event']==x and collision['TGT']['issuer_total']=='3.96' and collision['TGT']['frozen_total']=='5.04'
origin=json.loads((S/'collision_origin_audit.json').read_text());assert any(v['frozen_event']==x for v in origin['rows'])
O.mkdir(exist_ok=False)
decision={'status':'EXCLUDE_INVALID_CASH_EVENT','original_event':x,'rationale':'Reviewed data-quality inference: issuer complete2022 distribution history lists four cash dividends totaling3.96, each already represented by a distinct accepted frozen event. The additional September15 1.08 raw-provider dividend would increase total to5.04 and has no matching vendor event. Exclude this extra cash action from the corrected research schedule; preserve original and evidence. This is not a provider-issued correction or independent exchange exdate certification.','scope':'Exact TGT2022-09-15 cash row only. No inference about other events, issuer universes or security lifecycle.','sha256':{str(p.relative_to(R)):sha(p) for p in [S/'event_collision_audit_2022.json',S/'collision_origin_audit.json',S/'TGT_2022_exception.web.json']}}
D=O/'TGT_exclusion_decision.json';D.write_text(json.dumps(decision,indent=2)+'\n')
excluded=[{'instrument_id':x['instrument_id'],'ex_date':x['ex_date'],'original_event':x,'decision_file':str(D.relative_to(R))}]
unresolved=[v for v in unresolved if v!=x];assert len(accepted)==3405 and len(unresolved)==60
for n,v in [('reviewed_schedule.json',accepted),('unresolved.json',unresolved),('excluded.json',excluded)]: (O/n).write_text(json.dumps(v,indent=2)+'\n')
gate={'status':'INCOMPLETE_SOURCE_SCHEDULE_REPLAY_FORBIDDEN','total':3466,'reviewed':3405,'unresolved':60,'excluded':1,'unchanged_amount':3295,'explicit_new_amounts':110,'unresolved_by_symbol':dict(Counter(v['symbol'] for v in unresolved)),'qualification':False,'limitations':'Cash-source partition only; exdate/PIT/foreign/lifecycle constraints remain. Source guard v2 required. Original source and v24 preserved. Any corrected feature pipeline must consume the same exclusion before a newly registered replay; no historical replay performed.','sha256':{str(p.relative_to(R)):sha(p) for p in [P/'gate.json',S/'match_audit.json',D,Path(__file__),R/'scripts/alphamax_payment_source_guard_v2.py',O/'reviewed_schedule.json',O/'unresolved.json',O/'excluded.json']}}
(O/'gate.json').write_text(json.dumps(gate,indent=2)+'\n');print(gate['status'],gate['reviewed'],gate['unresolved'],gate['excluded'])
