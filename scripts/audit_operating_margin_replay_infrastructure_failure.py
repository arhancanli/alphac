#!/usr/bin/env python3
"""Seal the failed symlink-lake replay attempt without calling it a strategy result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from alphaforge.data.store.lake import LakePaths
from alphaforge.data.universe.store import UniverseStore

REPO: Final[Path] = Path(__file__).resolve().parents[1]
IDENTITY: Final[str] = "e5f48adc25065ce9"
SUPPORT: Final[Path] = REPO / "artifacts" / "probe" / "fundamental_single_replays" / IDENTITY
ENVIRONMENT: Final[Path] = SUPPORT / "replay_environment.json"
LAKE_MANIFEST: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"
OUTPUT: Final[Path] = SUPPORT / "replay_infrastructure_failure.json"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build() -> dict[str, Any]:
    environment = json.loads(ENVIRONMENT.read_text(encoding="utf-8"))
    manifest = json.loads(LAKE_MANIFEST.read_text(encoding="utf-8"))
    data = environment.get("data_environment", {})
    if data.get("versioned_correction_content_hash") != manifest.get("content_hash"):
        raise ValueError("failed replay environment does not bind the current lake manifest")
    lake = REPO / str(manifest["corrected_lake"])
    symlinks = [
        name
        for name in ("fundamentals", "ohlcv_1d", "universe_membership")
        if (lake / name).is_symlink()
    ]
    if symlinks != ["fundamentals", "ohlcv_1d", "universe_membership"]:
        raise ValueError(f"unexpected failed-lake symlink layout: {symlinks}")
    intervals = UniverseStore(LakePaths(lake)).read_intervals()
    if intervals.num_rows != 0:
        raise ValueError("the failed symlink lake is now readable; refusing the recorded diagnosis")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-replay-infrastructure-failure.v1",
        "author": "Arhan Canli",
        "hypothesis_key": IDENTITY,
        "run_name": "single_operating_margin",
        "decision": "FAILED_BEFORE_SIMULATION_VERSIONED_LAKE_LAYOUT_UNREADABLE",
        "status": "INFRASTRUCTURE_FAILURE_NO_STRATEGY_RESULT",
        "hypotheses_spent": 0,
        "return_frame_created": False,
        "failure": {
            "exception_type": "ValueError",
            "exception_message": (
                "no universe members overlap the window [946684800000, 1780272000000)"
            ),
            "stage": "SignalService._panel universe membership load",
            "root_cause": (
                "UniverseStore.glob does not traverse a top-level symlinked "
                "universe_membership dataset directory."
            ),
            "universe_rows_visible": intervals.num_rows,
            "symlinked_datasets": symlinks,
        },
        "evidence": {
            "replay_environment_path": str(ENVIRONMENT.relative_to(REPO)),
            "replay_environment_sha256": _sha256(ENVIRONMENT),
            "failed_lake_manifest_path": str(LAKE_MANIFEST.relative_to(REPO)),
            "failed_lake_manifest_sha256": _sha256(LAKE_MANIFEST),
            "failed_lake_manifest": manifest,
        },
        "required_next_action": (
            "Build a new physical lake version with real dataset directories and hard-linked "
            "leaves, verify non-empty universe overlap before replay, preserve this failed version, "
            "and launch at most one replacement replay."
        ),
        "claim_boundary": (
            "This records a physical data-layout failure before signal or return computation. It "
            "is not a strategy trial, does not alter the immutable operating-margin KILL, and "
            "supplies no Sharpe, drawdown, capacity, diversification, or sleeve claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
