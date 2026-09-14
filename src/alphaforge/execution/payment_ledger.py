"""Prospective settled-cash journal; source authentication and completeness stay false."""
import hashlib
import json
import os
import re
import sqlite3
from decimal import Context, Decimal, localcontext
from pathlib import Path


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,24}(\.\d{1,18})?', value):
        raise ValueError('bounded plain decimal string required')
    return Decimal(value)


def body(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def connect(path, mode):
    return sqlite3.connect(Path(path).resolve().as_uri()+f'?mode={mode}', uri=True)


def create(path, *, account, epoch, currency, initial_cash):
    if not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (account, epoch, currency)):
        raise ValueError('explicit ledger identity required')
    number(initial_cash)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    c = connect(path, 'rw')
    try:
        c.execute('PRAGMA synchronous=FULL')
        with c:
            c.execute('CREATE TABLE ledger '
                      '(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT, cash TEXT)')
            c.execute('CREATE TABLE payments (seq INTEGER PRIMARY KEY, source TEXT, event_id TEXT, '
                      'body TEXT, sha256 TEXT, cash_after TEXT, UNIQUE(source,event_id))')
            metadata = body({'account': account, 'epoch': epoch, 'currency': currency,
                             'initial_cash': initial_cash})
            c.execute('INSERT INTO ledger VALUES (1,?,?)', (metadata, initial_cash))
    finally:
        c.close()


def _verify(c):
    metadata, recorded = c.execute('SELECT body,cash FROM ledger WHERE id=1').fetchone()
    metadata = json.loads(metadata)
    cash = number(metadata['initial_cash'])
    rows = c.execute('SELECT body,sha256,cash_after,source,event_id '
                     'FROM payments ORDER BY seq').fetchall()
    with localcontext(Context(prec=200)):
        for raw, digest, after, source, identity in rows:
            if hashlib.sha256(raw.encode()).hexdigest() != digest:
                raise ValueError('payment content hash mismatch')
            event = json.loads(raw)
            if '_evidence' in event:
                from alphaforge.execution.payment_evidence import verify_payment
                verify_payment(event, event['_evidence'])
            if (event['source'] != source or event['event_id'] != identity
                    or any(event[k] != metadata[k] for k in ('account', 'epoch', 'currency'))):
                raise ValueError('stored event identity mismatch')
            cash += number(event['amount'])
            if cash != Decimal(after):
                raise ValueError('payment cash chain mismatch')
    if cash != Decimal(recorded):
        raise ValueError('closing cash mismatch')
    return metadata, cash, len(rows)


def apply(path, event, *, evidence=None):
    """Exact replay is a no-op; conflicting identity or incomplete evidence rejects.

    References are retained declarations, not verified source objects. This API
    books settled funding, fees, transfers and explicit reversals only.
    """
    if '_evidence' in event:
        raise ValueError('use explicit evidence argument')
    if evidence is not None:
        from alphaforge.execution.payment_evidence import verify_payment
        # Detach from caller mutation before checking and committing the same content.
        event = json.loads(body({**event, '_evidence': evidence}))
        verify_payment(event, event['_evidence'])
    for key in ('account', 'epoch', 'currency', 'source', 'event_id', 'source_receipt'):
        if not isinstance(event.get(key), str) or not 0 < len(event[key]) <= 256:
            raise ValueError('missing event identity or receipt reference')
    for key in ('effective_ms', 'source_ms', 'received_ms'):
        if type(event.get(key)) is not int or event[key] < 0:
            raise ValueError('explicit timestamp required')
    amount = number(event['amount'])
    kind = event.get('kind')
    if kind not in ('funding', 'fee', 'transfer', 'reversal'):
        raise ValueError('unsupported settled event type')
    if kind == 'funding':
        for key in ('instrument', 'contract_reference', 'position_reference', 'mark_reference',
                    'settlement_schedule'):
            if not isinstance(event.get(key), str) or not event[key]:
                raise ValueError('missing funding evidence')
        with localcontext(Context(prec=200)):
            qty, price, rate = (number(event[k]) for k in ('quantity', 'mark', 'rate'))
            if price <= 0 or event.get('multiplier') != '1' or amount != -qty*price*rate:
                raise ValueError('unsupported contract or inconsistent funding')
    raw = body(event)
    c = connect(path, 'rw')
    try:
        c.execute('PRAGMA synchronous=FULL')
        with c:
            c.execute('BEGIN IMMEDIATE')
            metadata, cash, _ = _verify(c)
            if any(event[k] != metadata[k] for k in ('account', 'epoch', 'currency')):
                raise ValueError('ledger identity or currency mismatch')
            prior = c.execute('SELECT body FROM payments WHERE source=? AND event_id=?',
                              (event['source'], event['event_id'])).fetchone()
            if prior:
                if prior[0] != raw:
                    raise ValueError('conflicting event replay')
                return {'applied': False, 'cash': str(cash), 'valuation_clearance': False}
            if kind == 'reversal':
                ref = event.get('reverses')
                if not isinstance(ref, list) or len(ref) != 2:
                    raise ValueError('explicit reversal identity required')
                previous = c.execute('SELECT body FROM payments WHERE source=? AND event_id=?',
                                     tuple(ref)).fetchone()
                if (previous is None
                        or amount != number(json.loads(previous[0])['amount']).copy_negate()):
                    raise ValueError('invalid reversal amount or target')
                for prior_body, in c.execute('SELECT body FROM payments'):
                    if json.loads(prior_body).get('reverses') == ref:
                        raise ValueError('event already reversed')
            with localcontext(Context(prec=200)):
                after = str(cash+amount)
            c.execute('INSERT INTO payments(source,event_id,body,sha256,cash_after) '
                      'VALUES(?,?,?,?,?)',
                      (event['source'], event['event_id'], raw,
                       hashlib.sha256(raw.encode()).hexdigest(), after))
            c.execute('UPDATE ledger SET cash=? WHERE id=1', (after,))
        return {'applied': True, 'cash': after, 'valuation_clearance': False}
    finally:
        c.close()


def recover(path):
    c = connect(path, 'ro')
    try:
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')
        metadata, cash, count = _verify(c)
        return {'metadata': metadata, 'cash': str(cash), 'payments': count,
                'flows_complete': False, 'source_authentication_verified': False,
                'valuation_clearance': False, 'runtime_clearance': False}
    finally:
        c.close()
