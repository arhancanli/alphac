#!/usr/bin/env python3
# ruff: noqa: E501  (verbatim recovered source-patch strings exceed the project line length)
"""Build a fail-closed lineage receipt for historical ``prereg_investment``.

The artifact is a historical gate input, not an admitted sleeve and not a valid
execution of the later AlphaLedger pre-registration.  This script recovers and
binds what can still be established locally before an upstream replay is run:

* the exact orchestration and launch events in the private conversation record;
* the predecessor commit and three run-critical files recovered from the first
  post-run commit, with the two source edits independently present in the
  private execution record;
* the surviving artifact, membership, Sharadar-row, and experiment-ledger state;
* the boundary between preserved inputs and a corporate-action reconstruction
  candidate that still needs to be adjudicated by a clean replay.

No backtest is run, no historical metric is regraded, and no private vendor row
or conversation content is copied into the public receipt.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import duckdb
import numpy as np
import pyarrow.parquet as pq

ROOT: Final = Path(__file__).resolve().parents[1]
ARTIFACT: Final = ROOT / "artifacts/walkforward/prereg_investment"
LEDGER: Final = ROOT / "var/experiments.jsonl"
TRANSCRIPT: Final = (
    Path.home()
    / ".claude/projects/-Users-arhancanli/"
    / "0039cc52-3755-446f-a516-316da07f1b06.jsonl"
)
OUTPUT: Final = ROOT / "artifacts/publication/prereg_investment_historical_lineage.json"

SOURCE_COMMIT: Final = "8417cb850a27306b30f6c70365c3565f3d209ddf"
POST_RUN_COMMIT: Final = "6aa26b55254ce33ed6ca3a817ce52433924a71ed"
RUN_LAUNCHED_UTC: Final = "2026-06-21T05:21:24.293000+00:00"
TRIAL_NOW_MS: Final = 1_782_027_281_509
LOAD_INGESTED_AT_UTC: Final = "2026-06-21T05:23:11.023000+00:00"
EXPECTED_TRANSCRIPT_SHA256: Final = (
    "a9dfd8aad3a27530293130fc43240782f4813d7c53fe3a00948b190331b337df"
)
EXPECTED_ARTIFACT_HASHES: Final = {
    "equity.parquet": "e81f22c716da8590ee0a7129760ffa65f56b6967f8ef8c3c2ed86845cdf1645b",
    "summary.txt": "a52cbc9604cd015f6d3557582bdeb01e538752baba6eacc5cd021b8bf33d4376",
    "tearsheet.png": "ee2a150c4e1e4f9f597bd25d225903e6f8d24df7f7389f2ed48949c3240ef37f",
    "tearsheet.txt": "a52cbc9604cd015f6d3557582bdeb01e538752baba6eacc5cd021b8bf33d4376",
    "walkforward.json": "fb11cba28271462444de855e2da294d026bcffdfd7176ec9a4ffabe7be46485f",
}
EXPECTED_COMMAND: Final = (
    "uv run af research walkforward --profile equity --allocator rank "
    "--rebalance-bars 63 --start 2000-01-01 --end 2026-06-01 "
    "--train-days 252 --test-days 63 --alphas eq_asset_growth "
    "--out artifacts/walkforward/prereg_investment"
)
EXPECTED_LEDGER_HASH: Final = "e8c9b78fb4f7c195"
EXPECTED_LEDGER_VARIANCE: Final = 0.0011398070210704527
EXPECTED_MEMBERSHIP = {
    "instrument_ids": 6_835,
    "intervals": 11_359,
    "open_intervals": 2_088,
}
EXPECTED_LOAD = {
    "ohlcv_rows": 24_085_990,
    "ohlcv_instrument_ids": 8_436,
    "fundamental_rows_stored": 380_878,
    "fundamental_instrument_ids": 8_082,
    "fundamental_rows_reported_by_loader": 392_229,
    "corporate_action_rows_reported_by_loader": 172_200,
    "splits_reported_by_loader": 5_079,
}
EXPECTED_RAW_ARCHIVES: Final[dict[str, tuple[int, str]]] = {
    "ACTIONS.zip": (
        9_766_443,
        "166d6ae17921b6a3a1f13a734e43bfd32ca5d9e88398030290a5246c89d7185c",
    ),
    "SEP.zip": (
        994_782_292,
        "d537322141302331cc3dc43f4eefe1222057e329525a835cc93bd0a079db92b3",
    ),
    "SF1.zip": (
        170_695_165,
        "701c3ac5ea8c65c6621461f51d4ff23358c46a3b019c6acf3a1e85ee2998487a",
    ),
    "TICKERS.zip": (
        3_919_917,
        "8f3e03012dd25d0a2fb3950e39d81f1ddff106391cd20eb9e547cd53f92525f5",
    ),
}

_FEATURE_OLD: Final = """    zs = [_cs_zscore(c).reindex(idx) for c in components]
    mat = pd.concat(zs, axis=1)
    valid = mat.notna().sum(axis=1).to_numpy()
    comp = mat.mean(axis=1, skipna=True).to_numpy(dtype=\"float64\")
    comp[valid < min_valid] = np.nan
    return pd.Series(comp, index=idx, dtype=\"float64\", name=name)"""
_FEATURE_NEW: Final = """    zs = [_cs_zscore(c).reindex(idx) for c in components]
    mat = pd.concat(zs, axis=1)
    valid = mat.notna().sum(axis=1).to_numpy()
    mean = mat.mean(axis=1, skipna=True).to_numpy(dtype=\"float64\")
    # np.where returns a fresh writable array (.to_numpy() is read-only under CoW pandas 2.x).
    comp = np.where(valid >= min_valid, mean, np.nan)
    return pd.Series(comp, index=idx, dtype=\"float64\", name=name)"""
_LOADER_OLD: Final = """        for ch in pd.read_csv(fh, usecols=cols, chunksize=chunk):  # type: ignore[arg-type]
            ch = ch[ch[\"ticker\"].astype(str).str.upper().isin(candidates)]
            ch = ch[(ch[\"close\"] > 0) & (ch[\"closeunadj\"] > 0)]
            if len(ch):
                parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    del parts
    df[\"ratio\"] = df[\"closeunadj\"] / df[\"close\"]  # adjusted -> raw
    df[\"dollar\"] = df[\"close\"] * df[\"volume\"]  # split-invariant dollar volume"""
_LOADER_NEW: Final = """        for ch in pd.read_csv(fh, usecols=cols, chunksize=chunk):  # type: ignore[arg-type]
            ch = ch[ch[\"ticker\"].astype(str).str.upper().isin(candidates)]
            # Prices must be finite + positive (the backtest's BarView rejects non-finite OHLC);
            # wide survivorship-free names have halted/gappy bars the top-200 large-caps did not.
            for c in (\"open\", \"high\", \"low\", \"close\", \"closeunadj\"):
                ch = ch[np.isfinite(ch[c]) & (ch[c] > 0)]
            if len(ch):
                parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    del parts
    # Volume on a halted day can be NaN/negative; the lake requires finite >= 0 -> floor to 0
    # (keeps the price bar; the universe ranker medians dollar-volume so a 0 day is harmless).
    df[\"volume\"] = df[\"volume\"].where(np.isfinite(df[\"volume\"]) & (df[\"volume\"] >= 0.0), 0.0)
    df[\"ratio\"] = df[\"closeunadj\"] / df[\"close\"]  # adjusted -> raw
    df[\"dollar\"] = df[\"close\"] * df[\"volume\"]  # split-invariant dollar volume"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _transcript_evidence() -> dict[str, Any]:
    if not TRANSCRIPT.is_file():
        raise FileNotFoundError(TRANSCRIPT)
    transcript_sha = _sha256(TRANSCRIPT)
    if transcript_sha != EXPECTED_TRANSCRIPT_SHA256:
        raise ValueError("private transcript binding drifted")

    orchestration: dict[str, Any] | None = None
    launch: dict[str, Any] | None = None
    feature_edit: dict[str, Any] | None = None
    loader_edit: dict[str, Any] | None = None
    measured_output: dict[str, Any] | None = None
    forbidden_edits_during_investment: list[dict[str, str]] = []
    investment_started = datetime.fromtimestamp(TRIAL_NOW_MS / 1000, tz=UTC)
    investment_finished = datetime.fromisoformat("2026-06-21T08:34:57+00:00")

    with TRANSCRIPT.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            event = json.loads(raw)
            timestamp = str(event.get("timestamp", ""))
            for node in _walk(event.get("message", {})):
                name = node.get("name")
                tool_input = node.get("input")
                if name == "Bash" and isinstance(tool_input, dict):
                    command = str(tool_input.get("command", ""))
                    if "cat > /tmp/reload_and_run.sh" in command:
                        expands_to_expected = all(
                            fragment in command
                            for fragment in (
                                'WF="uv run af research walkforward --profile equity '
                                "--allocator rank --rebalance-bars 63 --start 2000-01-01 "
                                '--end 2026-06-01 --train-days 252 --test-days 63"',
                                "investment:eq_asset_growth",
                                '$WF --alphas "$alpha" --out "artifacts/walkforward/prereg_$name"',
                            )
                        )
                        orchestration = {
                            "timestamp": timestamp,
                            "event_uuid": event.get("uuid"),
                            "line_number_private_record": line_number,
                            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                            "expands_to_expected_strategy_command": expands_to_expected,
                        }
                    elif command == "cd ~/alphaforge && bash /tmp/reload_and_run.sh":
                        launch = {
                            "timestamp": timestamp,
                            "event_uuid": event.get("uuid"),
                            "line_number_private_record": line_number,
                            "background": bool(tool_input.get("run_in_background")),
                        }
                elif name == "Edit" and isinstance(tool_input, dict):
                    path = str(tool_input.get("file_path", ""))
                    record = {
                        "timestamp": timestamp,
                        "event_uuid": event.get("uuid"),
                        "line_number_private_record": line_number,
                        "path": path.removeprefix(str(ROOT) + "/"),
                        "old_sha256": hashlib.sha256(
                            str(tool_input.get("old_string", "")).encode()
                        ).hexdigest(),
                        "new_sha256": hashlib.sha256(
                            str(tool_input.get("new_string", "")).encode()
                        ).hexdigest(),
                    }
                    if (
                        path.endswith("equity_fundamental.py")
                        and timestamp == "2026-06-21T05:18:19.015Z"
                    ):
                        if tool_input.get("old_string") != _FEATURE_OLD:
                            raise ValueError("recovered feature patch old text drifted")
                        if tool_input.get("new_string") != _FEATURE_NEW:
                            raise ValueError("recovered feature patch new text drifted")
                        feature_edit = record
                    elif (
                        path.endswith("scripts/sharadar_load.py")
                        and timestamp == "2026-06-21T05:20:34.845Z"
                    ):
                        if tool_input.get("old_string") != _LOADER_OLD:
                            raise ValueError("recovered loader patch old text drifted")
                        if tool_input.get("new_string") != _LOADER_NEW:
                            raise ValueError("recovered loader patch new text drifted")
                        loader_edit = record

                    if timestamp:
                        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        if investment_started <= instant <= investment_finished:
                            forbidden_edits_during_investment.append(record)

            rendered_message = json.dumps(event.get("message", {}), sort_keys=True)
            if (
                "=== SLEEVE investment (eq_asset_growth) ===" in rendered_message
                and "SR_ann 0.83" in rendered_message
                and "N_trials 75" in rendered_message
            ):
                measured_output = {
                    "timestamp": timestamp,
                    "event_uuid": event.get("uuid"),
                    "line_number_private_record": line_number,
                    "output_sha256": hashlib.sha256(rendered_message.encode()).hexdigest(),
                }

    required = {
        "orchestration": orchestration,
        "launch": launch,
        "feature_edit": feature_edit,
        "loader_edit": loader_edit,
        "measured_output": measured_output,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(f"private transcript evidence missing: {', '.join(missing)}")
    if launch["timestamp"] != "2026-06-21T05:21:24.293Z":  # type: ignore[index]
        raise ValueError("successful rerun launch timestamp drifted")
    if not orchestration["expands_to_expected_strategy_command"]:  # type: ignore[index]
        raise ValueError("recovered orchestration no longer expands to the expected command")
    if forbidden_edits_during_investment:
        raise ValueError("tracked Edit event occurred while prereg_investment was running")

    return {
        "record_type": "private_local_conversation_record",
        "redistributed": False,
        "sha256": transcript_sha,
        "events": required,
        "tracked_edit_events_during_investment_run": 0,
        "limitation": (
            "Absence of a tracked Edit event is not proof of a globally clean historical "
            "worktree. Source equivalence remains replay-adjudicated."
        ),
    }


def _source_evidence() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", SOURCE_COMMIT + "^{commit}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if commit != SOURCE_COMMIT:
        raise ValueError("source commit resolution drifted")
    post_run_commit = subprocess.run(
        ["git", "rev-parse", POST_RUN_COMMIT + "^{commit}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if post_run_commit != POST_RUN_COMMIT:
        raise ValueError("post-run source commit resolution drifted")
    feature_source = subprocess.run(
        ["git", "show", f"{SOURCE_COMMIT}:src/alphaforge/features/library/equity_fundamental.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if _FEATURE_OLD not in feature_source:
        raise ValueError("pre-run feature patch no longer applies to predecessor commit")
    patched_feature = feature_source.replace(_FEATURE_OLD, _FEATURE_NEW, 1)
    if patched_feature == feature_source:
        raise ValueError("feature patch application was a no-op")
    loader_source = subprocess.run(
        ["git", "show", f"{SOURCE_COMMIT}:scripts/sharadar_load.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if _LOADER_OLD not in loader_source:
        raise ValueError("pre-run loader patch no longer applies to predecessor commit")
    patched_loader = loader_source.replace(_LOADER_OLD, _LOADER_NEW, 1)
    if patched_loader == loader_source:
        raise ValueError("loader patch application was a no-op")
    recovered_paths = (
        "configs/equity.yaml",
        "scripts/sharadar_load.py",
        "src/alphaforge/features/library/equity_fundamental.py",
    )
    recovered_files: dict[str, str] = {}
    for relative in recovered_paths:
        recovered = subprocess.run(
            ["git", "show", f"{POST_RUN_COMMIT}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        recovered_files[relative] = hashlib.sha256(recovered).hexdigest()
    if recovered_files["src/alphaforge/features/library/equity_fundamental.py"] != (
        hashlib.sha256(patched_feature.encode()).hexdigest()
    ):
        raise ValueError("post-run feature file differs beyond the transcript-recovered edit")
    if _LOADER_NEW not in subprocess.run(
        ["git", "show", f"{POST_RUN_COMMIT}:scripts/sharadar_load.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout:
        raise ValueError("post-run loader file omits the transcript-recovered edit")
    return {
        "predecessor_commit": SOURCE_COMMIT,
        "first_post_run_commit": POST_RUN_COMMIT,
        "classification": (
            "PREDECESSOR_COMMIT_PLUS_RUN_CRITICAL_FILES_RECOVERED_FROM_FIRST_POST_RUN_COMMIT"
        ),
        "feature_file_after_patch_sha256": hashlib.sha256(patched_feature.encode()).hexdigest(),
        "loader_file_after_patch_sha256": hashlib.sha256(patched_loader.encode()).hexdigest(),
        "recovered_run_critical_file_sha256": recovered_files,
        "recovery_basis": (
            "The first post-run commit was authored the following morning and contains the "
            "wide-universe profile and complete loader state required by the historical "
            "6,835-equity membership counts. The first clean attempt using only the predecessor "
            "profile failed before strategy execution with 1,050 equities. This correction is "
            "source-lineage adjudication, not a return-threshold or performance regrade."
        ),
        "full_historical_dirty_source_tree_exactly_recovered": False,
        "equivalence_requires_clean_replay": True,
    }


def _artifact_evidence() -> dict[str, Any]:
    actual = {name: _sha256(ARTIFACT / name) for name in EXPECTED_ARTIFACT_HASHES}
    if actual != EXPECTED_ARTIFACT_HASHES:
        raise ValueError("historical prereg_investment root artifact binding drifted")
    walkforward = json.loads((ARTIFACT / "walkforward.json").read_text(encoding="utf-8"))
    config = walkforward["config"]
    summary = walkforward["summary"]
    validation = walkforward["validation"]
    legs = list((ARTIFACT / "legs").glob("leg_*"))
    leg_files = list((ARTIFACT / "legs").glob("leg_*/*"))
    venues: dict[str, int] = {}
    for instrument_id in config["instrument_ids"]:
        venue = str(instrument_id).split(":", 1)[0]
        venues[venue] = venues.get(venue, 0) + 1
    if len(legs) != 86 or len([path for path in leg_files if path.is_file()]) != 774:
        raise ValueError("historical leg inventory drifted")
    return {
        "root_file_sha256": actual,
        "legs": len(legs),
        "leg_files": 774,
        "instrument_ids": len(config["instrument_ids"]),
        "instrument_ids_by_venue": venues,
        "n_days": summary["n_days"],
        "n_periods": summary["n_periods"],
        "historical_metrics_preserved_not_regraded": {
            "sharpe": summary["sharpe"],
            "cagr": summary["cagr"],
            "max_dd": summary["max_dd"],
            "final_equity": summary["final_equity"],
            "dsr": validation["dsr"],
            "n_trials": validation["n_trials"],
        },
    }


def _membership_evidence() -> dict[str, Any]:
    paths = ROOT / "data/lake/universe_membership"
    files = list(paths.glob("instrument_id=XUSE*/year=*/data.parquet"))
    rows = 0
    open_rows = 0
    instrument_ids: set[str] = set()
    starts: list[Any] = []
    ends: list[Any] = []
    for path in files:
        table = pq.ParquetFile(path).read(  # type: ignore[no-untyped-call]
            columns=["instrument_id", "effective_from", "effective_to"]
        )
        values = table.to_pydict()
        rows += table.num_rows
        instrument_ids.update(values["instrument_id"])
        starts.extend(values["effective_from"])
        for value in values["effective_to"]:
            if value is None:
                open_rows += 1
            else:
                ends.append(value)
    measured = {
        "instrument_ids": len(instrument_ids),
        "intervals": rows,
        "open_intervals": open_rows,
    }
    if measured != EXPECTED_MEMBERSHIP:
        raise ValueError(f"surviving XUSE membership state drifted: {measured}")
    return {
        **measured,
        "parquet_files": len(files),
        "min_effective_from": min(starts).isoformat(),
        "max_effective_from": max(starts).isoformat(),
        "max_effective_to": max(ends).isoformat(),
        "matches_original_rebuild_output_counts": True,
    }


def _raw_archive_evidence() -> dict[str, Any]:
    archive_root = ROOT / "data/sharadar_raw"
    run_launched = datetime.fromisoformat(RUN_LAUNCHED_UTC)
    records: list[dict[str, Any]] = []
    for name, (expected_bytes, expected_sha) in sorted(EXPECTED_RAW_ARCHIVES.items()):
        path = archive_root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        actual_sha = _sha256(path)
        if stat.st_size != expected_bytes or actual_sha != expected_sha:
            raise ValueError(f"preserved Sharadar archive binding drifted: {name}")
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if modified_at >= run_launched:
            raise ValueError(f"Sharadar archive does not predate successful rerun: {name}")
        records.append(
            {
                "name": name,
                "bytes": stat.st_size,
                "sha256": actual_sha,
                "filesystem_modified_at_utc": modified_at.isoformat(),
                "predates_successful_rerun": True,
            }
        )
    return {
        "status": "FOUR_LOCAL_LICENSED_BULK_ARCHIVES_HASH_BOUND",
        "files": len(records),
        "bytes": sum(record["bytes"] for record in records),
        "records": records,
        "raw_archives_redistributed": False,
        "hashes_were_precommitted_before_historical_run": False,
        "claim_boundary": (
            "The current local bytes are hash-bound and their filesystem timestamps predate "
            "the run. No pre-run hash commitment survives, so exact historical equivalence "
            "remains clean-replay adjudicated."
        ),
    }


def _market_data_evidence() -> dict[str, Any]:
    connection = duckdb.connect()
    old_day = "2026-06-21"
    ohlcv = connection.execute(
        f"""
        SELECT count(*) AS n, count(DISTINCT instrument_id) AS ids
        FROM read_parquet(
          '{ROOT}/data/lake/ohlcv_1d/instrument_id=XUSE*/year=*/data.parquet',
          hive_partitioning=false)
        WHERE CAST(ingested_at AS DATE) = DATE '{old_day}'
        """
    ).fetchone()
    fundamentals = connection.execute(
        f"""
        SELECT count(*) AS n, count(DISTINCT instrument_id) AS ids
        FROM read_parquet(
          '{ROOT}/data/lake/fundamentals/instrument_id=XUSE*/year=*/data.parquet',
          hive_partitioning=false)
        WHERE CAST(ingested_at AS DATE) = DATE '{old_day}'
        """
    ).fetchone()
    actions_preserved = connection.execute(
        f"""
        SELECT count(*) AS n,
               sum(CASE WHEN action_type='split' THEN 1 ELSE 0 END) AS splits
        FROM read_parquet(
          '{ROOT}/data/lake/corporate_actions/instrument_id=XUSE*/year=*/data.parquet',
          hive_partitioning=false)
        WHERE CAST(ingested_at AS DATE) = DATE '{old_day}'
        """
    ).fetchone()
    if ohlcv is None or fundamentals is None or actions_preserved is None:
        raise ValueError("market-data aggregate query returned no row")
    measured = {
        "ohlcv_rows": int(ohlcv[0]),
        "ohlcv_instrument_ids": int(ohlcv[1]),
        "fundamental_rows_stored": int(fundamentals[0]),
        "fundamental_instrument_ids": int(fundamentals[1]),
    }
    expected_subset = {key: EXPECTED_LOAD[key] for key in measured}
    if measured != expected_subset:
        raise ValueError(f"surviving Sharadar row state drifted: {measured}")
    return {
        "load_ingested_at_utc": LOAD_INGESTED_AT_UTC,
        "preserved_exactly_timestamp_identifiable": measured,
        "loader_reported_counts_from_private_execution_record": {
            "fundamental_rows": EXPECTED_LOAD["fundamental_rows_reported_by_loader"],
            "corporate_action_rows": EXPECTED_LOAD["corporate_action_rows_reported_by_loader"],
            "splits": EXPECTED_LOAD["splits_reported_by_loader"],
        },
        "corporate_actions": {
            "preserved_rows_still_carrying_original_ingestion_date": int(actions_preserved[0]),
            "preserved_splits_still_carrying_original_ingestion_date": int(actions_preserved[1]),
            "raw_actions_archive_locally_preserved": True,
            "classification": "RAW_ARCHIVE_PRESERVED_NORMALIZED_REPLAY_NOT_YET_ADJUDICATED",
            "exact_historical_normalized_input_claimed": False,
        },
        "raw_rows_redistributed": False,
    }


def _ledger_evidence() -> dict[str, Any]:
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line]
    historical = rows[:75]
    if len(historical) != 75 or len({row["config_hash"] for row in historical}) != 75:
        raise ValueError("historical experiment union is not 75 distinct trials")
    target = historical[-1]
    if target["config_hash"] != EXPECTED_LEDGER_HASH or target["now_ms"] != TRIAL_NOW_MS:
        raise ValueError("historical prereg_investment ledger record drifted")
    values = np.asarray([float(row["sharpe_per_period"]) for row in historical], dtype=float)
    numpy_variance = float(np.var(values, ddof=1))
    statistics_variance = statistics.variance(values.tolist())
    if numpy_variance != EXPECTED_LEDGER_VARIANCE:
        raise ValueError("historical NumPy trial variance drifted")
    return {
        "target_line": 75,
        "target_config_hash": target["config_hash"],
        "target_now_ms": target["now_ms"],
        "distinct_trials_through_target": len(historical),
        "numpy_sample_variance": numpy_variance,
        "statistics_sample_variance": statistics_variance,
        "stored_artifact_sample_variance": EXPECTED_LEDGER_VARIANCE,
        "context_reconstructable_without_regrading": True,
    }


def build() -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "canli.alphac-prereg-investment-historical-lineage.v1",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "status": "HISTORICAL_LINEAGE_RECOVERED_UPSTREAM_REPLAY_PENDING",
        "classification": {
            "artifact_role": "HISTORICAL_GATE_INPUT_ONLY",
            "admitted_sleeve": False,
            "valid_execution_of_later_preregistration": False,
            "not_a_sleeve": True,
            "reason": (
                "The run dynamically resolved 6,880 ids and predates the later declaration; "
                "it cannot be relabeled as prospective evidence."
            ),
        },
        "historical_run": {
            "successful_orchestration_launched_utc": RUN_LAUNCHED_UTC,
            "trial_now_ms": TRIAL_NOW_MS,
            "expanded_strategy_command": EXPECTED_COMMAND,
            "command_recovered_from_private_execution_record": True,
        },
        "private_execution_record": _transcript_evidence(),
        "source": _source_evidence(),
        "artifact": _artifact_evidence(),
        "surviving_membership_state": _membership_evidence(),
        "preserved_raw_vendor_archives": _raw_archive_evidence(),
        "surviving_market_data_state": _market_data_evidence(),
        "historical_experiment_context": _ledger_evidence(),
        "replay_gate": {
            "status": "PENDING",
            "historical_source_tree_exact": False,
            "historical_corporate_action_input_exact": False,
            "raw_corporate_action_archive_locally_preserved": True,
            "clean_workspace_replay_completed": False,
            "artifact_equivalence_established": False,
            "required_next_evidence": (
                "Build a rights-withheld private minimal input snapshot, run the recovered "
                "strategy in a clean workspace, and compare every surviving output file and "
                "equity return before changing this status."
            ),
        },
        "rights_and_release": {
            "market_source": "Sharadar SEP/SF1/ACTIONS under the owner's local license",
            "raw_or_normalized_rows_publication_authorized": False,
            "private_conversation_publication_authorized": False,
            "hash_and_aggregate_receipt_may_be_public": True,
        },
        "claim_boundary": (
            "This receipt establishes recoverable lineage and surviving local state. It does "
            "not establish an exact upstream reproduction, independent verification, valid "
            "prospective pre-registration, sleeve admission, or corrected performance. The "
            "stored historical metrics are preserved without regrading."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(OUTPUT.read_text(encoding="utf-8")))
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("published prereg_investment lineage content hash is invalid")
    return document


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
