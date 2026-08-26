#!/usr/bin/env python3
"""Build a deterministic, prediction-blind archive for an external reviewer."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PACKET: Final[Path] = REPO / "artifacts/labeling/active_ownership_13d_item4_v3_blind"
HANDOFF_DIR: Final[Path] = REPO / "artifacts/handoffs"
ARCHIVE: Final[Path] = HANDOFF_DIR / "active_ownership_13d_item4_v3_blind.tar.gz"
RECEIPT: Final[Path] = HANDOFF_DIR / "active_ownership_13d_item4_v3_blind.json"
TOP_LEVEL: Final[tuple[str, ...]] = (
    "INSTRUCTIONS.md",
    "manifest.json",
    "review.html",
    "reviewer_attestation.json",
    "reviewer_labels.csv",
    "verify_review.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _files() -> list[Path]:
    files = [PACKET / name for name in TOP_LEVEL]
    files.extend(sorted((PACKET / "documents").glob("AO13D-*.txt")))
    if len(files) != 54 or any(not path.is_file() for path in files):
        raise ValueError("frozen review packet must contain six control files and 48 documents")
    return files


def build_archive() -> tuple[bytes, dict[str, Any]]:
    manifest = json.loads((PACKET / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("content_hash") != _content_hash(
        {key: value for key, value in manifest.items() if key != "content_hash"}
    ):
        raise ValueError("source packet manifest content hash mismatch")
    if (
        manifest.get("schema") != "canli.labeling.active-ownership-13d-item4-blind-packet.v3"
        or manifest.get("rows") != 48
        or manifest.get("prediction_blind") is not True
    ):
        raise ValueError("source packet is not the frozen 48-row prediction-blind packet")
    packet_files = manifest.get("packet_files", {})
    controls = {
        "instructions_sha256": PACKET / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": PACKET / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": PACKET / "reviewer_attestation.json",
        "review_workspace_sha256": PACKET / "review.html",
        "review_verifier_sha256": PACKET / "verify_review.py",
    }
    for field, path in controls.items():
        if packet_files.get(field) != _sha256_bytes(path.read_bytes()):
            raise ValueError(f"source packet control hash mismatch: {field}")
    expected_documents = {f"AO13D-{index:03d}.txt" for index in range(1, 49)}
    document_hashes = packet_files.get("documents", {})
    if set(document_hashes) != expected_documents:
        raise ValueError("source packet document inventory mismatch")
    for name, expected_hash in document_hashes.items():
        if _sha256_bytes((PACKET / "documents" / name).read_bytes()) != expected_hash:
            raise ValueError(f"source packet document hash mismatch: {name}")
    labels = (PACKET / "reviewer_labels.csv").read_text(encoding="utf-8")
    if any(line.rstrip(",").count(",") >= 6 for line in labels.splitlines()[1:]):
        raise ValueError("reviewer label template appears to contain completed labels")
    attestation = json.loads((PACKET / "reviewer_attestation.json").read_text(encoding="utf-8"))
    blank_fields = (
        "reviewer_name",
        "reviewer_role",
        "reviewer_affiliation",
        "relationship_to_researcher",
        "compensation_or_incentive",
        "conflicts_of_interest",
        "completed_at",
        "packet_manifest_content_hash",
    )
    if any(attestation.get(field) for field in blank_fields) or any(
        value is True for value in attestation.values()
    ):
        raise ValueError("reviewer attestation template is not blank")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in _files():
            data = path.read_bytes()
            relative = path.relative_to(PACKET)
            info = tarfile.TarInfo(f"active_ownership_13d_item4_v3_blind/{relative}")
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    gzip_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gzip_buffer, mode="wb", filename="", mtime=0, compresslevel=9) as gz:
        gz.write(tar_buffer.getvalue())
    compressed = gzip_buffer.getvalue()
    receipt: dict[str, Any] = {
        "schema": "canli.alphac-active-ownership-external-review-handoff.v1",
        "author": "Arhan Canli",
        "decision": "EXTERNAL_BLIND_REVIEW_PACKET_READY_LABELS_NOT_COMPLETED",
        "archive": str(ARCHIVE.relative_to(REPO)),
        "public_archive_path": "/glassbox/active_ownership_13d_item4_v3_blind.tar.gz",
        "archive_bytes": len(compressed),
        "archive_sha256": _sha256_bytes(compressed),
        "packet_manifest_content_hash": manifest["content_hash"],
        "files": len(_files()),
        "documents": 48,
        "prediction_blind": True,
        "labels_completed": 0,
        "return_data_opened": False,
        "hypotheses_spent": 0,
        "required_return_files": ["completed_labels.csv", "completed_attestation.json"],
        "claim_boundary": (
            "The archive is ready for a genuinely independent source review. It contains no "
            "machine predictions or return data and does not itself provide accuracy evidence."
        ),
    }
    receipt["content_hash"] = _content_hash(receipt)
    return compressed, receipt


def main() -> int:
    compressed, receipt = build_archive()
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_bytes(compressed)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": receipt["decision"], "content_hash": receipt["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
