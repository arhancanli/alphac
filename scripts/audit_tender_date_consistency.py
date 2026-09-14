"""Audit retained header date fields; no inference about first public availability."""
from pathlib import Path
from datetime import datetime
import hashlib,json,re
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/merger-tender-date-consistency-20260913'
SOURCE=ROOT/'evidence/merger-tender-headers-20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    refs={}
    binding=ROOT/'evidence/merger-tender-linkage-20260913/audit_bindings.json'
    for p,h in json.loads(binding.read_text())['sha256'].items():
        assert sha(ROOT/p)==h,p
        refs[p]=h
    queue=json.loads((ROOT/'evidence/merger-tender-linkage-20260913/queue.json').read_text())
    rows=[]
    for q in queue:
        p=SOURCE/'headers'/(q['accession']+'.sgml');text=p.read_text()
        def one(tag):
            x=re.findall('^<'+tag+'>([^\\r\\n<]+)',text,re.M)
            assert len(x)==1,(q['accession'],tag)
            return x[0]
        assert one('ACCESSION-NUMBER')==q['accession']
        filing=datetime.strptime(one('FILING-DATE'),'%Y%m%d').date()
        accepted=datetime.strptime(one('ACCEPTANCE-DATETIME'),'%Y%m%d%H%M%S')
        changed=datetime.strptime(one('DATE-OF-FILING-DATE-CHANGE'),'%Y%m%d').date()
        indexed=datetime.strptime(q['filing_date'],'%Y-%m-%d').date()
        row={'accession':q['accession'],'filing_date':str(filing),'acceptance_raw':one('ACCEPTANCE-DATETIME'),
             'date_change':str(changed),'index_date':str(indexed),'index_matches_current_filing_date':indexed==filing,
             'filing_minus_acceptance_calendar_days':(filing-accepted.date()).days,
             'date_change_minus_filing_days':(changed-filing).days,
             'header_vintage_or_public_availability_certified':False}
        rows.append(row)
    assert len(rows)==205
    counts=Counter(r['filing_minus_acceptance_calendar_days'] for r in rows)
    result={'headers':205,'filing_acceptance_day_offsets':dict(sorted(counts.items())),
            'index_filing_date_mismatches':sum(not r['index_matches_current_filing_date'] for r in rows),
            'date_change_differs_from_filing':sum(r['date_change_minus_filing_days']!=0 for r in rows),
            'first_publication_times_verified':0,'qualified':False,'new_return_trials':0,
            'decision':'PARK_EXPANDED_ACQUISITION_PENDING_REVIEW_AND_VINTAGE_PLAN'}
    OUT.mkdir(exist_ok=False)
    for name,obj in [('rows.json',rows),('result.json',result)]:
        p=OUT/name;p.write_text(json.dumps(obj,indent=2)+'\n');refs[str(p.relative_to(ROOT))]=sha(p)
    refs[str(Path(__file__).relative_to(ROOT))]=sha(Path(__file__))
    (OUT/'source_bindings.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(json.dumps(result,indent=2))
    print('Negative offsets:',json.dumps([r for r in rows if r['filing_minus_acceptance_calendar_days']<0],indent=2))

if __name__=='__main__':main()
