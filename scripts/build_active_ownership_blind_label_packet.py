#!/usr/bin/env python3
"""Build a deterministic, prediction-blind reviewer packet for the frozen Item 4 audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

SOURCE_DIR: Final = Path("artifacts/feasibility/active_ownership_13d_item4_v3")
OUT: Final = Path("artifacts/labeling/active_ownership_13d_item4_v3_blind")
VERIFIER_SOURCE: Final = Path(__file__).with_name("reviewer_verify_active_ownership.py")
REVIEW_UI_TEMPLATE: Final = (
    Path(__file__).resolve().parents[1] / "assets" / "active_ownership_review_workspace.html"
)
SEED: Final = "active-ownership-13d-item4-v3-blind-v1"
FORBIDDEN_MACHINE_FIELDS: Final = {
    "specific_active_intent",
    "active_sentences",
    "ownership_pct_candidates",
}


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


def build(source_dir: Path, out: Path) -> dict[str, Any]:
    labels_path = source_dir / "frozen_human_labels.csv"
    audit_path = source_dir / "document_audit.parquet"
    result_path = source_dir / "result.json"
    labels = pd.read_csv(labels_path, dtype={"accession": str}, keep_default_na=False)
    if len(labels) != 48 or labels["accession"].duplicated().any():
        raise ValueError("the frozen audit must contain 48 unique accessions")
    if not _labels_are_unopened(labels):
        raise ValueError("refusing to rebuild a blind packet after human labels were opened")

    audit = pd.read_parquet(audit_path)
    audit["accession"] = audit["accession"].astype(str)

    source = labels[["year", "accession", "ticker", "submission_url"]].merge(
        audit[
            [
                "accession",
                "item4_extracted",
                "item4_text",
                "primary_document_sha256",
                "item4_sha256",
            ]
        ],
        on="accession",
        validate="one_to_one",
    )
    source["blind_rank"] = source["accession"].map(_blind_rank)
    source = source.sort_values("blind_rank").reset_index(drop=True)
    source.insert(0, "packet_id", [f"AO13D-{index:03d}" for index in range(1, 49)])
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
            f"Accession: {row['accession']}\n"
            f"Ticker at acceptance: {row['ticker']}\n"
            f"Official submission: {row['submission_url']}\n"
            f"Primary document SHA-256: {row['primary_document_sha256']}\n"
            f"Item 4 SHA-256: {row['item4_sha256']}\n\n"
            f"{text}\n"
        )
        path = documents_dir / f"{packet_id}.txt"
        path.write_text(document)
        document_hashes[path.name] = sha256_file(path)

    review = source[
        ["packet_id", "year", "accession", "ticker", "submission_url", "item4_sha256"]
    ].copy()
    review["human_specific_active_intent"] = ""
    review["human_representative_sentence"] = ""
    review["human_aggregate_ownership_pct_or_unresolved"] = ""
    review["human_notes"] = ""
    review_path = out / "reviewer_labels.csv"
    review.to_csv(review_path, index=False)

    review_ui_payload = {
        "packet_key": SEED,
        "immutable_columns": [
            "packet_id",
            "year",
            "accession",
            "ticker",
            "submission_url",
            "item4_sha256",
        ],
        "rows": [
            {
                "packet_id": str(row["packet_id"]),
                "year": int(row["year"]),
                "accession": str(row["accession"]),
                "ticker": str(row["ticker"]),
                "submission_url": str(row["submission_url"]),
                "item4_sha256": ("" if pd.isna(row["item4_sha256"]) else str(row["item4_sha256"])),
                "document_text": (
                    str(row["item4_text"])
                    if bool(row["item4_extracted"])
                    else "[ITEM 4 UNRESOLVED]"
                ),
            }
            for row in source.to_dict("records")
        ],
    }
    template = REVIEW_UI_TEMPLATE.read_text(encoding="utf-8")
    if template.count("__PACKET_DATA__") != 1:
        raise ValueError("review workspace template must contain exactly one packet-data marker")
    embedded = json.dumps(
        review_ui_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).replace("</", "<\\/")
    review_ui_path = out / "review.html"
    review_ui_path.write_text(template.replace("__PACKET_DATA__", embedded), encoding="utf-8")

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

    instructions = """# Independent blind review instructions

Review all 48 rows without consulting parser outputs, aggregate results, prices, or returns.

## Before labeling

- Keep this extracted directory intact. Do not edit `manifest.json`, `reviewer_labels.csv`,
  `reviewer_attestation.json`, `review.html`, `verify_review.py`, or any file under `documents/`.
- Run `python3 verify_review.py`. Continue only if it prints `PACKET_VALID`.
- Copy `reviewer_labels.csv` to `completed_labels.csv` and `reviewer_attestation.json` to
  `completed_attestation.json`. Edit only those two copies.
- For a guided offline workspace, open `review.html`. It autosaves locally, captures selected
  source text, and downloads the two completed files in the governed schemas. It performs no
  network request unless you explicitly open an official SEC filing link.

## Frozen labeling rubric

- Mark `human_specific_active_intent=true` only when the filing states that the reporting person or
  group has taken, committed to, or is presently pursuing a specific action intended to influence
  issuer governance, control, capital allocation, or a strategic transaction. Examples include an
  actual nomination, proposal, demand, agreement, delivered communication, or stated present plan.
- Mark it `false` for passive ownership, transaction history alone, generic monitoring, or
  boilerplate saying the filer may communicate, review alternatives, or act in the future without
  a specific current action.
- Base the decision only on the supplied filing text and, if necessary, the linked official SEC
  submission. Do not search for outcomes, prices, returns, parser results, or later filings.
- Copy one representative source sentence verbatim. For a negative row, copy the sentence most
  relevant to the negative decision. Use `[ITEM 4 UNRESOLVED]` only when extraction is unresolved.
  The verifier normalizes whitespace and rejects a sentence that is not present in the frozen
  source excerpt; do not paraphrase it.
- Record one unambiguous aggregate ownership percentage explicitly reported for the reporting
  person or group as a plain number without a percent sign. Do not infer, sum, average, or choose
  among conflicting percentages. Enter exactly `unresolved` when one aggregate percentage cannot
  be established from the filing.
- Use `human_notes` for ambiguity or document-location notes; do not put labels in that field.

## Completing and returning the review

- Read `documents/<packet_id>.txt` and, where needed for cover-page/Item 5 ownership, the linked
  official SEC submission.
- Complete all 48 rows in `completed_labels.csv`. Do not reorder, add, or remove rows and do not
  change the frozen identity or source columns.
- Fill every reviewer/disclosure field and the timezone-aware ISO 8601 `completed_at` in
  `completed_attestation.json`. Use `none` when a relationship, payment, or conflict field truly
  has nothing to disclose. Copy `content_hash` from `manifest.json` into
  `packet_manifest_content_hash`; set every independence boolean to `true` only when truthful.
  No generative-AI, classifier, scripted, or other automated assistance may be used to make or
  draft any label, sentence, ownership value, or note. Preserve the blank template.
- Run `python3 verify_review.py --completed completed_labels.csv --attestation
  completed_attestation.json`. Return the two completed files only if it prints
  `REVIEW_RETURN_VALID`; the output also gives both file hashes.
- Return exactly `completed_labels.csv` and `completed_attestation.json` to Arhan Canli. The
  researcher, not the reviewer, performs the governed import and frozen scoring run.

The packet intentionally contains no machine classification, matched sentence, ownership candidate,
market price, return, or portfolio output.
"""
    instructions_path = out / "INSTRUCTIONS.md"
    instructions_path.write_text(instructions)

    manifest: dict[str, Any] = {
        "schema": "canli.labeling.active-ownership-13d-item4-blind-packet.v3",
        "author": "Arhan Canli",
        "rows": len(review),
        "prediction_blind": True,
        "forbidden_machine_fields": sorted(FORBIDDEN_MACHINE_FIELDS),
        "source_lineage": {
            "frozen_labels_sha256": sha256_file(labels_path),
            "document_audit_sha256": sha256_file(audit_path),
            "result_sha256": sha256_file(result_path),
        },
        "packet_files": {
            "instructions_sha256": sha256_file(instructions_path),
            "reviewer_labels_sha256": sha256_file(review_path),
            "reviewer_attestation_template_sha256": sha256_file(attestation_path),
            "review_workspace_sha256": sha256_file(review_ui_path),
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
