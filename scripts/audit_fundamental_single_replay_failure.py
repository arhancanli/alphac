#!/usr/bin/env python3
"""Bind the selected fundamental replay's fail-closed data error to evidence.

This is deliberately separate from the replay runner.  The historical trial and its
experiment identity remain immutable; this audit records why the attempted exact replay
did not earn a result packet.  It does not repair, suppress, or reinterpret the bad row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import duckdb

REPO: Final[Path] = Path(__file__).resolve().parent.parent
IDENTITY: Final[str] = "1d2924f28fe31a9a"
RUN_NAME: Final[str] = "single_gross_profitability"
REPLAY_DIR: Final[Path] = (
    REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
)
ENVIRONMENT: Final[Path] = REPLAY_DIR / "replay_environment.json"
PRESERVED_DIR: Final[Path] = REPO / "artifacts" / "walkforward" / RUN_NAME
ACTION_GLOB: Final[str] = str(
    REPO / "data" / "lake_sharadar" / "corporate_actions" / "**" / "*.parquet"
)
OUTPUT: Final[Path] = REPLAY_DIR / "replay_failure.json"
CANDIDATES: Final[dict[str, str]] = {
    "single_gross_profitability": "1d2924f28fe31a9a",
    "single_book_to_price": "a238c1a5ecc5d1e3",
    "single_earnings_yield": "e86109044ab18734",
    "single_sales_to_price": "2d966892fb5db520",
    "single_operating_margin": "e5f48adc25065ce9",
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build(
    run_name: str = RUN_NAME,
    identity: str = IDENTITY,
) -> dict[str, Any]:
    replay_dir = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    environment_path = replay_dir / "replay_environment.json"
    preserved_dir = REPO / "artifacts" / "walkforward" / run_name
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    preserved_artifact = preserved_dir / "walkforward.json"
    preserved_equity = preserved_dir / "equity.parquet"

    # Cast timestamps to strings in DuckDB so the audit does not depend on an optional
    # timezone package merely to serialise the offending source row.
    rows = duckdb.connect().execute(
        """
        SELECT instrument_id, action_type, ex_date::VARCHAR, available_at::VARCHAR,
               ratio, cash_amount, ingested_at::VARCHAR, filename
        FROM read_parquet(?, filename=true, hive_partitioning=true)
        WHERE action_type = 'dividend' AND cash_amount <= 0
        ORDER BY ex_date, instrument_id
        """,
        [ACTION_GLOB],
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            "expected exactly one non-positive dividend in the frozen Sharadar lake; "
            f"found {len(rows)}"
        )
    row = rows[0]
    if row[0] != "XUSE:CASH:HDBUSD" or float(row[5]) != 0.0:
        raise RuntimeError(f"unexpected invalid corporate-action row: {row!r}")

    replay_outputs = {
        name: (replay_dir / name).exists()
        for name in ("walkforward.json", "equity.parquet", "result.json")
    }
    if any(replay_outputs.values()):
        raise RuntimeError(
            "a replay output now exists; refuse to publish the earlier failure as current"
        )

    source_path = Path(str(row[7]))
    if not source_path.is_absolute():
        source_path = REPO / source_path
    payload: dict[str, Any] = {
        "schema": "canli.alphac-fundamental-single-replay-failure.v1",
        "author": "Arhan Canli",
        "hypothesis_key": identity,
        "run_name": run_name,
        "status": "FAILED_CLOSED",
        "packet_status": "INCOMPLETE",
        "decision": "INVALID_CORPORATE_ACTION_SOURCE_ROW",
        "failure": {
            "stage": "walk_forward.corporate_action_validation",
            "exception_type": "ValueError",
            "exception_message": "cash dividend cash_amount must be > 0",
            "invalid_row_count_entire_sharadar_lake": len(rows),
            "offending_row": {
                "instrument_id": row[0],
                "action_type": row[1],
                "ex_date": row[2],
                "available_at": row[3],
                "ratio": float(row[4]),
                "cash_amount": float(row[5]),
                "ingested_at": row[6],
                "source_path": str(source_path.relative_to(REPO)),
                "source_sha256": _sha256(source_path),
            },
        },
        "evidence": {
            "replay_environment_path": str(environment_path.relative_to(REPO)),
            "replay_environment_sha256": _sha256(environment_path),
            "source_environment_content_hash": environment["content_hash"],
            "preserved_walkforward_path": str(preserved_artifact.relative_to(REPO)),
            "preserved_walkforward_sha256": _sha256(preserved_artifact),
            "preserved_equity_path": str(preserved_equity.relative_to(REPO)),
            "preserved_equity_sha256": _sha256(preserved_equity),
            "replay_outputs_present": replay_outputs,
        },
        "claim_boundary": (
            "This artifact proves only that the selected exact replay failed closed on the "
            "sole non-positive dividend row in the current Sharadar corporate-action lake. "
            "It is not a successful replay, does not validate the historical return curve, "
            "does not create a new trial, and supplies no Sharpe, drawdown, or sleeve claim."
        ),
        "required_next_action": (
            "Resolve the source-row semantics through an independently documented data repair "
            "or vendor correction, then rerun under a newly hash-bound environment. Never drop "
            "the row silently and never mark this identity complete without exact equality."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name", nargs="?", default=RUN_NAME, choices=CANDIDATES)
    args = parser.parse_args()
    identity = CANDIDATES[args.run_name]
    payload = build(args.run_name, identity)
    output = (
        REPO
        / "artifacts"
        / "probe"
        / "fundamental_single_replays"
        / identity
        / "replay_failure.json"
    )
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
