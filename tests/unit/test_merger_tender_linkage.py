import pytest
from audit_merger_headers import parse_header
from audit_merger_tender_linkage import subject_state


@pytest.mark.parametrize('subjects,cik,expected', [
    ([10],10,'SUBJECT_CIK_MATCH_METADATA_ONLY'),
    ([10],20,'INDEXED_CIK_NOT_SUBJECT'),
    ([],20,'UNRESOLVED_SUBJECT_COUNT'),
    ([10,20],10,'UNRESOLVED_SUBJECT_COUNT'),
])
def test_subject_not_bidder(subjects,cik,expected):
    blocks=''.join(f'<SUBJECT-COMPANY>\n<CIK>{v}\n</SUBJECT-COMPANY>\n' for v in subjects)
    text='<ACCESSION-NUMBER>0000000001-10-000001\n<TYPE>SC TO-T\n<ACCEPTANCE-DATETIME>20100101120000\n'+blocks+'<FILED-BY>\n<CIK>20\n</FILED-BY>\n'
    parsed=parse_header(text)
    assert subject_state(parsed,cik)==expected
    assert not parsed['acceptance_utc_verified']
