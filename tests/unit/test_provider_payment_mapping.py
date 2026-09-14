import copy

import pytest

from alphaforge.execution.payment_evidence import digest
from alphaforge.execution.provider_payment_mapping import map_capture, timestamp
from alphaforge.execution.spot_paper import account_digest


def fixture():
    account = {'id': 'synthetic'}
    params = {'after': '2026-01-01T00:00:00Z', 'until': '2026-01-02T00:00:00Z', 'direction': 'asc'}
    record = {'id': '1', 'activity_type': 'FEE', 'created_at': '2026-01-01T12:00:00Z',
              'currency': 'USD', 'net_amount': '-2', 'date': '2026-01-01', 'status': 'executed'}
    packet = {'schema': 'canli.portfolio-observation.v1',
              'expected_account_binding': account_digest(account),
              'requested_activity_window': params,
              'activity_scan': {'pagination_exhausted': True},
              'receipts': [{'path': '/v2/account', 'status': 'RECEIVED',
                            'parsed_response': account},
                           {'path': '/v2/account/activities', 'status': 'RECEIVED',
                            'params': params, 'parsed_response': [record],
                            'receipt_wall_ns': 1000000},
                           {'path': '/v2/account/activities', 'status': 'RECEIVED',
                            'params': {**params, 'page_token': '1'}, 'parsed_response': [],
                            'receipt_wall_ns': 2000000}]}
    return packet


def seal(packet):
    return {**packet, 'content_sha256': digest(packet)}


def test_date_only_payment_not_promoted():
    result = map_capture(seal(fixture()))
    assert result['coverage']['scan_complete']
    assert not result['coverage']['settlement_complete']
    assert result['records'][0]['effective_ms'] is None
    assert result['records'][0]['source_ms'] is None
    assert result['bookable_payments'] == []


def test_hash_change_rejected():
    packet = seal(fixture())
    packet['activity_scan'] = None
    with pytest.raises(ValueError, match='hash'):
        map_capture(packet)


def test_missing_created_does_not_use_provider_date():
    packet = fixture()
    del packet['receipts'][1]['parsed_response'][0]['created_at']
    result = map_capture(seal(packet))
    assert result['coverage'] is None
    assert result['records'][0]['created_ms'] is None


def test_wrong_account_rejected():
    packet = fixture()
    packet['expected_account_binding'] = 'wrong'
    with pytest.raises(ValueError, match='identity'):
        map_capture(seal(packet))


def test_changed_window_rejected():
    packet = copy.deepcopy(fixture())
    packet['receipts'][1]['params'] = {**packet['receipts'][1]['params'],
                                       'after': '2025-01-01T00:00:00Z'}
    with pytest.raises(ValueError, match='window'):
        map_capture(seal(packet))


def test_date_only_and_naive_timestamp_rejected():
    for raw in ['2026-01-01', '2026-01-01T00:00:00']:
        with pytest.raises(ValueError):
            timestamp(raw)
