import hashlib
import json
import sqlite3

import pandas as pd
import pytest

from alphaforge.validation.portfolio_acquisition import read_component
from alphaforge.validation.portfolio_valuation import DAY_MS, ValuationError

CUT = int(pd.Timestamp('2026-08-11T00:00Z').value // 1000000)


@pytest.fixture
def database(tmp_path):
    path = tmp_path/'observations.sqlite'
    con = sqlite3.connect(path)
    con.executescript('''
        CREATE TABLE equity_curve(cycle_ts INTEGER,ts INTEGER,equity_quote REAL,
                                  cash_quote REAL,n_pos INTEGER);
        CREATE TABLE cycles(cycle_ts INTEGER,started_ms INTEGER,finished_ms INTEGER,status TEXT);
        CREATE TABLE positions_snapshots(cycle_ts INTEGER,instrument_id TEXT,qty REAL,
                                        mark_price REAL,mark_source TEXT,market_value_quote REAL);
    ''')
    con.execute('INSERT INTO equity_curve VALUES(?,?,?,?,?)', (CUT,CUT,110,100,1))
    con.execute('INSERT INTO cycles VALUES(?,?,?,?)', (CUT,CUT+600000,CUT+601000,'ok'))
    con.execute('INSERT INTO positions_snapshots VALUES(?,?,?,?,?,?)',
                (CUT,'BTC',1,10,'order_book_mid',10))
    con.commit()
    con.close()
    return path


def mutate(path, sql):
    con = sqlite3.connect(path)
    con.execute(sql)
    con.commit()
    con.close()


def read(path, kind='crypto_cycle', cut=CUT):
    return read_component(path, kind=kind, cut_ms=cut)


def test_read_only_consistent_packet_preserves_cycle_and_price_evidence(database):
    before = database.read_bytes()
    result = read(database)
    assert database.read_bytes() == before
    assert result['interpretation']['accounting_residual_quote'] == 0
    assert 'accounting_residual_usd' not in result['interpretation']
    assert 'NO_QUOTE_CURRENCY_BINDING_OR_USD_CONVERSION' in result['blocking_reasons']
    assert result['schema'] == 'canli.alphac-legacy-acquisition.v2'
    assert result['interpretation']['recorded_start_offset_ms'] == 600000
    assert 'CYCLE_EXECUTION_NOT_AT_DECLARED_CUT' in result['blocking_reasons']
    assert result['payload']['equity_rows'][0]['ts'] == CUT
    assert result['valuation_snapshot'] is None
    assert result['runtime_clearance'] is False
    digest = result.pop('content_sha256')
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == digest


def test_exact_label_and_arithmetic_do_not_prove_cut_price_or_authentication(database):
    mutate(database, f'UPDATE cycles SET started_ms={CUT},finished_ms={CUT}')
    result = read(database)
    assert 'CYCLE_EXECUTION_NOT_AT_DECLARED_CUT' not in result['blocking_reasons']
    assert 'NO_PER_POSITION_PRICE_ASOF_OR_RECEIPT_TIMESTAMP' in result['blocking_reasons']
    assert result['authentication_verified'] is False
    assert result['valuation_snapshot'] is None


def test_history_label_retained_and_session_interpretation_not_promoted(database):
    result = read(database, 'alpaca_legacy_history')
    meaning = result['interpretation']['history_label_interpretation']
    assert meaning['session_date'] == '2026-08-10'
    assert meaning['raw_label_ms'] == CUT
    assert meaning['source_origin_verified'] is False
    assert result['valuation_snapshot'] is None


def test_invalid_monday_label_does_not_get_floored_to_friday(database):
    mutate(database, f'UPDATE equity_curve SET ts={CUT-DAY_MS}')
    result = read(database, 'alpaca_legacy_history', CUT-DAY_MS)
    assert result['interpretation']['history_label_interpretation'] is None
    assert 'RAW_LABEL_NOT_VALID_D_PLUS_ONE_SESSION_CLOSE' in result['blocking_reasons']


@pytest.mark.parametrize('kind', ['crypto_cycle', 'alpaca_legacy_history'])
def test_missing_cut_row_does_not_fall_back_to_latest(database, kind):
    result = read(database, kind, CUT+DAY_MS)
    assert result['payload']['equity_rows'] == []
    assert result['valuation_snapshot'] is None


@pytest.mark.parametrize(('sql','reason'), [
    ('UPDATE equity_curve SET n_pos=2', 'POSITION_COUNT_MISMATCH'),
    ("UPDATE positions_snapshots SET mark_source='entry_price'",
     'INCOMPLETE_FALLBACK_OR_INCONSISTENT_POSITION_MARKS'),
    ('UPDATE positions_snapshots SET mark_price=NULL',
     'INCOMPLETE_FALLBACK_OR_INCONSISTENT_POSITION_MARKS'),
    ('UPDATE positions_snapshots SET mark_price=11',
     'INCOMPLETE_FALLBACK_OR_INCONSISTENT_POSITION_MARKS'),
    ('UPDATE equity_curve SET cash_quote=50', 'CASH_PLUS_POSITIONS_NAV_MISMATCH'),
    ("UPDATE cycles SET status='failed'", 'CYCLE_NOT_SUCCESSFULLY_COMPLETED'),
    ('UPDATE cycles SET finished_ms=NULL', 'CYCLE_NOT_SUCCESSFULLY_COMPLETED'),
])
def test_incomplete_or_inconsistent_data_remains_blocked(database, sql, reason):
    mutate(database, sql)
    assert reason in read(database)['blocking_reasons']


@pytest.mark.parametrize('table', ['equity_curve','cycles','positions_snapshots'])
def test_duplicate_rows_refused(database, table):
    mutate(database, f'INSERT INTO {table} SELECT * FROM {table}')
    with pytest.raises(ValuationError):
        read(database)


def test_absent_database_is_not_created(tmp_path):
    path = tmp_path/'absent.sqlite'
    with pytest.raises(ValuationError, match='missing'):
        read(path)
    assert not path.exists()


def test_nonfinite_stored_values_refused(database):
    mutate(database, 'UPDATE equity_curve SET cash_quote=1e999')
    with pytest.raises(ValuationError):
        read(database)


def test_schema_failure_never_creates_tables(tmp_path):
    path = tmp_path/'empty.sqlite'
    sqlite3.connect(path).close()
    before = path.read_bytes()
    with pytest.raises(sqlite3.Error):
        read(path)
    assert path.read_bytes() == before
