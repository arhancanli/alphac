"""Opt-in durable decoded-book receipts; never confer valuation clearance."""
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path


def classify_mark(book, fallback):
    """Preserve legacy prices while making one-sided and fallback provenance explicit."""
    if book is None:
        return fallback, 'entry_fallback_missing_book'
    if book.bids and book.asks:
        return 0.5 * (book.bids[0][0] + book.asks[0][0]), 'order_book_mid'
    if book.bids:
        return book.bids[0][0], 'order_book_bid_only'
    if book.asks:
        return book.asks[0][0], 'order_book_ask_only'
    return fallback, 'entry_fallback_empty_book'


def _body(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class CryptoReceiptRecorder:
    """Separate append-only start/end events survive interrupted observations.

    Caller supplies host/boot identities; these are declarations, not verified
    attestations. Decoded legacy float books have no authenticated source time.
    Use a new private database per recording session; reopening cannot erase it.
    """

    def __init__(self, path: Path, *, host_id: str, boot_id: str,
                 wall=time.time_ns, monotonic=time.monotonic_ns):
        if not host_id or not boot_id:
            raise ValueError('host and boot identity required')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        self.connection = sqlite3.connect(path)
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('CREATE TABLE events '
                                '(observation_id TEXT, phase TEXT, body TEXT, sha256 TEXT, '
                                'PRIMARY KEY(observation_id,phase))')
        self.connection.commit()
        self.wall, self.monotonic = wall, monotonic
        self.context = {'host_id': host_id, 'boot_id': boot_id, 'pid': os.getpid(),
                        'session_id': str(uuid.uuid4())}

    def close(self):
        self.connection.close()

    def bind_account(self, account, marks, receipts):
        """Commit account and complete price links in one immutable ACCOUNT event."""
        identity = str(uuid.uuid4())
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            links = {iid: {'id': rid, 'end_sha256': _read_event(
                self.connection, rid, 'END')[1]} for iid, rid in receipts.items()}
            payload = json.loads(_body({
                'schema': 'canli.crypto-account-receipt.v1', **self.context,
                'account_snapshot_id': identity, 'account': asdict(account),
                'marks': marks, 'price_receipts': links,
                'account_identity_verified': False, 'quote_currency': None,
                'flows_complete': False, 'valuation_clearance': False}))
            _validate_account(self.connection, payload)
            body = _body(payload)
            self.connection.execute('INSERT INTO events VALUES (?,?,?,?)',
                                    (identity, 'ACCOUNT', body,
                                     hashlib.sha256(body.encode()).hexdigest()))
        return identity

    def _append(self, identity, phase, payload):
        body = _body(payload)
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.connection:
            self.connection.execute('INSERT INTO events VALUES (?,?,?,?)',
                                    (identity, phase, body, digest))
        return digest

    def observe(self, source, instrument_id, logical_cycle_ms, fallback):
        identity = str(uuid.uuid4())
        start = {'schema': 'canli.crypto-mark-receipt.v1', **self.context,
                 'observation_id': identity, 'instrument_id': instrument_id,
                 'logical_cycle_ms': logical_cycle_ms,
                 'start_wall_ns': self.wall(), 'start_monotonic_ns': self.monotonic()}
        start_hash = self._append(identity, 'START', start)
        end = {'start_sha256': start_hash, 'valuation_clearance': False,
               'source_timestamp_semantics': 'UNVERIFIED', 'quote_currency': None,
               'contract_binding': None, 'account_binding': None, 'raw_wire_payload': None}
        try:
            try:
                book = source.snapshot(instrument_id, ts=logical_cycle_ms)
            except KeyError:
                book = None
            if book is not None and book.instrument_id != instrument_id:
                raise ValueError('instrument mismatch')
            if book is not None and len(book.bids) + len(book.asks) > 10000:
                raise ValueError('decoded book exceeds receipt budget')
            end['decoded_book'] = None if book is None else {
                'instrument_id': book.instrument_id, 'reported_ts': book.ts,
                'bids': book.bids, 'asks': book.asks}
            price, rule = classify_mark(book, fallback)
            if not math.isfinite(price) or price <= 0:
                raise ValueError('invalid mark')
            end.update(mark_price=price, mark_rule=rule, status='OBSERVED')
        except BaseException:
            end['status'] = 'FAILED'
            raise
        finally:
            end.update(completion_monotonic_ns=self.monotonic(), completion_wall_ns=self.wall())
            end['elapsed_ns'] = end['completion_monotonic_ns'] - start['start_monotonic_ns']
            end['local_clock_ordering_valid'] = (
                end['elapsed_ns'] >= 0 and end['completion_wall_ns'] >= start['start_wall_ns'])
            # If persistence fails, do not return a mark claiming a durable receipt.
            self._append(identity, 'END', end)
        return price, rule, identity


def _read_event(connection, identity, phase):
    row = connection.execute('SELECT body,sha256 FROM events WHERE observation_id=? AND phase=?',
                             (identity, phase)).fetchone()
    if row is None or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
        raise ValueError('missing or corrupted receipt')
    return json.loads(row[0]), row[1]


def _validate_account(connection, payload):
    account = payload['account']
    links = payload['price_receipts']
    positions = account['positions']
    if len(positions) > 10000 or len({p['instrument_id'] for p in positions}) != len(positions):
        raise ValueError('duplicate or excessive positions')
    if set(links) != {p['instrument_id'] for p in positions}:
        raise ValueError('incomplete position receipt bindings')
    if len({r['id'] for r in links.values()}) != len(links):
        raise ValueError('reused position receipt')
    equity = account['cash_quote']
    for position in positions:
        iid = position['instrument_id']
        link = links[iid]
        start, start_hash = _read_event(connection, link['id'], 'START')
        end, end_hash = _read_event(connection, link['id'], 'END')
        if (start['instrument_id'] != iid or start['logical_cycle_ms'] != account['ts']
                or start['session_id'] != payload['session_id']
                or start['host_id'] != payload['host_id'] or start['boot_id'] != payload['boot_id']
                or end['status'] != 'OBSERVED' or end['start_sha256'] != start_hash
                or end_hash != link['end_sha256']):
            raise ValueError('receipt identity, cycle, context or completion mismatch')
        if [end['mark_price'], end['mark_rule']] != payload['marks'][iid]:
            raise ValueError('account mark differs from recorded price')
        if not math.isfinite(position['qty']):
            raise ValueError('nonfinite position')
        equity += position['qty'] * end['mark_price']
    if not math.isfinite(equity) or equity != account['equity_quote']:
        raise ValueError('recorded account arithmetic does not reconcile')


def recover_accounts(path: Path):
    """Read-only consistency recovery; never resumes trading or repairs evidence."""
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        accounts = []
        linked = set()
        for identity, in connection.execute(
                "SELECT observation_id FROM events WHERE phase='ACCOUNT' ORDER BY rowid"):
            payload, _ = _read_event(connection, identity, 'ACCOUNT')
            _validate_account(connection, payload)
            accounts.append(payload)
            linked.update(r['id'] for r in payload['price_receipts'].values())
        started = {r[0] for r in connection.execute(
            "SELECT observation_id FROM events WHERE phase='START'")}
        return {'accounts': accounts, 'unbound_observations': sorted(started-linked),
                'valuation_clearance': False, 'runtime_clearance': False}
    finally:
        connection.close()
