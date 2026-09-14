"""Legacy simulated ledger coverage checks, not economic admission or USD valuation."""
import hashlib
import json
import math


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite legacy numeric value required')
    return value


def assess_legacy_accounting(state, *, contracts=None, account_binding=None):
    """Reconcile retained fills diagnostically; missing event inventories always block.

    Contract declarations must be independently source-bound by a later verifier.
    A populated binding is not authenticated simply because this function accepts it.
    """
    contracts = contracts or {}
    cash = _number(state['initial_cash'])
    actual_cash = _number(state['cash'])
    fills, positions = state['fills'], state['positions']
    if len(fills) > 1000000 or len(positions) > 10000:
        raise ValueError('ledger size budget exceeded')
    gaps = {'NO_FUNDING_PAYMENT_INVENTORY', 'NO_EXTERNAL_INTERNAL_FLOW_INVENTORY',
            'NO_ACCRUAL_LIABILITY_INVENTORY', 'LEGACY_FLOAT_ACCOUNTING',
            'CONTRACT_SOURCE_AUTHENTICATION_UNVERIFIED'}
    if not account_binding:
        gaps.add('NO_ACCOUNT_PARTITION_BINDING')
    ids, instruments, quantities = set(), set(), {}
    fees = 0.
    for fill in fills:
        identity = fill['client_order_id']
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError('duplicate or missing retained fill identity')
        ids.add(identity)
        iid = fill['instrument_id']
        instruments.add(iid)
        if fill['side'] not in ('buy', 'sell'):
            raise ValueError('unsupported fill side')
        qty, price, fee = (_number(fill[k]) for k in ('qty', 'price', 'fee_quote'))
        if qty <= 0 or price <= 0:
            raise ValueError('invalid fill economics')
        signed = qty if fill['side'] == 'buy' else -qty
        cash = cash - signed * price - fee
        fees += fee
        quantities[iid] = quantities.get(iid, 0.) + signed
    position_ids = set()
    for position in positions:
        iid = position['instrument_id']
        if iid in position_ids:
            raise ValueError('duplicate position')
        position_ids.add(iid)
        instruments.add(iid)
        qty = _number(position['qty'])
        if not math.isclose(qty, quantities.get(iid, 0.), rel_tol=1e-10, abs_tol=1e-8):
            gaps.add('POSITIONS_NOT_RECONSTRUCTED_FROM_RETAINED_FILLS')
    if any(abs(qty) > 1e-8 for iid, qty in quantities.items() if iid not in position_ids):
        gaps.add('POSITIONS_NOT_RECONSTRUCTED_FROM_RETAINED_FILLS')
    for iid in instruments:
        contract = contracts.get(iid)
        if contract is None:
            gaps.add('MISSING_CONTRACT_BINDING')
            continue
        if (contract.get('instrument_id') != iid or not contract.get('source_sha256')
                or contract.get('quantity_unit') != 'base'
                or contract.get('accounting') != 'cash_plus_signed_inventory'
                or contract.get('multiplier') != 1):
            gaps.add('UNSUPPORTED_OR_UNBOUND_CONTRACT_SEMANTICS')
        if not contract.get('quote') or contract.get('settlement') != contract.get('quote'):
            gaps.add('UNSUPPORTED_SETTLEMENT_CURRENCY')
    quotes = {c.get('quote') for c in contracts.values()}
    if len(quotes) != 1 or None in quotes:
        gaps.add('NO_SINGLE_QUOTE_CURRENCY_BINDING')
    if quotes != {'USD'}:
        gaps.add('NO_BOUND_USD_CONVERSION')
    residual = actual_cash - cash
    if not all(math.isfinite(x) for x in (cash, fees, residual)):
        raise ValueError('nonfinite ledger arithmetic')
    if abs(residual) > .01:
        gaps.add('UNEXPLAINED_CASH_MOVEMENT')
    report = {'schema': 'canli.legacy-crypto-accounting.v1',
              'state_sha256': hashlib.sha256(json.dumps(
                  state, sort_keys=True, separators=(',', ':'),
                  allow_nan=False).encode()).hexdigest(),
              'declared_contracts': contracts, 'declared_account_binding': account_binding,
              'retained_fills': len(fills), 'retained_positions': len(positions),
              'instrument_ids': sorted(instruments), 'fill_fees_quote': fees,
              'cash_from_initial_and_fills_quote': cash, 'recorded_cash_quote': actual_cash,
              'unexplained_cash_residual_quote': residual,
              'blocking_reasons': sorted(gaps), 'flows_complete': False,
              'valuation_clearance': False, 'usd_equity': None}
    return report
