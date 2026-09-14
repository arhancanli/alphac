import copy

import pytest

from alphaforge.validation.crypto_accounting import assess_legacy_accounting


def state():
    return {'initial_cash': 1000., 'cash': 799.,
            'fills': [{'client_order_id': 'a', 'instrument_id': 'x', 'side': 'buy',
                       'qty': 2., 'price': 100., 'fee_quote': 1.}],
            'positions': [{'instrument_id': 'x', 'qty': 2.}]}


def test_cash_match_does_not_prove_complete_funding():
    result = assess_legacy_accounting(state())
    assert result['unexplained_cash_residual_quote'] == 0
    assert result['fill_fees_quote'] == 1
    assert not result['flows_complete'] and result['usd_equity'] is None
    assert 'NO_FUNDING_PAYMENT_INVENTORY' in result['blocking_reasons']


def test_unexplained_cash_is_not_assigned_to_funding():
    s = state()
    s['cash'] -= 5
    result = assess_legacy_accounting(s)
    assert result['unexplained_cash_residual_quote'] == -5
    assert 'UNEXPLAINED_CASH_MOVEMENT' in result['blocking_reasons']


@pytest.mark.parametrize('key,value', [('qty', float('nan')), ('price', -1), ('side', 'bad')])
def test_bad_fill_rejected(key, value):
    s = state()
    s['fills'][0][key] = value
    with pytest.raises(ValueError):
        assess_legacy_accounting(s)


def test_duplicate_fill_rejected():
    s = state()
    s['fills'].append(copy.deepcopy(s['fills'][0]))
    with pytest.raises(ValueError):
        assess_legacy_accounting(s)


def test_missing_position_detected():
    s = state()
    s['positions'] = []
    assert 'POSITIONS_NOT_RECONSTRUCTED_FROM_RETAINED_FILLS' in (
        assess_legacy_accounting(s)['blocking_reasons'])


def test_usdt_is_not_usd_and_multiplier_not_silently_applied():
    contracts = {'x': {'instrument_id': 'x', 'source_sha256': 'fixture', 'quantity_unit': 'base',
                       'accounting': 'cash_plus_signed_inventory', 'multiplier': 2,
                       'quote': 'USDT', 'settlement': 'USDT'}}
    result = assess_legacy_accounting(state(), contracts=contracts, account_binding='fixture')
    assert 'UNSUPPORTED_OR_UNBOUND_CONTRACT_SEMANTICS' in result['blocking_reasons']
    assert 'NO_BOUND_USD_CONVERSION' in result['blocking_reasons']
    assert not result['valuation_clearance']


def test_sell_cash_and_closed_position_reconstruct():
    s = state()
    s['fills'].append({'client_order_id': 'b', 'instrument_id': 'x', 'side': 'sell',
                       'qty': 2., 'price': 110., 'fee_quote': 1.})
    s['positions'] = []
    s['cash'] = 1018.
    result = assess_legacy_accounting(s)
    assert result['unexplained_cash_residual_quote'] == 0
    assert 'POSITIONS_NOT_RECONSTRUCTED_FROM_RETAINED_FILLS' not in result['blocking_reasons']


def test_valid_declarations_do_not_authenticate_contract_or_flows():
    contracts = {'x': {'instrument_id': 'x', 'source_sha256': 'fixture', 'quantity_unit': 'base',
                       'accounting': 'cash_plus_signed_inventory', 'multiplier': 1,
                       'quote': 'USD', 'settlement': 'USD'}}
    result = assess_legacy_accounting(state(), contracts=contracts, account_binding='fixture')
    assert 'CONTRACT_SOURCE_AUTHENTICATION_UNVERIFIED' in result['blocking_reasons']
    assert 'NO_EXTERNAL_INTERNAL_FLOW_INVENTORY' in result['blocking_reasons']
    assert not result['valuation_clearance'] and result['usd_equity'] is None
