#!/usr/bin/env python3
"""Replay AlphaMax from sealed reacquired inputs in a pinned clean workspace."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
MANIFEST: Final = ROOT / "artifacts/publication/alphamax_upstream_replay_manifest.json"
OUTPUT: Final = ROOT / "artifacts/publication/alphamax_upstream_clean_workspace.json"
SOURCE_COMMIT: Final = "fd3e930f41b0a62b222ecda4ab83bae21a4ce9f2"
REPLAY_COMMAND: Final = (
    "uv",
    "run",
    "af",
    "research",
    "walkforward",
    "--profile",
    "equity",
    "--start",
    "2022-07-01",
    "--end",
    "2026-06-01",
    "--train-days",
    "252",
    "--test-days",
    "63",
    "--rebalance-bars",
    "63",
    "--allocator",
    "rank",
    "--alphas",
    "eq_mom_252_21",
    "--out",
    "outputs/k30_dn_63",
)


class ReplayCommandError(RuntimeError):
    """Preserve a bounded command record when a clean-workspace stage fails."""

    def __init__(self, record: dict[str, Any]) -> None:
        super().__init__(f"clean-workspace command exited {record['exit_code']}")
        self.record = record


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _validate_manifest(document: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("AlphaMax replay manifest content hash is invalid")
    if document["source_reconstruction"]["commit"] != SOURCE_COMMIT:
        raise ValueError("AlphaMax replay source commit drifted")
    snapshot = ROOT / document["private_input_snapshot"]["path"]
    reference = ROOT / document["private_reference_output"]["path"]
    receipt_binding = document["private_input_snapshot"]["private_inventory_receipt"]
    acquisition_path = ROOT / receipt_binding["path"]
    if _sha256(acquisition_path) != receipt_binding["sha256"]:
        raise ValueError("AlphaMax private acquisition receipt SHA drifted")
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    if acquisition.get("content_hash") != _content_hash(acquisition):
        raise ValueError("AlphaMax private acquisition content hash is invalid")
    if acquisition["content_hash"] != receipt_binding["content_hash"]:
        raise ValueError("AlphaMax private acquisition content binding drifted")
    for record in acquisition["snapshot"]["records"]:
        path = snapshot / record["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise ValueError(f"sealed AlphaMax input drifted: {path}")
    for record in document["private_reference_output"]["records"]:
        path = reference / record["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise ValueError(f"sealed AlphaMax reference output drifted: {path}")
    return snapshot, reference, acquisition


def _safe_extract_git_archive(workspace: Path) -> dict[str, Any]:
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
        "commit": SOURCE_COMMIT,
        "git_archive_sha256": archive_sha,
        "tracked_source_reconstruction": "POST_RUN_COMMIT_OF_PRECOMMIT_CONTENT",
        "full_dirty_historical_source_tree_recovered": False,
    }


def _run(command: list[str], workspace: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    record = {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        "stdout_tail": completed.stdout[-1600:],
        "stderr_tail": completed.stderr[-1600:],
    }
    if completed.returncode:
        raise ReplayCommandError(record)
    return record


def _file_index(directory: Path, *, recursive: bool = True) -> dict[str, dict[str, Any]]:
    paths = directory.rglob("*") if recursive else directory.iterdir()
    return {
        str(path.relative_to(directory)): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(paths)
        if path.is_file()
    }


def _equity_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = pd.read_parquet(reference)
    fresh = pd.read_parquet(replay)
    same_shape = expected.shape == fresh.shape
    expected_equity = expected["equity"].to_numpy(dtype=float)
    fresh_equity = fresh["equity"].to_numpy(dtype=float)
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


def _json_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = json.loads(reference.read_text(encoding="utf-8"))
    fresh = json.loads(replay.read_text(encoding="utf-8"))
    return {
        "document_exact": fresh == expected,
        "config_exact": fresh.get("config") == expected.get("config"),
        "summary_exact": fresh.get("summary") == expected.get("summary"),
        "legs_exact": fresh.get("legs") == expected.get("legs"),
        "validation_exact": fresh.get("validation") == expected.get("validation"),
        "historical_validation": expected.get("validation"),
        "replay_validation": fresh.get("validation"),
        "stored_historical_result_preserved_without_regrading": True,
    }


def execute() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot, reference, acquisition = _validate_manifest(manifest)
    execution_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="alphamax-upstream-") as raw_workspace:
        workspace = Path(raw_workspace).resolve()
        source_binding = _safe_extract_git_archive(workspace)
        expected_archive_sha = manifest["source_reconstruction"]["git_archive_sha256"]
        if source_binding["git_archive_sha256"] != expected_archive_sha:
            raise ValueError("AlphaMax pinned git archive SHA drifted")
        os.symlink(snapshot / "data", workspace / "data", target_is_directory=True)
        shutil.copytree(snapshot / "var", workspace / "var")
        execution_records.append(_run(["uv", "sync", "--frozen"], workspace))
        execution_records.append(_run(list(REPLAY_COMMAND), workspace))

        replay = workspace / "outputs/k30_dn_63"
        reference_index = _file_index(reference, recursive=False)
        replay_root_index = _file_index(replay, recursive=False)
        replay_full_index = _file_index(replay, recursive=True)
        shared = sorted(set(reference_index) & set(replay_root_index))
        different = [
            path
            for path in shared
            if reference_index[path]["sha256"] != replay_root_index[path]["sha256"]
        ]
        output_tree = {
            "surviving_reference_files": len(reference_index),
            "replay_root_files": len(replay_root_index),
            "replay_total_files": len(replay_full_index),
            "root_path_sets_exact": set(reference_index) == set(replay_root_index),
            "byte_exact_surviving_files": len(shared) - len(different),
            "different_surviving_files": different,
            "missing_from_reference_root": sorted(set(replay_root_index) - set(reference_index)),
            "missing_from_replay_root": sorted(set(reference_index) - set(replay_root_index)),
            "historical_leg_files_survived_for_comparison": False,
        }
        equity = _equity_comparison(reference / "equity.parquet", replay / "equity.parquet")
        walkforward = _json_comparison(reference / "walkforward.json", replay / "walkforward.json")

    _validate_manifest(manifest)
    byte_exact = (
        output_tree["root_path_sets_exact"]
        and not output_tree["different_surviving_files"]
        and equity["bytes_exact"]
        and equity["frame_exact"]
        and equity["log_returns_exact"]
        and walkforward["document_exact"]
    )
    numeric_exact = (
        equity["frame_exact"]
        and equity["log_returns_exact"]
        and walkforward["config_exact"]
        and walkforward["summary_exact"]
        and walkforward["validation_exact"]
    )
    if byte_exact:
        status = "PASS_UPSTREAM_REFERENCE_ROOT_BYTE_EXACT_STRATEGY_SUFFICIENT_VENDOR_REACQUISITION"
    elif numeric_exact:
        status = "PASS_UPSTREAM_STRATEGY_NUMERIC_EXACT_STRATEGY_SUFFICIENT_VENDOR_REACQUISITION"
    else:
        status = "FAIL_UPSTREAM_STRATEGY_REPLAY_FRESH_VENDOR_INPUTS_DIFFER"

    document: dict[str, Any] = {
        "schema": "canli.alphac-alphamax-upstream-clean-workspace-receipt.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": status,
        "passes_strategy_reproduction": numeric_exact,
        "surviving_reference_root_byte_exact": byte_exact,
        "strategy_sufficient_fresh_vendor_reacquisition_completed": True,
        "full_historical_universe_lookback_reacquired": False,
        "preserved_historical_raw_input_snapshot": False,
        "full_historical_source_tree_recovered": False,
        "author_clean_workspace_run_not_independent": True,
        "historical_leg_output_available_for_comparison": False,
        "execution": {
            "workspace_outside_repository": True,
            "workspace_destroyed_after_execution": True,
            "repository_strategy_artifacts_mutated_by_replay": False,
            "private_inputs_revalidated_after_replay": True,
            "source": source_binding,
            "records": execution_records,
        },
        "comparison": {
            "output_tree": output_tree,
            "equity_curve": equity,
            "walkforward_json": walkforward,
        },
        "source_bindings": {
            "manifest": {
                "path": str(MANIFEST.relative_to(ROOT)),
                "sha256": _sha256(MANIFEST),
                "content_hash": manifest["content_hash"],
            },
            "private_acquisition_content_hash": acquisition["content_hash"],
            "reference_equity_sha256": manifest["private_reference_output"][
                "equity_parquet_sha256"
            ],
            "source_commit": SOURCE_COMMIT,
        },
        "rights_and_release": manifest["rights_and_release"],
        "claim_boundary": (
            "This author-run clean workspace uses freshly reacquired Polygon inputs from the "
            "first entitled session, 2021-08-23, not a preserved copy of the 2026-06-20 raw "
            "lake. The unavailable 58-session earlier universe lookback is disclosed, so a full "
            "historical universe rebuild is not claimed. Exact strategy reproduction is claimed "
            "only when the equity frame, log returns, config, summary, and historical 27-trial "
            "validation block all match. Byte-exact scope is limited to the five surviving "
            "historical root files; the original per-leg files are unavailable. The stored "
            "historical result is not regraded. This is not redistribution clearance or an "
            "independent human reproduction."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(OUTPUT.read_text(encoding="utf-8")))
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("published AlphaMax clean-workspace receipt content hash is invalid")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    if document["source_bindings"]["manifest"]["sha256"] != _sha256(MANIFEST):
        raise ValueError("published AlphaMax receipt manifest binding drifted")
    return document


def _failure_document(exc: Exception) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": str(exc)[:1000],
    }
    if isinstance(exc, ReplayCommandError):
        detail["command_record"] = exc.record
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphamax-upstream-clean-workspace-receipt.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": "FAIL_UPSTREAM_STRATEGY_REPLAY",
        "passes_strategy_reproduction": False,
        "surviving_reference_root_byte_exact": False,
        "strategy_sufficient_fresh_vendor_reacquisition_completed": False,
        "full_historical_universe_lookback_reacquired": False,
        "preserved_historical_raw_input_snapshot": False,
        "full_historical_source_tree_recovered": False,
        "author_clean_workspace_run_not_independent": True,
        "failure": detail,
        "claim_boundary": (
            "A failed AlphaMax clean-workspace attempt establishes no strategy equivalence, "
            "does not regrade the stored historical result, and does not establish complete "
            "fresh-input reacquisition unless the success receipt explicitly says so."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    try:
        document = execute()
    except Exception as exc:  # a failed replay attempt must leave a fail-closed receipt
        document = _failure_document(exc)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0 if document["passes_strategy_reproduction"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
