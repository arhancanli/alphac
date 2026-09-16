"""Close the measured failed path-momentum combined identity without admission."""
from pathlib import Path
import json,hashlib
R=Path(__file__).resolve().parents[1];D=R/'artifacts/analysis/combined_path_momentum_20260913/normal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2,sort_keys=True);f.write('\n')
audit=json.loads((D/'independent_audit.json').read_text());assert audit['pass'] and not audit['stress_allowed']
for p,h in audit['sha256'].items():assert sha(R/p)==h
reservation=json.loads((D/'reservation.json').read_text());record=json.loads((D/'experiments.jsonl').read_text().splitlines()[0])
template=json.loads((R/'artifacts/research/trial_packets/59901461092dd7a6.json').read_text())
limitation='Retrospective fixed path-momentum substitution in an existing AlphaMax sleeve. Normal combined excess gain and no-lower-return gates failed; stop candidate, no stress/2022 or parameter rescue. No admission, new distinct sleeve, live qualification or publication claim. Current-vintage sources, modeled metadata/borrow/action timing and daily fixed subbook-weight proxy remain. Standalone feature reconstruction is from bound source/code; runtime feature snapshot absent; full raw-fill quantity/impact reconstruction not claimed.'
paths=[p for p in D.iterdir() if p.is_file() and p.name!='closure.json']+[Path(__file__),R/'evidence/alphamax-path-momentum-design-20260913/DESIGN.json',R/'artifacts/analysis/alphamax_path_momentum_20260913/candidate/closure.json']
refs=[{'path':str(p.relative_to(R)),'sha256':sha(p)} for p in paths]
packet={k:v for k,v in template.items() if k not in ['content_hash','required_sections','immutable_first_measurement']}
packet.update(hypothesis_key=reservation['hypothesis_identity'],config_hash=record['config_hash'],configuration=record['config'],immutable_first_measurement=record,research_family_key='alphamax_path_momentum',packet_status='COMPLETE_DIAGNOSTIC_ACCOUNTING_NOT_ADMITTED',claim_boundary=limitation,completion_assessment={'packet_evidence_accounting_complete':True,'candidate_evidence_complete_for_admission':False,'disposition':'FAILED_NORMAL_COMBINED_GATE'},required_sections={k:{'status':'MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION','statement':limitation,'evidence':refs} for k in template['required_sections']})
packet['content_hash']='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
p=R/'artifacts/research/trial_packets'/f"{reservation['hypothesis_identity']}.json";write(p,packet)
write(D/'closure.json',{'status':'PATH_NORMAL_COMBINED_FAILED_CLOSED','qualified':False,'packet':str(p.relative_to(R)),'packet_sha256':sha(p),'audit_sha256':sha(D/'independent_audit.json'),'stress_allowed':False,'2022_allowed':False})
print('Closed combined',reservation['hypothesis_identity'],'ordinal',reservation['governance_epoch']['reservation_ordinal'])
