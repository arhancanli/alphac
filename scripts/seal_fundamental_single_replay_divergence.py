#!/usr/bin/env python3
"""Seal a completed fundamental replay that failed exact reproduction.

This command never runs a backtest.  It verifies the already-written replay,
the frozen source environment, corrected-lake lineage, and immutable first
measurement, then records a fail-closed divergence receipt.  A divergent
replay is diagnostic evidence only and cannot be promoted as a new result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent


def _runner_module() -> ModuleType:
    path = REPO / "scripts" / "replay_fundamental_single_identity.py"
    spec = importlib.util.spec_from_file_location("fundamental_replay_contract", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _curve_comparison(original_path: Path, replay_path: Path) -> dict[str, Any]:
    original = pd.read_parquet(original_path)
    replay = pd.read_parquet(replay_path)
    if list(original.columns) != list(replay.columns):
        raise ValueError("replay curve columns differ; numeric divergence cannot be compared")
    if len(original) != len(replay):
        raise ValueError("replay curve row count differs; numeric divergence cannot be compared")
    if "equity" not in original or "ts" not in original:
        raise ValueError("expected ts and equity columns in replay curves")

    original_ts = original["ts"].to_numpy()
    replay_ts = replay["ts"].to_numpy()
    timestamps_equal = bool(np.array_equal(original_ts, replay_ts))
    left = original["equity"].to_numpy(dtype="float64")
    right = replay["equity"].to_numpy(dtype="float64")
    equal = np.equal(left, right)
    mismatch = np.flatnonzero(~equal)
    if mismatch.size == 0:
        raise ValueError("curves match exactly; a divergence receipt would be false")
    first = int(mismatch[0])
    absolute = np.abs(right - left)
    denominator = np.maximum(np.abs(left), np.finfo("float64").tiny)
    relative = absolute / denominator
    return {
        "rows": len(original),
        "timestamps_equal": timestamps_equal,
        "equity_values_equal": False,
        "equity_mismatch_count": int(mismatch.size),
        "equity_mismatch_fraction": float(mismatch.size / len(original)),
        "first_mismatch_row": first,
        "first_mismatch_ts": int(original_ts[first]),
        "original_equity_at_first_mismatch": float(left[first]),
        "replay_equity_at_first_mismatch": float(right[first]),
        "maximum_absolute_equity_difference": float(np.nanmax(absolute)),
        "maximum_relative_equity_difference": float(np.nanmax(relative)),
    }


def seal(run_name: str, *, lake_dir: Path) -> dict[str, Any]:
    runner = _runner_module()
    audit = runner.preflight(run_name, lake_dir=lake_dir)
    identity = audit["hypothesis_key"]
    replay_dir = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
    environment_path = replay_dir / "replay_environment.json"
    replay_artifact_path = replay_dir / "walkforward.json"
    replay_equity_path = replay_dir / "equity.parquet"
    for path in (environment_path, replay_artifact_path, replay_equity_path):
        if not path.is_file():
            relative = path.relative_to(REPO)
            raise FileNotFoundError(f"completed replay evidence is missing: {relative}")

    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    current_environment = runner._source_environment(lake_dir)
    if environment.get("content_hash") != current_environment.get("content_hash"):
        raise ValueError("source environment no longer matches the completed replay")
    replay_artifact = json.loads(replay_artifact_path.read_text(encoding="utf-8"))
    original_artifact = audit["artifact"]
    comparison = _curve_comparison(
        audit["artifact_dir"] / "equity.parquet",
        replay_equity_path,
    )
    summary_equal = replay_artifact.get("summary") == original_artifact.get("summary")
    if summary_equal:
        raise ValueError("summary matches despite curve divergence; manual audit required")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-fundamental-single-replay-divergence.v1",
        "status": "FAILED_CLOSED",
        "decision": "EXACT_REPRODUCTION_FAILED",
        "packet_status": "INCOMPLETE",
        "evidence_date": "2026-08-23",
        "author": "Arhan Canli",
        "run_name": run_name,
        "hypothesis_key": identity,
        "hypotheses_spent": 0,
        "exact_first_measurement_reproduced": False,
        "comparison": {
            "summary_equal": summary_equal,
            **comparison,
        },
        "immutable_first_measurement": {
            "annualized_sharpe": audit["record"].sharpe_ann,
            "maximum_drawdown": original_artifact["summary"]["max_dd"],
            "final_equity": original_artifact["summary"]["final_equity"],
        },
        "quarantined_replay_diagnostic": {
            "annualized_sharpe": replay_artifact["summary"]["sharpe"],
            "maximum_drawdown": replay_artifact["summary"]["max_dd"],
            "final_equity": replay_artifact["summary"]["final_equity"],
            "eligible_for_admission": False,
        },
        "evidence": {
            "preserved_walkforward_path": str(audit["artifact_path"].relative_to(REPO)),
            "preserved_walkforward_sha256": "sha256:" + _sha256(audit["artifact_path"]),
            "preserved_equity_path": str(
                (audit["artifact_dir"] / "equity.parquet").relative_to(REPO)
            ),
            "preserved_equity_sha256": "sha256:"
            + _sha256(audit["artifact_dir"] / "equity.parquet"),
            "replay_walkforward_path": str(replay_artifact_path.relative_to(REPO)),
            "replay_walkforward_sha256": "sha256:" + _sha256(replay_artifact_path),
            "replay_equity_path": str(replay_equity_path.relative_to(REPO)),
            "replay_equity_sha256": "sha256:" + _sha256(replay_equity_path),
            "replay_environment_path": str(environment_path.relative_to(REPO)),
            "replay_environment_sha256": "sha256:" + _sha256(environment_path),
            "source_environment_content_hash": environment["content_hash"],
            "data_environment": environment["data_environment"],
            "runner_invoked_without_experiment_logging": True,
            "current_ledger_state": runner._ledger_state(),
        },
        "required_next_action": (
            "Investigate why the current corrected-data/current-code replay diverges from the "
            "immutable first measurement. Do not rerun variants, promote the diagnostic curve, "
            "or mark the packet complete unless exact lineage and equality are established."
        ),
        "claim_boundary": (
            "This receipt proves a completed zero-new-hypothesis replay failed exact equality. "
            "The replay metrics are quarantined diagnostics, not a new trial, validated result, "
            "Sharpe claim, admission claim, or evidence of future performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    output = replay_dir / "replay_failure.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_name")
    parser.add_argument("--lake-dir", required=True, type=Path)
    args = parser.parse_args()
    lake_dir = args.lake_dir if args.lake_dir.is_absolute() else REPO / args.lake_dir
    print(json.dumps(seal(args.run_name, lake_dir=lake_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
