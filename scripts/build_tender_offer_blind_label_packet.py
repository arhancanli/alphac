#!/usr/bin/env python3
"""Build a deterministic, prediction-blind reviewer packet for the frozen SC 14D9 audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

SOURCE_DIR: Final = Path("artifacts/feasibility/tender_offer_spread")
OUT: Final = Path("artifacts/labeling/tender_offer_item4_blind")
REPO: Final = Path(__file__).resolve().parents[1]
PROTOCOL: Final = REPO / "docs/design/FEASIBILITY_TENDER_OFFER_SPREAD.md"
VERIFIER_SOURCE: Final = Path(__file__).with_name("reviewer_verify_tender_offer.py")
SEED: Final = "tender-offer-item4-blind-v1"
ROWS: Final = 30
# The frozen parser's own outputs. A reviewer who sees any of them is no longer measuring the
# parser; the packet must carry the source document and nothing the parser concluded from it.
FORBIDDEN_MACHINE_FIELDS: Final = {
    "unique_price",
    "recommendation",
    "strict_price_candidates",
    "strict_price_count",
}
IDENTITY_COLUMNS: Final = [
    "packet_id",
    "year",
    "cik",
    "accession",
    "source_url",
    "document_sha256",
    "item4_sha256",
]
HUMAN_COLUMNS: Final = [
    "human_unique_cash_price",
    "human_recommendation",
    "human_notes",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _blind_rank(accession: str) -> str:
    return hashlib.sha256(f"{SEED}|{accession}".encode()).hexdigest()


def _labels_are_unopened(labels: pd.DataFrame) -> bool:
    human = [str(column) for column in labels.columns if str(column).startswith("human_")]
    return bool(human) and all(
        labels[column].fillna("").astype(str).eq("").all() for column in human
    )


INSTRUCTIONS: Final = """# Independent blind SC 14D9 review instructions

Review all 30 rows without consulting parser outputs, aggregate results, prices, or returns.

## Before labeling

- Keep this extracted directory intact. Do not edit `manifest.json`, `reviewer_labels.csv`,
  `reviewer_attestation.json`, `verify_review.py`, or any file under `documents/`.
- Run `python3 verify_review.py`. Continue only if it prints `PACKET_VALID`.
- Copy `reviewer_labels.csv` to `completed_labels.csv` and `reviewer_attestation.json` to
  `completed_attestation.json`. Edit only those two copies.

## What each document is

Each file under `documents/` is the Item 4 section, "Solicitation or Recommendation", of a
Schedule 14D9 filed with the SEC by the subject company of a tender offer. The header names the
official document URL and the source hashes; the body is the extracted section.

## Frozen labeling rubric

Two judgements are recorded per document, both from the supplied text and, if necessary, the
linked official filing. Nothing else may be consulted.

- `human_unique_cash_price`: the single cash amount offered per share, as a plain decimal number
  with no currency symbol, comma, or range (for example `12.50`). Enter it only when the document
  establishes exactly one such amount for the offer described in this filing.
- Enter exactly `ineligible` when it does not: no cash-per-share consideration, consideration that
  is stock or part stock, or two or more different cash amounts left standing (amended,
  contingent, or alternative) that the document does not resolve into one.
- `human_recommendation`: the board's stated posture toward the offer, exactly one of
  `recommend_accept`, `recommend_reject`, or `neutral_or_unable` (expresses no opinion or states
  it is unable to take a position). Enter `ineligible` when, and only when, the price cell is
  `ineligible`; the two cells are `ineligible` together or neither is.
- Judge the posture from what the board states in this document, not from what you expect, and
  not from any later event. When the document states more than one conflicting posture, record
  the one the board expresses as its own recommendation to shareholders.
- Use `human_notes` for ambiguity or document-location notes; do not put labels in that field.

## Completing and returning the review

- Complete all 30 rows in `completed_labels.csv`. Do not reorder, add, or remove rows, and do not
  change the frozen identity or source columns.
- Fill every reviewer/disclosure field and the timezone-aware ISO 8601 `completed_at` in
  `completed_attestation.json`. Use `none` when a relationship, payment, or conflict field truly
  has nothing to disclose. Copy `content_hash` from `manifest.json` into
  `packet_manifest_content_hash`; set every independence boolean to `true` only when truthful.
  No generative-AI, classifier, scripted, or other automated assistance may be used to make or
  draft any label or note. Preserve the blank template.
- Run `python3 verify_review.py --completed completed_labels.csv --attestation
  completed_attestation.json`. Return the two completed files only if it prints
  `REVIEW_RETURN_VALID`; the output also gives both file hashes.
- Return exactly `completed_labels.csv` and `completed_attestation.json` to Arhan Canli. The
  researcher, not the reviewer, performs the governed import and the frozen scoring run.

The packet intentionally contains no machine classification, price candidate, posture, market
price, return, or portfolio output.
"""


def build(source_dir: Path = SOURCE_DIR, out: Path = OUT) -> dict[str, Any]:
    labels_path = source_dir / "frozen_human_labels.csv"
    audit_path = source_dir / "document_audit.parquet"
    result_path = source_dir / "result.json"
    labels = pd.read_csv(labels_path, dtype={"accession": str}, keep_default_na=False)
    if len(labels) != ROWS or labels["accession"].duplicated().any():
        raise ValueError(f"the frozen audit must contain {ROWS} unique accessions")
    if not _labels_are_unopened(labels):
        raise ValueError("refusing to rebuild a blind packet after human labels were opened")

    audit = pd.read_parquet(audit_path)
    audit["accession"] = audit["accession"].astype(str)

    source = labels[["year", "cik", "accession", "source_url", "document_sha256"]].merge(
        audit[["accession", "item4_extracted", "item4_text", "item4_sha256"]],
        on="accession",
        validate="one_to_one",
    )
    if len(source) != ROWS:
        raise ValueError("every frozen audit row must resolve to exactly one audited document")
    source["blind_rank"] = source["accession"].map(_blind_rank)
    source = source.sort_values("blind_rank").reset_index(drop=True)
    source.insert(0, "packet_id", [f"TOS-{index:03d}" for index in range(1, ROWS + 1)])
    source = source.drop(columns="blind_rank")

    if FORBIDDEN_MACHINE_FIELDS.intersection(source.columns):
        raise AssertionError("prediction fields leaked into blind packet")

    out.mkdir(parents=True, exist_ok=True)
    documents_dir = out / "documents"
    documents_dir.mkdir(exist_ok=True)
    document_hashes: dict[str, str] = {}
    for row in source.to_dict("records"):
        packet_id = str(row["packet_id"])
        text = str(row["item4_text"]) if bool(row["item4_extracted"]) else "[ITEM 4 UNRESOLVED]"
        document = (
            f"Packet ID: {packet_id}\n"
            f"Year: {row['year']}\n"
            f"CIK: {row['cik']}\n"
            f"Accession: {row['accession']}\n"
            f"Official document: {row['source_url']}\n"
            f"Primary document SHA-256: {row['document_sha256']}\n"
            f"Item 4 SHA-256: {row['item4_sha256']}\n\n"
            f"{text}\n"
        )
        path = documents_dir / f"{packet_id}.txt"
        path.write_text(document, encoding="utf-8")
        document_hashes[path.name] = sha256_file(path)

    review = source[IDENTITY_COLUMNS].copy()
    for column in HUMAN_COLUMNS:
        review[column] = ""
    review_path = out / "reviewer_labels.csv"
    review.to_csv(review_path, index=False)

    attestation = {
        "reviewer_name": "",
        "reviewer_role": "",
        "reviewer_affiliation": "",
        "relationship_to_researcher": "",
        "compensation_or_incentive": "",
        "conflicts_of_interest": "",
        "completed_at": "",
        "packet_manifest_content_hash": "",
        "independent_of_parser_development": False,
        "independent_of_research_design": False,
        "machine_outputs_not_consulted": False,
        "prices_and_returns_not_consulted": False,
        "no_automated_or_ai_labeling_assistance": False,
        "no_outcome_contingent_compensation": False,
        "conflicts_disclosed_completely": False,
        "all_labels_are_personally_reviewed": False,
    }
    attestation_path = out / "reviewer_attestation.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")

    verifier_path = out / "verify_review.py"
    verifier_path.write_bytes(VERIFIER_SOURCE.read_bytes())

    instructions_path = out / "INSTRUCTIONS.md"
    instructions_path.write_text(INSTRUCTIONS)

    manifest: dict[str, Any] = {
        "schema": "canli.labeling.tender-offer-item4-blind-packet.v1",
        "author": "Arhan Canli",
        "rows": len(review),
        "prediction_blind": True,
        "forbidden_machine_fields": sorted(FORBIDDEN_MACHINE_FIELDS),
        "source_lineage": {
            "protocol_sha256": sha256_file(PROTOCOL),
            "frozen_labels_sha256": sha256_file(labels_path),
            "document_audit_sha256": sha256_file(audit_path),
            "result_sha256": sha256_file(result_path),
        },
        "packet_files": {
            "instructions_sha256": sha256_file(instructions_path),
            "reviewer_labels_sha256": sha256_file(review_path),
            "reviewer_attestation_template_sha256": sha256_file(attestation_path),
            "review_verifier_sha256": sha256_file(verifier_path),
            "documents": document_hashes,
        },
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "claim_boundary": (
            "This packet enables an independent blind source audit only. It contains no machine "
            "predictions and makes no accuracy, return, Sharpe, drawdown, or sleeve claim."
        ),
    }
    manifest["content_hash"] = content_hash(manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
