"""Close measured diagnostic identity with explicit nonqualification limits."""
import argparse,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/analysis/bil_cash_2022_20260913'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2,sort_keys=True);f.write('\n')
def close(arm):
 directory=OUT/arm;a=json.loads((directory/'independent_audit.json').read_text());assert a['pass']
 for p,h in a['sha256'].items():assert sha(ROOT/p)==h
 reservation=json.loads((directory/'reservation.json').read_text());record=json.loads((directory/'immutable_measurement.json').read_text())
 template=json.loads((ROOT/'artifacts/research/trial_packets/59901461092dd7a6.json').read_text())
 claims={
 'admission_or_kill_decision':'Diagnostic arm measured and accounted; reference adoption requires this2022 pair and prior main-period pair to pass their frozen gates. No admission.',
 'code_environment_and_reproduction':'Hash-bound inputs/code files; eight synthetic ledger tests passed. Independent cumulative cash/share/issuer entitlement audit checks 365 days. Not independent full environment reproduction.',
 'economic_mechanism_and_falsifiable_hypothesis':'Replace fixed32.5% zero-yield cash with BIL; monthly integer buys, issuer dividend receivables. No alpha-sleeve novelty claim.',
 'execution_and_cost_model':'Raw-open all-in modeled purchase charge6bp normal12bp stress. Issuer ex/pay dates; end-pay-date settlement, no borrowing, no unpaid-dividend reinvestment. Terminal receivables retained; no terminal liquidation. Actual fills/settlement/capacity unverified.',
 'family_and_union_trial_accounting':'Canonical reservation and immutable combined measurement retained. Cash-subbook ledger belongs to this implementation identity, not a qualified new alpha sleeve. Failed preflight attempts preserved.',
 'identity_and_authorship':'Authorized agent research in this worktree. No independent reviewer or external authorship verification.',
 'literature_and_overlap_decision':'Cash implementation of short Treasury ETF exposure; not claimed new alpha mechanism. Does not count toward15 distinct sleeves.',
 'machine_readable_packet_and_stable_public_paper':'Local evidence packet with hashes. Public paths in reservation are intended identifiers; no verified remote publication.',
 'point_in_time_data_and_survivorship_controls':'Current issuer distribution workbook and current-vintage provider raw prices. All1358 requested source sessions passed prior coverage audit. Issuer/vendor conflicts retained. Historical publication vintages and actual broker payments not verified.',
 'preregistration_and_hashes':'Frozen design before returns; runner and input manifest bound; canonical reservation validation/preflight precede ledger computation. Original zero-yield baseline retained.',
 'result_uncertainty_stress_capacity_and_diversification':'Retrospective fixed-weight combined research proxy; daily statistics, not intraday risk. Source/cost/collateral/rebalancing limitations remain. This arm passes or fails only its saved gates; not untouched OOS, capacity,15-sleeve or launch evidence.'}
 assert set(claims)==set(template['required_sections'])
 paths=[directory/n for n in ['reservation.json','reservation_validation.json','preregistration.json','immutable_measurement.json','experiments.jsonl','independent_audit.json','result.json','ledger.csv','daily.csv']]+[OUT/'protocol.json',OUT/'input_manifest.json',Path(__file__)]
 evidence=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths]
 packet={k:v for k,v in template.items() if k not in ['content_hash','required_sections','immutable_first_measurement']}
 packet.update(hypothesis_key=reservation['hypothesis_identity'],config_hash=record['config_hash'],configuration=record['config'],immutable_first_measurement=record,
 research_family_key='bil_cash_implementation_2022_validation',packet_status='COMPLETE_DIAGNOSTIC_ACCOUNTING_NOT_ADMITTED',
 completion_assessment={'packet_evidence_accounting_complete':True,'candidate_evidence_complete_for_admission':False,'disposition':'DIAGNOSTIC_ARM_ACCOUNTED'},
 claim_boundary='Cash implementation diagnostic only. Both horizon pairs and their frozen gates required; no admission or reference adoption.',
 required_sections={k:{'status':'MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION','statement':v,'evidence':evidence} for k,v in claims.items()})
 packet['content_hash']='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 path=ROOT/'artifacts/research/trial_packets'/f"{reservation['hypothesis_identity']}.json";write(path,packet)
 loaded=json.loads(path.read_text());h=loaded.pop('content_hash');assert h=='sha256:'+hashlib.sha256(json.dumps(loaded,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 for b in evidence:assert sha(ROOT/b['path'])==b['sha256']
 write(directory/'closure.json',{'status':'BIL_DIAGNOSTIC_ARM_ACCOUNTED','qualified':False,'packet':str(path.relative_to(ROOT)),'packet_sha256':sha(path),'audit_sha256':sha(directory/'independent_audit.json')})
 print('Closed '+reservation['hypothesis_identity'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--arm',required=True,choices=['normal','stress']);close(p.parse_args().arm)
