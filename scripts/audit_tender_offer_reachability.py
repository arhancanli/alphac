#!/usr/bin/env python3
"""Establish whether tender-offer parser work is justified, without opening returns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
PROTOCOL: Final[Path] = REPO / "docs" / "design" / "FEASIBILITY_TENDER_OFFER_SPREAD.md"
AUDIT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "tender_offer_spread" / "document_audit.parquet"
)
LABELS: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "tender_offer_spread" / "frozen_human_labels.csv"
)
FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "tender_offer_spread" / "result.json"
)
OUT: Final[Path] = (
    REPO / "artifacts" / "analysis" / "tender_offer_reachability" / "result.json"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build() -> dict[str, Any]:
    audit = pd.read_parquet(AUDIT)
    labels = pd.read_csv(LABELS, keep_default_na=False)
    feasibility = json.loads(FEASIBILITY_RESULT.read_text(encoding="utf-8"))
    required_label_columns = {
        "accession",
        "document_sha256",
        "human_unique_cash_price",
        "human_recommendation",
    }
    if not required_label_columns <= set(labels.columns):
        raise ValueError("frozen tender accuracy labels have an unexpected schema")
    if len(labels) != 30 or labels["accession"].duplicated().any():
        raise ValueError("frozen tender accuracy set must contain 30 unique accessions")
    if audit["accession"].duplicated().any():
        raise ValueError("tender document audit contains duplicate accessions")
    audit_by_accession = audit.set_index("accession")
    if not set(labels["accession"]) <= set(audit_by_accession.index):
        raise ValueError("frozen tender accuracy accessions do not resolve to the document audit")
    expected_hashes = labels.set_index("accession")["document_sha256"]
    actual_hashes = audit_by_accession.loc[expected_hashes.index, "document_sha256"]
    if not expected_hashes.equals(actual_hashes):
        raise ValueError("frozen tender labels no longer bind to the audited documents")

    valid_postures = {"recommend_accept", "recommend_reject", "neutral_or_unable", "ineligible"}
    completed = labels["human_unique_cash_price"].ne("") & labels[
        "human_recommendation"
    ].isin(valid_postures)
    extracted = audit["item4_extracted"].fillna(False).astype(bool)
    extracted_audit = audit[extracted]
    labels_complete = bool(completed.all())
    decision = "CEILING_MEASURABLE" if labels_complete else "CEILING_NOT_MEASURED"
    payload: dict[str, Any] = {
        "schema": "canli.alphac-tender-offer-reachability.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "stage": "document_extraction_reachability_no_prices_no_returns",
        "decision": decision,
        "return_data_opened": False,
        "market_return_files_opened": [],
        "return_hypotheses_spent": 0,
        "source_lineage": {
            "protocol_path": str(PROTOCOL.relative_to(REPO)),
            "protocol_sha256": sha256_file(PROTOCOL),
            "document_audit_path": str(AUDIT.relative_to(REPO)),
            "document_audit_sha256": sha256_file(AUDIT),
            "frozen_labels_path": str(LABELS.relative_to(REPO)),
            "frozen_labels_sha256": sha256_file(LABELS),
            "feasibility_result_path": str(FEASIBILITY_RESULT.relative_to(REPO)),
            "feasibility_result_sha256": sha256_file(FEASIBILITY_RESULT),
        },
        "locked_sample": {
            "documents": len(audit),
            "item4_sections_extracted": int(extracted.sum()),
            "frozen_accuracy_documents": len(labels),
            "completed_accuracy_labels": int(completed.sum()),
            "all_label_document_hashes_match": True,
        },
        "observed_parser_result": {
            "unique_price_sections": int(extracted_audit["strict_price_count"].eq(1).sum()),
            "multiple_price_sections": int(extracted_audit["strict_price_count"].gt(1).sum()),
            "resolved_recommendation_sections": int(
                extracted_audit["recommendation"].ne("unresolved").sum()
            ),
            "feasibility_decision": feasibility["decision"],
        },
        "parser_work_authorized": labels_complete,
        "required_next_evidence": (
            "Complete all 30 frozen, hash-bound human labels and score exact price/ineligibility "
            "and recommendation agreement. Only then can a perfect-detector ceiling distinguish "
            "repairable extraction from language that does not identify one tradable state."
        ),
        "claim_boundary": (
            "This audit classifies whether parser work is evidentially justified. It does not "
            "claim edge, sign, return, Sharpe, drawdown, capacity, correlation or admission."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], **payload["locked_sample"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
