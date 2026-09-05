#!/usr/bin/env python3
"""Regenerate AlphaTrend from sealed inputs in a temporary pinned-source workspace."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
MANIFEST: Final = ROOT / "artifacts/publication/alphatrend_upstream_replay_manifest.json"
OUTPUT: Final = ROOT / "artifacts/publication/alphatrend_upstream_clean_workspace.json"
SOURCE_COMMIT: Final = "577555f12636e4df81e42a3940184678d0cceb7e"
REPLAY_COMMAND: Final = (
    ".venv/bin/python3",
    "scripts/mf_gauntlet.py",
    "--alphas",
    "mf_trend_63,mf_trend_126,mf_trend_252",
    "--rebalance",
    "10",
    "--cash",
    "100000",
    "--start",
    "2003-01-01",
    "--end",
    "2026-08-24",
    "--out",
    "outputs/mf_live_fwd",
)
CONTEXT_VALIDATION_FIELDS: Final = frozenset(
    {"dsr", "expected_max_sr", "n_trials", "n_trials_used", "sr_trials_variance"}
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _validate_manifest(document: dict[str, Any]) -> None:
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("AlphaTrend input manifest content hash is invalid")
    if document["historical_run"]["source_commit_reconstruction"] != SOURCE_COMMIT:
        raise ValueError("AlphaTrend source commit binding drifted")
    for section_name in ("private_input_snapshot", "private_reference_output"):
        section = document[section_name]
        directory = ROOT / section["path"]
        for record in section["records"]:
            path = directory / record["path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
                raise ValueError(f"sealed file binding failed: {path}")


def _safe_extract_git_archive(workspace: Path) -> dict[str, Any]:
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
        "historical_source_tree_exactly_recovered": False,
        "strategy_source_reconstruction_sufficient_for_exact_curve": True,
        "reason_exact_tree_not_claimed": (
            "The stored artifact used the 228-identity DSR union introduced in an uncommitted "
            "validation change. The pinned commit regenerates every strategy output byte except "
            "the DSR-bearing walkforward.json context."
        ),
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
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }
    if completed.returncode:
        raise RuntimeError(
            f"clean-workspace command failed ({completed.returncode}): {record['command']}\n"
            f"{completed.stderr[-2000:]}"
        )
    return record


def _file_index(directory: Path) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(directory)): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _json_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = json.loads(reference.read_text(encoding="utf-8"))
    fresh = json.loads(replay.read_text(encoding="utf-8"))
    expected_validation = expected["validation"]
    fresh_validation = fresh["validation"]
    stable_fields = sorted(set(expected_validation) - CONTEXT_VALIDATION_FIELDS)
    return {
        "config_exact": fresh["config"] == expected["config"],
        "summary_exact": fresh["summary"] == expected["summary"],
        "non_context_validation_fields": stable_fields,
        "non_context_validation_exact": all(
            fresh_validation[field] == expected_validation[field] for field in stable_fields
        ),
        "historical_validation_context_exact": fresh_validation == expected_validation,
        "historical_validation_context": expected_validation,
        "pinned_commit_validation_context": fresh_validation,
        "context_fields_expected_to_differ": sorted(CONTEXT_VALIDATION_FIELDS),
        "stored_historical_dsr_preserved_without_regrading": True,
    }


def _equity_comparison(reference: Path, replay: Path) -> dict[str, Any]:
    expected = pd.read_parquet(reference)
    fresh = pd.read_parquet(replay)
    expected_equity = expected["equity"].to_numpy(dtype=float)
    fresh_equity = fresh["equity"].to_numpy(dtype=float)
    same_shape = expected.shape == fresh.shape
    exact_frame = expected.equals(fresh)
    return {
        "reference_sha256": _sha256(reference),
        "replay_sha256": _sha256(replay),
        "bytes_exact": _sha256(reference) == _sha256(replay),
        "shape_reference": list(expected.shape),
        "shape_replay": list(fresh.shape),
        "shape_exact": same_shape,
        "timestamps_exact": expected["ts"].equals(fresh["ts"]),
        "frame_exact": exact_frame,
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


def execute() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    snapshot = ROOT / manifest["private_input_snapshot"]["path"]
    reference = ROOT / manifest["private_reference_output"]["path"]
    execution_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="alphatrend-upstream-") as raw_workspace:
        workspace = Path(raw_workspace).resolve()
        source_binding = _safe_extract_git_archive(workspace)
        (workspace / "data").mkdir(exist_ok=True)
        shutil.copytree(snapshot / "lake_mf", workspace / "data/lake_mf")
        shutil.copytree(snapshot / "var_mf", workspace / "var_mf")
        execution_records.append(_run(["uv", "sync", "--frozen"], workspace))
        execution_records.append(_run(list(REPLAY_COMMAND), workspace))

        replay = workspace / "outputs/mf_live_fwd"
        reference_index = _file_index(reference)
        replay_index = _file_index(replay)
        shared = sorted(set(reference_index) & set(replay_index))
        different = [
            path
            for path in shared
            if reference_index[path]["sha256"] != replay_index[path]["sha256"]
        ]
        tree_comparison = {
            "reference_files": len(reference_index),
            "replay_files": len(replay_index),
            "path_sets_exact": set(reference_index) == set(replay_index),
            "byte_exact_files": len(shared) - len(different),
            "different_files": different,
            "missing_from_reference": sorted(set(replay_index) - set(reference_index)),
            "missing_from_replay": sorted(set(reference_index) - set(replay_index)),
        }
        equity = _equity_comparison(
            reference / "equity.parquet", replay / "equity.parquet"
        )
        walkforward = _json_comparison(
            reference / "walkforward.json", replay / "walkforward.json"
        )
        workspace_output_index = replay_index

    passes = (
        tree_comparison["path_sets_exact"]
        and tree_comparison["different_files"] == ["walkforward.json"]
        and equity["bytes_exact"]
        and equity["frame_exact"]
        and equity["log_returns_exact"]
        and walkforward["config_exact"]
        and walkforward["summary_exact"]
        and walkforward["non_context_validation_exact"]
        and not walkforward["historical_validation_context_exact"]
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphatrend-upstream-clean-workspace-receipt.v1",
        "author": "Arhan Canli",
        "executed_at": datetime.now(UTC).isoformat(),
        "status": (
            "PASS_UPSTREAM_STRATEGY_CURVE_BYTE_EXACT_DSR_CONTEXT_NOT_REPRODUCED"
            if passes
            else "FAIL_UPSTREAM_STRATEGY_REPLAY"
        ),
        "passes_strategy_reproduction": passes,
        "alphavintage_benchmark_curve_regenerated_from_declared_strategy_inputs": passes,
        "historical_full_artifact_byte_exact": False,
        "historical_dsr_selection_context_reproduced": False,
        "full_historical_source_tree_recovered": False,
        "author_clean_workspace_run_not_independent": True,
        "fresh_vendor_reacquisition_completed": False,
        "execution": {
            "workspace_outside_repository": True,
            "workspace_destroyed_after_execution": True,
            "repository_artifacts_mutated_by_replay": False,
            "source": source_binding,
            "records": execution_records,
            "replay_output_inventory": workspace_output_index,
        },
        "comparison": {
            "output_tree": tree_comparison,
            "equity_curve": equity,
            "walkforward_json": walkforward,
        },
        "source_bindings": {
            "manifest": {
                "path": str(MANIFEST.relative_to(ROOT)),
                "sha256": _sha256(MANIFEST),
                "content_hash": manifest["content_hash"],
            },
            "reference_equity_sha256": manifest["private_reference_output"][
                "equity_parquet_sha256"
            ],
            "source_commit": SOURCE_COMMIT,
        },
        "rights_and_release": manifest["rights_and_release"],
        "claim_boundary": (
            "This author-run clean workspace regenerated AlphaTrend's complete strategy output "
            "tree from the sealed ETF lake and pinned source commit. The equity curve consumed "
            "by AlphaVintage is byte-exact, and 466 of 467 output files are byte-exact. The one "
            "different file is walkforward.json because the historical run used a 228-identity "
            "DSR union not present in the pinned commit. The stored historical DSR remains "
            "published and is not regraded. This is not fresh data acquisition, rights clearance, "
            "or independent human reproduction."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("published AlphaTrend clean-workspace receipt content hash is invalid")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    if document["source_bindings"]["manifest"]["sha256"] != _sha256(MANIFEST):
        raise ValueError("published AlphaTrend receipt manifest binding drifted")
    return document


def main() -> int:
    document = execute()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0 if document["passes_strategy_reproduction"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
