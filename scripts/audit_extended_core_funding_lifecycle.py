"""Inspect retained funding cadence and lifecycle bounds without calculating returns."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COVER = ROOT / 'evidence/core-2023-2026-coverage-20260913'
OUT = ROOT / 'evidence/core-2023-2026-funding-lifecycle-20260913'
HOUR = 3600000

def main():
    OUT.mkdir(exist_ok=False)
    refs = {}
    def bind(p):
        refs[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return p
    manifest = json.loads(bind(COVER / 'source_manifest.json').read_text())['sha256']
    protocol = json.loads(bind(COVER / 'PROTOCOL.json').read_text())
    coverage = pd.read_csv(bind(COVER / 'coverage.csv'))
    members = pd.read_parquet(bind(COVER / 'active_intervals.parquet'))
    metadata = {x['instrument_id']: x for x in json.loads(bind(COVER / 'instrument_versions.json').read_text())}
    rows, gaps, lifecycles = [], [], []
    def ms(series):
        return pd.to_datetime(series, utc=True).astype('datetime64[ms, UTC]').astype('int64')
    for row in coverage.itertuples():
        iid = row.instrument_id
        meta = metadata[iid]
        if pd.notna(row.modeled_listing_end_ms):
            lifecycles.append({'instrument_id': iid, 'last_observed_ms': int(row.last_observed_ms), 'modeled_delisted_ms': int(row.modeled_listing_end_ms), 'last_bar_open_minus_delisted_hours': (row.last_observed_ms-row.modeled_listing_end_ms)/HOUR, 'claim': 'Modeled lifecycle only; final-close liquidation is not independently verified terminal proceeds.'})
        if row.sleeve != 'crypto_carry_wk':
            continue
        paths = [Path(p) for p in manifest if '/funding/' in p and f'instrument_id={iid}/' in p]
        frames = []
        for p in paths:
            bind(p)
            assert refs[str(p)] == manifest[str(p)]
            frames.append(pd.read_parquet(p))
        if not frames:
            rows.append({'instrument_id': iid, 'missing_all_funding': True})
            continue
        f = pd.concat(frames, ignore_index=True)
        f['t'] = ms(f.ts_funding); f['a'] = ms(f.available_at)
        f = f[(f.t >= protocol['crypto_shared_context_start_ms']) & (f.t < protocol['end_exclusive_ms'])].sort_values('t')
        ts = f.t.to_numpy(); delta = np.diff(ts)
        intervals = members[(members.instrument_id == iid) & (members.sleeve == row.sleeve)]
        # A >8h + 1s gap is an anomaly candidate, not proof of a missing payment.
        for j in np.flatnonzero(delta > 8*HOUR+1000):
            left, right = int(ts[j]), int(ts[j+1])
            active = any(left < (int(x.effective_to.timestamp()*1000) if pd.notna(x.effective_to) else protocol['end_exclusive_ms']) and right > max(protocol['crypto_train_start_ms'], int(x.effective_from.timestamp()*1000)) for x in intervals.itertuples())
            gaps.append({'instrument_id': iid, 'left_ms': left, 'right_ms': right, 'hours': float(delta[j]/HOUR), 'overlaps_train_test_membership': active})
        lag = f.a-f.t
        rows.append({'instrument_id': iid, 'rows': len(f), 'duplicate_timestamps': int(f.t.duplicated().sum()), 'nonfinite_rates': int((~np.isfinite(f.rate)).sum()), 'negative_availability_lag': int((lag<0).sum()), 'availability_lag_min_ms': int(lag.min()) if len(f) else None, 'availability_lag_max_ms': int(lag.max()) if len(f) else None, 'first_funding_ms': int(ts[0]) if len(ts) else None, 'last_funding_ms': int(ts[-1]) if len(ts) else None, 'first_price_ms': int(row.first_observed_ms), 'last_price_ms': int(row.last_observed_ms), 'cadence_hours_rounded_counts': json.dumps(pd.Series(np.round(delta/HOUR,3)).value_counts().sort_index().to_dict()), 'gaps_over_8h_plus_1s': int((delta>8*HOUR+1000).sum()), 'schedule_verified': False})
    pd.DataFrame(rows).to_csv(OUT/'funding_inventory.csv', index=False)
    pd.DataFrame(gaps).to_csv(OUT/'funding_gap_candidates.csv', index=False)
    pd.DataFrame(lifecycles).to_csv(OUT/'terminal_boundaries.csv', index=False)
    result = {'funding_instruments': len(rows), 'funding_rows': sum(x.get('rows',0) for x in rows), 'duplicate_timestamps': sum(x.get('duplicate_timestamps',0) for x in rows), 'negative_availability_lag': sum(x.get('negative_availability_lag',0) for x in rows), 'nonfinite_rates': sum(x.get('nonfinite_rates',0) for x in rows), 'gaps_over_8h_plus_1s': len(gaps), 'gap_candidates_overlapping_train_test_membership': sum(x['overlaps_train_test_membership'] for x in gaps), 'modeled_terminal_boundaries': len(lifecycles), 'new_returns': False, 'replay_cleared': False, 'limitation': 'Stored events do not prove complete exchange payment schedule. Long gaps are candidates, not filled or excluded. Current listing metadata does not certify historical known-by timing or settlement.'}
    (OUT/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    bind(Path(__file__))
    for name in ['src/alphaforge/backtest/engine.py','src/alphaforge/backtest/terminal_engine.py','src/alphaforge/data/store/reader.py']:
        bind(ROOT/name)
    (OUT/'source_manifest.json').write_text(json.dumps({'sha256': refs},indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
