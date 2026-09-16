#!/usr/bin/env python3
"""Validate and import a completed independent SC 14D9 Item 4 blind review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final, cast

import pandas as pd

SOURCE_DIR: Final = Path("artifacts/feasibility/tender_offer_spread")
PACKET_DIR: Final = Path("artifacts/labeling/tender_offer_item4_blind")
REPO: Final = Path(__file__).resolve().parents[1]
PROTOCOL: Final = REPO / "docs/design/FEASIBILITY_TENDER_OFFER_SPREAD.md"
SCHEMA: Final = "canli.labeling.tender-offer-item4-blind-packet.v1"
ROWS: Final = 30
PACKET_ID_PREFIX: Final = "TOS"
INELIGIBLE: Final = "ineligible"
POSTURES: Final = {"recommend_accept", "recommend_reject", "neutral_or_unable", INELIGIBLE}
HUMAN_COLUMNS: Final = [
    "human_unique_cash_price",
    "human_recommendation",
    "human_notes",
]
ATTESTATION_TRUE_FIELDS: Final = [
    "independent_of_parser_development",
    "independent_of_research_design",
    "machine_outputs_not_consulted",
    "prices_and_returns_not_consulted",
    "no_automated_or_ai_labeling_assistance",
    "no_outcome_contingent_compensation",
    "conflicts_disclosed_completely",
    "all_labels_are_personally_reviewed",
]
ATTESTATION_TEXT_FIELDS: Final = [
    "reviewer_name",
    "reviewer_role",
    "reviewer_affiliation",
    "relationship_to_researcher",
    "compensation_or_incentive",
    "conflicts_of_interest",
    "completed_at",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_packet(packet_dir: Path) -> dict[str, Any]:
    manifest_path = packet_dir / "manifest.json"
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("content_hash") != content_hash(manifest):
        raise ValueError("blind packet manifest content hash mismatch")
    if manifest.get("schema") != SCHEMA:
        raise ValueError("blind packet schema is not the governed v1 schema")
    if manifest.get("prediction_blind") is not True or manifest.get("rows") != ROWS:
        raise ValueError(f"blind packet must be prediction-blind with exactly {ROWS} rows")
    packet_files = cast(dict[str, Any], manifest.get("packet_files", {}))
    controls = {
        "instructions_sha256": packet_dir / "INSTRUCTIONS.md",
        "reviewer_labels_sha256": packet_dir / "reviewer_labels.csv",
        "reviewer_attestation_template_sha256": packet_dir / "reviewer_attestation.json",
        "review_verifier_sha256": packet_dir / "verify_review.py",
    }
    for field, path in controls.items():
        if not path.is_file() or packet_files.get(field) != sha256_file(path):
            raise ValueError(f"blind packet control hash mismatch: {field}")
    expected = {f"{PACKET_ID_PREFIX}-{index:03d}.txt" for index in range(1, ROWS + 1)}
    documents = cast(dict[str, str], packet_files.get("documents", {}))
    if set(documents) != expected:
        raise ValueError("blind packet document inventory mismatch")
    for name, expected_hash in documents.items():
        if sha256_file(packet_dir / "documents" / name) != expected_hash:
            raise ValueError(f"blind packet document hash mismatch: {name}")
    return manifest


def validate_source_lineage(manifest: dict[str, Any], source_dir: Path) -> None:
    lineage = cast(dict[str, str], manifest.get("source_lineage", {}))
    current = {
        "protocol_sha256": PROTOCOL,
        "frozen_labels_sha256": source_dir / "frozen_human_labels.csv",
        "document_audit_sha256": source_dir / "document_audit.parquet",
        "result_sha256": source_dir / "result.json",
    }
    for field, path in current.items():
        if lineage.get(field) != sha256_file(path):
            raise ValueError(f"blind packet is not bound to the current {field}")


def validate_attestation(path: Path, packet_content_hash: str) -> dict[str, Any]:
    attestation = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    for field in ATTESTATION_TEXT_FIELDS:
        if not str(attestation.get(field, "")).strip():
            raise ValueError(f"reviewer attestation requires {field}")
    completed_at = str(attestation["completed_at"]).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(completed_at)
    except ValueError as error:
        raise ValueError("reviewer attestation completed_at must be ISO 8601") from error
    if parsed.tzinfo is None:
        raise ValueError("reviewer attestation completed_at must include a timezone")
    if attestation.get("packet_manifest_content_hash") != packet_content_hash:
        raise ValueError("reviewer attestation is not bound to this packet content hash")
    for field in ATTESTATION_TRUE_FIELDS:
        if attestation.get(field) is not True:
            raise ValueError(f"reviewer attestation requires {field}=true")
    return attestation


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_labels(completed: Path, template: Path) -> pd.DataFrame:
    labels = pd.read_csv(completed, dtype=str, keep_default_na=False)
    frozen = pd.read_csv(template, dtype=str, keep_default_na=False)
    if list(labels.columns) != list(frozen.columns):
        raise ValueError("completed label columns differ from the frozen template")
    if len(labels) != len(frozen) or len(labels) != ROWS:
        raise ValueError(f"completed review must preserve all {ROWS} frozen rows")
    immutable = [column for column in frozen.columns if column not in HUMAN_COLUMNS]
    if not labels[immutable].equals(frozen[immutable]):
        raise ValueError("completed review changed frozen row identity or source metadata")

    posture = labels["human_recommendation"].str.strip().str.lower()
    if not posture.isin(sorted(POSTURES)).all():
        raise ValueError("every recommendation must be one of " + ", ".join(sorted(POSTURES)))
    price = labels["human_unique_cash_price"].str.strip().str.lower()
    if price.eq("").any():
        raise ValueError(f"every row requires a cash price per share or {INELIGIBLE}")
    price_ineligible = price.eq(INELIGIBLE)
    numeric = pd.to_numeric(price.where(~price_ineligible), errors="coerce")
    if not (price_ineligible | numeric.gt(0)).all():
        raise ValueError(f"every price must be a number greater than zero or {INELIGIBLE}")
    # The frozen scorer reads an ineligible posture as "this document establishes no single cash
    # price", so a row ineligible in one cell and priced in the other would be scored against a
    # rule the reviewer did not intend.
    if not price_ineligible.eq(posture.eq(INELIGIBLE)).all():
        raise ValueError(
            f"a row must be {INELIGIBLE} in both the price and recommendation cells, or neither"
        )
    labels["human_unique_cash_price"] = price
    labels["human_recommendation"] = posture
    return labels


def import_labels(
    completed: Path,
    attestation_path: Path,
    source_dir: Path = SOURCE_DIR,
    packet_dir: Path = PACKET_DIR,
) -> dict[str, Any]:
    canonical = source_dir / "frozen_human_labels.csv"
    receipt_path = source_dir / "human_label_import_receipt.json"
    template = packet_dir / "reviewer_labels.csv"
    manifest = validate_packet(packet_dir)
    if receipt_path.exists():
        raise ValueError("human labels already have an import receipt; refusing to overwrite")
    validate_source_lineage(manifest, source_dir)
    existing = pd.read_csv(canonical, dtype=str, keep_default_na=False)
    human_columns = [str(column) for column in existing if str(column).startswith("human_")]
    if not human_columns or not all(existing[column].eq("").all() for column in human_columns):
        raise ValueError("canonical human labels are no longer blank; refusing to overwrite")
    attestation = validate_attestation(attestation_path, str(manifest["content_hash"]))
    labels = validate_labels(completed, template)

    # The canonical file keeps its own frozen schema; only its blank human columns are filled,
    # matched by accession rather than by row order.
    by_accession = labels.set_index("accession")
    if set(by_accession.index) != set(existing["accession"]):
        raise ValueError("completed review does not cover exactly the canonical accessions")
    filled = existing.copy()
    for column in HUMAN_COLUMNS:
        filled[column] = filled["accession"].map(by_accession[column])
    if filled[HUMAN_COLUMNS].isna().to_numpy().any():
        raise ValueError("every canonical row must receive a label")

    canonical_before_sha256 = sha256_file(canonical)
    canonical_bytes = filled.to_csv(index=False).encode()
    canonical_after_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    receipt: dict[str, Any] = {
        "schema": "canli.labeling.tender-offer-item4-import-receipt.v1",
        "reviewer": {
            "name": attestation["reviewer_name"],
            "role": attestation["reviewer_role"],
            "affiliation": attestation["reviewer_affiliation"],
            "relationship_to_researcher": attestation["relationship_to_researcher"],
            "compensation_or_incentive": attestation["compensation_or_incentive"],
            "conflicts_of_interest": attestation["conflicts_of_interest"],
            "completed_at": attestation["completed_at"],
        },
        "attestation_sha256": sha256_file(attestation_path),
        "packet_manifest_sha256": sha256_file(packet_dir / "manifest.json"),
        "packet_content_hash": manifest["content_hash"],
        "completed_labels_sha256": sha256_file(completed),
        "canonical_labels_before_sha256": canonical_before_sha256,
        "canonical_labels_after_sha256": canonical_after_sha256,
        "rows_imported": len(filled),
        "ineligible_rows": int(filled["human_recommendation"].eq(INELIGIBLE).sum()),
        "prediction_blind_attested": True,
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "claim_boundary": (
            "This receipt proves structural import and reviewer attestation only. Price and "
            "posture agreement, and every downstream research claim, remain unproven until the "
            "frozen document-feasibility scorer is rerun."
        ),
    }
    receipt["content_hash"] = content_hash(receipt)
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    _atomic_write(canonical, canonical_bytes)
    _atomic_write(receipt_path, receipt_bytes)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--packet-dir", type=Path, default=PACKET_DIR)
    args = parser.parse_args()
    receipt = import_labels(args.completed, args.attestation, args.source_dir, args.packet_dir)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
