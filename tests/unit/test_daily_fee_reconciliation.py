import runpy
from pathlib import Path

from alphaforge.execution.daily_fee_reconciliation import annotate_fees
from alphaforge.execution.payment_evidence import digest

fixture_path = Path(__file__).with_name('test_provider_payment_mapping.py')
fixture = runpy.run_path(str(fixture_path))['fixture']


def capture():
    packet = fixture()
    account = packet['receipts'][0]
    account['receipt_wall_ns'] = 1000000
    account['parsed_response'].update(cash='100', equity='101', accrued_fees='2',
                                      pending_reg_taf_fees='1')
    packet['receipts'].append({**account, 'receipt_wall_ns': 2000000})
    return packet


def seal(packet):
    return {**packet, 'content_sha256': digest(packet)}


def test_date_group_without_double_deduction():
    report = annotate_fees(seal(capture()))
    assert report['fee_groups'][0]['signed_net_amount'] == '-2'
    assert report['observed_cash_delta'] == '0'
    assert report['extra_nav_deduction'] is None
    assert not report['reconciled']
    assert report['provider_date_timezone'] is None


def test_missing_accrual_is_not_zero():
    packet = capture()
    del packet['receipts'][0]['parsed_response']['accrued_fees']
    report = annotate_fees(seal(packet))
    assert 'accrued_fees' in report['missing_balance_fields']
    assert report['balance_observations'][0]['fields']['accrued_fees'] is None


def test_rebate_sign_preserved():
    packet = capture()
    packet['receipts'][1]['parsed_response'][0]['net_amount'] = '2'
    assert annotate_fees(seal(packet))['fee_groups'][0]['signed_net_amount'] == '2'


def test_pending_fee_is_unclassified():
    packet = capture()
    packet['receipts'][1]['parsed_response'][0]['status'] = 'pending'
    report = annotate_fees(seal(packet))
    assert report['fee_groups'] == []
    assert len(report['unclassified_record_hashes']) == 1
