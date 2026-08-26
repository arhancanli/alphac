from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/export_crypto_position_attribution.py"
SPEC = importlib.util.spec_from_file_location("export_crypto_position_attribution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _database(
    *,
    marked: bool,
    fallback: bool = False,
    market_value: float | None = None,
    unrealized_pnl: float | None = None,
) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE equity_curve (cycle_ts INTEGER PRIMARY KEY, equity_quote REAL NOT NULL, "
        "cash_quote REAL NOT NULL, n_pos INTEGER NOT NULL, ts INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE positions_snapshots (cycle_ts INTEGER NOT NULL, instrument_id TEXT NOT NULL, "
        "qty REAL NOT NULL, avg_entry_price REAL NOT NULL, opened_ts INTEGER NOT NULL, "
        "mark_price REAL, mark_source TEXT, market_value_quote REAL, "
        "unrealized_pnl_quote REAL, PRIMARY KEY (cycle_ts, instrument_id)) WITHOUT ROWID"
    )
    connection.execute("INSERT INTO equity_curve VALUES (1000, 1100, 900, 1, 1000)")
    mark = 100.0 if marked else None
    source = "entry_fallback_missing_book" if fallback else "order_book_mid"
    connection.execute(
        "INSERT INTO positions_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1000,
            "BINANCE:PERP:BTCUSDT",
            2.0,
            80.0,
            500,
            mark,
            source,
            (200.0 if market_value is None else market_value) if marked else None,
            (40.0 if unrealized_pnl is None else unrealized_pnl) if marked else None,
        ),
    )
    return connection


def test_complete_cycle_reconciles_to_account_equity() -> None:
    result = MODULE.evaluate(_database(marked=True))

    assert result["status"] == "COMPLETE"
    assert result["passes"] is True
    assert result["latest_cycle"]["reconciliation_residual_quote"] == 0.0
    assert result["latest_cycle"]["position_arithmetic_passes"] is True


def test_unmarked_legacy_cycle_fails_closed_without_backfill() -> None:
    result = MODULE.evaluate(_database(marked=False))

    assert result["status"] == "WAITING_FOR_FIRST_COMPLETE_MARKED_CYCLE"
    assert result["passes"] is False
    assert result["positions"][0]["mark_price"] is None


def test_fallback_mark_is_visible_and_not_complete() -> None:
    result = MODULE.evaluate(_database(marked=True, fallback=True))

    assert result["status"] == "FALLBACK_MARKS_PRESENT"
    assert result["passes"] is False
    assert result["latest_cycle"]["fallback_mark_count"] == 1


def test_stored_position_arithmetic_is_independently_recomputed() -> None:
    result = MODULE.evaluate(_database(marked=True, market_value=200.0, unrealized_pnl=41.0))

    assert result["status"] == "POSITION_ARITHMETIC_FAILED"
    assert result["passes"] is False
    assert result["latest_cycle"]["position_arithmetic_passes"] is False
    assert result["latest_cycle"]["max_abs_unrealized_pnl_residual_quote"] == 1.0


def test_flat_cycle_cannot_vacuously_certify_position_attribution() -> None:
    connection = _database(marked=True)
    connection.execute("DELETE FROM positions_snapshots")
    connection.execute("UPDATE equity_curve SET equity_quote = cash_quote, n_pos = 0")

    result = MODULE.evaluate(connection)

    assert result["status"] == "NO_OPEN_POSITIONS_TO_VERIFY"
    assert result["passes"] is False


def test_pre_migration_schema_fails_closed() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE positions_snapshots (cycle_ts INTEGER, instrument_id TEXT, qty REAL, "
        "avg_entry_price REAL, opened_ts INTEGER)"
    )

    result = MODULE.evaluate(connection)

    assert result["status"] == "SCHEMA_NOT_YET_MIGRATED"
    assert set(result["missing_columns"]) == MODULE.REQUIRED_COLUMNS
