"""Read-only frozen-input diagnostic; does not authorize a lifecycle correction."""
from pathlib import Path
import hashlib
import json
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/alphamax-azn-lifecycle-audit-20260913'
LAKE = ROOT / 'evidence/core-2023-2026-frozen-inputs-20260913/lake'


def main():
    actions = sorted(LAKE.glob('corporate_actions/instrument_id=XUSE:CASH:AZNUSD/**/*.parquet'))
    price = LAKE / 'ohlcv_1d/instrument_id=XUSE:CASH:AZNUSD/year=2026/data.parquet'
    a = pd.concat([pq.ParquetFile(p).read().to_pandas() for p in actions])
    b = pq.ParquetFile(price).read().to_pandas().set_index('ts_open')
    before = float(b.loc[pd.Timestamp('2026-01-30', tz='UTC'), 'close'])
    after = float(b.loc[pd.Timestamp('2026-02-02', tz='UTC'), 'close'])
    assert before == 92.77 and after == 188.5
    assert not (a.action_type == 'split').any()
    dividend = a[a.ex_date == pd.Timestamp('2026-02-20', tz='UTC')]
    assert len(dividend) == 1 and float(dividend.iloc[0].cash_amount) == 2.153
    sources = sorted(OUT.glob('*.web.json'))
    assert len(sources) == 3
    result = {
        'status': 'CONFIRMED_FROZEN_LIFECYCLE_GAP_REPAIR_NOT_APPLIED',
        'instrument_id': 'XUSE:CASH:AZNUSD',
        'frozen_action_rows': len(a), 'frozen_split_rows': 0,
        'last_ads_close': before, 'first_ordinary_close': after,
        'unadjusted_close_return': after / before - 1,
        'two_ads_to_one_ordinary_economic_return_before_costs': after / (2 * before) - 1,
        'diagnostic_only': True,
        'issuer_dividend': {'announcement': '2026-02-10', 'usd_per_ordinary': 2.17,
                           'gbp_per_ordinary': 1.595, 'nyse_ex_date': '2026-02-20',
                           'record_date': '2026-02-20', 'pay_date': '2026-03-23'},
        'frozen_dividend': 2.153,
        'limitations': [
            'Economic ratio diagnostic is not a position-level realized return.',
            'No correction of quantity, fractional interests, cash in lieu, fees, prices or features applied.',
            'August 7 2025 extra cash row remains unresolved; August 8 row also exists.',
            'Earlier dividend-independence feature test does not establish lifecycle correctness.',
            'No combined-performance improvement measured; v28 remains unchanged.'
        ],
        'next_step': 'Recover conversion mechanics and price/volume normalization lineage; implement one source-bound correction across positions and split-aware features, preserving originals.',
        'qualification': False,
        'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [*actions, price, *sources, Path(__file__)]}
    }
    with (OUT / 'checkpoint.json').open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'unadjusted_close_return',
          'two_ads_to_one_ordinary_economic_return_before_costs')}, indent=2))


if __name__ == '__main__':
    main()
