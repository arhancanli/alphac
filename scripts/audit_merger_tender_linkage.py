"""Audit exact tender filing roles; do not infer transaction eligibility."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import pandas as pd
from audit_merger_headers import parse_header

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/merger-tender-linkage-20260913'
HEADERS = ROOT/'evidence/merger-tender-headers-20260913'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def subject_state(parsed, cik):
    subjects = parsed['roles']['SUBJECT-COMPANY']
    if len(subjects) != 1:
        return 'UNRESOLVED_SUBJECT_COUNT'
    return 'SUBJECT_CIK_MATCH_METADATA_ONLY' if subjects[0] == cik else 'INDEXED_CIK_NOT_SUBJECT'


def main():
    scope = json.loads((OUT/'SCOPE.json').read_text()); refs = {}
    for p,h in scope['source_sha256'].items():
        assert sha(ROOT/p) == h
        refs[p] = h
    done = json.loads((HEADERS/'acquisition_result.json').read_text())
    receipt = [json.loads(x) for x in (HEADERS/'receipts.jsonl').read_text().splitlines()]
    assert len({x['accession'] for x in receipt}) == len(receipt)
    assert len(receipt)+done['skipped'] == 205
    assert sum(x['success'] for x in receipt) == done['success']
    queue = {r['accession']:r for r in json.loads((OUT/'queue.json').read_text())}
    parsed = {}; errors = []
    for r in receipt:
        q = queue[r['accession']]
        assert r['url']==q['header_url'] and r['index_cik']==q['cik']
        if not r['success']:
            continue
        p=HEADERS/'headers'/(r['accession']+'.sgml')
        assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes']
        refs[str(p.relative_to(ROOT))]=sha(p)
        try:
            h=parse_header(p.read_text())
            assert h['accession']==r['accession'] and h['form']=='SC TO-T'
            assert q['cik'] in {v for ciks in h['roles'].values() for v in ciks}
            parsed[r['accession']]=h
        except (ValueError,AssertionError) as exc:
            errors.append({'accession':r['accession'],'error_type':type(exc).__name__})
    relations=pd.read_parquet(ROOT/'evidence/merger-predecessor-inventory-20260913/candidate_relations.parquet')
    relations=relations[relations.candidate_form=='SC TO-T']
    assert len(relations)==211
    rows=[]
    for r in relations.to_dict('records'):
        h=parsed.get(r['candidate_accession'])
        rows.append({**r,'linkage_state':subject_state(h,r['anchor_cik']) if h else 'UNRESOLVED_HEADER',
                     'header':h,'same_transaction_verified':False,'exact_public_availability_verified':False})
    result={'acquisition':done,'parsed_headers':len(parsed),'parse_errors':errors,
            'relations':len(rows),'states':dict(Counter(r['linkage_state'] for r in rows)),
            'deferred_unique_filings':1020,'qualified':False,'new_return_trials':0}
    for name,value in [('header_roles.json',parsed),('relation_linkage.json',rows),('verification.json',result)]:
        p=OUT/name
        with p.open('x') as f:
            json.dump(value,f,indent=2);f.write('\n')
        refs[str(p.relative_to(ROOT))]=sha(p)
    for p in [Path(__file__),ROOT/'scripts/audit_merger_headers.py',OUT/'SCOPE.json',
              HEADERS/'scope.json',HEADERS/'receipts.jsonl',HEADERS/'acquisition_result.json']:
        refs[str(p.relative_to(ROOT))]=sha(p)
    runtime=json.loads((HEADERS/'scope.json').read_text())
    runner=ROOT/'scripts/acquire_merger_tender_headers.py'
    assert sha(runner)==runtime['runner_sha256']
    refs[str(runner.relative_to(ROOT))]=sha(runner)
    with (OUT/'audit_bindings.json').open('x') as f:
        json.dump({'sha256':refs},f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
