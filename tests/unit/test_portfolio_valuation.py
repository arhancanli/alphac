from dataclasses import replace
from decimal import Decimal, localcontext

import pandas as pd
import pytest

from alphaforge.validation.portfolio_valuation import (
    DAY_MS,
    CashBenchmark,
    Component,
    ExternalFlow,
    Policy,
    Position,
    Snapshot,
    ValuationError,
    expected_price_time,
    measured_interval,
    value_book,
)

HASH = 'a' * 64
CUT = int(pd.Timestamp('2026-08-11T00:00Z').value // 1_000_000)


def policy():
    return Policy('synthetic-epoch', CUT, (Component('a', 'sleeve', 'ledger-a'),),
                  1000, '0.01', HASH,
                  (('BTC', 'UTC24X7'), ('SPY', 'XNYS'), ('short', 'UTC24X7')))


def mark(p=None, cut=CUT, cash='100'):
    p = p or policy()
    return Snapshot('a', 'ledger-a', p.epoch, p.fingerprint(), cut, cut, cut, cut+100,
                    cash, '0', '0', cash, (), HASH, True)


def value(p, records, cut=CUT):
    return value_book(p, records, cut_ms=cut, evaluated_ms=cut+1000)


def interval(closing_cash='110', flows=(), **kwargs):
    p = policy()
    args = {'policy': p, 'opening': (mark(p),),
            'closing': (mark(p, CUT+DAY_MS, closing_cash),),
            'flows': flows, 'benchmark': CashBenchmark(CUT, CUT+DAY_MS, '0.001', HASH),
            'start_ms': CUT, 'end_ms': CUT+DAY_MS, 'evaluated_ms': CUT+DAY_MS+1000,
            'flow_inventory_complete': True}
    args.update(kwargs)
    return measured_interval(**args)


def test_exact_nav_and_no_authentication_or_qualification_claim():
    result = value(policy(), (mark(),))
    assert Decimal(result['nav_usd']) == 100
    assert result['authentication_verified'] is False
    assert result['runtime_clearance'] is False
    assert result['portfolio_targets_established'] is False


@pytest.mark.parametrize('records', [(), (mark(), mark()), (replace(mark(), component='extra'),)])
def test_missing_duplicate_extra_component_refused(records):
    with pytest.raises(ValuationError):
        value(policy(), records)


@pytest.mark.parametrize(('field', 'bad'), [
    ('ledger_id', 'another-account'), ('epoch', 'old'), ('policy_sha256', 'b'*64),
    ('cut_ms', CUT-DAY_MS), ('cash_asof_ms', CUT-1), ('positions_asof_ms', CUT-1),
    ('received_ms', CUT-1), ('received_ms', CUT+1001), ('cashflows_complete', False),
    ('cashflows_complete', 1), ('source_sha256', 'not-a-hash'),
    ('reported_nav_usd', '100.02'), ('cash_usd', 'NaN'), ('cash_usd', 100),
    ('receivables_usd', '-1'), ('liabilities_usd', '-1'),
])
def test_snapshot_defects_refused(field, bad):
    with pytest.raises(ValuationError):
        value(policy(), (replace(mark(), **{field: bad}),))


def test_evidence_cannot_be_used_before_receipt():
    with pytest.raises(ValuationError, match='not yet received'):
        value_book(policy(), (mark(),), cut_ms=CUT, evaluated_ms=CUT)


def test_overlay_requires_separate_capital_partition_and_is_in_nav():
    p = replace(policy(), components=(*policy().components, Component('overlay', 'overlay', 'o')))
    equity = replace(mark(p), cash_usd='90', reported_nav_usd='90')
    overlay = replace(mark(p), component='overlay', ledger_id='o', cash_usd='0',
                      positions=(Position('BTC', '1', '10', CUT, 'UTC24X7', HASH),),
                      reported_nav_usd='10')
    assert Decimal(value(p, (equity, overlay))['nav_usd']) == 100
    duplicate = replace(p, components=(
        p.components[0], Component('overlay', 'overlay', 'ledger-a')))
    with pytest.raises(ValuationError, match='counted twice'):
        duplicate.fingerprint()


@pytest.mark.parametrize(('date', 'close'), [
    ('2026-08-11T00:00Z', '2026-08-10T20:00Z'),
    ('2026-08-10T00:00Z', '2026-08-07T20:00Z'),
    ('2026-09-08T00:00Z', '2026-09-04T20:00Z'),
    ('2026-11-28T00:00Z', '2026-11-27T18:00Z'),
])
def test_weekend_holiday_and_early_close_policy(date, close):
    cut = int(pd.Timestamp(date).value // 1_000_000)
    assert expected_price_time(cut, 'XNYS') == pd.Timestamp(close).value // 1_000_000


def test_equity_close_mark_requires_current_cut_cash_and_positions():
    p = policy()
    position = Position('SPY', '1', '10', expected_price_time(CUT, 'XNYS'), 'XNYS', HASH)
    snapshot = replace(mark(p), cash_usd='90', positions=(position,))
    assert Decimal(value(p, (snapshot,))['nav_usd']) == 100
    with pytest.raises(ValuationError, match='stale'):
        stale = replace(position, price_asof_ms=position.price_asof_ms-1)
        value(p, (replace(snapshot, positions=(stale,)),))
    with pytest.raises(ValuationError, match='same cut'):
        value(p, (replace(snapshot, cash_asof_ms=position.price_asof_ms),))


@pytest.mark.parametrize('delta', [-1, 1])
def test_crypto_cannot_borrow_equity_closure_rule(delta):
    position = Position('BTC', '1', '100', CUT+delta, 'UTC24X7', HASH)
    with pytest.raises(ValuationError, match='stale'):
        value(policy(), (replace(mark(), cash_usd='0', positions=(position,)),))


def test_short_assets_and_liabilities_reconcile_without_double_deducting_fees():
    position = Position('short', '-1', '10', CUT, 'UTC24X7', HASH)
    snapshot = replace(mark(), cash_usd='120', receivables_usd='3', liabilities_usd='13',
                       positions=(position,))
    assert Decimal(value(policy(), (snapshot,))['nav_usd']) == 100
    # Closing cash is already net of charged fees. No additional fee subtraction.
    result = interval('109')
    assert Decimal(result['net_return']) == Decimal('.09')
    assert Decimal(result['excess_return']) == Decimal('.089')


def test_deposit_neutral_return_and_reference_cash_not_credited_twice():
    flow = ExternalFlow('deposit', CUT+DAY_MS, '20', HASH)
    result = interval('130', (flow,))
    assert Decimal(result['net_return']) == Decimal('.1')
    assert Decimal(result['excess_return']) == Decimal('.099')


def test_withdrawal_at_cut_is_neutral():
    result = interval('90', (ExternalFlow('withdrawal', CUT+DAY_MS, '-20', HASH),))
    assert Decimal(result['net_return']) == Decimal('.1')


@pytest.mark.parametrize('flows', [
    (ExternalFlow('midday', CUT+1000, '20', HASH),),
    (ExternalFlow('x', CUT+DAY_MS, '20', HASH), ExternalFlow('x', CUT+DAY_MS, '20', HASH)),
])
def test_unsupported_flow_timing_or_duplicates_refused(flows):
    with pytest.raises(ValuationError):
        interval(flows=flows)


def test_missing_flow_inventory_or_wrong_benchmark_refused():
    with pytest.raises(ValuationError):
        interval(flow_inventory_complete=False)
    with pytest.raises(ValuationError):
        interval(benchmark=CashBenchmark(CUT-1, CUT+DAY_MS, '0.001', HASH))
    with pytest.raises(ValuationError):
        interval(end_ms=CUT+2*DAY_MS)


def test_loss_of_all_capital_is_reported_not_dropped():
    result = interval('-10')
    assert Decimal(result['net_return']) == Decimal('-1.1')
    assert result['capital_loss_at_least_100pct'] is True


def test_policy_changes_change_epoch_binding():
    p = replace(policy(), max_receipt_delay_ms=2000)
    assert p.fingerprint() != policy().fingerprint()
    with pytest.raises(ValuationError, match='Mixed epoch'):
        value(p, (mark(),))


def test_crypto_cannot_claim_equity_calendar_to_accept_old_prices():
    position = Position('BTC', '1', '100', expected_price_time(CUT, 'XNYS'), 'XNYS', HASH)
    with pytest.raises(ValuationError, match='calendar not bound'):
        value(policy(), (replace(mark(), cash_usd='0', positions=(position,)),))


def test_decimal_context_cannot_change_results():
    expected = interval('109.123456789123456789')
    with localcontext() as context:
        context.prec = 6
        assert interval('109.123456789123456789') == expected


def test_interval_hash_binds_cash_benchmark_and_flow_evidence():
    original = interval()
    changed = interval(benchmark=CashBenchmark(CUT, CUT+DAY_MS, '0.001', 'b'*64))
    assert original['net_return'] == changed['net_return']
    assert original['interval_evidence_sha256'] != changed['interval_evidence_sha256']
