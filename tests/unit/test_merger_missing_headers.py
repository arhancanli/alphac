import pytest
from audit_merger_missing_headers import parse_header

HEADER = '''<SEC-HEADER>
<ACCESSION-NUMBER>0000032776-12-000007
<TYPE>8-K
<ACCEPTANCE-DATETIME>20121011154452
<ITEMS>1.01
<ITEMS>9.01
<FILER>
<CIK>0000032776
</FILER>
</SEC-HEADER>'''


def test_identity_and_item_screen_only():
    r = parse_header(HEADER, '0000032776-12-000007', 32776)
    assert r['state'] == 'ITEM_CODE_CANDIDATE'
    assert r['acceptance_raw'] == '20121011154452'
    assert 'transaction_label' not in r


@pytest.mark.parametrize('old,new', [
    ('<TYPE>8-K', '<TYPE>8-K/A'),
    ('<CIK>0000032776', '<CIK>0000000001'),
    ('<ACCESSION-NUMBER>0000032776-12-000007', '<ACCESSION-NUMBER>bad'),
    ('<ITEMS>1.01', '<ITEMS>unknown'),
])
def test_reject_wrong_identity_or_malformed_item(old, new):
    with pytest.raises(AssertionError):
        parse_header(HEADER.replace(old, new), '0000032776-12-000007', 32776)


def test_missing_items_remain_unresolved():
    text = HEADER.replace('<ITEMS>1.01\n', '').replace('<ITEMS>9.01\n', '')
    assert parse_header(text, '0000032776-12-000007', 32776)['state'] == 'EMPTY_ITEMS_UNRESOLVED'
