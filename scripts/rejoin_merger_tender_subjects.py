"""Rejoin held tender subject headers to frozen anchors; raw clocks only."""
import hashlib
import json
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/merger-tender-rejoin-20260913'
LINK=ROOT/'evidence/merger-tender-linkage-20260913'
ANCH=ROOT/'evidence/merger-header-acquisition-20260913'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def raw_window(anchor,source):
    a=datetime.strptime(anchor,'%Y%m%d%H%M%S')
    s=datetime.strptime(source,'%Y%m%d%H%M%S')
    delta=a-s
    state='RAW_CLOCK_AFTER_ANCHOR' if delta<timedelta(0) else 'RAW_CLOCK_OLDER_THAN_365D' if delta>timedelta(days=365) else 'RAW_CLOCK_WITHIN_365D'
    return state,delta.total_seconds()


def main():
    refs={}
    for folder,file,key in [(LINK,'audit_bindings.json','sha256'),(ANCH,'closure.json','files')]:
        p=folder/file
        for name,h in json.loads(p.read_text())[key].items():
            assert sha(ROOT/name)==h,name
            refs[name]=h
        refs[str(p.relative_to(ROOT))]=sha(p)
    anchors=json.loads((ANCH/'header_mapping.json').read_text())
    headers=json.loads((LINK/'header_roles.json').read_text())
    old=json.loads((LINK/'relation_linkage.json').read_text())
    oldkeys={(r['anchor_cik'],r['anchor_accession'],r['candidate_accession']) for r in old}
    assert len(anchors)==400 and len(headers)==205
    OUT.mkdir(exist_ok=False)
    rows=[];unresolved=[]
    for a in anchors:
        role='SUBJECT-COMPANY' if a['form']=='SC 14D9' else 'FILER'
        assert a['form'] in ['SC 14D9','DEFM14A']
        ciks=a['all_header_roles'][role]
        if len(ciks)!=1:
            unresolved.append({'anchor':a,'reason':'NONUNIQUE_HEADER_ROLE_CIK'});continue
        for acc,h in headers.items():
            if h['roles']['SUBJECT-COMPANY']!=ciks:continue
            state,seconds=raw_window(a['acceptance_raw'],h['acceptance_raw'])
            key=(a['index_cik'],a['accession'],acc)
            rows.append({'anchor_index_cik':a['index_cik'],'anchor_accession':a['accession'],'stratum':a['form'],
                         'anchor_header_subject_cik':ciks[0],'anchor_role_used':role,
                         'index_cik_differs_from_header_subject':a['index_cik']!=ciks[0],
                         'source_accession':acc,'source_acceptance_raw':h['acceptance_raw'],
                         'anchor_acceptance_raw':a['acceptance_raw'],'raw_clock_state':state,
                         'raw_elapsed_seconds':seconds,'present_in_original_index_date_relations':key in oldkeys,
                         'utc_window_certified':False,'transaction_identity_verified':False})
    selected=[r for r in rows if r['raw_clock_state']=='RAW_CLOCK_WITHIN_365D']
    new=[r for r in selected if not r['present_in_original_index_date_relations']]
    # Do not erase original same-day or wrong-role rows when refining workload.
    indexed=[]
    amap={(a['index_cik'],a['accession']):a for a in anchors}
    for r in old:
        a=amap[(r['anchor_cik'],r['anchor_accession'])];h=headers[r['candidate_accession']]
        state,seconds=raw_window(a['acceptance_raw'],h['acceptance_raw'])
        indexed.append({'anchor_index_cik':r['anchor_cik'],'anchor_accession':r['anchor_accession'],
                        'source_accession':r['candidate_accession'],'old_linkage_state':r['linkage_state'],
                        'raw_clock_state':state,'raw_elapsed_seconds':seconds})
    result={'anchors':400,'source_headers':205,'unresolved_anchor_roles':len(unresolved),
            'subject_equal_pairs_all_dates':len(rows),'raw_clock_states':dict(Counter(r['raw_clock_state'] for r in rows)),
            'within_raw_window_pairs':len(selected),'new_vs_original_pairs':len(new),
            'covered_anchor_index_rows':len({(r['anchor_index_cik'],r['anchor_accession']) for r in selected}),
            'original_index_relation_raw_clock_states':dict(Counter(r['raw_clock_state'] for r in indexed)),
            'deferred_filings':1020,'new_return_trials':0,'qualified':False}
    for name,obj in [('all_subject_pairs.json',rows),('new_raw_window_pairs.json',new),('unresolved_anchor_roles.json',unresolved),('original_relation_clock_audit.json',indexed),('result.json',result)]:
        p=OUT/name
        with p.open('x') as f:json.dump(obj,f,indent=2);f.write('\n')
        refs[str(p.relative_to(ROOT))]=sha(p)
    refs[str(Path(__file__).relative_to(ROOT))]=sha(Path(__file__))
    with (OUT/'source_bindings.json').open('x') as f:json.dump({'sha256':refs},f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
