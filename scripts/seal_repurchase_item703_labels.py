#!/usr/bin/env python3
"""Validate and seal blind Item 703 labels before parser evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_repurchase_item703_manifest import (
    LABEL_SAMPLE,
    LABEL_TEMPLATE,
    MANIFEST,
    content_hash_valid,
)
from build_repurchase_item703_manifest import (
    RESULT as MANIFEST_RESULT,
)
from collect_repurchase_issuance_companyfacts import file_sha256
from collect_repurchase_item703_documents import (
    COLLECTOR_VERSION,
    parts_lineage,
)
from collect_repurchase_item703_documents import (
    OUT_DIR as DOCUMENT_PARTS,
)
from collect_repurchase_item703_documents import (
    RESULT as DOCUMENT_RESULT,
)

OUT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/label_seal.json"
)
PARSER_SOURCE: Final = Path("scripts/parse_repurchase_item703_documents.py")
PARSER_RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/parser_result.json"
)
PARSE_PARTS: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/parser_parts"
)
LABEL_COLUMNS: Final = (
    "cik",
    "accession",
    "filing_year",
    "form",
    "document_url",
    "has_item703_table",
    "expected_month_rows",
    "expected_total_row",
    "label_notes",
)


def parse_bool(value: object, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"{field} must be true/false or 1/0")


def validate_labels(labels: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    missing = set(LABEL_COLUMNS) - set(labels.columns)
    if missing:
        raise ValueError(f"label columns missing: {sorted(missing)}")
    expected = sample[["cik", "accession", "filing_year", "form", "document_url"]].copy()
    actual = labels[list(LABEL_COLUMNS)].copy()
    if len(actual) != len(expected) or actual["accession"].duplicated().any():
        raise ValueError("labels must contain exactly one row per frozen label identity")
    joined = expected.merge(
        actual,
        on=["cik", "accession", "filing_year", "form", "document_url"],
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    if not joined["_merge"].eq("both").all():
        raise ValueError("labels do not exactly match the frozen label sample")
    actual["has_item703_table"] = actual["has_item703_table"].map(
        lambda value: parse_bool(value, "has_item703_table")
    )
    actual["expected_total_row"] = actual["expected_total_row"].map(
        lambda value: parse_bool(value, "expected_total_row")
    )
    rows = pd.to_numeric(actual["expected_month_rows"], errors="raise")
    if rows.isna().any() or (rows < 0).any() or (rows % 1 != 0).any():
        raise ValueError("expected_month_rows must be a nonnegative integer")
    actual["expected_month_rows"] = rows.astype(int)
    absent = ~actual["has_item703_table"]
    if (
        actual.loc[absent, "expected_month_rows"].ne(0).any()
        or actual.loc[absent, "expected_total_row"].any()
    ):
        raise ValueError("documents without Item 703 must label zero rows and no total row")
    actual["label_notes"] = actual["label_notes"].fillna("").astype(str)
    return actual.sort_values("accession").reset_index(drop=True)


def require_sources(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(Path(args.manifest_result).read_text())
    documents = json.loads(Path(args.documents_result).read_text())
    part_count, part_hash = parts_lineage(Path(args.document_parts))
    if (
        manifest.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-manifest.v1"
        or manifest.get("complete") is not True
        or manifest.get("label_sample_sha256") != file_sha256(Path(args.label_sample))
        or manifest.get("document_manifest_sha256") != file_sha256(Path(args.manifest))
        or not content_hash_valid(manifest)
    ):
        raise RuntimeError("Item 703 manifest is stale or incomplete")
    if (
        documents.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-documents.v1"
        or documents.get("collector_version") != COLLECTOR_VERSION
        or documents.get("complete") is not True
        or documents.get("return_data_opened") is not False
        or documents.get("return_hypotheses_spent") != 0
        or documents.get("part_count") != part_count
        or documents.get("parts_sha256") != part_hash
        or documents.get("source_manifest_hash") != manifest.get("content_hash")
        or not content_hash_valid(documents)
    ):
        raise RuntimeError("Item 703 document collection is stale or incomplete")
    return manifest, documents


def run(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.out)
    parse_parts = Path(args.parse_parts)
    if out.exists():
        raise FileExistsError("label seal already exists and is immutable")
    if Path(args.parser_result).exists() or any(parse_parts.glob("parse-*.parquet")):
        raise RuntimeError("refusing to seal labels after parser output exists")
    manifest, documents = require_sources(args)
    parser_source = Path(args.parser_source)
    if not parser_source.exists():
        raise RuntimeError("frozen parser source must exist before labels are sealed")
    labels_path = Path(args.labels)
    labels = validate_labels(
        pd.read_csv(labels_path, keep_default_na=False),
        pd.read_parquet(args.label_sample),
    )
    if len(labels) != manifest["label_sample_size"]:
        raise ValueError("completed label count differs from frozen sample size")
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.repurchase-issuance-item703-label-seal.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "blind_labels_sealed_before_parser_evaluation",
        "source_manifest_hash": manifest["content_hash"],
        "source_documents_parts_sha256": documents["parts_sha256"],
        "label_sample_sha256": manifest["label_sample_sha256"],
        "labels_sha256": file_sha256(labels_path),
        "parser_source_sha256": file_sha256(parser_source),
        "label_count": len(labels),
        "positive_count": int(labels["has_item703_table"].sum()),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--manifest-result", default=str(MANIFEST_RESULT))
    parser.add_argument("--label-sample", default=str(LABEL_SAMPLE))
    parser.add_argument("--labels", default=str(LABEL_TEMPLATE))
    parser.add_argument("--document-parts", default=str(DOCUMENT_PARTS))
    parser.add_argument("--documents-result", default=str(DOCUMENT_RESULT))
    parser.add_argument("--parser-source", default=str(PARSER_SOURCE))
    parser.add_argument("--parser-result", default=str(PARSER_RESULT))
    parser.add_argument("--parse-parts", default=str(PARSE_PARTS))
    parser.add_argument("--out", default=str(OUT))
    result = run(parser.parse_args())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
