#!/usr/bin/env python3
"""Replay historical ``prereg_investment`` from raw archives in a clean workspace."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "data/reproduction/prereg_investment_raw_upstream_20260824"
PRIVATE_RECEIPT: Final = SNAPSHOT / "reconstruction_complete.json"
REFERENCE: Final = (
    ROOT / "artifacts/reproduction_private/prereg_investment_20260621/reference_output"
)
PRIVATE_LOGS: Final = ROOT / "artifacts/reproduction_private/prereg_investment_20260621/replay_logs"
MANIFEST: Final = ROOT / "artifacts/publication/prereg_investment_upstream_replay_manifest.json"
OUTPUT: Final = ROOT / "artifacts/publication/prereg_investment_upstream_clean_workspace.json"
ATTEMPTS: Final = ROOT / "artifacts/publication/prereg_investment_upstream_attempts"
SOURCE_COMMIT: Final = "8417cb850a27306b30f6c70365c3565f3d209ddf"
EXPECTED_XUSE_MEMBERSHIP = {
    "instrument_ids": 6_835,
    "intervals": 11_359,
    "open_intervals": 2_088,
}
EXPECTED_CONFIG_IDS: Final = 6_880
EXPECTED_REFERENCE_FILES: Final = 779
REPLAY_COMMAND: Final = (
    "uv",
    "run",
    "af",
    "research",
    "walkforward",
    "--profile",
    "equity",
    "--allocator",
    "rank",
    "--rebalance-bars",
    "63",
    "--start",
    "2000-01-01",
    "--end",
    "2026-06-01",
    "--train-days",
    "252",
    "--test-days",
    "63",
    "--alphas",
    "eq_asset_growth",
    "--out",
    "outputs/prereg_investment",
)


class ReplayCommandError(RuntimeError):
    def __init__(self, stage: str, record: dict[str, Any]) -> None:
        super().__init__(f"{stage} exited {record['exit_code']}")
        self.stage = stage
        self.record = record


def _load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _extract_source(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
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
    return {
        "predecessor_commit": SOURCE_COMMIT,
        "git_archive_sha256": archive_sha,
    }


def _apply_recovered_patches(workspace: Path, lineage: ModuleType) -> dict[str, str]:
    bindings: dict[str, str] = {}
    lineage_document = json.loads(lineage.OUTPUT.read_text(encoding="utf-8"))
    expected = lineage_document["source"]["recovered_run_critical_file_sha256"]
    for relative, expected_sha in expected.items():
        completed = subprocess.run(
            ["git", "show", f"{lineage.POST_RUN_COMMIT}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(completed.stdout)
        actual = _sha256(path)
        if actual != expected_sha:
            raise ValueError(f"recovered source patch hash drifted: {path}")
        bindings[str(path.relative_to(workspace))] = actual
    return bindings


def _prior_attempts() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not ATTEMPTS.is_dir():
        return records
    for path in sorted(ATTEMPTS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("content_hash") != _content_hash(document):
            raise ValueError(f"prior replay attempt content hash is invalid: {path}")
        records.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path),
                "content_hash": document["content_hash"],
                "executed_at": document["executed_at"],
                "status": document["status"],
                "failure": document.get("failure"),
            }
        )
    return records


def _validate_private_manifest() -> dict[str, Any]:
    seal = _load_script(
        "prereg_investment_seal",
        ROOT / "scripts/seal_prereg_investment_upstream_replay_inputs.py",
    )
    rebuilt = seal.build()
    published = seal.validate_published()
    if rebuilt != published:
        raise ValueError("published input manifest differs from private sealed inputs")
    return cast(dict[str, Any], published)


def _stage_inputs(workspace: Path) -> None:
    private = json.loads(PRIVATE_RECEIPT.read_text(encoding="utf-8"))
    (workspace / "data/sharadar_raw").mkdir(parents=True, exist_ok=True)
    for record in private["raw_vendor_archives"]:
        source = SNAPSHOT / record["path"]
        destination = workspace / "data/sharadar_raw" / source.name
        destination.symlink_to(source)
    shutil.copytree(SNAPSHOT / "data/lake", workspace / "data/lake")
    shutil.copytree(SNAPSHOT / "var", workspace / "var")


def _run(
    stage: str,
    command: list[str],
    workspace: Path,
    attempt_id: str,
) -> dict[str, Any]:
    PRIVATE_LOGS.mkdir(parents=True, exist_ok=True)
    log = PRIVATE_LOGS / f"{attempt_id}_{stage}.log"
    started = datetime.now(UTC)
    with log.open("wb") as handle:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        while True:
            try:
                process.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print(
                    f"{stage} running pid={process.pid} log_bytes={log.stat().st_size}",
                    flush=True,
                )
    finished = datetime.now(UTC)
    output = log.read_text(encoding="utf-8", errors="replace")
    record = {
        "stage": stage,
        "command": " ".join(command),
        "exit_code": int(process.returncode),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "private_log_sha256": _sha256(log),
        "private_log_bytes": log.stat().st_size,
        "output_tail": output[-1200:],
    }
    if process.returncode:
        raise ReplayCommandError(stage, record)
    return record


def _membership_state(workspace: Path) -> dict[str, Any]:
    root = workspace / "data/lake/universe_membership"
    files = list(root.glob("instrument_id=XUSE*/year=*/data.parquet"))
    rows = 0
    open_rows = 0
    xuse_ids: set[str] = set()
    window_ids: set[str] = set()
    for path in files:
        table = pq.ParquetFile(path).read(  # type: ignore[no-untyped-call]
            columns=["instrument_id", "effective_from", "effective_to"]
        )
        values = table.to_pydict()
        rows += table.num_rows
        for instrument_id, effective_from, effective_to in zip(
            values["instrument_id"],
            values["effective_from"],
            values["effective_to"],
            strict=True,
        ):
            xuse_ids.add(str(instrument_id))
            if effective_to is None:
                open_rows += 1
            start_ms = int(effective_from.timestamp() * 1000)
            end_ms = None if effective_to is None else int(effective_to.timestamp() * 1000)
            if start_ms < 1_780_272_000_000 and (end_ms is None or end_ms > 946_684_800_000):
                window_ids.add(str(instrument_id))
    for path in root.glob("instrument_id=BINANCE*/year=*/data.parquet"):
        table = pq.ParquetFile(path).read(  # type: ignore[no-untyped-call]
            columns=["instrument_id", "effective_from", "effective_to"]
        )
        values = table.to_pydict()
        for instrument_id, effective_from, effective_to in zip(
            values["instrument_id"],
            values["effective_from"],
            values["effective_to"],
            strict=True,
        ):
            start_ms = int(effective_from.timestamp() * 1000)
            end_ms = None if effective_to is None else int(effective_to.timestamp() * 1000)
            if start_ms < 1_780_272_000_000 and (end_ms is None or end_ms > 946_684_800_000):
                window_ids.add(str(instrument_id))
    measured = {
        "instrument_ids": len(xuse_ids),
        "intervals": rows,
        "open_intervals": open_rows,
    }
    if measured != EXPECTED_XUSE_MEMBERSHIP:
        raise ValueError(f"replayed XUSE membership state differs: {measured}")
    reference = json.loads((REFERENCE / "walkforward.json").read_text(encoding="utf-8"))
    expected_ids = set(reference["config"]["instrument_ids"])
    if len(window_ids) != EXPECTED_CONFIG_IDS or window_ids != expected_ids:
        raise ValueError("replayed full window-id union differs from the historical artifact")
    return {
        "xuse": measured,
        "full_window_instrument_ids": len(window_ids),
        "full_window_instrument_set_exact": True,
    }


def _file_index(directory: Path) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(directory)): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _equity_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = pd.read_parquet(reference)
    fresh = pd.read_parquet(replay)
    expected_equity = expected["equity"].to_numpy(dtype=float)
    fresh_equity = fresh["equity"].to_numpy(dtype=float)
    same_shape = expected.shape == fresh.shape
    return {
        "reference_sha256": _sha256(reference),
        "replay_sha256": _sha256(replay),
        "bytes_exact": _sha256(reference) == _sha256(replay),
        "shape_reference": list(expected.shape),
        "shape_replay": list(fresh.shape),
        "shape_exact": same_shape,
        "timestamps_exact": expected["ts"].equals(fresh["ts"]),
        "frame_exact": expected.equals(fresh),
        "max_absolute_equity_difference": (
            float(np.max(np.abs(expected_equity - fresh_equity))) if same_shape else None
        ),
        "log_returns_exact": (
            bool(
                np.array_equal(
                    np.diff(np.log(expected_equity)),
                    np.diff(np.log(fresh_equity)),
                )
            )
            if same_shape
            else False
        ),
    }


def _semantic_tree_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected_index = _file_index(reference)
    replay_index = _file_index(replay)
    expected_paths = set(expected_index)
    replay_paths = set(replay_index)
    shared = sorted(expected_paths & replay_paths)
    different = [
        path for path in shared if expected_index[path]["sha256"] != replay_index[path]["sha256"]
    ]
    semantic_differences: list[str] = []
    checked_by_type: dict[str, int] = {}
    for relative in different:
        suffix = Path(relative).suffix.lower()
        checked_by_type[suffix] = checked_by_type.get(suffix, 0) + 1
        expected_path = reference / relative
        replay_path = replay / relative
        if suffix == ".json":
            same = json.loads(expected_path.read_text()) == json.loads(replay_path.read_text())
        elif suffix == ".parquet":
            expected_table = pq.ParquetFile(expected_path).read()  # type: ignore[no-untyped-call]
            replay_table = pq.ParquetFile(replay_path).read()  # type: ignore[no-untyped-call]
            same = expected_table.equals(replay_table)
        elif suffix == ".txt":
            same = expected_path.read_text() == replay_path.read_text()
        elif suffix == ".png":
            with (
                Image.open(expected_path) as expected_image,
                Image.open(replay_path) as replay_image,
            ):
                same = (
                    expected_image.mode == replay_image.mode
                    and expected_image.size == replay_image.size
                    and np.array_equal(np.asarray(expected_image), np.asarray(replay_image))
                )
        else:
            same = False
        if not same:
            semantic_differences.append(relative)
    return {
        "reference_files": len(expected_index),
        "replay_files": len(replay_index),
        "path_sets_exact": expected_paths == replay_paths,
        "byte_exact_files": len(shared) - len(different),
        "different_files": different,
        "missing_from_reference": sorted(replay_paths - expected_paths),
        "missing_from_replay": sorted(expected_paths - replay_paths),
        "semantic_checks_for_byte_differences_by_extension": checked_by_type,
        "semantic_differences": semantic_differences,
    }


def _walkforward_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = json.loads(reference.read_text(encoding="utf-8"))
    fresh = json.loads(replay.read_text(encoding="utf-8"))
    return {
        "config_exact": fresh["config"] == expected["config"],
        "summary_exact": fresh["summary"] == expected["summary"],
        "validation_exact": fresh["validation"] == expected["validation"],
        "legs_exact": fresh["legs"] == expected["legs"],
    }


def execute() -> dict[str, Any]:
    manifest = _validate_private_manifest()
    prior_attempts = _prior_attempts()
    lineage = _load_script(
        "prereg_investment_lineage",
        ROOT / "scripts/build_prereg_investment_historical_lineage.py",
    )
    attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    execution: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="prereg-investment-upstream-") as raw:
        workspace = Path(raw).resolve()
        source = _extract_source(workspace)
        source["recovered_patch_file_sha256"] = _apply_recovered_patches(workspace, lineage)
        source["full_historical_dirty_source_tree_exactly_recovered"] = False
        source["equivalence_is_replay_adjudicated"] = True
        _stage_inputs(workspace)
        execution.append(_run("uv_sync", ["uv", "sync", "--frozen"], workspace, attempt_id))
        execution.append(
            _run(
                "sharadar_load",
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/sharadar_load.py",
                    "--min-dollar",
                    "500000",
                ],
                workspace,
                attempt_id,
            )
        )
        execution.append(
            _run(
                "universe_rebuild",
                [
                    "uv",
                    "run",
                    "af",
                    "universe",
                    "rebuild",
                    "--profile",
                    "equity",
                    "--start",
                    "2000-01-01",
                    "--end",
                    "2026-06-01",
                ],
                workspace,
                attempt_id,
            )
        )
        membership = _membership_state(workspace)
        execution.append(_run("strategy", list(REPLAY_COMMAND), workspace, attempt_id))
        replay = workspace / "outputs/prereg_investment"
        tree = _semantic_tree_comparison(REFERENCE, replay)
        equity = _equity_comparison(REFERENCE / "equity.parquet", replay / "equity.parquet")
        walkforward = _walkforward_comparison(
            REFERENCE / "walkforward.json", replay / "walkforward.json"
        )
        replay_inventory = _file_index(replay)

    _validate_private_manifest()
    semantic_exact = (
        tree["path_sets_exact"]
        and not tree["semantic_differences"]
        and equity["frame_exact"]
        and equity["timestamps_exact"]
        and equity["log_returns_exact"]
        and all(walkforward.values())
    )
    byte_exact = semantic_exact and not tree["different_files"]
    status = (
        "PASS_FULL_RAW_TO_ARTIFACT_BYTE_EXACT"
        if byte_exact
        else (
            "PASS_FULL_RAW_TO_STRATEGY_SEMANTIC_EXACT_NONSEMANTIC_BYTES_DIFFER"
            if semantic_exact
            else "FAIL_FULL_RAW_TO_STRATEGY_REPLAY"
        )
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-prereg-investment-upstream-clean-workspace.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": status,
        "passes_strategy_reproduction": semantic_exact,
        "historical_full_artifact_byte_exact": byte_exact,
        "raw_to_strategy_pipeline_replay_completed": True,
        "historical_full_dirty_source_tree_recovered": False,
        "historical_crypto_membership_intervals_exact": False,
        "author_clean_workspace_run_not_independent": True,
        "fresh_vendor_reacquisition_completed": False,
        "classification": {
            "artifact_role": "HISTORICAL_GATE_INPUT_ONLY",
            "not_a_sleeve": True,
            "later_preregistration_covered_historical_run": False,
        },
        "execution": {
            "attempt_id": attempt_id,
            "prior_attempts": prior_attempts,
            "workspace_outside_repository": True,
            "workspace_destroyed_after_execution": True,
            "repository_historical_artifact_mutated": False,
            "source": source,
            "commands": execution,
            "replay_output_inventory": replay_inventory,
        },
        "input_validation": {
            "validated_before_and_after_replay": True,
            "manifest_path": str(MANIFEST.relative_to(ROOT)),
            "manifest_sha256": _sha256(MANIFEST),
            "manifest_content_hash": manifest["content_hash"],
            "membership_after_raw_rebuild": membership,
            "crypto_membership_classification": manifest["private_input_snapshot"][
                "crypto_membership"
            ]["classification"],
        },
        "comparison": {
            "output_tree": tree,
            "equity_curve": equity,
            "walkforward_json": walkforward,
        },
        "rights_and_release": manifest["rights_and_release"],
        "claim_boundary": (
            "This author-run temporary workspace replayed the recovered raw Sharadar loader, "
            "universe rebuild, and historical strategy command against hash-bound private "
            "inputs. The zero-held Binance memberships are artifact-informed minimal intervals, "
            "so even a passing result establishes strategy-output equivalence, not exact recovery "
            "of every historical input, valid prospective evidence, sleeve admission, or "
            "independent reproduction. Historical metrics are compared, never regraded."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _failure_document(exc: Exception) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": str(exc)[:1000],
    }
    if isinstance(exc, ReplayCommandError):
        detail["failed_stage"] = exc.stage
        detail["command_record"] = exc.record
    document: dict[str, Any] = {
        "schema": "canli.alphac-prereg-investment-upstream-clean-workspace.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": "FAIL_FULL_RAW_TO_STRATEGY_REPLAY",
        "passes_strategy_reproduction": False,
        "historical_full_artifact_byte_exact": False,
        "raw_to_strategy_pipeline_replay_completed": False,
        "author_clean_workspace_run_not_independent": True,
        "failure": detail,
        "prior_attempts": _prior_attempts(),
        "claim_boundary": (
            "A failed attempt establishes no strategy equivalence and does not alter or regrade "
            "the historical artifact."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(OUTPUT.read_text(encoding="utf-8")))
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("published prereg_investment replay receipt content hash is invalid")
    return document


def main() -> int:
    try:
        document = execute()
    except Exception as exc:  # fail receipt must survive any attempted replay stage
        document = _failure_document(exc)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ATTEMPTS.mkdir(parents=True, exist_ok=True)
    attempt_stamp = document["executed_at"].replace(":", "").replace("-", "").replace("+", "_")
    attempt_path = ATTEMPTS / f"{attempt_stamp}_{document['content_hash'][7:19]}.json"
    attempt_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"attempt_receipt: {attempt_path}")
    print(f"content_hash: {document['content_hash']}")
    return 0 if document["passes_strategy_reproduction"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
