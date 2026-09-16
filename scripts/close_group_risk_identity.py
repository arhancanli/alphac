"""Close accounted group-risk diagnostic identities without admission claims."""
from pathlib import Path
import json,hashlib,argparse
R=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def close(directory,combined=False):
    d=R/directory
    audit=json.loads((d/'independent_audit.json').read_text())
    for path,h in audit['sha256'].items():assert sha(R/path)==h,path
    if combined:assert audit['pass']
    else:assert audit['status']=='ALL_SESSION_NAV_CASH_RECEIVABLES_RECONCILED'
    reservation=json.loads((d/'reservation.json').read_text())
    record=json.loads((d/'experiments.jsonl').read_text().splitlines()[0])
    template=json.loads((R/'artifacts/research/trial_packets/59901461092dd7a6.json').read_text())
    statements={
    'admission_or_kill_decision':'Combined gate result controls progression; standalone descriptive. No admission or reference substitution. '+('Normal combined gate failure stops group design; no stress/2022 rescue.' if combined else 'Normal combined comparison pending.'),
    'code_environment_and_reproduction':'Isolated group allocator/strategy/bundle with17 synthetic tests across unit and full-engine scope. Saved accounting independently reconstructed; not independent historical source certification.',
    'economic_mechanism_and_falsifiable_hypothesis':'Equal stand-alone estimated risk of four fixed asset-class groups before original gross/name caps, using existing causal covariance and unchanged forecast signs. No newly distinct alpha sleeve.',
    'execution_and_cost_model':'Same raw-open and payable dividend engine as reference; normal commission/spread/impact/latency/borrow settings retained. Group sizing only. Final caps/vol overlay may break group-risk equality. Inter-sleeve rebalancing/collateral remain modeled.',
    'family_and_union_trial_accounting':'Canonical validated reservation before candidate return identity, immutable first measured record retained. Existing failed category short-mask and other trials preserved.',
    'identity_and_authorship':'Authorized agent research in local worktree. No independent reviewer or authorship verification claimed.',
    'literature_and_overlap_decision':'Portfolio-construction hypothesis within existing Trend, not a new forecast or literature novelty claim. Config-name prior review non-exhaustive; retains all eligible signs unlike retired short masks.',
    'machine_readable_packet_and_stable_public_paper':'Local hash-bound packet and reports only. Reservation public paths are intended identifiers, not verified remote publication.',
    'point_in_time_data_and_survivorship_controls':'Retrospective inspected historical forecasts/current-vintage data, synthetic dividend-reinvestment feature prices, raw execution and modeled action/borrow metadata. No untouched OOS or historical publication-vintage claim.',
    'preregistration_and_hashes':'Fixed group design, gates and source hashes before candidate replay. Canonical reservation and prepared runner manifest retained; allocation/risk/price baselines not overwritten.',
    'result_uncertainty_stress_capacity_and_diversification':'Jan2023–June1 2026 frozen evaluation; daily drawdown is not intraday risk, bootstrap or capacity certification. No2Sharpe/15sleeve/launch qualification. Failed normal combined gate prevents further performance trials for this design.'}
    assert set(statements)==set(template['required_sections'])
    paths=[p for p in d.iterdir() if p.is_file() and p.name not in ['ops.sqlite','ops.sqlite-wal','ops.sqlite-shm','closure.json']]
    paths.extend([R/'evidence/trend-group-risk-design-20260913/EXPERIMENT_SPEC.json',Path(__file__)])
    refs=[{'path':str(p.relative_to(R)),'sha256':sha(p)} for p in paths]
    packet={k:v for k,v in template.items() if k not in ['content_hash','required_sections','immutable_first_measurement']}
    packet.update(hypothesis_key=reservation['hypothesis_identity'],config_hash=record['config_hash'],configuration=record['config'],immutable_first_measurement=record,
        research_family_key='trend_fixed_asset_group_risk',packet_status='COMPLETE_DIAGNOSTIC_ACCOUNTING_NOT_ADMITTED',claim_boundary='Retrospective group-sizing diagnostic only; no admission, new sleeve or live implementation.',
        completion_assessment={'packet_evidence_accounting_complete':True,'candidate_evidence_complete_for_admission':False,'disposition':'FAILED_NORMAL_COMBINED_GATE' if combined else 'NORMAL_STANDALONE_ACCOUNTED'},
        required_sections={k:{'status':'MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION','statement':v,'evidence':refs} for k,v in statements.items()})
    packet['content_hash']='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    pp=R/'artifacts/research/trial_packets'/f"{reservation['hypothesis_identity']}.json"
    with pp.open('x') as f:json.dump(packet,f,indent=2,sort_keys=True);f.write('\n')
    with (d/'closure.json').open('x') as f:json.dump({'status':'GROUP_NORMAL_COMBINED_FAILED_CLOSED' if combined else 'GROUP_NORMAL_STANDALONE_ACCOUNTED','qualified':False,'packet':str(pp.relative_to(R)),'packet_sha256':sha(pp),'audit_sha256':sha(d/'independent_audit.json')},f,indent=2);f.write('\n')
    print('Closed',reservation['hypothesis_identity'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--combined',action='store_true');a=p.parse_args();close(a.directory,a.combined)
