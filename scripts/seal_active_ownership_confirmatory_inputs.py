#!/usr/bin/env python3
"""Seal the compact source receipt used by the Active Ownership confirmation design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
METADATA_RESULT: Final = (
    ROOT / "artifacts" / "feasibility" / "active_ownership_13d_schema_v2" / "result.json"
)
HEADER_AUDIT: Final = (
    ROOT
    / "artifacts"
    / "feasibility"
    / "active_ownership_13d_schema_v2"
    / "header_audit.parquet"
)
ORIGINAL_SAMPLE: Final = (
    ROOT
    / "artifacts"
    / "feasibility"
    / "active_ownership_13d_item4_v3"
    / "locked_document_sample.csv"
)
FEASIBILITY_RESULT: Final = (
    ROOT / "artifacts" / "feasibility" / "active_ownership_13d_item4_v3" / "result.json"
)
POINT_GATE_AUDIT: Final = (
    ROOT / "artifacts" / "analysis" / "active_ownership_human_gate_audit.json"
)
OUTPUT: Final = ROOT / "config" / "active_ownership_confirmatory_design_inputs.json"
YEARS: Final = tuple(range(2010, 2026))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def build() -> dict[str, Any]:
    metadata = json.loads(METADATA_RESULT.read_text(encoding="utf-8"))
    feasibility = json.loads(FEASIBILITY_RESULT.read_text(encoding="utf-8"))
    point_audit = json.loads(POINT_GATE_AUDIT.read_text(encoding="utf-8"))
    headers = pd.read_parquet(HEADER_AUDIT)
    original = pd.read_csv(ORIGINAL_SAMPLE, dtype={"accession": str})

    if metadata.get("decision") != "PASS_TO_DOCUMENT_FEASIBILITY":
        raise ValueError("Schedule 13D metadata feasibility is not in the governed pass state")
    if metadata.get("unique_initial_accessions") != 22_353 or len(headers) != 800:
        raise ValueError("Schedule 13D metadata universe or cached header sample changed")
    original_by_year = {
        str(year): int(rows) for year, rows in original.groupby("year").size().items()
    }
    if (
        len(original) != 160
        or original["accession"].nunique() != 160
        or original_by_year != {str(year): 10 for year in YEARS}
    ):
        raise ValueError("original document corpus is not the governed 160-row design")
    if (
        point_audit.get("stage") != "PROSPECTIVE_PRE_LABEL_PRE_RETURN_GATE_AUDIT"
        or point_audit.get("governance", {}).get("labels_opened") is not False
        or point_audit.get("governance", {}).get("return_data_opened") is not False
    ):
        raise ValueError("confirmatory inputs must be sealed before labels and returns")
    if feasibility.get("return_data_opened") is not False:
        raise ValueError("return boundary is already open")

    original_accessions = set(original["accession"].astype(str))
    cached_eligible = headers[
        headers["error"].isna()
        & headers["acceptance_datetime"].notna()
        & headers["subject_cik"].notna()
        & headers["filed_by_cik"].notna()
        & headers["ticker_match_count"].eq(1)
        & ~headers["accession"].astype(str).isin(original_accessions)
    ]
    cached_by_year = {
        str(year): int((cached_eligible["year"].astype(int) == year).sum()) for year in YEARS
    }
    if len(cached_eligible) != 218 or min(cached_by_year.values()) != 5:
        raise ValueError("cached disjoint eligibility inventory changed; re-audit the design")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-active-ownership-confirmatory-design-inputs.v1",
        "status": "SEALED_COMPACT_INPUT_RECEIPT_RAW_WORKSPACE_SOURCES_NOT_INCLUDED",
        "sealed_on": "2026-08-26",
        "governed_values": {
            "metadata": {
                "decision": metadata["decision"],
                "unique_initial_accessions": metadata["unique_initial_accessions"],
            },
            "header_audit": {
                "rows": len(headers),
                "eligible_disjoint_rows": len(cached_eligible),
                "eligible_disjoint_by_year": cached_by_year,
                "minimum_year_count": min(cached_by_year.values()),
            },
            "original_document_sample": {
                "rows": len(original),
                "unique_accessions": len(original_accessions),
                "rows_by_year": original_by_year,
            },
            "feasibility": {
                "return_data_opened": feasibility["return_data_opened"],
                "specific_active_intent_rate": feasibility["specific_active_intent_rate"],
            },
            "point_gate_audit": {
                "stage": point_audit["stage"],
                "governance": point_audit["governance"],
                "minimum_all_success_denominators": point_audit[
                    "statistical_establishment_audit"
                ]["minimum_all_success_denominators"],
                "content_hash": point_audit["content_hash"],
            },
        },
        "raw_source_bindings": {
            "metadata_result": {
                "path": str(METADATA_RESULT.relative_to(ROOT)),
                "sha256": _sha256(METADATA_RESULT),
            },
            "header_audit": {
                "path": str(HEADER_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(HEADER_AUDIT),
            },
            "original_document_sample": {
                "path": str(ORIGINAL_SAMPLE.relative_to(ROOT)),
                "sha256": _sha256(ORIGINAL_SAMPLE),
            },
            "feasibility_result": {
                "path": str(FEASIBILITY_RESULT.relative_to(ROOT)),
                "sha256": _sha256(FEASIBILITY_RESULT),
            },
            "point_gate_audit": {
                "path": str(POINT_GATE_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(POINT_GATE_AUDIT),
                "content_hash": point_audit["content_hash"],
            },
        },
        "claim_boundary": (
            "This tracked compact receipt preserves governed counts and hashes needed to rebuild "
            "the pre-outcome design in a clean checkout. It does not include the raw workstation "
            "artifacts and therefore does not independently reproduce their row-level audit."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
