"""Date-level fee annotations and diagnostic retained-balance comparison."""
from datetime import date
from decimal import Context, localcontext

from alphaforge.execution.payment_ledger import number
from alphaforge.execution.provider_payment_mapping import map_capture


def annotate_fees(packet):
    mapped = map_capture(packet)
    groups = {}
    unclassified = []
    for row in mapped['records']:
        provider_date = row['provider_date']
        try:
            if not isinstance(provider_date, str) or date.fromisoformat(
                    provider_date).isoformat() != provider_date:
                raise ValueError('date-only label required')
            if row['kind'] != 'fee' or row['provider_status'] != 'executed':
                raise ValueError('unconfirmed fee')
            if row['currency'] != 'USD':
                raise ValueError('unsupported fee currency')
            amount = number(row['amount'])
        except (ValueError, TypeError):
            unclassified.append(row['raw_reference'])
            continue
        key = (provider_date, row['currency'])
        group = groups.setdefault(key, {'provider_date': provider_date, 'currency': row['currency'],
                                       'signed_net_amount': '0', 'source_records': []})
        with localcontext(Context(prec=200)):
            group['signed_net_amount'] = str(number(group['signed_net_amount'])+amount)
        group['source_records'].append(row['raw_reference'])
    receipts = [r for r in packet['receipts'] if r['path'] == '/v2/account'
                and r['status'] == 'RECEIVED']
    balances = []
    missing = set()
    for receipt in (receipts[0], receipts[-1]):
        raw = receipt['parsed_response']
        fields = {}
        for key in ('cash', 'equity', 'accrued_fees', 'pending_reg_taf_fees'):
            value = raw.get(key)
            try:
                number(value)
            except ValueError:
                missing.add(key)
                value = None
            fields[key] = value
        balances.append({'receipt_wall_ns': receipt['receipt_wall_ns'], 'fields': fields})
    delta = None
    if 'cash' not in missing:
        with localcontext(Context(prec=200)):
            delta = str(number(balances[1]['fields']['cash'])-number(balances[0]['fields']['cash']))
    return {'schema': 'canli.daily-fee-annotation.v1', 'capture_sha256': mapped['capture_sha256'],
            'fee_groups': list(groups.values()), 'unclassified_record_hashes': unclassified,
            'balance_observations': balances, 'missing_balance_fields': sorted(missing),
            'observed_cash_delta': delta,
            'receipt_span_ns': balances[1]['receipt_wall_ns']-balances[0]['receipt_wall_ns'],
            'blocking_reasons': ['NO_BOUND_DAILY_OPENING_AND_CLOSING_BALANCES',
                                 'NO_COMPLETE_INTERVAL_FLOW_INVENTORY',
                                 'FEE_DATE_TO_POSTING_INTERVAL_UNVERIFIED',
                                 'ACCRUAL_INCLUSION_AND_OVERLAP_UNVERIFIED'],
            'provider_date_timezone': None, 'fees_proven_in_endpoint_nav': False,
            'extra_nav_deduction': None, 'reconciled': False, 'valuation_clearance': False}
