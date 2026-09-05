#!/usr/bin/env python3
"""Audit the versioned Sharadar corporate-action lake before any replay."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np

REPO: Final[Path] = Path(__file__).resolve().parents[1]
BUILD: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corporate_action_corrected_lake.json"
)
OUTPUT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corrected_corporate_action_validation.json"
)
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
SPLIT_TOLERANCE: Final[float] = 0.30


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _dividend_audit(lake: Path) -> dict[str, Any]:
    script = REPO / "scripts" / "audit_sharadar_dividend_price_consistency.py"
    spec = importlib.util.spec_from_file_location("corrected_lake_dividend_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load dividend audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_audit(lake=lake)


def _split_frame(lake: Path):
    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            WITH split_groups AS (
                SELECT
                    instrument_id,
                    ex_date,
                    product(ratio) AS ratio,
                    count(*) AS source_rows
                FROM read_parquet(?, hive_partitioning = true)
                WHERE action_type = 'split' AND ratio > 0
                GROUP BY instrument_id, ex_date
            ),
            bars AS (
                SELECT instrument_id, ts_open, open, close
                FROM read_parquet(?, hive_partitioning = true)
            )
            SELECT
                split_groups.*,
                pre.ts_open AS pre_close_ts,
                pre.close AS pre_close,
                post.ts_open AS post_open_ts,
                post.open AS post_open
            FROM split_groups
            ASOF LEFT JOIN bars AS pre
                ON split_groups.instrument_id = pre.instrument_id
                AND split_groups.ex_date > pre.ts_open
            ASOF LEFT JOIN bars AS post
                ON split_groups.instrument_id = post.instrument_id
                AND split_groups.ex_date <= post.ts_open
            ORDER BY split_groups.instrument_id, split_groups.ex_date
            """,
            [
                str(lake / "corporate_actions" / "**" / "*.parquet"),
                str(lake / "ohlcv_1d" / "**" / "*.parquet"),
            ],
        ).fetchdf()
    finally:
        connection.close()


def _timestamp(value: Any) -> str | None:
    if value is None or str(value) == "NaT":
        return None
    return str(value)


def _split_record(row: Any) -> dict[str, Any]:
    return {
        "instrument_id": str(row.instrument_id),
        "ex_date": _timestamp(row.ex_date),
        "source_rows": int(row.source_rows),
        "stored_ratio": float(row.ratio),
        "pre_close_ts": _timestamp(row.pre_close_ts),
        "pre_close": None if np.isnan(row.pre_close) else float(row.pre_close),
        "post_open_ts": _timestamp(row.post_open_ts),
        "post_open": None if np.isnan(row.post_open) else float(row.post_open),
        "stored_log_error": None if np.isnan(row.stored_log_error) else float(row.stored_log_error),
        "reciprocal_log_error": (
            None if np.isnan(row.reciprocal_log_error) else float(row.reciprocal_log_error)
        ),
        "classification": str(row.classification),
    }


def build_audit() -> dict[str, Any]:
    build = json.loads(BUILD.read_text(encoding="utf-8"))
    if build.get("decision") != "VERSIONED_CORPORATE_ACTION_LAKE_BUILT_VALIDATION_PENDING":
        raise ValueError("corrected-lake build state changed")
    lake = REPO / build["corrected_lake"]
    dividend = _dividend_audit(lake)
    splits = _split_frame(lake)
    valid = (
        splits["pre_close"].notna()
        & splits["post_open"].notna()
        & (splits["pre_close"] > 0.0)
        & (splits["post_open"] > 0.0)
    )
    splits["stored_log_error"] = np.nan
    splits["reciprocal_log_error"] = np.nan
    move = splits.loc[valid, "post_open"] / splits.loc[valid, "pre_close"]
    splits.loc[valid, "stored_log_error"] = np.abs(
        np.log(move * splits.loc[valid, "ratio"])
    )
    splits.loc[valid, "reciprocal_log_error"] = np.abs(
        np.log(move / splits.loc[valid, "ratio"])
    )
    consistent = valid & (splits["stored_log_error"] <= SPLIT_TOLERANCE)
    reciprocal = (
        valid
        & ~consistent
        & (splits["reciprocal_log_error"] <= SPLIT_TOLERANCE)
    )
    unexplained = valid & ~consistent & ~reciprocal
    missing = ~valid
    splits["classification"] = "CONSISTENT"
    splits.loc[reciprocal, "classification"] = "RECIPROCAL_RATIO_WOULD_VERIFY"
    splits.loc[unexplained, "classification"] = "UNEXPLAINED_PRICE_BOUNDARY"
    splits.loc[missing, "classification"] = "MISSING_TWO_SIDED_PRICE_BOUNDARY"
    failures = splits[~consistent]

    dividend_pass = dividend["decision"] == "DIVIDEND_PRICE_CONSISTENCY_PASSED"
    split_pass = len(failures) == 0
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-corrected-corporate-action-validation.v1",
        "evidence_date": "2026-08-23",
        "author": "Arhan Canli",
        "decision": (
            "CORPORATE_ACTION_VALIDATION_PASSED_REPLAY_STILL_SEPARATELY_GATED"
            if dividend_pass and split_pass
            else "CORPORATE_ACTION_VALIDATION_FAILED_SPLIT_BOUNDARIES"
        ),
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "lake": str(lake.relative_to(REPO)),
        "dividend_gate": {
            "passed": dividend_pass,
            "decision": dividend["decision"],
            "summary": dividend["summary"],
        },
        "split_gate": {
            "passed": split_pass,
            "tolerance_absolute_log_error": SPLIT_TOLERANCE,
            "summary": {
                "split_groups": len(splits),
                "consistent": int(consistent.sum()),
                "reciprocal_ratio_would_verify": int(reciprocal.sum()),
                "unexplained_price_boundary": int(unexplained.sum()),
                "missing_two_sided_price_boundary": int(missing.sum()),
                "failed_or_unverifiable": len(failures),
                "affected_instruments": int(failures["instrument_id"].nunique()),
            },
            "failures": [_split_record(row) for row in failures.itertuples(index=False)],
        },
        "lineage": {
            "build_path": str(BUILD.relative_to(REPO)),
            "build_sha256": _sha256(BUILD),
            "build_content_hash": build["content_hash"],
            "corrected_corporate_actions_root": build["lineage"][
                "corrected_corporate_actions_root"
            ],
            "engine_split_tolerance_source": "src/alphaforge/backtest/engine.py",
            "engine_split_tolerance": SPLIT_TOLERANCE,
        },
        "required_next_action": (
            "Resolve reciprocal and unexplained split groups with independent source evidence. "
            "Prove missing-boundary events cannot become exposed or quarantine their instruments. "
            "Do not replay on this lake while the split gate fails."
        ),
        "claim_boundary": (
            "The dividend normalization passes globally, but the lake fails the independent split "
            "gate. This artifact opens no returns, spends no hypothesis, and explicitly forbids "
            "using the lake for a replay or performance claim."
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
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0 if payload["decision"].startswith("CORPORATE_ACTION_VALIDATION_PASSED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
