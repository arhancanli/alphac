#!/usr/bin/env python3
"""Evaluate the frozen Item 703 parser against sealed blind labels, without returns."""

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
from build_repurchase_item703_manifest import LABEL_SAMPLE, LABEL_TEMPLATE, content_hash_valid
from collect_repurchase_issuance_companyfacts import file_sha256
from parse_repurchase_item703_documents import (
    OUT_DIR as PARSE_PARTS,
)
from parse_repurchase_item703_documents import (
    PARSER_VERSION,
)
from parse_repurchase_item703_documents import (
    RESULT as PARSER_RESULT,
)
from seal_repurchase_item703_labels import OUT as LABEL_SEAL
from seal_repurchase_item703_labels import validate_labels

OUT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/extraction_audit.json"
)


def classification_metrics(labels: pd.DataFrame, predictions: pd.DataFrame) -> dict[str, Any]:
    joined = labels.merge(
        predictions,
        on=["cik", "accession", "filing_year", "form"],
        how="left",
        validate="one_to_one",
        suffixes=("_expected", "_predicted"),
    )
    missing = joined["has_item703_table_predicted"].isna()
    expected = joined["has_item703_table_expected"].astype(bool)
    predicted = joined["has_item703_table_predicted"].fillna(False).astype(bool)
    tp = int((expected & predicted).sum())
    fp = int((~expected & predicted).sum())
    fn = int((expected & ~predicted).sum())
    tn = int((~expected & ~predicted).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    positive = expected
    month_exact = (
        joined.loc[positive, "expected_month_rows"]
        == joined.loc[positive, "month_rows"]
    )
    total_exact = (
        joined.loc[positive, "expected_total_row"]
        == joined.loc[positive, "has_total_row"]
    )
    return {
        "labels": len(joined),
        "missing_predictions": int(missing.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "positive_month_row_exact_rate": float(month_exact.mean()) if len(month_exact) else 0.0,
        "positive_total_row_accuracy": float(total_exact.mean()) if len(total_exact) else 0.0,
    }


def require_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    seal = json.loads(Path(args.label_seal).read_text())
    parser = json.loads(Path(args.parser_result).read_text())
    parse_parts = sorted(Path(args.parse_parts).glob("parse-*.parquet"))
    if len(parse_parts) != 1:
        raise RuntimeError("exactly one immutable parser part is required")
    if (
        seal.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-label-seal.v1"
        or seal.get("complete") is not True
        or seal.get("labels_sha256") != file_sha256(Path(args.labels))
        or seal.get("label_sample_sha256") != file_sha256(Path(args.label_sample))
        or not content_hash_valid(seal)
    ):
        raise RuntimeError("blind labels are stale or unsealed")
    if (
        parser.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-parser.v1"
        or parser.get("parser_version") != PARSER_VERSION
        or parser.get("complete") is not True
        or parser.get("source_label_seal_hash") != seal.get("content_hash")
        or parser.get("parser_source_sha256") != seal.get("parser_source_sha256")
        or parser.get("parse_part_sha256") != file_sha256(parse_parts[0])
        or parser.get("labels_opened") is not False
        or parser.get("return_data_opened") is not False
        or parser.get("return_hypotheses_spent") != 0
        or not content_hash_valid(parser)
    ):
        raise RuntimeError("parser result is stale, incomplete, or not blind")
    return seal, parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    seal, parser = require_inputs(args)
    labels = validate_labels(
        pd.read_csv(args.labels, keep_default_na=False),
        pd.read_parquet(args.label_sample),
    )
    parse_path = next(Path(args.parse_parts).glob("parse-*.parquet"))
    predictions = pd.read_parquet(parse_path)
    if predictions["parser_version"].ne(PARSER_VERSION).any():
        raise RuntimeError("parser part contains an unexpected version")
    metrics = classification_metrics(labels, predictions)
    gates = {
        "all_60_labels_joined": metrics["labels"] == 60
        and metrics["missing_predictions"] == 0,
        "precision_gte_0_85": metrics["precision"] >= 0.85,
        "recall_gte_0_80": metrics["recall"] >= 0.80,
        "parser_hash_bound_before_evaluation": True,
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    passed = all(gates.values())
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.repurchase-issuance-item703-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "blind_item703_extraction_audit_no_returns",
        "claim_boundary": (
            "Passing this extraction gate does not pass family feasibility; Company Facts "
            "coverage, contamination, amendment replay, and context gates remain mandatory."
        ),
        "source_item703_manifest_hash": seal["source_manifest_hash"],
        "source_label_seal_hash": seal["content_hash"],
        "source_parser_hash": parser["content_hash"],
        "metrics": metrics,
        "gates": gates,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "decision": "ITEM703_EXTRACTION_PASS" if passed else "ITEM703_EXTRACTION_FAIL",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    out = Path(args.out)
    if out.exists():
        raise FileExistsError("extraction audit is immutable; refusing to overwrite")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default=str(LABEL_TEMPLATE))
    parser.add_argument("--label-sample", default=str(LABEL_SAMPLE))
    parser.add_argument("--label-seal", default=str(LABEL_SEAL))
    parser.add_argument("--parse-parts", default=str(PARSE_PARTS))
    parser.add_argument("--parser-result", default=str(PARSER_RESULT))
    parser.add_argument("--out", default=str(OUT))
    result = run(parser.parse_args())
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "ITEM703_EXTRACTION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
