"""Classify saved gap-query evidence; no queries, timestamps changed or P&L built."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/paper-gap-recovery-20260913'


def main():
    bindings = json.loads((OUT / 'source-bindings.json').read_text())
    for record in bindings.values():
        digest = hashlib.sha256((OUT / record['snapshot']).read_bytes()).hexdigest()
        assert digest == record['sha256']
    source = next(OUT / r['snapshot'] for p, r in bindings.items()
                  if p.endswith('/scripts/audit_record_continuity.py'))
    spec = importlib.util.spec_from_file_location('retained_continuity', source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    local = json.loads((OUT / 'local-query-results.json').read_text())
    remote = json.loads((OUT / 'remote-query-result.json').read_text())
    assert remote.get('exit_code') == 0, 'Remote evidence is unavailable, not a negative finding'
    records = local + remote['result']['databases']
    results = []
    for record in records:
        assert record['exists'], 'Missing DB is not proof of missing observations'
        claimed = record['query_result_sha256']
        body = {k: v for k, v in record.items() if k != 'query_result_sha256'}
        actual = hashlib.sha256(json.dumps(body, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        assert actual == claimed
        crypto = 'crypto' in record['path']
        days = []
        for target in ['2026-08-09', '2026-08-10']:
            observed = [{'raw_ts': ts, 'session_date': target, 'equity_quote': eq}
                        for ts, eq in record['marks']
                        if mod.mark_session_date(ts, trades_24_7=crypto) == target]
            date = datetime.fromisoformat(target).date()
            expected = bool(mod.expected_days(date, date, trades_24_7=crypto))
            lower = int(datetime.fromisoformat(target).replace(tzinfo=UTC).timestamp()*1000)
            failed = [x for x in record['cycles']
                      if lower <= x[0] < lower + 86400000 and x[1] == 'failed']
            days.append({'date': target, 'expected_by_calendar': expected,
                         'retained_observations': observed,
                         'status': 'RETAINED_SESSION_OBSERVATION' if observed else
                         'NO_RETAINED_MARK_IN_SEARCHED_SOURCE' if expected else 'MARKET_CLOSED',
                         'failed_cycles': len(failed)})
        results.append({'source': record['path'], 'trades_24_7': crypto, 'days': days,
                        'source_predates_gap': record['bounds'][1] < 1786233600000})
    result = {'schema': 'canli.alphac-paper-gap-recovery.v1', 'databases_checked': len(records),
              'sources': results, 'disposition': 'NO_RECOVERED_CRYPTO_MARKS_IN_BOUNDED_SEARCH',
              'combined_marks_recovered': 0, 'raw_marks_rewritten': False,
              'new_epoch_started': False, 'strategy_trials': 0,
              'limits': 'Negative findings apply only to listed local/remote sources. '
                        'Rows retained today do not prove original reception time. '
                        'Mapping a session label does not create a synchronized combined NAV.'}
    assert all(not d['retained_observations']
               for r in results if r['trades_24_7'] for d in r['days'])
    with (OUT / 'classification.json').open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write('\n')
    print('Verified', len(records), 'query hashes; no missing crypto marks recovered.')
    for r in results[:4]:
        print(Path(r['source']).name, [(d['date'], d['status']) for d in r['days']])


if __name__ == '__main__':
    main()
