"""Retain expanded split-failure scope and exact missing warmup timestamps; no returns."""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/core-2023-2026-gap-preparation-20260913'
COVER = ROOT / 'evidence/core-2023-2026-coverage-20260913'
PROD = Path('/Users/arhancanli/alphaforge')

def main():
    OUT.mkdir(exist_ok=False)
    refs = {}
    def bind(p):
        refs[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return p
    protocol = json.loads(bind(COVER / 'PROTOCOL.json').read_text())
    coverage = pd.read_csv(bind(COVER / 'coverage.csv'))
    ids = set(coverage.loc[coverage.sleeve == 'k30_dn_63', 'instrument_id'])
    validation = json.loads(bind(PROD / 'artifacts/audit/sharadar_corrected_corporate_action_validation.json').read_text())
    failures = pd.DataFrame(validation['split_gate']['failures'])
    selected = failures[failures.instrument_id.isin(ids)].copy()
    dates = pd.to_datetime(selected.ex_date, utc=True)
    selected['in_shared_context'] = dates.between(pd.Timestamp(protocol['equity_shared_context_start_ms'], unit='ms', tz='UTC'), pd.Timestamp(protocol['end_exclusive_ms'], unit='ms', tz='UTC'), inclusive='left')
    selected['in_train_or_test'] = dates.between(pd.Timestamp(protocol['equity_train_start_ms'], unit='ms', tz='UTC'), pd.Timestamp(protocol['end_exclusive_ms'], unit='ms', tz='UTC'), inclusive='left')
    selected.to_csv(OUT / 'expanded_split_failures.csv', index=False)
    rows = []
    gaps = json.loads(bind(COVER / 'gaps.json').read_text())
    for gap in gaps:
        if gap['scope'] != 'context' or not gap['interior_count']:
            continue
        iid = gap['instrument_id']
        p = ROOT / 'artifacts/analysis/crypto_full2022_terminal_20260913/state/repaired_snapshot/ohlcv' / f'instrument_id={iid}/year=2022/data.parquet'
        observed = set(pd.to_datetime(pd.read_parquet(bind(p), columns=['ts_open']).ts_open, utc=True).astype('datetime64[ms, UTC]').astype('int64'))
        missing = [t for t in range(gap['first_ms'], gap['last_ms'] + 1, 3600000) if t not in observed]
        assert len(missing) == gap['interior_count'] == gap['count']
        rows.extend({'instrument': iid, 'missing_active_hour': t, 'actual_scope': 'feature_warmup_interior'} for t in missing)
    pd.DataFrame(rows).to_csv(OUT / 'missing_active_hours.csv', index=False)
    result = {'equity_instruments': len(ids), 'all_date_split_failures': len(selected), 'shared_context_split_failures': int(selected.in_shared_context.sum()), 'train_or_test_split_failures': int(selected.in_train_or_test.sum()), 'warmup_interior_hours': len(rows), 'replay_clearance': False, 'claim_boundary': 'Timestamp/source scope only. Warmup artifacts and lifecycle/funding treatment require follow-up; no new signals or returns.'}
    (OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    bind(Path(__file__))
    (OUT / 'source_manifest.json').write_text(json.dumps({'sha256': refs}, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
