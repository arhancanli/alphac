"""Read-only snapshot residual trace; differences are not identified payments."""
import gzip
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/crypto-cash-trace-20260913'


def trace(records):
    rows = []
    previous = None
    with localcontext() as ctx:
        ctx.prec = 60
        for cycle, blob in records:
            state = json.loads(blob, parse_float=Decimal)
            cash = Decimal(state['initial_cash'])
            fills = {}
            for fill in state['fills']:
                identity = fill['client_order_id']
                if identity in fills or fill['side'] not in ('buy', 'sell'):
                    raise ValueError('ambiguous retained fill')
                fills[identity] = fill
                cash -= (1 if fill['side'] == 'buy' else -1)*Decimal(fill['qty'])*Decimal(
                    fill['price']) + Decimal(fill['fee_quote'])
            residual = Decimal(state['cash']) - cash
            if not residual.is_finite():
                raise ValueError('nonfinite residual')
            reset = previous is not None and (
                previous[0] != state['initial_cash']
                or any(fills.get(k) != v for k, v in previous[1].items()))
            delta = None if previous is None or reset else residual-previous[2]
            rows.append({'cycle_label_ms': cycle,
                         'cycle_label_utc': datetime.fromtimestamp(cycle/1000, UTC).isoformat(),
                         'blob_sha256': hashlib.sha256(blob.encode()).hexdigest(),
                         'fill_count': len(fills), 'initial_cash_quote': str(state['initial_cash']),
                         'residual_quote': str(residual),
                         'comparable_previous_state': previous is not None and not reset,
                         'delta_residual_quote': None if delta is None else str(delta),
                         'retained_state_discontinuity': reset})
            previous = (state['initial_cash'], fills, residual)
    return rows


def main():
    OUT.mkdir(exist_ok=False)
    path = Path('/Users/arhancanli/alphaforge/var/trading_crypto_perp.sqlite')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        records = connection.execute(
            'SELECT cycle_ts,blob FROM paper_state ORDER BY cycle_ts').fetchall()
    finally:
        connection.close()
    with gzip.open(OUT/'retained-snapshots.jsonl.gz', 'wt') as stream:
        for cycle, blob in records:
            stream.write(json.dumps({'cycle': cycle, 'blob': blob})+'\n')
    rows = trace(records)
    changes = [r for r in rows if r['delta_residual_quote'] is not None
               and abs(Decimal(r['delta_residual_quote'])) > Decimal('.01')]
    report = {'snapshots': len(rows), 'first': rows[0], 'last': rows[-1],
              'discontinuities': [r for r in rows if r['retained_state_discontinuity']],
              'material_changes': changes, 'attribution_verified': False,
              'scope': 'LOCAL_RETAINED_SNAPSHOTS_NOT_PAYMENT_LEDGER'}
    (OUT/'trace.json').write_text(json.dumps(rows, indent=2)+'\n')
    (OUT/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Snapshots:', len(rows), 'material changes:', len(changes),
          'discontinuities:', len(report['discontinuities']))


if __name__ == '__main__':
    main()
