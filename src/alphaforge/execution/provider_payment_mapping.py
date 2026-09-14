"""Map retained Alpaca activity pages to partial evidence, never inferred payments."""
import json
from datetime import datetime, timedelta

from alphaforge.execution.payment_evidence import assess_window, digest
from alphaforge.execution.spot_paper import account_digest


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('explicit UTC timestamp required')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None or date.utcoffset() != timedelta(0):
        raise ValueError('explicit UTC timestamp required')
    return int(date.timestamp()*1000)


def map_capture(packet):
    packet = json.loads(json.dumps(packet, allow_nan=False))
    checksum = packet.pop('content_sha256')
    if digest(packet) != checksum:
        raise ValueError('capture hash mismatch')
    if packet.get('schema') != 'canli.portfolio-observation.v1':
        raise ValueError('unsupported capture schema')
    binding = packet['expected_account_binding']
    accounts = [r for r in packet['receipts'] if r['path'] == '/v2/account'
                and r['status'] == 'RECEIVED']
    if not accounts or any(account_digest(r['parsed_response']) != binding for r in accounts):
        raise ValueError('account identity mismatch')
    requested = packet['requested_activity_window']
    window = {'account': binding, 'source': 'alpaca-paper-account-activities',
              'scan_id': checksum, 'after_ms': timestamp(requested['after']),
              'until_ms': timestamp(requested['until']), 'pages': [], 'status': 'partial'}
    objects, rows, missing_created = {}, [], False
    for receipt in packet['receipts']:
        if receipt['path'] != '/v2/account/activities':
            continue
        if receipt['status'] != 'RECEIVED':
            break
        params = receipt['params']
        if (timestamp(params['after']) != window['after_ms']
                or timestamp(params['until']) != window['until_ms']
                or params.get('direction') != 'asc'):
            raise ValueError('activity request window mismatch')
        raw_page = receipt['parsed_response']
        if not isinstance(raw_page, list) or len(raw_page) > 100:
            raise ValueError('unsupported activity page')
        refs = []
        for raw in raw_page:
            raw_ref = digest(raw)
            objects[raw_ref] = raw
            gaps = ['NO_EXACT_EFFECTIVE_TIMESTAMP', 'NO_SOURCE_OBSERVATION_TIMESTAMP',
                    'LOCAL_RECEIPT_CLOCK_UNCALIBRATED']
            try:
                created = timestamp(raw.get('created_at'))
            except (ValueError, TypeError):
                created = None
                missing_created = True
                gaps.append('NO_USABLE_CREATION_TIMESTAMP')
            if raw.get('activity_type') != 'FEE':
                gaps.append('UNSUPPORTED_ACTIVITY_TYPE')
            row = {'account': binding, 'source': window['source'], 'event_id': raw.get('id'),
                   'created_ms': created, 'currency': raw.get('currency'),
                   'kind': 'fee' if raw.get('activity_type') == 'FEE' else None,
                   'amount': raw.get('net_amount'), 'effective_ms': None, 'source_ms': None,
                   'received_ms': receipt['receipt_wall_ns']//1000000,
                   'provider_date': raw.get('date'), 'provider_status': raw.get('status'),
                   'raw_reference': raw_ref, 'capture_sha256': checksum,
                   'blocking_reasons': gaps}
            objects[digest(row)] = row
            refs.append(digest(row))
            rows.append(row)
        page = {k: v for k, v in window.items() if k not in ('pages', 'status')}
        page.update(cursor=params.get('page_token'), records=refs,
                    next_cursor=raw_page[-1]['id'] if raw_page else None)
        objects[digest(page)] = page
        window['pages'].append(digest(page))
    if packet.get('activity_scan') and packet['activity_scan'].get('pagination_exhausted'):
        window['status'] = 'completed'
    bundle = {'window': window, 'objects': objects}
    coverage = None if missing_created else assess_window(window, objects)
    return {'schema': 'canli.provider-payment-mapping.v1', 'capture_sha256': checksum,
            'bundle': bundle, 'coverage': coverage, 'records': rows, 'bookable_payments': [],
            'valuation_clearance': False, 'source_authentication_verified': False}
