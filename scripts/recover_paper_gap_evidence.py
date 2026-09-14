"""Bounded read-only inventory of retained August 9/10 paper marks."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = Path('/Users/arhancanli/alphaforge')
OUT = ROOT / 'evidence/paper-gap-recovery-20260913'
START = int(datetime(2026, 8, 7, tzinfo=UTC).timestamp() * 1000)
END = START + 6 * 86400000

# Execute the same bounded query locally and at the known sole-writer host.
# No credentials, holdings, fills or entire database contents are returned.
QUERY = '''
def inspect_database(path):
    if not path.is_file():
        return {"path": str(path), "exists": False}
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        marks = connection.execute(
            "SELECT ts,equity_quote FROM equity_curve WHERE ts>=? AND ts<? ORDER BY ts",
            (START, END)).fetchall()
        bounds = connection.execute("SELECT min(ts),max(ts),count(*) FROM equity_curve").fetchone()
        cycles = connection.execute(
            "SELECT cycle_ts,status,detail FROM cycles "
            "WHERE cycle_ts>=? AND cycle_ts<? ORDER BY cycle_ts",
            (START, END)).fetchall() if "cycles" in tables else []
        result = {"path": str(path), "exists": True, "bounds": bounds,
                  "marks": marks, "cycles": cycles}
        body = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        result["query_result_sha256"] = hashlib.sha256(body).hexdigest()
        return result
    finally:
        connection.close()
'''


def main():
    OUT.mkdir(exist_ok=False)
    paths = [PROD / 'var' / name for name in [
        'trading_crypto_perp.sqlite', 'trading_equity.sqlite',
        'trading_managed_futures.sqlite', 'trading_alphavintage.sqlite',
        'vps_stage/trading_crypto_perp.sqlite',
        'restart_backup_v1_20260629/trading_crypto_perp.sqlite']]
    paths += [PROD / 'artifacts/archive/live_record_20260807T111240Z/trading_crypto_perp.sqlite',
              Path('/Users/arhancanli/alphac-sleeve-review-20260911/crypto-snapshot.sqlite')]
    namespace = {'sqlite3': sqlite3, 'json': json, 'hashlib': hashlib, 'START': START, 'END': END}
    exec(QUERY, namespace)
    local = [namespace['inspect_database'](path) for path in paths]
    (OUT / 'local-query-results.json').write_text(json.dumps(local, indent=2) + '\n')
    remote_code = ('import sqlite3,json,hashlib\nfrom pathlib import Path\n'
                   f'START={START}\nEND={END}\n' + QUERY + '''
root = Path('/opt/alphaforge')
paths = [root / 'var/trading_crypto_perp.sqlite']
backups = sorted((root / 'var/deploy_backups/crypto-position-attribution').glob(
    '*/trading_crypto_perp.sqlite'))
if len(backups) > 20:
    raise RuntimeError('More than 20 backups: explicit wider inventory required')
paths.extend(backups)
print(json.dumps({'databases': [inspect_database(p) for p in paths],
                  'backup_scope': str(root / 'var/deploy_backups/crypto-position-attribution')
                                  + '/*/trading_crypto_perp.sqlite'}))
''')
    (OUT / 'remote_query.py').write_text(remote_code)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', '-i', str(Path.home() / '.ssh/moonshot_vps'),
               'root@201.79.12.40', 'python3', '-']
    try:
        process = subprocess.run(command, input=remote_code, text=True,
                                 capture_output=True, timeout=25, check=False)
        remote = {'exit_code': process.returncode}
        if process.returncode == 0:
            remote['result'] = json.loads(process.stdout)
        else:
            remote['error'] = process.stderr[-1500:]
    except subprocess.TimeoutExpired:
        remote = {'error': 'Bounded remote query timed out; remote recovery unverified'}
    (OUT / 'remote-query-result.json').write_text(json.dumps(remote, indent=2) + '\n')
    sources = [PROD / 'docs/design/CORRECTION_ALPACA_SESSION_DATE_CONTINUITY.md',
               PROD / 'scripts/audit_record_continuity.py',
               PROD / 'scripts/paper_trading_state.py',
               PROD / 'artifacts/engineering/record_continuity.json',
               ROOT / 'LONG_TERM_GOALS.md']
    bindings = {}
    for i, path in enumerate(sources):
        data = path.read_bytes()
        target = OUT / f'source-{i}-{path.name}'
        target.write_bytes(data)
        bindings[str(path)] = {'sha256': hashlib.sha256(data).hexdigest(),
                               'snapshot': target.name}
    (OUT / 'source-bindings.json').write_text(json.dumps(bindings, indent=2) + '\n')
    print('Local databases inspected:', len(local))
    print('Remote query:', remote.get('exit_code', remote.get('error')))
    all_results = local + remote.get('result', {}).get('databases', [])
    for record in all_results:
        if not record['exists']:
            print(record['path'], 'absent')
            continue
        targets = [r for r in record['marks'] if START + 2*86400000 <= r[0] < START+4*86400000]
        print(record['path'], 'Aug 9/10 raw-timestamp marks:', len(targets))


if __name__ == '__main__':
    main()
