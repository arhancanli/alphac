#!/usr/bin/env python3
"""Export fail-closed instrument attribution for the latest crypto paper cycle."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var/trading_crypto_perp.sqlite"
OUTPUT_PATH = ROOT / "artifacts/engineering/crypto_position_attribution.json"
SCHEMA = "canli.alphac-crypto-position-attribution.v1"
REQUIRED_COLUMNS = {
    "mark_price",
    "mark_source",
    "market_value_quote",
    "unrealized_pnl_quote",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evaluate(connection: sqlite3.Connection) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(positions_snapshots)").fetchall()
    }
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        return {
            "status": "SCHEMA_NOT_YET_MIGRATED",
            "passes": False,
            "missing_columns": missing,
            "latest_cycle": None,
            "positions": [],
        }

    equity_row = connection.execute(
        "SELECT cycle_ts, equity_quote, cash_quote, n_pos, ts FROM equity_curve "
        "ORDER BY cycle_ts DESC LIMIT 1"
    ).fetchone()
    if equity_row is None:
        return {
            "status": "NO_EQUITY_CYCLE",
            "passes": False,
            "missing_columns": [],
            "latest_cycle": None,
            "positions": [],
        }

    cycle_ts = int(equity_row["cycle_ts"])
    rows = connection.execute(
        "SELECT cycle_ts, instrument_id, qty, avg_entry_price, opened_ts, mark_price, "
        "mark_source, market_value_quote, unrealized_pnl_quote "
        "FROM positions_snapshots WHERE cycle_ts = ? ORDER BY instrument_id",
        (cycle_ts,),
    ).fetchall()
    positions = [dict(row) for row in rows]
    expected_n = int(equity_row["n_pos"])
    row_count_matches = len(positions) == expected_n
    complete_marks = [
        row
        for row in positions
        if row["mark_price"] is not None
        and row["mark_source"] is not None
        and row["market_value_quote"] is not None
        and row["unrealized_pnl_quote"] is not None
    ]
    fallback_count = sum(row["mark_source"] != "order_book_mid" for row in complete_marks)
    market_value_residuals: list[float] = []
    unrealized_pnl_residuals: list[float] = []
    position_arithmetic_checks: list[bool] = []
    for row in complete_marks:
        qty = float(row["qty"])
        avg_entry = float(row["avg_entry_price"])
        mark = float(row["mark_price"])
        market_value = float(row["market_value_quote"])
        unrealized_pnl = float(row["unrealized_pnl_quote"])
        expected_market_value = qty * mark
        expected_unrealized_pnl = qty * (mark - avg_entry)
        market_value_residual = market_value - expected_market_value
        unrealized_pnl_residual = unrealized_pnl - expected_unrealized_pnl
        market_value_tolerance = max(1e-8, abs(expected_market_value) * 1e-10)
        unrealized_pnl_tolerance = max(1e-8, abs(expected_unrealized_pnl) * 1e-10)
        finite = all(
            math.isfinite(value) for value in (qty, avg_entry, mark, market_value, unrealized_pnl)
        )
        market_value_residuals.append(market_value_residual)
        unrealized_pnl_residuals.append(unrealized_pnl_residual)
        position_arithmetic_checks.append(
            finite
            and mark > 0.0
            and avg_entry > 0.0
            and abs(market_value_residual) <= market_value_tolerance
            and abs(unrealized_pnl_residual) <= unrealized_pnl_tolerance
        )
    position_arithmetic_passes = len(complete_marks) == expected_n and all(
        position_arithmetic_checks
    )
    equity = float(equity_row["equity_quote"])
    cash = float(equity_row["cash_quote"])
    reconstructed = cash + sum(
        float(row["market_value_quote"])
        for row in complete_marks
        if row["market_value_quote"] is not None
    )
    residual = equity - reconstructed
    tolerance = max(0.01, abs(equity) * 1e-9)
    reconciliation_passes = (
        row_count_matches and len(complete_marks) == expected_n and abs(residual) <= tolerance
    )

    if expected_n == 0:
        status = "NO_OPEN_POSITIONS_TO_VERIFY"
    elif not row_count_matches:
        status = "POSITION_COUNT_MISMATCH"
    elif len(complete_marks) != expected_n:
        status = "WAITING_FOR_FIRST_COMPLETE_MARKED_CYCLE"
    elif fallback_count:
        status = "FALLBACK_MARKS_PRESENT"
    elif not position_arithmetic_passes:
        status = "POSITION_ARITHMETIC_FAILED"
    elif not reconciliation_passes:
        status = "EQUITY_RECONCILIATION_FAILED"
    else:
        status = "COMPLETE"

    return {
        "status": status,
        "passes": status == "COMPLETE",
        "missing_columns": [],
        "latest_cycle": {
            "cycle_ts": cycle_ts,
            "account_ts": int(equity_row["ts"]),
            "equity_quote": equity,
            "cash_quote": cash,
            "expected_position_count": expected_n,
            "stored_position_count": len(positions),
            "complete_mark_count": len(complete_marks),
            "order_book_mark_count": len(complete_marks) - fallback_count,
            "fallback_mark_count": fallback_count,
            "position_arithmetic_passes": position_arithmetic_passes,
            "max_abs_market_value_residual_quote": max(
                (abs(value) for value in market_value_residuals), default=None
            ),
            "max_abs_unrealized_pnl_residual_quote": max(
                (abs(value) for value in unrealized_pnl_residuals), default=None
            ),
            "reconstructed_equity_quote": reconstructed,
            "reconciliation_residual_quote": residual,
            "reconciliation_tolerance_quote": tolerance,
            "reconciliation_passes": reconciliation_passes,
        },
        "positions": positions,
    }


def build_document() -> dict[str, Any]:
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as connection:
        result = evaluate(connection)
    query_payload = {
        "latest_cycle": result["latest_cycle"],
        "positions": result["positions"],
    }
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "claim_boundary": (
            "Latest-cycle arithmetic attribution for the locally simulated crypto paper account. "
            "It is not Alpaca attestation, a Sharpe estimate, a return trial, or permission to "
            "change the strategy. Historical rows without marks remain explicitly unavailable."
        ),
        "source_binding": {
            "path": "var/trading_crypto_perp.sqlite",
            "query_payload_sha256": _sha256(_canonical(query_payload)),
            "binding_scope": "latest equity row and same-cycle position snapshot rows",
        },
        "historical_boundary": (
            "No historical mark backfill. Completeness begins only with a cycle genuinely "
            "persisted by the mark-aware runtime."
        ),
        **result,
    }
    document["content_hash"] = f"sha256:{_sha256(_canonical(document))}"
    return document


def main() -> None:
    document = build_document()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
