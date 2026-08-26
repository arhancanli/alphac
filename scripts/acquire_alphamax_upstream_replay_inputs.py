#!/usr/bin/env python3
"""Reacquire the private inputs required to replay AlphaMax ``k30_dn_63``.

This is deliberately not described as recovery of a preserved historical snapshot. The
Polygon lake used by the 2026-06-20 run was deleted during the later Sharadar migration.
The harness instead reconstructs the historical instrument and experiment-ledger state,
reacquires the vendor bars/actions, rebuilds the universe with the pinned source tree, and
fails closed unless the rebuilt universe union matches the 375 ids sealed in the artifact.

The current flat-file entitlement begins on 2021-08-23: 58 requested sessions from
2021-06-01 through 2021-08-20 return HTTP 403. The gap precedes the first leg's 2022-10-26
training slice and 2023-07 test output, but the feature engine's global warmup can still request
it. The packet therefore makes no sufficiency claim before an exact clean output comparison.
It also cannot replay the wider 2021-06 universe-building command. The private failure log is
retained and hash-bound; the public acquisition claim is limited to the available vendor window
and exact strategy-window membership union, with output equivalence replay-pending.

Raw vendor rows remain under ignored private paths. Only hashes and conservative receipts
may enter a public bundle; this script does not grant or infer redistribution rights.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pyarrow.parquet as pq

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE_COMMIT: Final = "fd3e930f41b0a62b222ecda4ab83bae21a4ce9f2"
RUN_STARTED_UTC: Final = "2026-06-20T10:13:55.046000+00:00"
RUN_STARTED_MS: Final = 1_781_950_435_046
ORIGINAL_UNIVERSE_START: Final = "2021-06-01"
BAR_START: Final = "2021-08-23"
BAR_UNTIL_EXCLUSIVE: Final = "2026-06-02"
UNIVERSE_START: Final = BAR_START
UNIVERSE_END: Final = "2026-06-01"
STRATEGY_WINDOW_START_MS: Final = 1_656_633_600_000  # 2022-07-01T00:00:00Z
STRATEGY_WINDOW_END_MS: Final = 1_780_272_000_000  # 2026-06-01T00:00:00Z
GLOBAL_FEATURE_CONTEXT_START: Final = "2021-06-30"
FIRST_LEG_TRAIN_START: Final = "2022-10-26"
FIRST_LEG_TEST_START: Final = "2023-07-05"
EXPECTED_ENTITLEMENT_GAP_SESSIONS: Final = 58
EXPECTED_HISTORICAL_INSTRUMENTS: Final = 12_481
EXPECTED_HISTORICAL_DELISTED: Final = 6_601
EXPECTED_LEDGER_TRIALS: Final = 27
EXPECTED_LEDGER_VARIANCE: Final = 0.0009581739898135611
EXPECTED_UNIVERSE_IDS: Final = 375
EXPECTED_EQUITY_SHA256: Final = "76f82c8df3726f049144d7699c0f13069db6a1e0d1f1e4570babd8d82a85cfc9"

SNAPSHOT: Final = ROOT / "data/reproduction/alphamax_k30_dn_63_polygon_reacquired_20260824"
REFERENCE: Final = (
    ROOT / "artifacts/reproduction_private/alphamax_k30_dn_63_20260620/reference_output"
)
SOURCE_DB: Final = ROOT / "var/ops.sqlite"
SOURCE_LEDGER: Final = ROOT / "var/experiments.jsonl"
TARGET_ARTIFACT: Final = ROOT / "artifacts/walkforward/k30_dn_63"
POLYGON_ENV: Final = Path.home() / ".config/alphaforge/polygon.env"

_ACTION_WORKER = r"""from __future__ import annotations

import json
import os
from pathlib import Path

from alphaforge.core.time import parse_utc
from alphaforge.data.schemas import Dataset
from alphaforge.data.sources.polygon_source import PolygonEquitiesSource
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter

ids = json.loads(Path("var/alphamax_instrument_ids.json").read_text(encoding="utf-8"))
source = PolygonEquitiesSource(api_key=os.environ["POLYGON_API_KEY"])
writer = LakeWriter(LakePaths("data/lake"))
until = parse_utc("2026-06-02T00:00:00Z")
# Populate the canonical-id -> raw-vendor-ticker map before action calls. Without this,
# separator-bearing share classes such as BRK.B fall back to the invalid ticker BRKB.
listed = source.list_instruments(as_of=until - 1)
listed_ids = {instrument.instrument_id for instrument in listed}
missing_reference_ids = sorted(set(ids) - listed_ids)
if missing_reference_ids:
    raise RuntimeError(
        f"reference mapping missing {len(missing_reference_ids)} strategy ids"
    )
events = 0
failures: list[dict[str, str]] = []
for number, instrument_id in enumerate(ids, start=1):
    try:
        table = source.fetch_corporate_actions(instrument_id, since=0, until=until)
        if table.num_rows:
            writer.write(Dataset.CORPORATE_ACTIONS, table)
            events += table.num_rows
    except Exception as exc:
        failures.append({"instrument_id": instrument_id, "error": repr(exc)})
    if number % 25 == 0 or number == len(ids):
        print(
            f"actions progress {number}/{len(ids)} events={events} failures={len(failures)}",
            flush=True,
        )
if failures:
    Path("var/alphamax_action_failures.json").write_text(
        json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    raise SystemExit(1)
print(
    json.dumps(
        {
            "instrument_ids": len(ids),
            "reference_instrument_ids": len(listed_ids),
            "events": events,
        },
        sort_keys=True,
    )
)
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_polygon_environment() -> None:
    if POLYGON_ENV.is_file():
        for raw_line in POLYGON_ENV.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    required = {
        "POLYGON_API_KEY",
        "POLYGON_S3_ENDPOINT",
        "POLYGON_S3_ACCESS_KEY_ID",
        "POLYGON_S3_SECRET_ACCESS_KEY",
        "POLYGON_S3_BUCKET",
    }
    missing = sorted(required - os.environ.keys())
    if missing:
        raise RuntimeError(f"missing Polygon environment keys: {', '.join(missing)}")


def _extract_source(workspace: Path) -> str:
    completed = subprocess.run(
        ["git", "archive", "--format=tar", SOURCE_COMMIT],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace")[-2000:])
    archive_sha = hashlib.sha256(completed.stdout).hexdigest()
    with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as handle:
        for member in handle.getmembers():
            target = (workspace / member.name).resolve()
            if not target.is_relative_to(workspace):
                raise RuntimeError(f"unsafe git archive member: {member.name}")
        handle.extractall(workspace, filter="data")
    return archive_sha


def _historical_rows(source: sqlite3.Connection) -> list[tuple[Any, ...]]:
    columns = [
        "instrument_id",
        "asset_class",
        "market_type",
        "base",
        "quote",
        "tick_size",
        "lot_size",
        "min_qty",
        "min_notional",
        "contract_multiplier",
        "can_short",
        "maker_fee_bps",
        "taker_fee_bps",
        "funding_interval_hours",
        "listed_ts",
        "delisted_ts",
        "valid_from_ms",
        "valid_to_ms",
    ]
    query = f"""
        SELECT {", ".join(columns)}
          FROM instruments_v
         WHERE instrument_id LIKE 'XUSE:%'
           AND valid_from_ms <= ?
           AND (valid_to_ms IS NULL OR valid_to_ms > ?)
         ORDER BY instrument_id
    """
    return source.execute(query, (RUN_STARTED_MS, RUN_STARTED_MS)).fetchall()


def _prepare_instrument_store() -> dict[str, Any]:
    destination = SNAPSHOT / "var/ops.sqlite"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SOURCE_DB, timeout=60) as source:
            source.execute("PRAGMA busy_timeout=60000")
            rows = _historical_rows(source)
            if len(rows) != EXPECTED_HISTORICAL_INSTRUMENTS:
                raise ValueError(
                    f"historical instrument count drifted: {len(rows)} != "
                    f"{EXPECTED_HISTORICAL_INSTRUMENTS}"
                )
            with sqlite3.connect(destination) as target:
                source.backup(target)
                target.execute("DELETE FROM instruments_v")
                placeholders = ",".join("?" for _ in range(18))
                normalized = [(*row[:-1], None) for row in rows]
                target.executemany(f"INSERT INTO instruments_v VALUES ({placeholders})", normalized)
                target.execute("DELETE FROM watermarks")
                target.execute("DELETE FROM runs")
                target.commit()

    with sqlite3.connect(destination) as check:
        rows = check.execute(
            "SELECT COUNT(*), SUM(delisted_ts IS NOT NULL) FROM instruments_v"
        ).fetchone()
    count, delisted = int(rows[0]), int(rows[1] or 0)
    if count != EXPECTED_HISTORICAL_INSTRUMENTS or delisted != EXPECTED_HISTORICAL_DELISTED:
        raise ValueError(
            f"reconstructed instrument state mismatch: count={count}, delisted={delisted}"
        )
    return {
        "path": "var/ops.sqlite",
        "instrument_ids": count,
        "delisted_instrument_ids": delisted,
        "sha256": _sha256(destination),
        "historical_as_of_utc": RUN_STARTED_UTC,
    }


def _prepare_experiment_ledger() -> dict[str, Any]:
    destination = SNAPSHOT / "var/experiments.jsonl"
    selected: list[dict[str, Any]] = []
    for line in SOURCE_LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if int(record["now_ms"]) <= RUN_STARTED_MS:
            selected.append(record)
    hashes = {str(record["config_hash"]) for record in selected}
    if len(selected) != EXPECTED_LEDGER_TRIALS or len(hashes) != EXPECTED_LEDGER_TRIALS:
        raise ValueError(
            f"historical ledger reconstruction drifted: rows={len(selected)}, unique={len(hashes)}"
        )
    values = [float(record["sharpe_per_period"]) for record in selected]
    variance = statistics.variance(values)
    if not math.isclose(variance, EXPECTED_LEDGER_VARIANCE, rel_tol=0.0, abs_tol=1e-18):
        raise ValueError(
            f"historical trial variance drifted: {variance} != {EXPECTED_LEDGER_VARIANCE}"
        )
    rendered = "".join(
        json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n" for record in selected
    )
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered:
        raise ValueError("existing reconstructed experiment ledger differs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return {
        "path": "var/experiments.jsonl",
        "trials": len(hashes),
        "per_period_sharpe_sample_variance": variance,
        "stored_historical_variance": EXPECTED_LEDGER_VARIANCE,
        "variance_absolute_difference": abs(variance - EXPECTED_LEDGER_VARIANCE),
        "variance_validation_absolute_tolerance": 1e-18,
        "sha256": _sha256(destination),
        "cutoff_utc": RUN_STARTED_UTC,
    }


def _prepare_reference() -> dict[str, Any]:
    source_files = sorted(path for path in TARGET_ARTIFACT.iterdir() if path.is_file())
    if not REFERENCE.exists():
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(TARGET_ARTIFACT, REFERENCE)
    reference_files = sorted(path for path in REFERENCE.iterdir() if path.is_file())
    if [path.name for path in reference_files] != [path.name for path in source_files]:
        raise ValueError("private AlphaMax reference file set differs from source artifact")
    equity = REFERENCE / "equity.parquet"
    if _sha256(equity) != EXPECTED_EQUITY_SHA256:
        raise ValueError("AlphaMax reference equity hash drifted")
    return {
        "path": str(REFERENCE.relative_to(ROOT)),
        "files": len(reference_files),
        "equity_sha256": _sha256(equity),
        "tree_hash": hashlib.sha256(
            _canonical(
                [
                    {
                        "path": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                    for path in reference_files
                ]
            )
        ).hexdigest(),
    }


def _run_logged(command: list[str], workspace: Path, log_name: str) -> dict[str, Any]:
    log = SNAPSHOT / "logs" / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=os.environ.copy(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        last_update = time.monotonic()
        while process.poll() is None:
            time.sleep(2)
            if time.monotonic() - last_update >= 30:
                print(
                    f"still running: {' '.join(command)} (log_bytes={log.stat().st_size})",
                    flush=True,
                )
                last_update = time.monotonic()
    finished = datetime.now(UTC)
    if process.returncode:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(command)}\n{tail}")
    record = {
        "command": " ".join(command),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "exit_code": process.returncode,
        "log_path": str(log.relative_to(SNAPSHOT)),
        "log_sha256": _sha256(log),
    }
    print(f"completed: {record['command']}", flush=True)
    return record


def _universe_summary() -> dict[str, Any]:
    root = SNAPSHOT / "data/lake/universe_membership"
    files = sorted(root.glob("**/*.parquet"))
    intervals = 0
    open_intervals = 0
    ids: set[str] = set()
    strategy_window_ids: set[str] = set()
    for path in files:
        with pq.ParquetFile(path) as leaf:  # type: ignore[no-untyped-call]
            table = leaf.read(columns=["instrument_id", "effective_from", "effective_to"])
        intervals += table.num_rows
        instrument_values = table.column("instrument_id").to_pylist()
        from_values = table.column("effective_from").to_pylist()
        to_values = table.column("effective_to").to_pylist()
        ids.update(str(value) for value in instrument_values)
        open_intervals += sum(value is None for value in to_values)
        for instrument_id, effective_from, effective_to in zip(
            instrument_values,
            from_values,
            to_values,
            strict=True,
        ):
            start_ms = int(effective_from.timestamp() * 1000)
            end_ms = None if effective_to is None else int(effective_to.timestamp() * 1000)
            if start_ms < STRATEGY_WINDOW_END_MS and (
                end_ms is None or end_ms > STRATEGY_WINDOW_START_MS
            ):
                strategy_window_ids.add(str(instrument_id))

    expected = json.loads((TARGET_ARTIFACT / "walkforward.json").read_text(encoding="utf-8"))[
        "config"
    ]["instrument_ids"]
    expected_ids = {str(value) for value in expected}
    summary = {
        "files": len(files),
        "intervals": intervals,
        "open_intervals": open_intervals,
        "closed_intervals": intervals - open_intervals,
        "full_rebuild_instrument_ids": len(ids),
        "strategy_window_instrument_ids": len(strategy_window_ids),
        "strategy_window_instrument_id_set_exact": strategy_window_ids == expected_ids,
        "missing_from_strategy_window": sorted(expected_ids - strategy_window_ids),
        "unexpected_in_strategy_window": sorted(strategy_window_ids - expected_ids),
        "strategy_window_membership_records_hash": hashlib.sha256(
            _canonical(sorted(strategy_window_ids))
        ).hexdigest(),
        "historical_full_2021_06_rebuild_exact": False,
    }
    _write_json(SNAPSHOT / "var/alphamax_universe_summary.json", summary)
    if len(strategy_window_ids) != EXPECTED_UNIVERSE_IDS or strategy_window_ids != expected_ids:
        raise ValueError(
            f"reacquired strategy-window universe does not match historical target: {summary}"
        )
    _write_json(SNAPSHOT / "var/alphamax_instrument_ids.json", sorted(strategy_window_ids))
    return summary


def _entitlement_gap_evidence() -> dict[str, Any]:
    log = SNAPSHOT / "logs/polygon_bars.log"
    if not log.is_file():
        raise FileNotFoundError("initial full-lookback acquisition log is missing")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    failures: list[str] = []
    successes: list[str] = []
    session_pattern = re.compile(r"\bsession=(\d{4}-\d{2}-\d{2})\b")
    for line in lines:
        match = session_pattern.search(line)
        if match is None:
            continue
        if "equities_ingest.session_failed" in line:
            if "(403)" not in line or "Forbidden" not in line:
                raise ValueError("initial acquisition contains a non-entitlement session failure")
            failures.append(match.group(1))
        elif "equities_ingest.session_done" in line:
            successes.append(match.group(1))
    if (
        len(failures) != EXPECTED_ENTITLEMENT_GAP_SESSIONS
        or failures[0] != ORIGINAL_UNIVERSE_START
        or failures[-1] != "2021-08-20"
        or not successes
        or successes[0] != BAR_START
        or any(day >= BAR_START for day in failures)
    ):
        raise ValueError("initial Polygon entitlement-gap evidence differs from expectation")
    return {
        "requested_full_lookback_start": ORIGINAL_UNIVERSE_START,
        "first_available_session": BAR_START,
        "failed_sessions": len(failures),
        "first_failed_session": failures[0],
        "last_failed_session": failures[-1],
        "http_status": 403,
        "global_feature_context_requested_start": GLOBAL_FEATURE_CONTEXT_START,
        "gap_intersects_global_feature_context": True,
        "first_leg_train_start": FIRST_LEG_TRAIN_START,
        "first_leg_test_start": FIRST_LEG_TEST_START,
        "initial_private_log_path": str(log.relative_to(SNAPSHOT)),
        "initial_private_log_sha256": _sha256(log),
        "full_historical_universe_rebuild_available": False,
        "strategy_sufficiency_replay_pending": True,
        "acquisition_alone_establishes_strategy_sufficiency": False,
    }


def _bind_snapshot() -> dict[str, Any]:
    records = [
        {
            "path": str(path.relative_to(SNAPSHOT)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(SNAPSHOT.rglob("*"))
        if path.is_file() and path.name != "acquisition_complete.json"
    ]
    return {
        "files": len(records),
        "bytes": sum(record["bytes"] for record in records),
        "tree_content_hash": hashlib.sha256(_canonical(records)).hexdigest(),
        "records": records,
    }


def acquire(*, skip_sync: bool = False) -> dict[str, Any]:
    _load_polygon_environment()
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT / "data").mkdir(exist_ok=True)
    state = {
        "instrument_store": _prepare_instrument_store(),
        "experiment_ledger": _prepare_experiment_ledger(),
        "reference_output": _prepare_reference(),
        "entitlement_gap": _entitlement_gap_evidence(),
    }

    with tempfile.TemporaryDirectory(prefix="alphamax-acquisition-") as raw_workspace:
        workspace = Path(raw_workspace).resolve()
        archive_sha = _extract_source(workspace)
        os.symlink(SNAPSHOT / "data", workspace / "data", target_is_directory=True)
        os.symlink(SNAPSHOT / "var", workspace / "var", target_is_directory=True)
        (workspace / ".alphamax_actions_worker.py").write_text(_ACTION_WORKER, encoding="utf-8")
        records: list[dict[str, Any]] = []
        if not skip_sync:
            records.append(_run_logged(["uv", "sync", "--frozen"], workspace, "uv_sync.log"))
        python = workspace / ".venv/bin/python"
        if not python.is_file():
            raise FileNotFoundError(f"pinned workspace interpreter missing: {python}")

        bars_marker = SNAPSHOT / "var/bars_complete.json"
        if not bars_marker.exists():
            record = _run_logged(
                [
                    "uv",
                    "run",
                    "af",
                    "data",
                    "ingest-equities",
                    "--start",
                    BAR_START,
                    "--until",
                    BAR_UNTIL_EXCLUSIVE,
                    "--no-corp-actions",
                    "--profile",
                    "equity",
                ],
                workspace,
                "polygon_bars_available_window.log",
            )
            records.append(record)
            _write_json(bars_marker, record)

        universe_marker = SNAPSHOT / "var/universe_complete.json"
        if not universe_marker.exists():
            record = _run_logged(
                [
                    "uv",
                    "run",
                    "af",
                    "universe",
                    "rebuild",
                    "--profile",
                    "equity",
                    "--start",
                    UNIVERSE_START,
                    "--end",
                    UNIVERSE_END,
                ],
                workspace,
                "universe_rebuild.log",
            )
            summary = _universe_summary()
            record["summary"] = summary
            records.append(record)
            _write_json(universe_marker, record)
        else:
            summary = _universe_summary()

        actions_marker = SNAPSHOT / "var/actions_complete.json"
        if not actions_marker.exists():
            record = _run_logged(
                [str(python), ".alphamax_actions_worker.py"],
                workspace,
                "polygon_actions.log",
            )
            records.append(record)
            _write_json(actions_marker, record)

    # Universe/actions commands update operational tables in the same SQLite file. Re-hash it
    # only after those stages so the receipt never publishes the pre-execution file hash as if it
    # bound the final sealed snapshot. The historical instrument rows themselves are revalidated.
    state["instrument_store"] = _prepare_instrument_store()
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphamax-upstream-input-acquisition.v1",
        "author": "Arhan Canli",
        "acquired_at": datetime.now(UTC).isoformat(),
        "status": (
            "PASS_AVAILABLE_VENDOR_REACQUISITION_WINDOW_UNION_EXACT_"
            "FULL_LOOKBACK_GAP_DISCLOSED_REPLAY_PENDING"
        ),
        "historical_run": {
            "run_started_utc": RUN_STARTED_UTC,
            "source_commit": SOURCE_COMMIT,
            "command": (
                "uv run af research walkforward --profile equity --start 2022-07-01 "
                "--end 2026-06-01 --train-days 252 --test-days 63 "
                "--rebalance-bars 63 --allocator rank --alphas eq_mom_252_21 "
                "--out artifacts/walkforward/k30_dn_63"
            ),
        },
        "source": {
            "git_archive_sha256": archive_sha,
            "tracked_source_reconstruction": "POST_RUN_COMMIT_OF_PRECOMMIT_CONTENT",
        },
        "reconstruction": state,
        "vendor_reacquisition": {
            "provider": "Polygon.io Stocks Flat Files and reference API",
            "bars_start": BAR_START,
            "bars_until_exclusive": BAR_UNTIL_EXCLUSIVE,
            "corporate_actions_scope": "375 strategy-universe instrument ids",
            "available_window_fresh_vendor_reacquisition_completed": True,
            "strategy_sufficiency_established": False,
            "full_historical_universe_lookback_reacquired": False,
            "entitlement_gap": state["entitlement_gap"],
            "preserved_historical_raw_input_snapshot": False,
            "vendor_rows_may_have_been_revised_since_historical_run": True,
        },
        "universe": summary,
        "execution_records": records,
        "rights_and_release": {
            "raw_or_normalized_vendor_rows_publication_authorized": False,
            "private_snapshot_may_be_published": False,
            "hash_manifest_may_be_published": True,
            "public_bundle_must_withhold_vendor_rows": True,
        },
        "claim_boundary": (
            "This receipt establishes fresh private vendor reacquisition from the first entitled "
            "session, 2021-08-23, and an exact match of the 375-id universe union overlapping "
            "the 2022-07-01 to 2026-06-01 strategy window. The unavailable 58-session "
            "2021-06-01 to 2021-08-20 lookback is retained in a private hash-bound failure log; "
            "an exact full historical universe rebuild is not claimed. The entitlement boundary "
            "precedes the first leg's training and test spans but can intersect the global feature "
            "warmup, so strategy sufficiency remains replay-pending. Only the separate "
            "clean-workspace output comparison can establish strategy equivalence. "
            "This receipt does not establish exact per-date memberships, unchanged vendor rows, "
            "redistribution rights, or independent reproduction."
        ),
    }
    document["snapshot"] = _bind_snapshot()
    document["content_hash"] = "sha256:" + hashlib.sha256(_canonical(document)).hexdigest()
    _write_json(SNAPSHOT / "acquisition_complete.json", document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Use only when a pinned workspace venv is already present (normally false).",
    )
    args = parser.parse_args()
    document = acquire(skip_sync=args.skip_sync)
    print(f"{document['status']}: {SNAPSHOT}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
