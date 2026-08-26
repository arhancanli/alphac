#!/usr/bin/env python3
"""Seal compact inputs for the merger-announcement v2 confirmatory design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
RESULT: Final = ROOT / "artifacts" / "feasibility" / "merger_arbitrage" / "result.json"
TIMELINE: Final = (
    ROOT
    / "artifacts"
    / "feasibility"
    / "merger_arbitrage"
    / "target_anchor_timeline.parquet"
)
OUTPUT: Final = ROOT / "config" / "merger_announcement_confirmatory_design_inputs.json"
FORBIDDEN_MARKET_TOKENS: Final = (
    "price",
    "return",
    "pnl",
    "sharpe",
    "drawdown",
    "equity",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build() -> dict[str, Any]:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    timeline = pd.read_parquet(TIMELINE)
    if (
        result.get("schema") != "canli.feasibility.merger-arbitrage-metadata.v1"
        or result.get("decision") != "DATA_GATED"
        or result.get("period") != {"start": "2016-01-01", "end": "2025-12-31"}
        or result.get("target_anchors") != 1965
    ):
        raise ValueError("exploratory merger metadata result changed")
    forbidden = sorted(
        column
        for column in timeline.columns
        if any(token in column.lower() for token in FORBIDDEN_MARKET_TOKENS)
    )
    if forbidden:
        raise ValueError(f"market or return columns are prohibited: {forbidden}")
    if len(timeline) != 1965 or set(timeline["form"]) != {"DEFM14A", "SC 14D9"}:
        raise ValueError("exploratory merger timeline changed")

    strata: dict[str, Any] = {}
    for form, frame in timeline.groupby("form", sort=True):
        strata[str(form)] = {
            "anchors": len(frame),
            "prior_item101_8k_rate": float(frame["prior_8k_accession"].notna().mean()),
            "later_item201_or_102_8k_rate": float(
                frame["later_outcome_accession"].notna().mean()
            ),
            "first_filing_date": str(frame["filing_date"].min()),
            "last_filing_date": str(frame["filing_date"].max()),
        }
    expected_strata = {
        "DEFM14A": {
            "anchors": 1523,
            "prior_item101_8k_rate": 0.613263296126067,
            "later_item201_or_102_8k_rate": 0.9238345370978333,
            "first_filing_date": "2016-01-08",
            "last_filing_date": "2025-12-31",
        },
        "SC 14D9": {
            "anchors": 442,
            "prior_item101_8k_rate": 0.8665158371040724,
            "later_item201_or_102_8k_rate": 0.8959276018099548,
            "first_filing_date": "2016-01-05",
            "last_filing_date": "2025-12-29",
        },
    }
    if strata != expected_strata:
        raise ValueError("exploratory form-stratum measurements changed")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-merger-announcement-confirmatory-inputs.v1",
        "status": "SEALED_EXPLORATORY_INPUT_RECEIPT_CONFIRMATION_CORPUS_UNOPENED",
        "governed_values": {
            "exploration_period": {"start": "2016-01-01", "end": "2025-12-31"},
            "exploration_decision": "DATA_GATED",
            "target_anchors": len(timeline),
            "aggregate_prior_item101_8k_rate": result["prior_item101_8k_rate"],
            "strata": strata,
            "timeline_columns": list(timeline.columns),
            "forbidden_market_columns": forbidden,
            "confirmation_period": {"start": "2006-01-01", "end": "2015-12-31"},
            "confirmation_corpus_opened": False,
            "confirmation_documents_acquired": 0,
            "confirmation_labels_completed": 0,
            "return_data_opened": False,
            "return_hypotheses_spent": 0,
        },
        "raw_source_bindings": {
            "exploratory_result": {
                "path": str(RESULT.relative_to(ROOT)),
                "sha256": sha256_file(RESULT),
            },
            "exploratory_timeline": {
                "path": str(TIMELINE.relative_to(ROOT)),
                "sha256": sha256_file(TIMELINE),
            },
        },
        "claim_boundary": (
            "Binds already published no-return exploratory metadata and reserves a disjoint "
            "confirmation period. It opens no confirmation document, price, return, or outcome "
            "and proves no redesigned identity, alpha, or sleeve admission."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
