"""Close the failed normal identity with explicit limits; prohibit stress progression."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'artifacts/analysis/earnings_change_20260913_v2/normal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2,sort_keys=True);f.write('\n')
def main():
 a=json.loads((D/'accounting_audit.json').read_text());q=json.loads((D/'quantity_audit.json').read_text())
 assert a['pass'] and q['pass'] and a['excess_sharpe_DFF_proxy']<0
 for report in [a,q]:
  for b in report['bindings']:assert sha(Path(b['path']))==b['sha256']
 record=json.loads((D/'experiments.jsonl').read_text().splitlines()[-1]);reservation=json.loads((D/'reservation.json').read_text())
 template=json.loads((ROOT/'artifacts/research/trial_packets/59901461092dd7a6.json').read_text())
 claims={
 'admission_or_kill_decision':'REJECT: normal net excess Sharpe fails required positive gate. No stress/combined trial or parameter rescue. Failed formula/allocation family stopped.',
 'code_environment_and_reproduction':'Frozen runner v2 and9312input/source bindings verified. Synthetic component/engine tests and saved accounting reconstruction; not independent end-to-end reproduction.',
 'economic_mechanism_and_falsifiable_hypothesis':'Fixed seasonal quarterly common-income change divided by prior same-quarter assets, monthly20long20short. Measured normal result rejects the required utility gate.',
 'execution_and_cost_model':'Raw-open fills,split-corrected cost sigma,static modeled borrow/metadata and ex+nextsession modeled dividend payment. Quantities/marks match sources; exact cost rerun and real terminal proceeds unverified.',
 'family_and_union_trial_accounting':'Canonical trial330 preserved with immutable first measurement. Prior failed trials retained. No new qualified sleeve; no stress or combined hypothesis consumed.',
 'identity_and_authorship':'Agent-executed authorized research in this worktree; no independent reviewer, authorship or qualification claimed.',
 'literature_and_overlap_decision':'Filing underreaction prior,not exact earnings-announcement surprise replication.121local logs reviewed by names; no proof of exhaustive economic novelty.',
 'machine_readable_packet_and_stable_public_paper':'This local hash-bound packet and retained reports are reviewable. Remote publication,licensing and stable public availability are not established.',
 'point_in_time_data_and_survivorship_controls':'ARQ filing-date data with modeled two-calendar-date delay,stable-ID/currentcurrency filters and retrospective sources. Original EPS diagnostic led to aggregate basis before returns. Historical vintage/borrow/payment dates not certified.',
 'preregistration_and_hashes':'Canonical reservation validated before scores. Original protocol/manifest and first-run endpoint error preserved; frozen evaluation trims extraJune2source session without replay.',
 'result_uncertainty_stress_capacity_and_diversification':'Frozen855sessions return−10.2702284%,excessSharpe−.6780771,maxDD24.0847037%. Negative required normalgate stops stress/combined. No capacity,untouched OOS,15sleeve qualification or launch evidence.'}
 assert set(claims)==set(template['required_sections'])
 paths=[D/n for n in ['reservation.json','preregistration.json','reservation_validation.json','experiments.jsonl','accounting_audit.json','quantity_audit.json','calendar2023_2026_excess.csv','run/run_meta.json']]
 paths +=[ROOT/'evidence/earnings-normal-result-20260913/REPORT.md',D.parent/'protocol.json',D.parent/'input_manifest.json',Path(__file__)]
 evidence=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths]
 packet={k:v for k,v in template.items() if k not in ['content_hash','required_sections','immutable_first_measurement']}
 packet.update(hypothesis_key=reservation['hypothesis_identity'],config_hash=record['config_hash'],configuration=record['config'],immutable_first_measurement=record,research_family_key='filing_seasonal_common_income_change',packet_status='COMPLETE_ACCOUNTING_REJECTED_NOT_ADMITTED',completion_assessment={'packet_evidence_accounting_complete':True,'candidate_evidence_complete_for_admission':False,'disposition':'REJECTED_NORMAL_GATE_FAILED'},claim_boundary='Failed retrospective research identity; all remaining source/execution/endpoint limitations explicit. No qualification,publication or deployment.',required_sections={k:{'status':'MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION','statement':v,'evidence':evidence} for k,v in claims.items()})
 packet['content_hash']='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 pp=ROOT/'artifacts/research/trial_packets'/f"{reservation['hypothesis_identity']}.json";write(pp,packet)
 loaded=json.loads(pp.read_text());digest=loaded.pop('content_hash');assert digest=='sha256:'+hashlib.sha256(json.dumps(loaded,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 for section in loaded['required_sections'].values():
  for b in section['evidence']:assert sha(ROOT/b['path'])==b['sha256']
 write(D/'closure.json',{'status':'EARNINGS_REJECTED_NORMAL_GATE_PACKET_CLOSED','qualified':False,'stress_allowed':False,'packet':str(pp.relative_to(ROOT)),'packet_sha256':sha(pp),'accounting_sha256':sha(D/'accounting_audit.json'),'quantity_sha256':sha(D/'quantity_audit.json')})
 print('Trial330 rejected packet closed:',pp)
if __name__=='__main__':main()
