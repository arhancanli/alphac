"""Content-bound normalized evidence; hash consistency is not source authentication."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def object_at(objects, reference):
    value = objects.get(reference)
    if value is None or digest(value) != reference:
        raise ValueError('missing or changed evidence object')
    return value


def assess_window(window, objects):
    """Fixed creation-time query coverage; delayed settlement remains unresolved."""
    for key in ('account', 'source', 'scan_id'):
        if not isinstance(window.get(key), str) or not window[key]:
            raise ValueError('missing scan binding')
    first, last = window['after_ms'], window['until_ms']
    if type(first) is not int or type(last) is not int or not 0 <= first < last:
        raise ValueError('invalid acquisition window')
    pages = window['pages']
    if not isinstance(pages, list) or len(pages) > 100:
        raise ValueError('page budget exceeded')
    cursor = None
    seen = set()
    records = []
    exhausted = False
    for reference in pages:
        page = object_at(objects, reference)
        if exhausted or any(page.get(k) != window[k] for k in (
                'account', 'source', 'scan_id', 'after_ms', 'until_ms')):
            raise ValueError('mixed scan or page after exhaustion')
        if page.get('cursor') != cursor:
            raise ValueError('broken pagination chain')
        items = page['records']
        if not isinstance(items, list) or len(items) > 1000:
            raise ValueError('invalid page records')
        for ref in items:
            record = object_at(objects, ref)
            if (record.get('account') != window['account']
                    or record.get('source') != window['source']):
                raise ValueError('record identity mismatch')
            created = record.get('created_ms')
            if type(created) is not int or not first <= created <= last:
                raise ValueError('record outside creation-time window')
            identity = record.get('event_id')
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ValueError('missing or duplicate event identity')
            seen.add(identity)
            records.append(ref)
        cursor = page.get('next_cursor')
        exhausted = not items and cursor is None
        if not exhausted and (not isinstance(cursor, str) or not cursor):
            raise ValueError('nonterminal page lacks continuation cursor')
    return {'records': records, 'pagination_exhausted': exhausted,
            'scan_complete': exhausted and window.get('status') == 'completed',
            'settlement_complete': False, 'source_authentication_verified': False}


def verify_payment(event, bundle):
    objects, window = bundle['objects'], bundle['window']
    if len(objects) > 10000:
        raise ValueError('evidence object budget exceeded')
    coverage = assess_window(window, objects)
    if event['source_receipt'] not in coverage['records']:
        raise ValueError('payment absent from retained scan')
    record = object_at(objects, event['source_receipt'])
    for key in ('account', 'source', 'event_id', 'currency', 'kind', 'amount',
                'effective_ms', 'source_ms', 'received_ms'):
        if record.get(key) != event.get(key):
            raise ValueError('payment differs from source record')
    if event['kind'] == 'funding':
        required = {
            'contract_reference': ('instrument', 'currency', 'multiplier', 'settlement_schedule'),
            'position_reference': ('account', 'instrument', 'quantity', 'effective_ms'),
            'mark_reference': ('instrument', 'currency', 'mark', 'effective_ms'),
        }
        for reference, keys in required.items():
            obj = object_at(objects, event[reference])
            if any(obj.get(k) != event.get(k) for k in keys):
                raise ValueError('funding evidence binding mismatch')
        if record.get('rate') != event.get('rate'):
            raise ValueError('funding rate differs from source record')
    return coverage


def save_window(path, bundle):
    """Persist even partial/empty scans privately without booking cash."""
    from alphaforge.validation.portfolio_observation import save_capture
    detached = json.loads(json.dumps(bundle, allow_nan=False))
    coverage = assess_window(detached['window'], detached['objects'])
    packet = {'schema': 'canli.payment-window.v1', 'bundle': detached,
              'coverage': coverage, 'valuation_clearance': False}
    packet['content_sha256'] = digest(packet)
    save_capture(path, packet)
    return coverage
