"""Bounded four-component source audit; no broker calls, scheduler or valuation epoch."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from alphaforge.validation.portfolio_acquisition import read_component

ROOT = Path(__file__).resolve().parents[1]
PROD = Path('/Users/arhancanli/alphaforge')
OUT = ROOT / 'evidence/portfolio-acquisition-coverage-20260913'
CUT = int(datetime(2026, 9, 12, tzinfo=UTC).timestamp() * 1000)


def main():
    OUT.mkdir(exist_ok=False)
    sources = [
        ('alphaforge', 'trading_crypto_perp.sqlite', 'crypto_cycle'),
        ('alphamax', 'trading_equity.sqlite', 'alpaca_legacy_history'),
        ('alphatrend', 'trading_managed_futures.sqlite', 'alpaca_legacy_history'),
        ('alphavintage', 'trading_alphavintage.sqlite', 'alpaca_legacy_history'),
    ]
    rows = []
    for name, filename, kind in sources:
        packet = read_component(PROD/'var'/filename, kind=kind, cut_ms=CUT)
        (OUT/f'{name}.json').write_text(json.dumps(packet, indent=2, allow_nan=False)+'\n')
        rows.append({'component': name, 'content_sha256': packet['content_sha256'],
                     'blocking_reasons': packet['blocking_reasons'],
                     'interpretation': packet['interpretation'],
                     'valuation_snapshot_available': packet['valuation_snapshot'] is not None})
    source_files = [
        PROD/'scripts/export_alpaca_broker_reconciliation.py',
        PROD/'scripts/export_crypto_position_attribution.py',
        PROD/'src/alphaforge/live/loop.py', PROD/'src/alphaforge/live/store.py',
        ROOT/'src/alphaforge/execution/spot_account.py',
        ROOT/'src/alphaforge/validation/portfolio_acquisition.py',
        ROOT/'tests/unit/test_portfolio_acquisition.py',
        ROOT/'config/research/portfolio_evaluation_v1_draft.json', Path(__file__),
    ]
    bindings = {}
    for i, path in enumerate(source_files):
        data = path.read_bytes()
        target = OUT/f'source-{i}-{path.name}'
        target.write_bytes(data)
        bindings[str(path)] = {'sha256': hashlib.sha256(data).hexdigest(), 'snapshot': target.name}
    report = {'schema': 'canli.alphac-acquisition-coverage.v1',
              'requested_cut_ms': CUT, 'scope': 'READ_ONLY_LOCAL_RETAINED_RECORDS',
              'components': rows, 'complete_cut_snapshots': sum(
                  r['valuation_snapshot_available'] for r in rows),
              'unavailable_book_dependencies': ['FUNDED_OVERLAY_LEDGER',
                                                'DATED_CASH_BENCHMARK',
                                                'COMPLETE_EXTERNAL_AND_INTERNAL_FLOW_INVENTORY'],
              'source_bindings': bindings, 'new_market_return_trials': 0,
              'new_epoch_started': False, 'broker_calls': 0,
              'limits': 'Per-database consistent read transactions, not an atomic cross-account '
                        'observation. Local reading time is not original evidence receipt time. '
                        'Source and packet hashes do not authenticate source truth.'}
    (OUT/'coverage.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in rows:
        print(row['component'], row['interpretation'], len(row['blocking_reasons']), 'gaps')
    print('Complete cut snapshots:', report['complete_cut_snapshots'])


if __name__ == '__main__':
    main()
