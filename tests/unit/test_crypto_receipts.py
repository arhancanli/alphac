import hashlib
import json
import sqlite3

import pytest

from alphaforge.costs import TransactionCostModel
from alphaforge.execution.broker import OrderBook
from alphaforge.execution.crypto_receipts import CryptoReceiptRecorder
from alphaforge.execution.paper import FakeOrderBookSource, PaperBroker, PaperPosition, PaperState

IID = 'BINANCE:PERP:BTCUSDT'


def source(bids=((99., 1.),), asks=((101., 1.),)):
    return FakeOrderBookSource({IID: OrderBook(instrument_id=IID, bids=bids, asks=asks, ts=1)})


@pytest.fixture
def recorder(tmp_path):
    ticks = iter(range(1000, 10000, 10))
    r = CryptoReceiptRecorder(tmp_path/'receipts.sqlite', host_id='fixture-host',
                             boot_id='fixture-boot', wall=lambda: next(ticks),
                             monotonic=lambda: next(ticks))
    yield r
    r.close()


def events(r):
    rows = r.connection.execute('SELECT phase,body,sha256 FROM events ORDER BY rowid').fetchall()
    for _, body, digest in rows:
        assert hashlib.sha256(body.encode()).hexdigest() == digest
    return [(phase, json.loads(body)) for phase, body, _ in rows]


@pytest.mark.parametrize('bids,asks,price,label', [
    (((99., 1.),), ((101., 1.),), 100., 'order_book_mid'),
    (((99., 1.),), (), 99., 'order_book_bid_only'),
    ((), ((101., 1.),), 101., 'order_book_ask_only'),
    ((), (), 90., 'entry_fallback_empty_book'),
])
def test_exact_book_and_rule(recorder, bids, asks, price, label):
    actual, rule, identity = recorder.observe(source(bids, asks), IID, 500, 90.)
    assert (actual, rule) == (price, label)
    start, end = events(recorder)
    assert start[1]['observation_id'] == identity
    assert start[1]['logical_cycle_ms'] == 500
    assert end[1]['elapsed_ns'] > 0
    assert end[1]['completion_wall_ns'] > start[1]['start_wall_ns']
    assert end[1]['decoded_book']['bids'] == [list(x) for x in bids]
    assert not end[1]['valuation_clearance']
    assert end[1]['quote_currency'] is None
    assert end[1]['source_timestamp_semantics'] == 'UNVERIFIED'


def test_missing_book(recorder):
    assert recorder.observe(FakeOrderBookSource(), IID, 500, 90.)[:2] == (
        90., 'entry_fallback_missing_book')
    assert events(recorder)[-1][1]['decoded_book'] is None


def test_failed_read_retains_events_without_exception_text(recorder):
    class Broken:
        def snapshot(self, *args, **kwargs):
            raise RuntimeError('secret')
    with pytest.raises(RuntimeError):
        recorder.observe(Broken(), IID, 500, 90.)
    saved = events(recorder)
    assert saved[-1][1]['status'] == 'FAILED'
    assert 'secret' not in json.dumps(saved)


def test_crash_leaves_durable_start(recorder):
    class Interrupted:
        def snapshot(self, *args, **kwargs):
            raise SystemExit()
    with pytest.raises(SystemExit):
        recorder.observe(Interrupted(), IID, 500, 90.)
    # Abrupt process kill can leave only START; Python cancellation also records END.
    assert events(recorder)[0][0] == 'START'
    assert not events(recorder)[-1][1].get('valuation_clearance', False)


def test_clock_reversal_is_retained(tmp_path):
    ticks = iter([200, 100])
    r = CryptoReceiptRecorder(tmp_path/'r', host_id='h', boot_id='b', wall=lambda: next(ticks))
    try:
        r.observe(source(), IID, 500, 90.)
        assert not events(r)[-1][1]['local_clock_ordering_valid']
    finally:
        r.close()


def test_no_overwrite(recorder, tmp_path):
    with pytest.raises(FileExistsError):
        CryptoReceiptRecorder(tmp_path/'receipts.sqlite', host_id='h', boot_id='b')
    with pytest.raises(sqlite3.IntegrityError):
        recorder._append('x', 'START', {})
        recorder._append('x', 'START', {})


def test_broker_links_cached_mark_without_refetch(recorder):
    src = source()
    state = PaperState(initial_cash=1000., cash=820., positions={
        IID: PaperPosition(instrument_id=IID, qty=2., avg_entry_price=90., opened_ts=1)})
    broker = PaperBroker({}, TransactionCostModel(), book_source=src,
                         state=state, receipt_recorder=recorder)
    account = broker.account_at(500)
    assert account.equity_quote == 1020.
    links = broker.position_mark_receipts_at(500)
    src.set_book(OrderBook(instrument_id=IID, bids=(), asks=(), ts=1))
    assert broker.position_marks_at(500)[IID] == (100., 'order_book_mid')
    assert broker.position_mark_receipts_at(500) == links
    assert len(events(recorder)) == 3
    with pytest.raises(ValueError):
        broker.position_mark_receipts_at(501)


def test_end_write_failure_cannot_return_mark(recorder, monkeypatch):
    append = recorder._append
    def fail(identity, phase, payload):
        if phase == 'END':
            raise OSError('disk')
        return append(identity, phase, payload)
    monkeypatch.setattr(recorder, '_append', fail)
    with pytest.raises(OSError):
        recorder.observe(source(), IID, 500, 90.)
    assert [phase for phase, _ in events(recorder)] == ['START']


def bound_broker(recorder):
    state = PaperState(initial_cash=1000., cash=820., positions={
        IID: PaperPosition(instrument_id=IID, qty=2., avg_entry_price=90., opened_ts=1)})
    return PaperBroker({}, TransactionCostModel(), book_source=source(), state=state,
                       receipt_recorder=recorder)


def test_recovery_reads_account_and_exact_links(recorder, tmp_path):
    from alphaforge.execution.crypto_receipts import recover_accounts
    broker = bound_broker(recorder)
    broker.account_at(500)
    path = tmp_path/'receipts.sqlite'
    before = path.read_bytes()
    report = recover_accounts(path)
    assert path.read_bytes() == before
    assert len(report['accounts']) == 1
    saved = report['accounts'][0]
    assert saved['account_snapshot_id'] == broker.account_receipt_at(500)
    assert saved['account']['equity_quote'] == 1020.
    assert saved['price_receipts'][IID]['id'] == broker.position_mark_receipts_at(500)[IID]
    assert not report['unbound_observations'] and not report['runtime_clearance']


def test_account_insert_failure_leaves_only_unbound_prices(recorder, tmp_path):
    from alphaforge.execution.crypto_receipts import recover_accounts
    recorder.connection.execute("CREATE TRIGGER fail_account BEFORE INSERT ON events "
                                "WHEN NEW.phase='ACCOUNT' BEGIN SELECT RAISE(ABORT,'fault'); END")
    broker = bound_broker(recorder)
    with pytest.raises(sqlite3.IntegrityError):
        broker.account_at(500)
    with pytest.raises(ValueError):
        broker.account_receipt_at(500)
    with pytest.raises(ValueError):
        broker.position_mark_receipts_at(500)
    recovered = recover_accounts(tmp_path/'receipts.sqlite')
    assert recovered['accounts'] == [] and len(recovered['unbound_observations']) == 1


def test_tampered_link_target_rejected(recorder, tmp_path):
    from alphaforge.execution.crypto_receipts import recover_accounts
    broker = bound_broker(recorder)
    broker.account_at(500)
    recorder.connection.execute("UPDATE events SET body='{}' WHERE phase='END'")
    recorder.connection.commit()
    with pytest.raises(ValueError, match='corrupted'):
        recover_accounts(tmp_path/'receipts.sqlite')


def test_receipt_from_wrong_cycle_rejected(recorder):
    broker = bound_broker(recorder)
    account = broker.account_at(500)
    _, _, wrong = recorder.observe(source(), IID, 501, 90.)
    with pytest.raises(ValueError, match='mismatch'):
        recorder.bind_account(account, broker.position_marks_at(500), {IID: wrong})
    assert len([p for p, _ in events(recorder) if p == 'ACCOUNT']) == 1


def test_changed_account_arithmetic_rejected(recorder):
    from dataclasses import replace
    broker = bound_broker(recorder)
    account = broker.account_at(500)
    with pytest.raises(ValueError, match='reconcile'):
        recorder.bind_account(replace(account, equity_quote=2000.),
                              broker.position_marks_at(500),
                              broker.position_mark_receipts_at(500))


def test_cash_only_account_is_durable(recorder, tmp_path):
    from alphaforge.execution.crypto_receipts import recover_accounts
    broker = PaperBroker({}, TransactionCostModel(), book_source=source(),
                         receipt_recorder=recorder)
    broker.account_at(500)
    saved = recover_accounts(tmp_path/'receipts.sqlite')['accounts'][0]
    assert saved['price_receipts'] == {}
    assert saved['account']['cash_quote'] == saved['account']['equity_quote']
    assert not saved['flows_complete']


def test_state_change_during_mark_cannot_commit(recorder):
    broker = bound_broker(recorder)
    class Changing:
        def snapshot(self, *args, **kwargs):
            broker._state.cash += 1.
            return source().snapshot(*args, **kwargs)
    broker._book_source = Changing()
    with pytest.raises(ValueError, match='state changed'):
        broker.account_at(500)
    assert 'ACCOUNT' not in [phase for phase, _ in events(recorder)]


def test_missing_recovery_does_not_create_database(tmp_path):
    from alphaforge.execution.crypto_receipts import recover_accounts
    path = tmp_path/'missing'
    with pytest.raises(sqlite3.OperationalError):
        recover_accounts(path)
    assert not path.exists()


def test_process_exit_rolls_back_uncommitted_account(recorder, tmp_path):
    import subprocess
    import sys

    from alphaforge.execution.crypto_receipts import recover_accounts
    broker = bound_broker(recorder)
    broker.account_at(500)
    path = tmp_path/'receipts.sqlite'
    script = '''
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
c.execute('BEGIN IMMEDIATE')
c.execute("INSERT INTO events SELECT 'interrupted','ACCOUNT',body,sha256 FROM events "
          "WHERE phase='ACCOUNT'")
os._exit(17)
'''
    result = subprocess.run([sys.executable, '-c', script, str(path)], timeout=5, check=False)
    assert result.returncode == 17
    report = recover_accounts(path)
    assert len(report['accounts']) == 1
    assert recorder.connection.execute(
        "SELECT COUNT(*) FROM events WHERE observation_id='interrupted'").fetchone()[0] == 0
