import os
import sqlite3
import subprocess
import sys

import pytest

from alphaforge.execution import payment_ledger as ledger


@pytest.fixture
def path(tmp_path):
    p = tmp_path/'payments.sqlite'
    ledger.create(p, account='a', epoch='e', currency='USDT', initial_cash='1000')
    return p


def event(**changes):
    base = {'account': 'a', 'epoch': 'e', 'currency': 'USDT', 'source': 'fixture',
            'event_id': '1', 'source_receipt': 'synthetic', 'effective_ms': 1,
            'source_ms': 1, 'received_ms': 2, 'kind': 'fee', 'amount': '-2'}
    return {**base, **changes}


def test_replay_and_conflict(path):
    assert ledger.apply(path, event())['cash'] == '998'
    assert not ledger.apply(path, event())['applied']
    with pytest.raises(ValueError, match='conflicting'):
        ledger.apply(path, event(amount='-3'))
    assert ledger.recover(path)['payments'] == 1


@pytest.mark.parametrize('change', [{'currency': 'USD'}, {'epoch': 'wrong'},
                                    {'kind': 'unknown'}, {'amount': 'NaN'},
                                    {'source_receipt': ''}])
def test_invalid_event_no_cash_mutation(path, change):
    with pytest.raises(ValueError):
        ledger.apply(path, event(**change))
    assert ledger.recover(path)['cash'] == '1000'


@pytest.mark.parametrize('quantity,amount', [('2', '-2.00'), ('-2', '2.00'), ('0', '0')])
def test_signed_and_zero_funding(path, quantity, amount):
    payment = event(kind='funding', amount=amount, quantity=quantity, mark='100', rate='.01')
    payment['rate'] = '0.01'
    payment.update(instrument='x', contract_reference='c', position_reference='p',
                   mark_reference='m', settlement_schedule='fixture', multiplier='1')
    ledger.apply(path, payment)
    assert ledger.recover(path)['payments'] == 1
    assert not ledger.recover(path)['flows_complete']


def test_missing_position_evidence_blocks_funding(path):
    with pytest.raises(ValueError, match='funding evidence'):
        ledger.apply(path, event(kind='funding'))


def test_linked_reversal_once(path):
    ledger.apply(path, event())
    reversal = event(event_id='2', kind='reversal', amount='2', reverses=['fixture', '1'])
    ledger.apply(path, reversal)
    assert ledger.recover(path)['cash'] == '1000'
    with pytest.raises(ValueError, match='already reversed'):
        ledger.apply(path, {**reversal, 'event_id': '3'})


def test_changed_cash_fails_recovery(path):
    ledger.apply(path, event())
    with sqlite3.connect(path) as c:
        c.execute("UPDATE ledger SET cash='999'")
    with pytest.raises(ValueError):
        ledger.recover(path)


@pytest.mark.parametrize('before_commit', [True, False])
def test_process_crash_before_and_after_commit(path, before_commit):
    script = '''
import os,sys
from alphaforge.execution import payment_ledger as l
original=l.connect
if sys.argv[2]=='before':
 def connect(path,mode):
  c=original(path,mode)
  c.create_function('crash',0,lambda:os._exit(23))
  c.execute('CREATE TEMP TRIGGER stop BEFORE UPDATE ON ledger BEGIN SELECT crash(); END')
  return c
 l.connect=connect
l.apply(sys.argv[1],dict(account='a',epoch='e',currency='USDT',source='fixture',event_id='1',
 source_receipt='synthetic',effective_ms=1,source_ms=1,received_ms=2,kind='fee',amount='-2'))
os._exit(23)
'''
    result = subprocess.run([sys.executable, '-c', script, str(path),
                             'before' if before_commit else 'after'],
                            env={**os.environ, 'PYTHONPATH': 'src'}, timeout=10, check=False)
    assert result.returncode == 23
    assert ledger.recover(path)['payments'] == (0 if before_commit else 1)
    assert ledger.apply(path, event())['applied'] == before_commit
    assert ledger.recover(path)['cash'] == '998'


def test_exclusive_creation_and_missing_recovery(path, tmp_path):
    with pytest.raises(FileExistsError):
        ledger.create(path, account='a', epoch='e', currency='USDT', initial_cash='0')
    with pytest.raises(sqlite3.OperationalError):
        ledger.recover(tmp_path/'missing')
    assert not (tmp_path/'missing').exists()


def test_recovery_rejects_changed_event_key(path):
    ledger.apply(path, event())
    with sqlite3.connect(path) as c:
        c.execute("UPDATE payments SET event_id='other'")
    with pytest.raises(ValueError, match='identity'):
        ledger.recover(path)


def test_decimal_cash_independent_of_callers_precision(path):
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec = 3
        ledger.apply(path, event(amount='0.123456789012345678'))
        ledger.apply(path, event(event_id='2', kind='reversal',
                                 amount='-0.123456789012345678', reverses=['fixture', '1']))
        assert ledger.recover(path)['cash'] == '1000.000000000000000000'
