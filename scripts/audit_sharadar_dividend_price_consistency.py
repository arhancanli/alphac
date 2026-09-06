#!/usr/bin/env python3
"""Audit every Sharadar cash dividend against the observable pre-ex raw close.

This is a data-quality audit only. It never opens signals, positions, returns, or
trial outcomes. A plain cash-dividend row above the complete pre-ex share value
fails closed because the lake schema cannot express the alternative lifecycle
semantics or vendor-unit correction that would be required to execute it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
LAKE: Final[Path] = REPO / "data" / "lake_sharadar"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_dividend_price_consistency.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
MAX_PRE_CLOSE_MULTIPLE: Final[float] = 1.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def audit_frames(actions_glob: str, bars_glob: str) -> pd.DataFrame:
    """Return one row per dividend, paired with the last strictly pre-ex raw close."""
    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            WITH actions AS (
                SELECT instrument_id, ex_date, available_at, cash_amount
                FROM read_parquet(?, hive_partitioning = true)
                WHERE action_type = 'dividend'
                ORDER BY instrument_id, ex_date
            ),
            bars AS (
                SELECT instrument_id, ts_open, close
                FROM read_parquet(?, hive_partitioning = true)
                ORDER BY instrument_id, ts_open
            )
            SELECT
                actions.instrument_id,
                actions.ex_date,
                actions.available_at,
                actions.cash_amount,
                bars.ts_open AS pre_close_ts,
                bars.close AS pre_close,
                actions.cash_amount / bars.close AS pre_close_multiple
            FROM actions ASOF LEFT JOIN bars
                ON actions.instrument_id = bars.instrument_id
                AND actions.ex_date > bars.ts_open
            ORDER BY pre_close_multiple DESC NULLS LAST, instrument_id, ex_date
            """,
            [actions_glob, bars_glob],
        ).fetchdf()
    finally:
        connection.close()


def _row(record: Any) -> dict[str, Any]:
    def timestamp(value: Any) -> str | None:
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()

    def number(value: Any) -> float | None:
        return None if pd.isna(value) else float(value)

    return {
        "instrument_id": str(record.instrument_id),
        "ex_date": timestamp(record.ex_date),
        "available_at": timestamp(record.available_at),
        "cash_amount": number(record.cash_amount),
        "pre_close_ts": timestamp(record.pre_close_ts),
        "pre_close": number(record.pre_close),
        "pre_close_multiple": number(record.pre_close_multiple),
    }


def build_audit(*, lake: Path = LAKE) -> dict[str, Any]:
    actions_glob = str(lake / "corporate_actions" / "**" / "*.parquet")
    bars_glob = str(lake / "ohlcv_1d" / "**" / "*.parquet")
    frame = audit_frames(actions_glob, bars_glob)
    multiple = frame["pre_close_multiple"]
    offenders = frame[multiple > MAX_PRE_CLOSE_MULTIPLE]
    over_half = frame[multiple > 0.5]
    missing = frame[frame["pre_close"].isna()]
    offender_counts = (
        offenders.groupby("instrument_id", sort=False)
        .size()
        .sort_values(ascending=False)
        .to_dict()
    )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-dividend-price-consistency.v1",
        "evidence_date": "2026-08-23",
        "author": "Arhan Canli",
        "decision": (
            "DIVIDEND_PRICE_CONSISTENCY_FAILED"
            if len(offenders)
            else "DIVIDEND_PRICE_CONSISTENCY_PASSED"
        ),
        "threshold": {
            "maximum_plain_cash_dividend_to_pre_ex_raw_close": MAX_PRE_CLOSE_MULTIPLE,
            "comparison": "cash_amount / last raw close with ts_open < ex_date",
            "failure_policy": (
                "Fail closed. Do not execute, impute, scale, or silently drop the row without "
                "independently bound lifecycle and vendor-unit semantics."
            ),
        },
        "summary": {
            "dividend_rows": len(frame),
            "rows_without_pre_ex_close": len(missing),
            "rows_above_half_pre_ex_close": len(over_half),
            "rows_above_full_pre_ex_close": len(offenders),
            "affected_instruments": int(offenders["instrument_id"].nunique()),
            "maximum_pre_close_multiple": (
                None if frame.empty else float(frame["pre_close_multiple"].max())
            ),
        },
        "affected_instrument_counts": {
            str(key): int(value) for key, value in offender_counts.items()
        },
        "offending_rows": [_row(record) for record in offenders.itertuples(index=False)],
        "missing_pre_close_rows": [_row(record) for record in missing.itertuples(index=False)],
        "lineage": {
            "lake": str(lake.relative_to(REPO)),
            "raw_actions_archive": "data/sharadar_raw/ACTIONS.zip",
            "raw_actions_archive_sha256": _sha256(REPO / "data/sharadar_raw/ACTIONS.zip"),
            "loader": "scripts/sharadar_load.py",
            "loader_sha256": _sha256(REPO / "scripts/sharadar_load.py"),
            "engine": "src/alphaforge/backtest/engine.py",
            "engine_sha256": _sha256(REPO / "src/alphaforge/backtest/engine.py"),
            "audit_command": "uv run python scripts/audit_sharadar_dividend_price_consistency.py",
        },
        "claim_boundary": (
            "This is a source-data and executable-semantics audit. It opens no signals, "
            "positions, returns, Sharpe ratios, or strategy outcomes and makes no investment "
            "performance claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build_audit()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "content_hash": payload["content_hash"]}))
    return 0 if payload["decision"] == "DIVIDEND_PRICE_CONSISTENCY_PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
