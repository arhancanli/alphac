#!/usr/bin/env python3
"""Verify a blind SC 14D9 review packet, and a completed return, with the standard library only.

This file ships inside the reviewer's packet. It must run on a reviewer's own machine with no
installed dependencies, so it uses nothing beyond the standard library and avoids syntax newer
than Python 3.9.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

SCHEMA = "canli.labeling.tender-offer-item4-blind-packet.v1"
ROWS = 30
PACKET_ID_PREFIX = "TOS"
HUMAN_COLUMNS = [
    "human_unique_cash_price",
    "human_recommendation",
    "human_notes",
]
INELIGIBLE = "ineligible"
POSTURES = {"recommend_accept", "recommend_reject", "neutral_or_unable", INELIGIBLE}
PRICE_PATTERN = re.compile(r"^[0-9]+(\.[0-9]{1,4})?$")
ATTESTATION_TEXT_FIELDS = [
    "reviewer_name",
    "reviewer_role",
    "reviewer_affiliation",
    "relationship_to_researcher",
    "compensation_or_incentive",
    "conflicts_of_interest",
    "completed_at",
]
ATTESTATION_TRUE_FIELDS = [
    "independent_of_parser_development",
    "independent_of_research_design",
    "machine_outputs_not_consulted",
    "prices_and_returns_not_consulted",
    "no_automated_or_ai_labeling_assistance",
    "no_outcome_contingent_compensation",
    "conflicts_disclosed_completely",
    "all_labels_are_personally_reviewed",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [{column: (row.get(column) or "") for column in columns} for row in reader]
    return columns, rows


def validate_packet(packet_dir: Path) -> dict[str, Any]:
    manifest_path = packet_dir / "manifest.json"
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("expected " + SCHEMA)
    if manifest.get("content_hash") != content_hash(manifest):
        raise ValueError("packet manifest content hash mismatch")
    if manifest.get("prediction_blind") is not True or manifest.get("rows") != ROWS:
        raise ValueError(f"packet must be prediction-blind and contain exactly {ROWS} rows")

    packet_files = manifest.get("packet_files", {})
    controls = {
        "instructions_sha256": packet_dir / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": packet_dir / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": packet_dir / "reviewer_attestation.json",
        "review_verifier_sha256": packet_dir / "verify_review.py",
    }
    for field, path in controls.items():
        if not path.is_file() or packet_files.get(field) != sha256_file(path):
            raise ValueError(f"packet control hash mismatch: {field}")

    expected_names = {f"{PACKET_ID_PREFIX}-{index:03d}.txt" for index in range(1, ROWS + 1)}
    document_hashes = packet_files.get("documents", {})
    actual_names = {
        path.name for path in (packet_dir / "documents").glob(f"{PACKET_ID_PREFIX}-*.txt")
    }
    if set(document_hashes) != expected_names or actual_names != expected_names:
        raise ValueError(
            f"packet document inventory is not exactly {PACKET_ID_PREFIX}-001 "
            f"through {PACKET_ID_PREFIX}-{ROWS:03d}"
        )
    for name, expected_hash in document_hashes.items():
        if sha256_file(packet_dir / "documents" / name) != expected_hash:
            raise ValueError(f"packet document hash mismatch: {name}")
    return manifest


def validate_price(value: str, index: int) -> bool:
    """Return True when the row is labelled ineligible; raise when the cell is not a legal label."""
    text = value.strip().lower()
    if text == INELIGIBLE:
        return True
    if not text:
        raise ValueError(f"row {index} requires a cash price per share or {INELIGIBLE}")
    if not PRICE_PATTERN.match(text):
        raise ValueError(
            f"row {index} price must be a plain decimal number of dollars per share, "
            f"with no currency symbol, comma, or range, or exactly {INELIGIBLE}"
        )
    numeric = float(text)
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise ValueError(f"row {index} price must be greater than zero")
    return False


def validate_completed_labels(completed: Path, template: Path) -> None:
    completed_columns, completed_rows = _read_csv(completed)
    template_columns, template_rows = _read_csv(template)
    if completed_columns != template_columns:
        raise ValueError("completed label columns differ from the frozen template")
    if len(completed_rows) != ROWS or len(template_rows) != ROWS:
        raise ValueError(f"completed review must preserve exactly {ROWS} rows")
    immutable = [column for column in template_columns if column not in HUMAN_COLUMNS]
    # Both lengths are proven exactly ROWS immediately above. Index directly so the
    # dependency-free verifier remains executable on Python 3.9 without zip(strict=True).
    for offset in range(ROWS):
        index = offset + 1
        row = completed_rows[offset]
        frozen = template_rows[offset]
        if any(row[column] != frozen[column] for column in immutable):
            raise ValueError(f"row {index} changed frozen identity or source metadata")
        posture = row["human_recommendation"].strip().lower()
        if posture not in POSTURES:
            raise ValueError(
                f"row {index} recommendation must be one of " + ", ".join(sorted(POSTURES))
            )
        price_ineligible = validate_price(row["human_unique_cash_price"], index)
        # The frozen scorer reads an ineligible posture as "this document establishes no single
        # cash price". A row that is ineligible in one cell and priced in the other would be
        # scored against a rule the reviewer did not intend, so the two must agree.
        if price_ineligible != (posture == INELIGIBLE):
            raise ValueError(
                f"row {index} must be {INELIGIBLE} in both the price and recommendation cells, "
                "or in neither"
            )


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
        "documents_verified": ROWS,
        "prediction_blind": True,
        "return_data_opened": False,
    }
    if completed is not None and attestation is not None:
        validate_completed_labels(completed, packet_dir / "reviewer_labels.csv")
        validate_attestation(attestation, str(manifest["content_hash"]))
        result.update(
            {
                "status": "REVIEW_RETURN_VALID",
                "completed_labels_sha256": sha256_file(completed),
                "attestation_sha256": sha256_file(attestation),
                "rows_verified": ROWS,
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
