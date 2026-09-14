import asyncio
import hashlib
import json
import stat
from decimal import Decimal

import httpx
import pytest

from alphaforge.execution.spot_paper import PaperCredentials, account_digest
from alphaforge.validation.portfolio_observation import (
    ObservationReader,
    canonical,
    collect,
    save_capture,
)

ACCOUNT = {'id': 'synthetic-account', 'cash': '100.00', 'equity': '100.00'}
BINDING = account_digest(ACCOUNT)


def capture(handler=None, **kwargs):
    requests = []

    def respond(request):
        requests.append(request)
        if handler:
            result = handler(request, len(requests))
            if result is not None:
                return result
        payload = ACCOUNT if request.url.path == '/v2/account' else []
        return httpx.Response(200, json=payload)

    async def run():
        reader = ObservationReader(PaperCredentials('fake-key', 'fake-secret'),
                                   transport=httpx.MockTransport(respond), **kwargs)
        try:
            packet = await collect(reader, expected_binding=BINDING,
                                   after='2026-01-01T00:00:00Z', until='2026-01-02T00:00:00Z')
            return packet, requests
        finally:
            await reader.close()
    return asyncio.run(run())


def test_complete_scan_is_not_valuation():
    p, requests = capture()
    assert len(p['receipts']) == 7
    assert all(r.method == 'GET' for r in requests)
    assert p['activity_scan']['pagination_exhausted']
    assert not p['activity_scan']['settlement_complete']
    assert p['repeated_response_agreement']
    assert p['valuation_snapshot'] is None
    assert not p['runtime_clearance'] and not p['targets_verified']
    assert all(r['elapsed_ns'] >= 0 for r in p['receipts'])
    digest = p.pop('content_sha256')
    assert hashlib.sha256(canonical(p)).hexdigest() == digest


def test_failure_retains_prior_evidence_and_sanitizes_error():
    def handler(request, count):
        if count == 2:
            raise httpx.ConnectError('fake-secret DO NOT LOG')
    p, _ = capture(handler)
    assert len(p['receipts']) == 2
    assert p['receipts'][0]['parsed_response'] == ACCOUNT
    assert p['receipts'][1]['status'] == 'READ_FAILED'
    assert 'INCOMPLETE_OR_INVALID_CAPTURE' in p['blocking_reasons']
    assert 'fake-secret' not in json.dumps(p)


@pytest.mark.parametrize('which', [1, 3, 5, 7])
def test_identity_change_blocks(which):
    def handler(request, count):
        if count == which and request.url.path == '/v2/account':
            return httpx.Response(200, json={'id': 'wrong'})
    p, _ = capture(handler)
    assert 'INCOMPLETE_OR_INVALID_CAPTURE' in p['blocking_reasons']


def test_duplicate_activities_preserved_but_scan_incomplete():
    def handler(request, count):
        if request.url.path == '/v2/account/activities':
            return httpx.Response(200, json=[{'id': 'a', 'activity_type': 'DIV'}])
    p, _ = capture(handler)
    assert p['activity_scan'] is None
    assert 'INCOMPLETE_OR_INVALID_CAPTURE' in p['blocking_reasons']
    assert len([r for r in p['receipts'] if r['path'].endswith('activities')]) == 2


def test_all_activity_types_retained_and_empty_terminal_page_required():
    def handler(request, count):
        if request.url.path.endswith('activities') and 'page_token' not in request.url.params:
            return httpx.Response(200, json=[{'id': 'deposit', 'activity_type': 'CSD'}])
    p, _ = capture(handler)
    assert p['activity_scan']['records'][0]['activity_type'] == 'CSD'
    assert p['activity_scan']['pages_read'] == 2


def test_changing_balances_are_diagnostic():
    def handler(request, count):
        if count == 7:
            return httpx.Response(200, json={**ACCOUNT, 'cash': '101'})
    p, _ = capture(handler)
    assert not p['repeated_response_agreement']
    assert 'ACCOUNT_OR_POSITION_RESPONSES_CHANGED' in p['blocking_reasons']


def test_reversed_clock_blocks():
    ticks = iter(range(1000, 0, -1))
    p, _ = capture(wall=lambda: next(ticks))
    assert 'LOCAL_CLOCK_ORDERING_FAILURE' in p['blocking_reasons']


def test_decimal_body_preserved_without_float_rounding():
    def handler(request, count):
        if count == 1:
            return httpx.Response(
                200, content=b'{"id":"synthetic-account","x":0.1234567890123456789}')
    p, _ = capture(handler)
    assert p['receipts'][0]['parsed_response']['x'] == {
        'decimal_json_number': '0.1234567890123456789'}
    with pytest.raises(ValueError):
        canonical(Decimal('NaN'))


def test_private_exclusive_persistence(tmp_path):
    p, _ = capture()
    path = tmp_path/'capture.json'
    save_capture(path, p)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == p
    with pytest.raises(FileExistsError):
        save_capture(path, {})
    assert json.loads(path.read_text()) == p


def test_invalid_binding_does_not_request():
    async def run():
        reader = ObservationReader(PaperCredentials('x', 'y'))
        try:
            with pytest.raises(ValueError):
                await collect(reader, expected_binding='', after='', until='')
            assert not reader.receipts
        finally:
            await reader.close()
    asyncio.run(run())


@pytest.mark.parametrize('which', [2, 6])
def test_malformed_positions_block(which):
    def handler(request, count):
        if count == which:
            return httpx.Response(200, json={'error': 'not positions'})
    p, _ = capture(handler)
    assert 'INCOMPLETE_OR_INVALID_CAPTURE' in p['blocking_reasons']


def test_activity_budget_preserves_failed_page():
    def handler(request, count):
        if request.url.path.endswith('activities'):
            return httpx.Response(200, json=[
                {'id': f'{count}-{i}', 'activity_type': 'DIV'} for i in range(100)])
    p, _ = capture(handler)
    assert p['activity_scan'] is None
    assert 'INCOMPLETE_OR_INVALID_CAPTURE' in p['blocking_reasons']
    assert len([r for r in p['receipts'] if r['path'].endswith('activities')]) == 21
