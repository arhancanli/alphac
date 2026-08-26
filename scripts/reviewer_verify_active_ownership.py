#!/usr/bin/env python3
"""Dependency-free verifier shipped inside the Active Ownership blind-review packet."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

SCHEMA = "canli.labeling.active-ownership-13d-item4-blind-packet.v3"
HUMAN_COLUMNS = {
    "human_specific_active_intent",
    "human_representative_sentence",
    "human_aggregate_ownership_pct_or_unresolved",
    "human_notes",
}
ATTESTATION_TRUE_FIELDS = (
    "independent_of_parser_development",
    "independent_of_research_design",
    "machine_outputs_not_consulted",
    "prices_and_returns_not_consulted",
    "no_automated_or_ai_labeling_assistance",
    "no_outcome_contingent_compensation",
    "conflicts_disclosed_completely",
    "all_labels_are_personally_reviewed",
)
ATTESTATION_TEXT_FIELDS = (
    "reviewer_name",
    "reviewer_role",
    "reviewer_affiliation",
    "relationship_to_researcher",
    "compensation_or_incentive",
    "conflicts_of_interest",
    "completed_at",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError(f"CSV has extra unnamed fields: {path}")
        return list(reader.fieldnames), rows


def validate_packet(packet_dir: Path) -> dict[str, Any]:
    manifest_path = packet_dir / "manifest.json"
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"expected {SCHEMA}")
    if manifest.get("content_hash") != content_hash(manifest):
        raise ValueError("packet manifest content hash mismatch")
    if manifest.get("prediction_blind") is not True or manifest.get("rows") != 48:
        raise ValueError("packet must be prediction-blind and contain exactly 48 rows")

    packet_files = manifest.get("packet_files", {})
    controls = {
        "instructions_sha256": packet_dir / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": packet_dir / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": packet_dir / "reviewer_attestation.json",
        "review_workspace_sha256": packet_dir / "review.html",
        "review_verifier_sha256": packet_dir / "verify_review.py",
    }
    for field, path in controls.items():
        if not path.is_file() or packet_files.get(field) != sha256_file(path):
            raise ValueError(f"packet control hash mismatch: {field}")

    expected_names = {f"AO13D-{index:03d}.txt" for index in range(1, 49)}
    document_hashes = packet_files.get("documents", {})
    actual_names = {path.name for path in (packet_dir / "documents").glob("AO13D-*.txt")}
    if set(document_hashes) != expected_names or actual_names != expected_names:
        raise ValueError("packet document inventory is not exactly AO13D-001 through AO13D-048")
    for name, expected_hash in document_hashes.items():
        if sha256_file(packet_dir / "documents" / name) != expected_hash:
            raise ValueError(f"packet document hash mismatch: {name}")
    return manifest


def _normalized_source_text(value: str) -> str:
    return " ".join(value.split())


def _document_body(path: Path) -> str:
    document = path.read_text(encoding="utf-8")
    _header, separator, body = document.partition("\n\n")
    return body if separator else document


def validate_completed_labels(completed: Path, template: Path, packet_dir: Path) -> None:
    completed_columns, completed_rows = _read_csv(completed)
    template_columns, template_rows = _read_csv(template)
    if completed_columns != template_columns:
        raise ValueError("completed label columns differ from the frozen template")
    if len(completed_rows) != 48 or len(template_rows) != 48:
        raise ValueError("completed review must preserve exactly 48 rows")
    immutable = [column for column in template_columns if column not in HUMAN_COLUMNS]
    # Both lengths are proven exactly 48 immediately above. Index directly so the
    # dependency-free verifier remains executable on Python 3.9 without zip(strict=True).
    for offset in range(48):
        index = offset + 1
        row = completed_rows[offset]
        frozen = template_rows[offset]
        if any(row[column] != frozen[column] for column in immutable):
            raise ValueError(f"row {index} changed frozen identity or source metadata")
        if row["human_specific_active_intent"] not in {"true", "false"}:
            raise ValueError(f"row {index} active-intent label must be exactly true or false")
        if not row["human_representative_sentence"].strip():
            raise ValueError(f"row {index} requires a representative source sentence")
        source = _normalized_source_text(
            _document_body(packet_dir / "documents" / f"{row['packet_id']}.txt")
        )
        sentence = _normalized_source_text(row["human_representative_sentence"])
        if sentence not in source:
            raise ValueError(
                f"row {index} representative sentence is not verbatim in the frozen source"
            )
        ownership = row["human_aggregate_ownership_pct_or_unresolved"].strip().lower()
        if ownership == "unresolved":
            continue
        try:
            numeric = float(ownership)
        except ValueError as error:
            raise ValueError(f"row {index} ownership must be a number or unresolved") from error
        if not math.isfinite(numeric) or not 0.0 < numeric < 100.0:
            raise ValueError(f"row {index} ownership must be strictly between 0 and 100")


def validate_attestation(path: Path, packet_hash: str) -> None:
    attestation = json.loads(path.read_text(encoding="utf-8"))
    for field in ATTESTATION_TEXT_FIELDS:
        if not str(attestation.get(field, "")).strip():
            raise ValueError(f"reviewer attestation requires {field}")
    completed_at = str(attestation["completed_at"]).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(completed_at)
    except ValueError as error:
        raise ValueError("completed_at must be ISO 8601") from error
    if parsed.tzinfo is None:
        raise ValueError("completed_at must include a timezone")
    if attestation.get("packet_manifest_content_hash") != packet_hash:
        raise ValueError("attestation is not bound to this packet manifest")
    for field in ATTESTATION_TRUE_FIELDS:
        if attestation.get(field) is not True:
            raise ValueError(f"reviewer attestation requires {field}=true")


def verify(
    packet_dir: Path,
    completed: Path | None = None,
    attestation: Path | None = None,
) -> dict[str, Any]:
    manifest = validate_packet(packet_dir)
    if (completed is None) != (attestation is None):
        raise ValueError("provide both --completed and --attestation, or neither")
    result: dict[str, Any] = {
        "schema": "canli.external-review-verification.v1",
        "status": "PACKET_VALID",
        "packet_manifest_content_hash": manifest["content_hash"],
        "documents_verified": 48,
        "prediction_blind": True,
        "return_data_opened": False,
    }
    if completed is not None and attestation is not None:
        validate_completed_labels(completed, packet_dir / "reviewer_labels.csv", packet_dir)
        validate_attestation(attestation, str(manifest["content_hash"]))
        result.update(
            {
                "status": "REVIEW_RETURN_VALID",
                "completed_labels_sha256": sha256_file(completed),
                "attestation_sha256": sha256_file(attestation),
                "rows_verified": 48,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--completed", type=Path)
    parser.add_argument("--attestation", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.packet_dir, args.completed, args.attestation)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
