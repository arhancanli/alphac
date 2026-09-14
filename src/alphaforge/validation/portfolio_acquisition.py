"""Read-only legacy-source adapters. Partial evidence never becomes a cut NAV.

Stored REAL values remain source values. Reconciliation here is diagnostic;
neither a cycle label nor the audit's wall clock is a source-price timestamp.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from alphaforge.validation.portfolio_valuation import DAY_MS, ValuationError, timestamp


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def read_component(path: Path, *, kind: str, cut_ms: int) -> dict:
    timestamp(cut_ms)
    if cut_ms % DAY_MS:
        raise ValuationError('Midnight UTC cut required')
    if kind not in {'alpaca_legacy_history', 'crypto_cycle'}:
        raise ValuationError('Unknown source kind')
    if not path.is_file():
        raise ValuationError('Source database missing; not created by this reader')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        if kind == 'alpaca_legacy_history':
            rows = [dict(r) for r in connection.execute(
                'SELECT ts,equity_quote FROM equity_curve WHERE ts=? LIMIT 2', (cut_ms,))]
            if len(rows) > 1:
                raise ValuationError('Ambiguous duplicate NAV rows')
            payload = {'equity_rows': rows}
            gaps = ['NO_PER_ROW_ACCOUNT_BINDING', 'NO_ORIGINAL_RECEIPT_TIMESTAMP',
                    'NO_CUT_CASH_HOLDINGS_ACCRUALS_OR_FLOW_INVENTORY',
                    'LEGACY_FLOAT_NAV_NOT_EXACT_DECIMAL_ACCOUNTING',
                    'MIXED_HISTORY_AND_CURRENT_ROWS_WITHOUT_ROW_ORIGIN']
            interpretation = None
            if not rows:
                gaps.append('NO_ROW_AT_REQUESTED_LABEL')
            else:
                if not _number(rows[0]['equity_quote']):
                    raise ValuationError('Invalid stored NAV')
                # Interpretation of the declared D+1 history convention only.
                # Do not floor a missing/closed prior date to an earlier session.
                date = pd.Timestamp(cut_ms - DAY_MS, unit='ms')
                calendar = xcals.get_calendar('XNYS', start='2000-01-01', end='2030-12-31')
                if calendar.is_session(date):
                    interpretation = {
                        'session_date': str(date.date()),
                        'official_close_ms': int(calendar.session_close(date).value // 1000000),
                        'raw_label_ms': cut_ms, 'source_origin_verified': False,
                    }
                    gaps.append('PRIOR_SESSION_NAV_NOT_CURRENT_CUT_NAV')
                else:
                    gaps.append('RAW_LABEL_NOT_VALID_D_PLUS_ONE_SESSION_CLOSE')
            details = {'history_label_interpretation': interpretation}
        else:
            equity = [dict(r) for r in connection.execute(
                'SELECT cycle_ts,ts,equity_quote,cash_quote,n_pos FROM equity_curve '
                'WHERE cycle_ts=? LIMIT 2', (cut_ms,))]
            cycles = [dict(r) for r in connection.execute(
                'SELECT cycle_ts,started_ms,finished_ms,status FROM cycles '
                'WHERE cycle_ts=? LIMIT 2', (cut_ms,))]
            positions = [dict(r) for r in connection.execute(
                'SELECT instrument_id,qty,mark_price,mark_source,market_value_quote '
                'FROM positions_snapshots WHERE cycle_ts=? ORDER BY instrument_id LIMIT 10001',
                (cut_ms,))]
            if len(equity) > 1 or len(cycles) > 1 or len(positions) > 10000:
                raise ValuationError('Ambiguous rows or position budget exceeded')
            payload = {'equity_rows': equity, 'cycle_rows': cycles, 'positions': positions}
            gaps = ['NO_PER_POSITION_PRICE_ASOF_OR_RECEIPT_TIMESTAMP',
                    'NO_CUT_CASHFLOW_RECEIVABLE_LIABILITY_COVERAGE',
                    'NO_CRYPTO_ACCOUNT_OR_PARTITION_BINDING',
                    'NO_QUOTE_CURRENCY_BINDING_OR_USD_CONVERSION',
                    'LEGACY_FLOAT_VALUES_NOT_EXACT_DECIMAL_ACCOUNTING']
            details = {'recorded_start_offset_ms': None, 'accounting_residual_quote': None,
                       'position_arithmetic_matches': False}
            if not equity or not cycles:
                gaps.append('MISSING_EQUITY_OR_CYCLE_AT_CUT_LABEL')
            else:
                row, cycle = equity[0], cycles[0]
                for value in [row['equity_quote'], row['cash_quote']]:
                    if not _number(value):
                        raise ValuationError('Invalid stored equity/cash')
                timestamp(cycle['started_ms'])
                timestamp(row['ts'])
                if row['ts'] != cut_ms:
                    gaps.append('EQUITY_TIMESTAMP_DIFFERS_FROM_CYCLE_LABEL')
                if cycle['finished_ms'] is None or cycle['status'] != 'ok':
                    gaps.append('CYCLE_NOT_SUCCESSFULLY_COMPLETED')
                elif timestamp(cycle['finished_ms']) < cycle['started_ms']:
                    raise ValuationError('Invalid stored cycle chronology')
                offset = cycle['started_ms'] - cut_ms
                details['recorded_start_offset_ms'] = offset
                if offset != 0:
                    gaps.append('CYCLE_EXECUTION_NOT_AT_DECLARED_CUT')
                if type(row['n_pos']) is not int or row['n_pos'] < 0:
                    raise ValuationError('Invalid position count')
                if len(positions) != row['n_pos']:
                    gaps.append('POSITION_COUNT_MISMATCH')
                if len({p['instrument_id'] for p in positions}) != len(positions):
                    raise ValuationError('Duplicate stored position')
                arithmetic = True
                for p in positions:
                    if any(p[k] is not None and not _number(p[k])
                           for k in ['qty', 'mark_price', 'market_value_quote']):
                        raise ValuationError('Nonfinite stored position field')
                    if not all(_number(p[k]) for k in ['qty', 'mark_price', 'market_value_quote']):
                        arithmetic = False
                        continue
                    if p['mark_price'] <= 0 or p['mark_source'] != 'order_book_mid':
                        arithmetic = False
                    expected = p['qty'] * p['mark_price']
                    if not math.isfinite(expected) or (
                        abs(expected - p['market_value_quote']) > max(1e-8, abs(expected)*1e-10)
                    ):
                        arithmetic = False
                details['position_arithmetic_matches'] = arithmetic
                if not arithmetic:
                    gaps.append('INCOMPLETE_FALLBACK_OR_INCONSISTENT_POSITION_MARKS')
                if all(_number(p['market_value_quote']) for p in positions):
                    residual = row['equity_quote'] - row['cash_quote'] - sum(
                        p['market_value_quote'] for p in positions)
                    details['accounting_residual_quote'] = (
                        residual if math.isfinite(residual) else None)
                    if not math.isfinite(residual) or abs(residual) > .01:
                        gaps.append('CASH_PLUS_POSITIONS_NAV_MISMATCH')
        # Persist raw source fields with the interpretation; never emit a fabricated
        # Snapshot using zero liabilities, guessed timestamps or the reader's clock.
        packet = {'schema': 'canli.alphac-legacy-acquisition.v2', 'source_kind': kind,
                  'database': str(path.resolve()), 'requested_cut_ms': cut_ms,
                  'payload': payload, 'interpretation': details,
                  'blocking_reasons': sorted(set(gaps)),
                  'status': 'PARTIAL_EVIDENCE_NOT_CUT_VALUATION', 'valuation_snapshot': None,
                  'authentication_verified': False, 'runtime_clearance': False}
        body = json.dumps(packet, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        packet['content_sha256'] = hashlib.sha256(body).hexdigest()
        return packet
    finally:
        connection.close()
