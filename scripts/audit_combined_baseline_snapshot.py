"""Snapshot current local baseline evidence; run only synthetic combiner checks."""
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path('/Users/arhancanli/alphaforge')
OUT = ROOT / 'evidence/combined-baseline-audit-20260912'


def main():
    OUT.mkdir(exist_ok=False)
    bindings = {}

    def snapshot(relative):
        source = PROD / relative
        data = source.read_bytes()
        target = OUT / 'sources' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        bindings[relative] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        return target

    def load(relative):
        return json.loads(snapshot(relative).read_text())

    state = load('data/paper/state.json')
    maturity = load('artifacts/engineering/forward_evidence_maturity.json')
    fingerprint = load('artifacts/engineering/live_config_fingerprint.json')
    diversification = load('artifacts/analysis/current_book_diversification/result.json')
    max_replay = load('artifacts/publication/alphamax_upstream_clean_workspace.json')
    vintage = load('artifacts/probe/cpi_surprise_size/result.json')
    snapshot('scripts/paper_trading_state.py')
    snapshot('scripts/evaluate_forward_evidence_maturity.py')
    snapshot('src/alphaforge/portfolio/market_factor.py')
    inventory = []
    for relative, expected in diversification['source_bindings']['sleeve_equity_inputs'].items():
        frame = pd.read_parquet(snapshot(relative))
        assert not frame.ts.duplicated().any() and frame.ts.is_monotonic_increasing
        assert np.isfinite(frame.equity).all() and frame.equity.gt(0).all()
        inventory.append({'path': relative, 'rows': len(frame),
                          'start': pd.to_datetime(frame.ts.iloc[0], unit='ms').isoformat(),
                          'end': pd.to_datetime(frame.ts.iloc[-1], unit='ms').isoformat(),
                          'matches_retained_study': bindings[relative]['sha256'] == expected})
    flagship = [x for x in state['algorithms'] if x.get('flagship') is True]
    assert len(flagship) == 1
    frame = pd.DataFrame(flagship[0]['live_curve'])
    dates = pd.to_datetime(frame.date)
    assert dates.is_monotonic_increasing and not dates.duplicated().any()
    gaps = [{'previous': frame.date.iloc[i-1], 'next': frame.date.iloc[i],
             'elapsed_days': int((dates.iloc[i]-dates.iloc[i-1]).days)}
            for i in range(1,len(frame)) if (dates.iloc[i]-dates.iloc[i-1]).days != 1]
    book_path = snapshot('src/alphaforge/portfolio/book.py')
    spec = importlib.util.spec_from_file_location('baseline_audit_book', book_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    first_loss = module.combine_book(
        [module.SleeveCurve('synthetic', [0,86400000,172800000], [100,90,90])],
        scheme='fixed', fixed_weights={'synthetic':1})
    gap = module.combine_book(
        [module.SleeveCurve('gap', [0,86400000,259200000], [100,100,110])],
        scheme='fixed', fixed_weights={'gap':1})
    assert first_loss.maxdd == 0 and abs(first_loss.equity_curve[-1] - .9) < 1e-12
    assert np.allclose(gap.sleeve_returns['gap'], [0,0,.1])
    stable = {rel: hashlib.sha256((PROD/rel).read_bytes()).hexdigest() == b['sha256']
              for rel,b in bindings.items()}
    result = {
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'LOCAL_SAVED_EVIDENCE_NO_NETWORK_OR_NEW_MARKET_RETURN_TRIAL',
        'state_generated_at': state['generated_at'],
        'composition': {x['key']:x['weight'] for x in state['book']['sleeves']},
        'overlay': state['book']['strategic_tilt'], 'aggregation': state['book']['aggregation'],
        'composition_matches_fingerprint': {x['key']:x['weight'] for x in state['book']['sleeves']} == fingerprint['surface']['book_composition']['sleeves'],
        'state_matches_maturity_binding': bindings['data/paper/state.json']['sha256'] == maturity['source_bindings']['paper_state']['sha256'],
        'historical_sources': inventory, 'historical_window': diversification['window'],
        'alphamax_reproduction': max_replay['comparison']['equity_curve'],
        'alphavintage_probe_verdict': vintage['verdict'],
        'paper_record': maturity['record'], 'paper_curve_gaps': gaps,
        'actual_one_day_intervals': int(dates.diff().dt.days.eq(1).sum()),
        'paper_maturity_status': maturity['status'],
        'drawdown_evidence': maturity['drawdown_evidence'],
        'synthetic_checks': {'initial_loss_reported_drawdown': first_loss.maxdd,
                             'initial_loss_expected_drawdown_magnitude': .1,
                             'gap_aligned_returns': gap.sleeve_returns['gap'].tolist()},
        'sources_unchanged_during_capture': stable, 'source_bindings': bindings,
        'disposition': 'BASELINE_NOT_READY_FOR_NEW_TARGET_QUALIFICATION',
        'verification_limits': 'Hashes bind saved files, not independent truth, account ownership, live deployment, or a new broker reconciliation.'}
    (OUT/'audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['state_matches_maturity_binding','composition_matches_fingerprint','paper_curve_gaps','actual_one_day_intervals','synthetic_checks']},indent=2))
    print('Historical source hashes match:', all(x['matches_retained_study'] for x in inventory))
    print('Source files stable:', all(stable.values()))


if __name__ == '__main__':
    main()
