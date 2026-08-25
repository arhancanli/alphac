#!/usr/bin/env python3
"""Build a deterministic offline packet for the frozen blind Item 703 review."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SOURCE: Final[Path] = (
    REPO / "artifacts/feasibility/repurchase_issuance_flow/item703"
)
LABEL_SAMPLE: Final[Path] = SOURCE / "label_sample.parquet"
LABEL_TEMPLATE: Final[Path] = SOURCE / "labels.csv"
DOCUMENT_PARTS: Final[Path] = SOURCE / "document_parts"
DOCUMENT_RESULT: Final[Path] = SOURCE / "documents_result.json"
PARSER_RESULT: Final[Path] = SOURCE / "parser_result.json"
PARSER_PARTS: Final[Path] = SOURCE / "parser_parts"
OUT: Final[Path] = REPO / "artifacts/labeling/repurchase_item703_blind"
SEED: Final[str] = "repurchase-item703-independent-blind-review-v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _blind_rank(accession: str) -> str:
    return hashlib.sha256(f"{SEED}|{accession}".encode()).hexdigest()


def _latest_status() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for part_number, path in enumerate(sorted(DOCUMENT_PARTS.glob("status-*.parquet"))):
        frame = pd.read_parquet(path)
        frame["part_number"] = part_number
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("no frozen Item 703 document statuses")
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["accession", "part_number"])
        .drop_duplicates("accession", keep="last")
    )


def build(out: Path = OUT) -> dict[str, Any]:
    if PARSER_RESULT.exists() or any(PARSER_PARTS.glob("parse-*.parquet")):
        raise RuntimeError("refusing to build a blind packet after parser output exists")
    labels = pd.read_csv(LABEL_TEMPLATE, keep_default_na=False, dtype={"accession": str})
    label_fields = ["has_item703_table", "expected_month_rows", "expected_total_row"]
    if len(labels) != 60 or labels["accession"].duplicated().any():
        raise ValueError("frozen label template must contain 60 unique accessions")
    if not labels[label_fields].eq("").all().all():
        raise ValueError("refusing to rebuild the blind packet after labels were opened")

    sample = pd.read_parquet(LABEL_SAMPLE)
    sample["accession"] = sample["accession"].astype(str)
    status = _latest_status()
    status["accession"] = status["accession"].astype(str)
    selected = sample.merge(
        status[
            [
                "accession",
                "raw_cache_path",
                "raw_sha256",
                "raw_bytes",
                "error",
            ]
        ],
        on="accession",
        how="left",
        validate="one_to_one",
    )
    if len(selected) != 60 or selected["error"].notna().any():
        raise ValueError("all 60 frozen blind-review documents must be available")
    selected["blind_rank"] = selected["accession"].map(_blind_rank)
    selected = selected.sort_values("blind_rank").reset_index(drop=True)
    selected.insert(0, "packet_id", [f"RP703-{number:03d}" for number in range(1, 61)])

    out.mkdir(parents=True, exist_ok=True)
    documents = out / "documents"
    documents.mkdir(exist_ok=True)
    document_hashes: dict[str, str] = {}
    for row in selected.to_dict("records"):
        compressed = (REPO / str(row["raw_cache_path"])).read_bytes()
        raw = gzip.decompress(compressed)
        if len(raw) != int(row["raw_bytes"]) or _sha256_bytes(raw) != row["raw_sha256"]:
            raise ValueError(f"raw source bytes changed for {row['accession']}")
        destination = documents / f"{row['packet_id']}.html"
        destination.write_bytes(raw)
        document_hashes[destination.name] = _sha256(destination)

    review = selected[
        ["packet_id", "cik", "accession", "filing_year", "form", "document_url"]
    ].copy()
    review["has_item703_table"] = ""
    review["expected_month_rows"] = ""
    review["expected_total_row"] = ""
    review["label_notes"] = ""
    labels_path = out / "reviewer_labels.csv"
    review.to_csv(labels_path, index=False)

    attestation = {
        "reviewer_name": "",
        "reviewer_role": "",
        "completed_at": "",
        "independent_of_parser_development": False,
        "machine_outputs_not_consulted": False,
        "prices_and_returns_not_consulted": False,
        "all_labels_are_personally_reviewed": False,
    }
    attestation_path = out / "reviewer_attestation.json"
    attestation_path.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    instructions = """# Independent blind Item 703 review

Review all 60 documents without opening any parser output, return data, market prices, aggregate
machine result, or prior label. The packet is deterministically shuffled.

For each `packet_id`, open `documents/<packet_id>.html` and complete `reviewer_labels.csv`:

- `has_item703_table`: exactly `true` or `false`.
- `expected_month_rows`: count the monthly repurchase rows; use `0` when no Item 703 table exists.
- `expected_total_row`: exactly `true` or `false` for a total row.
- `label_notes`: concise source-based ambiguity notes; do not record a return opinion.

Do not reorder, add, or remove rows. After review, remove only the `packet_id` column or leave it
in place (the seal ignores extra columns), copy the completed values into the frozen `labels.csv`,
and complete `reviewer_attestation.json`. Then run
`uv run python scripts/seal_repurchase_item703_labels.py --attestation <completed-attestation>`
before any parser evaluation. Every independence flag may be set to `true` only after the review.
"""
    instructions_path = out / "INSTRUCTIONS.md"
    instructions_path.write_text(instructions, encoding="utf-8")

    source_result = json.loads(DOCUMENT_RESULT.read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
        "schema": "canli.labeling.repurchase-item703-blind-packet.v1",
        "author": "Arhan Canli",
        "rows": len(review),
        "prediction_blind": True,
        "parser_outputs_present": False,
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "source_lineage": {
            "label_sample_sha256": _sha256(LABEL_SAMPLE),
            "blank_label_template_sha256": _sha256(LABEL_TEMPLATE),
            "document_result_sha256": _sha256(DOCUMENT_RESULT),
            "document_result_content_hash": source_result["content_hash"],
        },
        "packet_files": {
            "instructions_sha256": _sha256(instructions_path),
            "reviewer_labels_sha256": _sha256(labels_path),
            "reviewer_attestation_template_sha256": _sha256(attestation_path),
            "documents": document_hashes,
        },
        "claim_boundary": (
            "This packet enables independent source labeling only. It contains no parser "
            "prediction, return, price, Sharpe, drawdown, correlation, capacity, or admission "
            "claim and spends zero return identities."
        ),
    }
    manifest["content_hash"] = _content_hash(manifest)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    manifest = build()
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
