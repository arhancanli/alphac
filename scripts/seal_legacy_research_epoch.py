#!/usr/bin/env python3
"""Retire the legacy return-identity epoch without forgiving its evidence debt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
MANIFEST: Final[Path] = REPO / "artifacts" / "research" / "trial_packet_manifest.json"
PACKET_INDEX: Final[Path] = REPO / "artifacts" / "research" / "trial_packets" / "index.json"
RECOVERABILITY: Final[Path] = (
    REPO / "artifacts" / "research" / "identity_packet_recoverability.json"
)
CURVE_INDEX: Final[Path] = (
    REPO / "artifacts" / "research" / "historical_curve_evidence" / "index.json"
)
OUT: Final[Path] = REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUT.name,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_hashed(path: Path, schema: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != schema:
        raise ValueError(f"unexpected schema: {path.relative_to(REPO)}")
    claimed = payload.pop("content_hash", None)
    if claimed != _content_hash(payload):
        raise ValueError(f"content hash mismatch: {path.relative_to(REPO)}")
    payload["content_hash"] = claimed
    return payload


def build_closure() -> dict[str, Any]:
    manifest = _load_hashed(MANIFEST, "canli.alphac-trial-packet-manifest.v2")
    packet_index = _load_hashed(
        PACKET_INDEX, "canli.alphac-identity-trial-packet-index.v2"
    )
    recoverability = _load_hashed(
        RECOVERABILITY, "canli.alphac-identity-packet-recoverability.v1"
    )
    curve_index = _load_hashed(
        CURVE_INDEX, "canli.alphac-historical-curve-evidence-index.v1"
    )
    summary = manifest["summary"]
    if summary != {
        **summary,
        "distinct_hypothesis_identities": 228,
        "complete_trial_packets": 2,
        "incomplete_trial_packets": 226,
        "published_identity_packets": 228,
        "audited_not_currently_completable": 221,
        "audited_exact_replay_candidates": 0,
        "audited_exact_replays_failed_data_quality": 4,
        "audited_exact_replays_failed_reproduction": 0,
        "audited_corrected_reproductions_kill_preserved": 1,
        "incomplete_not_yet_audited": 0,
        "coverage_status": "INCOMPLETE_BACKFILL_REQUIRED",
    }:
        raise ValueError("trial packet manifest is not the fully audited 228-identity snapshot")
    manifest_rows = {item["hypothesis_key"]: item for item in manifest["identities"]}
    packet_rows = {item["hypothesis_key"]: item for item in packet_index["packets"]}
    if len(manifest_rows) != 228 or set(manifest_rows) != set(packet_rows):
        raise ValueError("manifest and packet index identity sets differ")

    identities = []
    for identity in sorted(manifest_rows):
        manifest_row = manifest_rows[identity]
        packet_row = packet_rows[identity]
        if (
            manifest_row["identity_packet_content_hash"]
            != packet_row["packet_content_hash"]
            or manifest_row["config_hash"] != packet_row["config_hash"]
        ):
            raise ValueError(f"{identity}: manifest-to-packet binding mismatch")
        complete = bool(packet_row["complete"])
        identities.append(
            {
                "hypothesis_key": identity,
                "config_hash": packet_row["config_hash"],
                "packet_content_hash": packet_row["packet_content_hash"],
                "packet_file_sha256": packet_row["packet_file_sha256"],
                "completion_assessment_status": packet_row[
                    "completion_assessment_status"
                ],
                "packet_complete": complete,
                "disposition": (
                    "RETIRED_COMPLETE_EVIDENCED_KILL"
                    if complete
                    else "RETIRED_INCOMPLETE_EVIDENCE_DEBT"
                ),
                "eligible_for_admission": False,
                "identity_reuse_permitted": False,
            }
        )

    payload: dict[str, Any] = {
        "schema": "canli.alphac-legacy-research-epoch-closure.v1",
        "status": "LEGACY_EPOCH_RETIRED_FAIL_CLOSED",
        "evidence_date": "2026-08-23",
        "epoch_id": "legacy_pre_forward_reservation_2026_08_23",
        "author": "Arhan Canli",
        "claim_boundary": (
            "This closure retires every legacy return identity from admission and reuse. It does "
            "not complete missing packet sections, validate historical performance, forgive trial "
            "debt, or permit any result to enter a sleeve."
        ),
        "source_bindings": {
            "trial_packet_manifest": {
                "path": str(MANIFEST.relative_to(REPO)),
                "sha256": _sha256(MANIFEST),
                "content_hash": manifest["content_hash"],
            },
            "identity_packet_index": {
                "path": str(PACKET_INDEX.relative_to(REPO)),
                "sha256": _sha256(PACKET_INDEX),
                "content_hash": packet_index["content_hash"],
            },
            "recoverability_audit": {
                "path": str(RECOVERABILITY.relative_to(REPO)),
                "sha256": _sha256(RECOVERABILITY),
                "content_hash": recoverability["content_hash"],
            },
            "historical_curve_index": {
                "path": str(CURVE_INDEX.relative_to(REPO)),
                "sha256": _sha256(CURVE_INDEX),
                "content_hash": curve_index["content_hash"],
            },
        },
        "summary": {
            "retired_identities": len(identities),
            "retired_complete_evidenced_kills": sum(
                item["packet_complete"] for item in identities
            ),
            "retired_incomplete_evidence_debt": sum(
                not item["packet_complete"] for item in identities
            ),
            "retired_unassessed_identities": summary["incomplete_not_yet_audited"],
            "eligible_for_admission": 0,
            "identity_reuse_permitted": 0,
        },
        "forward_epoch_policy": {
            "new_identity_requires_pre_result_reservation": True,
            "new_identity_requires_exact_hashed_preregistration": True,
            "new_identity_requires_hashed_data_runner_project_and_environment": True,
            "new_identity_requires_reserved_packet_and_paper_urls": True,
            "legacy_identity_remeasurement_may_not_create_admission_eligibility": True,
            "legacy_result_may_not_be_relabelled_as_forward_evidence": True,
        },
        "identities": identities,
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build_closure()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    for path in HOSTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(
        "legacy research epoch: "
        f"{payload['summary']['retired_identities']} identities retired; 0 eligible"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
