import copy
import json

import pytest

from alphaforge.execution import payment_ledger as ledger
from alphaforge.execution.payment_evidence import assess_window, digest, save_window


def fixture():
    record = {'account': 'a', 'source': 's', 'event_id': '1', 'currency': 'USDT',
              'kind': 'fee', 'amount': '-2', 'effective_ms': 1, 'source_ms': 2,
              'received_ms': 3, 'created_ms': 2}
    ref = digest(record)
    window = {'account': 'a', 'source': 's', 'scan_id': 'scan', 'after_ms': 0,
              'until_ms': 5, 'status': 'completed'}
    base = {k: v for k, v in window.items() if k != 'status'}
    page = {**base, 'cursor': None, 'next_cursor': '1', 'records': [ref]}
    end = {**base, 'cursor': '1', 'next_cursor': None, 'records': []}
    objects = {ref: record, digest(page): page, digest(end): end}
    window['pages'] = [digest(page), digest(end)]
    event = {k: v for k, v in record.items() if k != 'created_ms'}
    event.update(epoch='e', source_receipt=ref)
    return event, {'objects': objects, 'window': window}


@pytest.fixture
def path(tmp_path):
    p = tmp_path/'ledger'
    ledger.create(p, account='a', epoch='e', currency='USDT', initial_cash='100')
    return p


def test_bound_commit_recovery_and_replay(path):
    event, bundle = fixture()
    assert ledger.apply(path, event, evidence=bundle)['cash'] == '98'
    assert not ledger.apply(path, event, evidence=bundle)['applied']
    assert ledger.recover(path)['payments'] == 1
    assert not ledger.recover(path)['flows_complete']


def test_changed_evidence_rejects_before_cash(path):
    event, bundle = fixture()
    bundle['objects'][event['source_receipt']]['amount'] = '-3'
    with pytest.raises(ValueError, match='changed evidence'):
        ledger.apply(path, event, evidence=bundle)
    assert ledger.recover(path)['cash'] == '100'


def test_changed_event_does_not_match_evidence(path):
    event, bundle = fixture()
    event['amount'] = '-3'
    with pytest.raises(ValueError, match='differs'):
        ledger.apply(path, event, evidence=bundle)


def test_partial_window_saved_without_completeness(tmp_path):
    _, bundle = fixture()
    bundle['window']['pages'].pop()
    bundle['window']['status'] = 'failed'
    p = tmp_path/'window.json'
    result = save_window(p, bundle)
    assert not result['scan_complete'] and not result['settlement_complete']
    packet = json.loads(p.read_text())
    actual = packet.pop('content_sha256')
    assert actual == digest(packet)
    with pytest.raises(FileExistsError):
        save_window(p, bundle)


def test_complete_scan_not_complete_settlement():
    _, bundle = fixture()
    result = assess_window(bundle['window'], bundle['objects'])
    assert result['scan_complete'] and not result['settlement_complete']


@pytest.mark.parametrize('field,value', [('account', 'wrong'), ('cursor', 'wrong'),
                                        ('after_ms', 1)])
def test_mixed_page_binding(field, value):
    _, bundle = fixture()
    page = copy.deepcopy(bundle['objects'][bundle['window']['pages'][0]])
    page[field] = value
    bundle['objects'][digest(page)] = page
    bundle['window']['pages'][0] = digest(page)
    with pytest.raises(ValueError):
        assess_window(bundle['window'], bundle['objects'])


def test_event_missing_from_window(path):
    event, bundle = fixture()
    bundle['window']['pages'] = []
    with pytest.raises(ValueError, match='absent'):
        ledger.apply(path, event, evidence=bundle)


@pytest.mark.parametrize('wrong_position', [False, True])
def test_funding_references(path, wrong_position):
    event, bundle = fixture()
    record = bundle['objects'][event['source_receipt']]
    record.update(kind='funding', rate='0.01')
    source_ref = digest(record)
    bundle['objects'][source_ref] = record
    page = bundle['objects'][bundle['window']['pages'][0]]
    page['records'] = [source_ref]
    bundle['objects'][digest(page)] = page
    bundle['window']['pages'][0] = digest(page)
    event.update(kind='funding', source_receipt=source_ref, instrument='x', quantity='2',
                 mark='100', rate='0.01', multiplier='1', settlement_schedule='fixture')
    for field, value in {
        'contract_reference': {'instrument': 'x', 'currency': 'USDT', 'multiplier': '1',
                               'settlement_schedule': 'fixture'},
        'position_reference': {'account': 'a', 'instrument': 'x',
                               'quantity': '3' if wrong_position else '2', 'effective_ms': 1},
        'mark_reference': {'instrument': 'x', 'currency': 'USDT', 'mark': '100',
                           'effective_ms': 1},
    }.items():
        bundle['objects'][digest(value)] = value
        event[field] = digest(value)
    if wrong_position:
        with pytest.raises(ValueError, match='binding mismatch'):
            ledger.apply(path, event, evidence=bundle)
        assert ledger.recover(path)['cash'] == '100'
    else:
        assert ledger.apply(path, event, evidence=bundle)['cash'] == '98'
        assert ledger.recover(path)['payments'] == 1
