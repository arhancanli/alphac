"""Verify acquired identities and extend metadata coverage without transaction labels."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/merger-missing-headers-20260913'
OLD = ROOT / 'evidence/merger-cached-item-screen-20260913'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_header(text, accession, cik):
    def tags(name):
        return re.findall(r'^<' + name + r'>([^\r\n<]+)', text, re.M)
    assert tags('ACCESSION-NUMBER') == [accession]
    assert tags('TYPE') == ['8-K']
    filers = re.findall(r'<FILER>(.*?)</FILER>', text, re.S)
    filer_ciks = [int(v) for f in filers for v in re.findall(r'<CIK>(\d+)', f)]
    assert cik in filer_ciks, (cik, filer_ciks)
    clocks = tags('ACCEPTANCE-DATETIME')
    assert len(clocks) == 1 and re.fullmatch(r'\d{14}', clocks[0])
    items = tags('ITEMS')
    assert all(re.fullmatch(r'\d+\.\d{2}', x) for x in items)
    codes = sorted(set(items))
    state = ('ITEM_CODE_CANDIDATE' if set(codes) & {'1.01', '7.01', '8.01'}
             else 'NO_SELECTED_ITEM_IN_HEADER' if codes else 'EMPTY_ITEMS_UNRESOLVED')
    return {'cik': cik, 'accession': accession, 'state': state,
            'item_codes': codes, 'acceptance_raw': clocks[0]}


def main():
    counts = json.loads((OUT / 'acquisition_result.json').read_text())
    scope = json.loads((OUT / 'scope.json').read_text())
    assert sha(ROOT / 'scripts/acquire_merger_missing_headers.py') == scope['runner_sha256']
    queue_path = OLD / 'missing_header_queue.json'
    assert sha(queue_path) == scope['sample_sha256']
    queue = json.loads(queue_path.read_text())
    receipts = [json.loads(x) for x in (OUT / 'receipts.jsonl').read_text().splitlines()]
    assert len({x['accession'] for x in receipts}) == len(receipts)
    assert sum(x['success'] for x in receipts) == counts['success']
    assert len(receipts) - counts['success'] == counts['failed']
    assert len(queue) - len(receipts) == counts['skipped']
    expected = {x['accession']: x for x in queue}
    refs = {}; resolved = []
    for r in receipts:
        q = expected[r['accession']]
        assert r['url'] == q['header_url'] and r['index_cik'] == q['cik']
        if not r['success']:
            continue
        p = OUT / 'headers' / (r['accession'] + '.sgml')
        assert p.stat().st_size == r['bytes'] and sha(p) == r['sha256']
        refs[str(p.relative_to(ROOT))] = sha(p)
        row = parse_header(p.read_text(), q['accession'], q['cik'])
        row['header_path'] = str(p.relative_to(ROOT))
        resolved.append(row)
    old = json.loads((OLD / 'item_screen.json').read_text())
    for p, h in json.loads((OLD / 'closure.json').read_text())['files'].items():
        assert sha(ROOT / p) == h
    replacements = {(r['cik'], r['accession']): r for r in resolved}
    assert set(replacements) <= {(r['cik'], r['accession']) for r in old
                                 if r['state'] == 'MISSING_CACHE_METADATA'}
    merged = [replacements.get((r['cik'], r['accession']), r) for r in old]
    assert len(merged) == len(old) == 4728
    assert len(replacements) == len(resolved)
    assert set(replacements) <= {(r['cik'], r['accession']) for r in old}
    summary = {'acquisition': counts, 'new_header_states': dict(Counter(r['state'] for r in resolved)),
               'combined_states': dict(Counter(r['state'] for r in merged)),
               'verified_headers': len(resolved), 'returns_computed': False,
               'qualified': False, 'independent_labels_generated': 0}
    for name, data in [('resolved_headers.json', resolved), ('combined_item_screen.json', merged),
                       ('verification.json', summary)]:
        with (OUT / name).open('x') as f:
            json.dump(data, f, indent=2); f.write('\n')
    for p in [Path(__file__), queue_path, OLD / 'closure.json', OUT / 'scope.json',
              OUT / 'receipts.jsonl', OUT / 'acquisition_result.json', OUT / 'resolved_headers.json',
              OUT / 'combined_item_screen.json', OUT / 'verification.json']:
        refs[str(p.relative_to(ROOT))] = sha(p)
    with (OUT / 'audit_bindings.json').open('x') as f:
        json.dump({'sha256': refs}, f, indent=2); f.write('\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
