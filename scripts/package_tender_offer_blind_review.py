#!/usr/bin/env python3
"""Build a deterministic, prediction-blind archive of the SC 14D9 packet for a reviewer."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PACKET: Final[Path] = REPO / "artifacts/labeling/tender_offer_item4_blind"
HANDOFF_DIR: Final[Path] = REPO / "artifacts/handoffs"
ARCHIVE: Final[Path] = HANDOFF_DIR / "tender_offer_item4_blind.tar.gz"
RECEIPT: Final[Path] = HANDOFF_DIR / "tender_offer_item4_blind.json"
SCHEMA: Final[str] = "canli.labeling.tender-offer-item4-blind-packet.v1"
ROOT_NAME: Final[str] = "tender_offer_item4_blind"
ROWS: Final[int] = 30
HUMAN_COLUMNS: Final[tuple[str, ...]] = (
    "human_unique_cash_price",
    "human_recommendation",
    "human_notes",
)
TOP_LEVEL: Final[tuple[str, ...]] = (
    "INSTRUCTIONS.md",
    "manifest.json",
    "reviewer_attestation.json",
    "reviewer_labels.csv",
    "verify_review.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _files() -> list[Path]:
    files = [PACKET / name for name in TOP_LEVEL]
    files.extend(sorted((PACKET / "documents").glob("TOS-*.txt")))
    if len(files) != len(TOP_LEVEL) + ROWS or any(not path.is_file() for path in files):
        raise ValueError(
            f"frozen review packet must contain {len(TOP_LEVEL)} control files and {ROWS} documents"
        )
    return files


def build_archive() -> tuple[bytes, dict[str, Any]]:
    manifest = json.loads((PACKET / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("content_hash") != _content_hash(manifest):
        raise ValueError("source packet manifest content hash mismatch")
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("rows") != ROWS
        or manifest.get("prediction_blind") is not True
    ):
        raise ValueError(f"source packet is not the frozen {ROWS}-row prediction-blind packet")
    packet_files = manifest.get("packet_files", {})
    controls = {
        "instructions_sha256": PACKET / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": PACKET / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": PACKET / "reviewer_attestation.json",
        "review_verifier_sha256": PACKET / "verify_review.py",
    }
    for field, path in controls.items():
        if packet_files.get(field) != _sha256_bytes(path.read_bytes()):
            raise ValueError(f"source packet control hash mismatch: {field}")
    expected_documents = {f"TOS-{index:03d}.txt" for index in range(1, ROWS + 1)}
    document_hashes = packet_files.get("documents", {})
    if set(document_hashes) != expected_documents:
        raise ValueError("source packet document inventory mismatch")
    for name, expected_hash in document_hashes.items():
        if _sha256_bytes((PACKET / "documents" / name).read_bytes()) != expected_hash:
            raise ValueError(f"source packet document hash mismatch: {name}")

    # An archive is only a blind handoff while the label template and the attestation are blank.
    with (PACKET / "reviewer_labels.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != ROWS or any(
        (row.get(column) or "").strip() for row in rows for column in HUMAN_COLUMNS
    ):
        raise ValueError("reviewer label template already contains labels")
    attestation = json.loads((PACKET / "reviewer_attestation.json").read_text(encoding="utf-8"))
    if any(str(value).strip() for value in attestation.values() if not isinstance(value, bool)) or (
        any(value is True for value in attestation.values())
    ):
        raise ValueError("reviewer attestation template is not blank")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in _files():
            data = path.read_bytes()
            relative = path.relative_to(PACKET)
            info = tarfile.TarInfo(f"{ROOT_NAME}/{relative}")
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
        "schema": "canli.alphac-tender-offer-external-review-handoff.v1",
        "author": "Arhan Canli",
        "decision": "EXTERNAL_BLIND_REVIEW_PACKET_READY_LABELS_NOT_COMPLETED",
        "archive": str(ARCHIVE.relative_to(REPO)),
        "archive_bytes": len(compressed),
        "archive_sha256": _sha256_bytes(compressed),
        "packet_manifest_content_hash": manifest["content_hash"],
        "files": len(_files()),
        "documents": ROWS,
        "prediction_blind": True,
        "labels_completed": 0,
        "return_data_opened": False,
        "hypotheses_spent": 0,
        "required_return_files": ["completed_labels.csv", "completed_attestation.json"],
        "import_command": (
            "uv run python scripts/import_tender_offer_blind_labels.py "
            "--completed <completed_labels.csv> --attestation <completed_attestation.json>"
        ),
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
