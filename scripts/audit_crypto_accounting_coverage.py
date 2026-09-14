"""Read-only retained simulated-state cash and evidence coverage audit."""
import hashlib
import json
import sqlite3
from pathlib import Path

from alphaforge.validation.crypto_accounting import assess_legacy_accounting

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT/'evidence/crypto-accounting-coverage-20260913'
    path = Path('/Users/arhancanli/alphaforge/var/trading_crypto_perp.sqlite')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        cycle, blob = connection.execute(
            'SELECT cycle_ts,blob FROM paper_state ORDER BY cycle_ts DESC LIMIT 1').fetchone()
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    finally:
        connection.close()
    state = json.loads(blob)
    report = assess_legacy_accounting(state)
    report.update(cycle_label_ms=cycle, inspected_tables=tables,
                  raw_state_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                  scope='READ_ONLY_LOCAL_RETAINED_STATE')
    with (out/'retained-state.json').open('x') as stream:
        stream.write(blob+'\n')
    with (out/'coverage.json').open('x') as stream:
        stream.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in [
        'retained_fills', 'retained_positions', 'fill_fees_quote',
        'unexplained_cash_residual_quote', 'blocking_reasons']}))


if __name__ == '__main__':
    main()
