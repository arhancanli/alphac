import json
import runpy
from pathlib import Path

trace = runpy.run_path(str(Path(__file__).resolve().parents[2]/
                          'scripts/trace_crypto_cash_residual.py'))['trace']


def record(cycle, cash, initial=100, fills=None):
    return cycle, json.dumps({'initial_cash': initial, 'cash': cash, 'fills': fills or []})


def test_positive_negative_and_unchanged_residuals():
    rows = trace([record(1, 100), record(2, 105), record(3, 103), record(4, 103)])
    assert [r['delta_residual_quote'] for r in rows] == [None, '5', '-2', '0']


def test_initial_capital_reset_is_not_cashflow():
    rows = trace([record(1, 100), record(2, 200, initial=200)])
    assert rows[1]['retained_state_discontinuity']
    assert rows[1]['delta_residual_quote'] is None


def test_removed_fill_blocks_comparison():
    fill = {'client_order_id': 'a', 'side': 'buy', 'qty': 1, 'price': 10, 'fee_quote': 1}
    rows = trace([record(1, 89, fills=[fill]), record(2, 100)])
    assert rows[1]['retained_state_discontinuity']
    assert rows[1]['delta_residual_quote'] is None
