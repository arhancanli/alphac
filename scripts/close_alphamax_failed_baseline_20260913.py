"""Preserve the consumed failed AlphaMax trial without invented performance."""
import hashlib
import json
import time
from pathlib import Path

from alphaforge.validation.experiments import ExperimentUnion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/analysis/alphamax_full2022_baseline_20260913'
ARM = OUT / 'baseline'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    with path.open('x') as stream:
        json.dump(obj, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    reservation = json.loads((ARM / 'reservation.json').read_text())
    failure_log = OUT / 'baseline_execution.log'
    assert 'got 1' in failure_log.read_text()
    assert not (ARM / 'execution_complete.json').exists()
    log = ExperimentUnion.discover(ARM / 'experiments.jsonl', ROOT)
    record = log.record(
        reservation['trial_config'], sharpe_ann=float('nan'),
        sharpe_per_period=float('nan'), n_obs=0, skew=float('nan'),
        kurtosis=float('nan'), now_ms=int(time.time() * 1000),
        reservation_path=ARM / 'reservation.json',
    ).to_json_obj()
    statement = (
        'Failed historical trial; earlier legs computed in memory but not saved. '
        'Final one-session leg rejected by engine requiring two closes. '
        'No completed return series or performance metrics retained. n_obs=0 denotes '
        'no retained completed metric sample, not absence of prior computation. '
        'Identity consumed; performance undefined; no admission or qualification.'
    )
    write(ARM / 'failure.json', {
        'status': 'FAILED_AFTER_HISTORICAL_COMPUTATION', 'reason': statement,
        'metrics_available': False, 'qualified': False,
        'failure_log_sha256': sha(failure_log),
        'input_snapshot': str((ARM / 'run/input_snapshot').relative_to(ROOT)),
    })
    with (ARM / 'REPORT.md').open('x') as stream:
        stream.write('# AlphaMax baseline: failed trial retained\n\n' + statement + '\n')
    template = json.loads((ROOT / 'artifacts/research/trial_packets/59901461092dd7a6.json').read_text())
    packet = {k: v for k, v in template.items()
              if k not in {'content_hash', 'required_sections', 'immutable_first_measurement'}}
    paths = [ARM / name for name in ['reservation.json', 'preregistration.json',
             'reservation_validation.json', 'experiments.jsonl', 'failure.json', 'REPORT.md']]
    paths += [failure_log, OUT / 'input_manifest.json', Path(__file__)]
    paths += sorted(p for p in (ARM / 'run/input_snapshot').rglob('*') if p.is_file())
    refs = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p)} for p in paths]
    packet.update(hypothesis_key=reservation['hypothesis_identity'],
                  config_hash=record['config_hash'], configuration=record['config'],
                  immutable_first_measurement=record, claim_boundary=statement)
    packet['required_sections'] = {k: {'status': 'FAILED_TRIAL_EXPLICIT_LIMITATION',
        'statement': statement, 'evidence': refs} for k in template['required_sections']}
    packet['content_hash'] = 'sha256:' + hashlib.sha256(
        json.dumps(packet, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    target = ROOT / 'artifacts/research/trial_packets' / (reservation['hypothesis_identity'] + '.json')
    write(target, packet)
    write(ARM / 'closure.json', {'status': 'FAILED_TRIAL_ACCOUNTED_PACKET_CLOSED',
        'qualified': False, 'packet': str(target.relative_to(ROOT)), 'packet_sha256': sha(target)})
    print(json.dumps({'hypothesis': reservation['hypothesis_identity'],
                     'union': log.n_hypotheses(), 'metrics': record['sharpe_ann']}))


if __name__ == '__main__':
    main()
