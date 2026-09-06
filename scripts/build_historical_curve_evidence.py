#!/usr/bin/env python3
"""Publish independently checkable curve evidence for uniquely bound legacy trials."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import numpy as np
import pandas as pd

from alphaforge.validation.legacy_epoch import load_legacy_identity_keys

REPO: Final[Path] = Path(__file__).resolve().parent.parent
ARTIFACT_DIR: Final[Path] = REPO / "artifacts" / "research" / "historical_curve_evidence"
HOST_DIRS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / "historical-curves",
    REPO.parent / "meridian-app" / "public" / "glassbox" / "historical-curves",
)
INDEX_NAME: Final[str] = "index.json"
LEGACY_EPOCH_CLOSURE: Final[Path] = (
    REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
)
ANNUALIZATION_DAYS: Final[int] = 365


def _recoverability_module() -> ModuleType:
    path = REPO / "scripts" / "audit_identity_packet_recoverability.py"
    spec = importlib.util.spec_from_file_location("historical_curve_recoverability", path)
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


def _load_sealed_evidence() -> tuple[dict[str, dict[str, Any]], dict[str, Any]] | None:
    """Load the closure-bound curve tree without rebinding it to an appended ledger."""
    if not LEGACY_EPOCH_CLOSURE.is_file():
        return None
    load_legacy_identity_keys(REPO)
    closure = json.loads(LEGACY_EPOCH_CLOSURE.read_text(encoding="utf-8"))
    binding = closure.get("source_bindings", {}).get("historical_curve_index", {})
    index_path = ARTIFACT_DIR / INDEX_NAME
    if binding.get("path") != str(index_path.relative_to(REPO)) or not index_path.is_file():
        raise ValueError("sealed historical curve index is missing")
    if _sha256(index_path) != binding.get("sha256"):
        raise ValueError("sealed historical curve index file hash mismatch")
    index: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
    claimed_index_hash = index.pop("content_hash", None)
    observed_index_hash = _content_hash(index)
    index["content_hash"] = claimed_index_hash
    if claimed_index_hash != observed_index_hash or claimed_index_hash != binding.get(
        "content_hash"
    ):
        raise ValueError("sealed historical curve index content hash mismatch")
    rows = index.get("curves")
    if not isinstance(rows, list) or len(rows) != 37:
        raise ValueError("sealed historical curve index must contain exactly 37 curves")
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get("hypothesis_key")
        if not isinstance(identity, str) or identity in evidence:
            raise ValueError("sealed historical curve identity is invalid or duplicated")
        path = ARTIFACT_DIR / identity / "evidence.json"
        if _sha256(path) != row.get("file_sha256"):
            raise ValueError(f"{identity}: sealed historical curve file hash mismatch")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        claimed = payload.pop("content_hash", None)
        observed = _content_hash(payload)
        payload["content_hash"] = claimed
        if claimed != observed or claimed != row.get("content_hash"):
            raise ValueError(f"{identity}: sealed historical curve content hash mismatch")
        evidence[identity] = payload
    return evidence, index


def _source_path(item: dict[str, Any]) -> Path:
    relative = item.get("path")
    expected = item.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise ValueError("curve evidence source requires path and sha256")
    path = (REPO / relative).resolve()
    try:
        path.relative_to(REPO.resolve())
    except ValueError as error:
        raise ValueError(f"curve evidence source escapes repository: {relative}") from error
    if not path.is_file() or _sha256(path) != expected:
        raise ValueError(f"curve evidence source hash mismatch: {relative}")
    return path


def _curve_evidence(identity: str, assessment: dict[str, Any]) -> dict[str, Any]:
    blockers = assessment.get("blockers", [])
    binding = next(
        (
            item
            for item in blockers
            if item.get("code") == "EXACT_ARTIFACT_LACKS_ORIGINAL_ENVIRONMENT_STAMP"
        ),
        None,
    )
    if binding is None or len(binding.get("evidence", [])) != 3:
        raise ValueError(f"{identity}: exact artifact binding is incomplete")
    walkforward_item, equity_item, ledger_item = binding["evidence"]
    walkforward_path = _source_path(walkforward_item)
    equity_path = _source_path(equity_item)
    _source_path(ledger_item)

    walkforward = json.loads(walkforward_path.read_text(encoding="utf-8"))
    validation = walkforward.get("validation")
    if not isinstance(validation, dict):
        raise ValueError(f"{identity}: walk-forward validation is missing")
    stored_sharpe = validation.get("sr_ann")
    stored_observations = validation.get("n_obs")
    if not isinstance(stored_sharpe, (int, float)) or not isinstance(stored_observations, int):
        raise ValueError(f"{identity}: walk-forward measurement is malformed")

    frame = pd.read_parquet(equity_path)
    if list(frame.columns) != ["ts", "equity"] or len(frame) < 3:
        raise ValueError(f"{identity}: unsupported equity schema")
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["ts"], unit="ms", utc=True))
    equity = pd.Series(frame["equity"].to_numpy(dtype=float), index=timestamps)
    if (
        timestamps.has_duplicates
        or not timestamps.is_monotonic_increasing
        or not np.isfinite(equity.to_numpy()).all()
        or (equity <= 0).any()
    ):
        raise ValueError(f"{identity}: equity curve fails structural validation")

    median_step = timestamps.diff().dropna().median()
    if median_step == pd.Timedelta(hours=1):
        sampled = equity.resample("1D").last()
        sampling_rule = "UTC_CALENDAR_DAY_LAST_FROM_HOURLY_EQUITY"
    elif median_step == pd.Timedelta(days=1):
        sampled = equity
        sampling_rule = "PRESERVED_DAILY_EQUITY"
    else:
        raise ValueError(f"{identity}: unsupported median equity interval: {median_step}")
    returns = sampled.pct_change().dropna()
    if len(returns) != stored_observations or returns.std(ddof=1) <= 0:
        raise ValueError(f"{identity}: return observation count or variance mismatch")
    recomputed_sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(ANNUALIZATION_DAYS))
    if not math.isclose(recomputed_sharpe, float(stored_sharpe), abs_tol=1e-12):
        raise ValueError(
            f"{identity}: recomputed Sharpe diverges: {recomputed_sharpe} != {stored_sharpe}"
        )
    drawdown = sampled / sampled.cummax() - 1.0
    public_root = f"/glassbox/historical-curves/{identity}"
    payload: dict[str, Any] = {
        "schema": "canli.alphac-historical-curve-evidence.v1",
        "evidence_date": "2026-08-23",
        "hypothesis_key": identity,
        "config_hash": assessment["config_hash"],
        "author": "Arhan Canli",
        "claim_boundary": (
            "This artifact proves preservation and deterministic recomputation of one historical "
            "curve measurement. It is not preregistration, current reproduction, admission, live "
            "performance, or evidence that the full trial packet is complete."
        ),
        "source_files": {
            "walkforward": {
                "repository_path": walkforward_item["path"],
                "public_path": f"{public_root}/walkforward.json",
                "sha256": walkforward_item["sha256"],
            },
            "equity": {
                "repository_path": equity_item["path"],
                "public_path": f"{public_root}/equity.parquet",
                "sha256": equity_item["sha256"],
            },
            "ledger": {
                "repository_path": ledger_item["path"],
                "sha256": ledger_item["sha256"],
                "config_hash": ledger_item["config_hash"],
            },
        },
        "curve_structure": {
            "raw_equity_points": len(equity),
            "sampled_equity_points": len(sampled),
            "return_observations": len(returns),
            "first_timestamp": sampled.index[0].isoformat(),
            "last_timestamp": sampled.index[-1].isoformat(),
            "median_source_interval_seconds": int(median_step.total_seconds()),
            "sampling_rule": sampling_rule,
        },
        "measurement": {
            "annualization_days": ANNUALIZATION_DAYS,
            "stored_annualized_sharpe": float(stored_sharpe),
            "recomputed_annualized_sharpe": recomputed_sharpe,
            "sharpe_absolute_difference": abs(recomputed_sharpe - float(stored_sharpe)),
            "total_return": float(sampled.iloc[-1] / sampled.iloc[0] - 1.0),
            "maximum_drawdown": float(drawdown.min()),
            "maximum_drawdown_magnitude": float(-drawdown.min()),
        },
        "verification": {
            "source_hashes_match": True,
            "observation_count_matches": True,
            "annualized_sharpe_matches_within_1e_12": True,
            "full_packet_section_verified": False,
            "remaining_result_section_debt": [
                "uncertainty suite",
                "stress suite",
                "capacity evidence",
                "canonical diversification evidence",
            ],
        },
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def build_evidence() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    sealed = _load_sealed_evidence()
    if sealed is not None:
        return sealed
    audit = _recoverability_module().build_audit()
    selected = {
        identity: assessment
        for identity, assessment in audit["identities"].items()
        if assessment.get("artifact_recoverability_class") == "UNIQUE_EXACT_ARTIFACT_BINDING"
    }
    if len(selected) != 37:
        raise ValueError(f"expected 37 unique exact artifact bindings, found {len(selected)}")
    evidence = {
        identity: _curve_evidence(identity, assessment)
        for identity, assessment in sorted(selected.items())
    }
    rows = []
    for identity, payload in evidence.items():
        serialized = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        rows.append(
            {
                "hypothesis_key": identity,
                "config_hash": payload["config_hash"],
                "public_path": f"/glassbox/historical-curves/{identity}/evidence.json",
                "content_hash": payload["content_hash"],
                "file_sha256": hashlib.sha256(serialized).hexdigest(),
                "walkforward_sha256": payload["source_files"]["walkforward"]["sha256"],
                "equity_sha256": payload["source_files"]["equity"]["sha256"],
            }
        )
    index: dict[str, Any] = {
        "schema": "canli.alphac-historical-curve-evidence-index.v1",
        "evidence_date": "2026-08-23",
        "claim_boundary": (
            "Exactly 37 legacy identities have one uniquely matched curve artifact. These "
            "historical curve proofs are partial packet evidence and make no forward-return claim."
        ),
        "summary": {
            "unique_exact_artifact_bindings": len(rows),
            "sharpe_recomputations_matched": sum(
                item["verification"]["annualized_sharpe_matches_within_1e_12"]
                for item in evidence.values()
            ),
            "complete_trial_packets_created": 0,
        },
        "curves": rows,
    }
    index["content_hash"] = _content_hash(index)
    return evidence, index


def main() -> int:
    evidence, index = build_evidence()
    destinations = (ARTIFACT_DIR, *HOST_DIRS)
    for root in destinations:
        root.mkdir(parents=True, exist_ok=True)
        for identity, payload in evidence.items():
            directory = root / identity
            directory.mkdir(parents=True, exist_ok=True)
            assessment = payload["source_files"]
            shutil.copyfile(
                REPO / assessment["walkforward"]["repository_path"],
                directory / "walkforward.json",
            )
            shutil.copyfile(
                REPO / assessment["equity"]["repository_path"],
                directory / "equity.parquet",
            )
            (directory / "evidence.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        (root / INDEX_NAME).write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"historical curve evidence: {len(evidence)} exact Sharpe recomputations published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
