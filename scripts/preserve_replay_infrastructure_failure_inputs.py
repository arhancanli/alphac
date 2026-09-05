#!/usr/bin/env python3
"""Recover and preserve the exact inputs bound by the operating-margin layout failure.

The replacement replay legitimately reuses ``replay_environment.json`` and the corrected-lake
builder legitimately advances ``sharadar_hdb_corrected_lake.json``.  The first infrastructure
failure recorded hashes for the earlier bytes but did not copy them to immutable names.  Its
embedded failed manifest plus the replacement environment's unchanged source inventory are
sufficient to reconstruct both original byte streams exactly.  This script refuses to write
unless each reconstruction matches the hash recorded before either mutable path advanced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SUPPORT: Final[Path] = (
    REPO
    / "artifacts"
    / "probe"
    / "fundamental_single_replays"
    / "e5f48adc25065ce9"
)
FAILURE: Final[Path] = SUPPORT / "replay_infrastructure_failure.json"
CURRENT_ENVIRONMENT: Final[Path] = SUPPORT / "replay_environment.json"
PRESERVED_ENVIRONMENT: Final[Path] = SUPPORT / "replay_infrastructure_failure_environment.json"
PRESERVED_MANIFEST: Final[Path] = SUPPORT / "replay_infrastructure_failure_lake_manifest.json"


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _pretty(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def reconstruct() -> tuple[bytes, bytes]:
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    evidence = failure["evidence"]

    failed_manifest = evidence["failed_lake_manifest"]
    manifest_bytes = _pretty(failed_manifest)
    if _sha256_bytes(manifest_bytes) != evidence["failed_lake_manifest_sha256"]:
        raise ValueError("embedded failed manifest does not reconstruct its recorded bytes")

    environment = json.loads(CURRENT_ENVIRONMENT.read_text(encoding="utf-8"))
    data_environment = environment["data_environment"]
    data_environment.update(
        {
            "lake_dir": failed_manifest["corrected_lake"],
            "kind": "VERSIONED_SHARADAR_HDB_ZERO_MARKER_QUARANTINE",
            "versioned_correction_manifest": (
                "artifacts/audit/sharadar_hdb_corrected_lake.json"
            ),
            "versioned_correction_manifest_sha256": evidence[
                "failed_lake_manifest_sha256"
            ].removeprefix("sha256:"),
            "versioned_correction_content_hash": failed_manifest["content_hash"],
            "corrected_corporate_actions_root": failed_manifest["lineage"][
                "corrected_corporate_actions_root"
            ],
            "rows_quarantined": failed_manifest["correction"]["rows_quarantined"],
            "cash_amount_imputed": failed_manifest["correction"]["cash_amount_imputed"],
        }
    )
    environment.pop("content_hash", None)
    canonical = json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
    environment["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    environment_bytes = _pretty(environment)
    if _sha256_bytes(environment_bytes) != evidence["replay_environment_sha256"]:
        raise ValueError("failed replay environment cannot be reconstructed exactly")
    return environment_bytes, manifest_bytes


def main() -> int:
    environment_bytes, manifest_bytes = reconstruct()
    PRESERVED_ENVIRONMENT.write_bytes(environment_bytes)
    PRESERVED_MANIFEST.write_bytes(manifest_bytes)
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    evidence = failure["evidence"]
    evidence["preserved_replay_environment_path"] = str(
        PRESERVED_ENVIRONMENT.relative_to(REPO)
    )
    evidence["preserved_replay_environment_sha256"] = _sha256_bytes(environment_bytes)
    evidence["preserved_failed_lake_manifest_path"] = str(PRESERVED_MANIFEST.relative_to(REPO))
    evidence["preserved_failed_lake_manifest_sha256"] = _sha256_bytes(manifest_bytes)
    failure.pop("content_hash", None)
    canonical = json.dumps(failure, sort_keys=True, separators=(",", ":")).encode()
    failure["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    FAILURE.write_bytes(_pretty(failure))
    print(f"wrote {PRESERVED_ENVIRONMENT.relative_to(REPO)}")
    print(f"wrote {PRESERVED_MANIFEST.relative_to(REPO)}")
    print(f"amended {FAILURE.relative_to(REPO)} with immutable recovery paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
