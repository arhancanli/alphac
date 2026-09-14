"""Map frozen anchors to retained source evidence and unresolved acquisition work."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/merger-source-workplan-20260913'
PRE = ROOT / 'evidence/merger-predecessor-inventory-20260913'
DOC = ROOT / 'evidence/merger-primary-documents-20260913'
HDR = ROOT / 'evidence/merger-missing-headers-20260913'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, x):
    with p.open('x') as f:
        json.dump(x, f, indent=2); f.write('\n')


def main():
    refs = {}
    for path, key in [(PRE/'closure.json', 'files'), (DOC/'closure.json', 'files'),
                      (HDR/'audit_bindings.json', 'sha256')]:
        refs[str(path.relative_to(ROOT))] = sha(path)
        for name, digest in json.loads(path.read_text())[key].items():
            assert sha(ROOT/name) == digest, name
            refs[name] = digest
    anchors = json.loads((DOC/'anchor_source_inventory.json').read_text())
    counts = pd.read_parquet(PRE/'anchor_counts.parquet')
    rel = pd.read_parquet(PRE/'candidate_relations.parquet')
    tender = pd.read_parquet(PRE/'all_tender_index_rows.parquet')
    items = json.loads((HDR/'combined_item_screen.json').read_text())
    item_map = {(r['cik'], r['accession']): r for r in items}
    assert len(item_map) == len(items) == 4728
    OUT.mkdir(exist_ok=False); (OUT/'anchors').mkdir()
    plan = []; all_candidates = []; expected_relations = 0
    for a in anchors:
        key = (a['index_cik'], a['accession'])
        matches = counts[(counts.anchor_cik == key[0]) & (counts.anchor_accession == key[1])]
        assert len(matches) == 1
        assert matches.iloc[0].stratum == a['form']
        subset = rel[(rel.anchor_cik == key[0]) & (rel.anchor_accession == key[1])]
        assert len(subset) == int(matches.iloc[0].candidate_rows)
        expected_relations += len(subset)
        candidates = []
        for r in subset.to_dict('records'):
            if r['candidate_form'] == '8-K':
                m = item_map[(key[0], r['candidate_accession'])]
                state = m['state']
                metadata = m
            else:
                state = 'NON_8K_FORM_CANDIDATE_LINKAGE_UNVERIFIED'
                metadata = None
            x = {**r, 'metadata_state': state, 'item_metadata': metadata,
                 'exact_acceptance_boundary_verified': False,
                 'same_transaction_linkage_verified': False,
                 'body_acquisition_needed_if_retained': state not in ['NO_SELECTED_ITEM_IN_CACHE','NO_SELECTED_ITEM_IN_HEADER']}
            candidates.append(x); all_candidates.append(x)
        packet_id = f"{a['form'].replace(' ', '_')}-{key[0]}-{key[1]}"
        packet = {'packet_id': packet_id, 'anchor': a, 'candidates': candidates,
                  'bidder_subject_route': 'UNRESOLVED_SEPARATE_2444_ROW_POOL',
                  'outcome_marker_sources': 'NOT_YET_BOUND',
                  'independent_review_complete': False,
                  'announcement_source_packet_complete': False,
                  'ready_for_accuracy_review': False,
                  'limitation': 'Source workplan only; no cash-merger or eligibility label. Date-index candidates are not exact acceptance-qualified sources.'}
        p = OUT/'anchors'/(packet_id+'.json'); write(p, packet)
        refs[str(p.relative_to(ROOT))] = sha(p)
        plan.append({'packet_id': packet_id, 'stratum': a['form'], 'year': a['sample_year'],
                     'cik': key[0], 'accession': key[1], 'path': str(p.relative_to(ROOT)),
                     'indexed_candidates': len(candidates),
                     'retained_or_unresolved_candidates': sum(x['body_acquisition_needed_if_retained'] for x in candidates),
                     'missing_item_metadata': sum(x['metadata_state']=='MISSING_CACHE_METADATA' for x in candidates)})
    assert len(plan) == 400 and len({x['packet_id'] for x in plan}) == 400
    assert expected_relations == len(all_candidates) == len(rel) == 6246
    assert Counter(x['stratum'] for x in plan) == {'DEFM14A': 200, 'SC 14D9': 200}
    table = pd.DataFrame(plan)
    table.to_csv(OUT/'anchor_workplan.csv', index=False)
    write(OUT/'relation_workplan.json', all_candidates)
    summaries = {}
    for stratum, frame in table.groupby('stratum'):
        summaries[stratum] = {'anchors': len(frame), 'indexed_relations': int(frame.indexed_candidates.sum()),
                             'retained_or_unresolved_relations': int(frame.retained_or_unresolved_candidates.sum()),
                             'anchors_without_retained_indexed_candidates': int(frame.retained_or_unresolved_candidates.eq(0).sum()),
                             'anchors_with_missing_item_metadata': int(frame.missing_item_metadata.gt(0).sum())}
    summary = {'strata': summaries, 'anchors': len(plan), 'relations': len(all_candidates),
               'unique_candidate_accessions': rel.candidate_accession.nunique(),
               'tender_pool_rows_unlinked': len(tender), 'ready_for_accuracy_review': 0,
               'independent_labels_generated': 0, 'new_return_trials': 0, 'qualified': False}
    write(OUT/'verification.json', summary)
    for p in [Path(__file__), OUT/'anchor_workplan.csv', OUT/'relation_workplan.json', OUT/'verification.json']:
        refs[str(p.relative_to(ROOT))] = sha(p)
    write(OUT/'source_bindings.json', {'sha256': refs})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
