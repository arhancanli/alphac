#!/usr/bin/env python3
"""Seal the pre-outcome Active Ownership confirmatory-corpus design."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_active_ownership_human_gate import (  # noqa: E402
    exact_one_sided_lower_bound,
)

INPUT_SNAPSHOT: Final = (
    ROOT / "config" / "active_ownership_confirmatory_design_inputs.json"
)
PROTOCOL: Final = ROOT / "docs" / "design" / "ACTIVE_OWNERSHIP_CONFIRMATORY_CORPUS_PROTOCOL.md"
OUTPUT: Final = ROOT / "artifacts" / "analysis" / "active_ownership_confirmatory_design.json"

YEARS: Final = tuple(range(2010, 2026))
ROWS_PER_YEAR: Final = 40
TARGET_ROWS: Final = len(YEARS) * ROWS_PER_YEAR
HEADER_BATCH_PER_YEAR: Final = 50
SELECTION_NAMESPACE: Final = "alphac-active-ownership-confirmatory-v1"
PRECISION_THRESHOLD: Final = 0.95
RECALL_THRESHOLD: Final = 0.80
OWNERSHIP_THRESHOLD: Final = 0.90
CONFIDENCE_LEVEL: Final = 0.95


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _maximum_failures_that_pass(success_denominator: int, threshold: float) -> int:
    failures = 0
    while failures <= success_denominator:
        successes = success_denominator - failures
        lower = exact_one_sided_lower_bound(successes, success_denominator, CONFIDENCE_LEVEL)
        if lower < threshold:
            return failures - 1
        failures += 1
    return success_denominator


def build() -> dict[str, Any]:
    snapshot = json.loads(INPUT_SNAPSHOT.read_text(encoding="utf-8"))
    if (
        snapshot.get("schema")
        != "canli.alphac-active-ownership-confirmatory-design-inputs.v1"
        or snapshot.get("status")
        != "SEALED_COMPACT_INPUT_RECEIPT_RAW_WORKSPACE_SOURCES_NOT_INCLUDED"
        or snapshot.get("content_hash") != content_hash(snapshot)
    ):
        raise ValueError("confirmatory-design input receipt is invalid")
    values = snapshot["governed_values"]
    metadata = values["metadata"]
    headers = values["header_audit"]
    original = values["original_document_sample"]
    feasibility = values["feasibility"]
    point_audit = values["point_gate_audit"]

    if metadata.get("decision") != "PASS_TO_DOCUMENT_FEASIBILITY":
        raise ValueError("Schedule 13D metadata feasibility is not in the governed pass state")
    if metadata.get("unique_initial_accessions") != 22_353 or headers.get("rows") != 800:
        raise ValueError("Schedule 13D metadata universe or cached header sample changed")
    if (
        original.get("rows") != 160
        or original.get("unique_accessions") != 160
        or original.get("rows_by_year") != {str(year): 10 for year in YEARS}
    ):
        raise ValueError("original document corpus is not the governed 160-row design")
    if (
        point_audit.get("stage") != "PROSPECTIVE_PRE_LABEL_PRE_RETURN_GATE_AUDIT"
        or point_audit.get("governance", {}).get("labels_opened") is not False
        or point_audit.get("governance", {}).get("return_data_opened") is not False
    ):
        raise ValueError("confirmatory design must be sealed before labels and returns")
    if feasibility.get("return_data_opened") is not False:
        raise ValueError("return boundary is already open")

    cached_by_year = headers["eligible_disjoint_by_year"]
    if (
        set(cached_by_year) != {str(year) for year in YEARS}
        or headers.get("eligible_disjoint_rows") != 218
        or sum(cached_by_year.values()) != 218
        or headers.get("minimum_year_count") != 5
        or min(cached_by_year.values()) != 5
    ):
        raise ValueError("cached disjoint eligibility inventory changed; re-audit the design")

    observed_positive_rate = float(feasibility["specific_active_intent_rate"])
    expected_predicted_positives = round(TARGET_ROWS * observed_positive_rate)
    minimum_denominators = point_audit["minimum_all_success_denominators"]
    expected_precision_failures = _maximum_failures_that_pass(
        expected_predicted_positives, PRECISION_THRESHOLD
    )

    payload: dict[str, Any] = {
        "schema": "canli.alphac-active-ownership-confirmatory-design.v1",
        "project_owner": "Arhan Canli",
        "technical_authorship_approved": False,
        "authorship_disclosure": (
            "AI-assisted technical draft prepared under the project owner's direction; "
            "Arhan Canli has not yet reviewed or approved the exact text."
        ),
        "declared_on": "2026-08-26",
        "stage": "PROSPECTIVE_PRE_LABEL_PRE_RETURN_CONFIRMATORY_DESIGN",
        "protocol_frozen": True,
        "corpus_acquired": False,
        "corpus_frozen": False,
        "independent_labels_completed": 0,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "execution_authorized": False,
        "activation": {
            "condition": "ORIGINAL_48_ROW_POINT_GATE_PASSES_GOVERNED_IMPORT_AND_SCORING",
            "if_condition_fails": (
                "Retire this design without acquiring confirmation documents; do not tune on "
                "the failed labels and do not open returns for the identity."
            ),
        },
        "population": {
            "form": "initial Schedule 13D",
            "years": {"first": YEARS[0], "last": YEARS[-1], "count": len(YEARS)},
            "initial_accessions_in_metadata_universe": metadata["unique_initial_accessions"],
            "eligibility": [
                "successful SEC header lineage",
                "subject and filed-by CIKs resolved",
                "exactly one contemporaneous ticker mapping",
                "accession absent from the original 160-document feasibility corpus",
            ],
            "original_accessions_excluded": original["unique_accessions"],
        },
        "selection": {
            "namespace": SELECTION_NAMESPACE,
            "rank_expression": "sha256(namespace + '|' + year + '|' + accession)",
            "header_acquisition_increment_per_year": HEADER_BATCH_PER_YEAR,
            "rows_per_year": ROWS_PER_YEAR,
            "target_rows": TARGET_ROWS,
            "rule": (
                "For each year, fetch headers in deterministic rank order until 40 eligible "
                "disjoint rows exist or the year is exhausted; freeze the first 40."
            ),
            "fewer_than_40_in_any_year": "DATA_GATED_NO_CROSS_YEAR_SUBSTITUTION",
            "selection_uses_document_text": False,
            "selection_uses_machine_prediction": False,
            "selection_uses_human_labels": False,
            "selection_uses_prices_or_returns": False,
        },
        "current_cache": {
            "headers": headers["rows"],
            "eligible_disjoint_rows": headers["eligible_disjoint_rows"],
            "eligible_disjoint_by_year": cached_by_year,
            "minimum_year_count": min(cached_by_year.values()),
            "sufficient_for_design": False,
            "additional_header_acquisition_required": True,
            "confirmation_submissions_acquired": 0,
        },
        "confidence_gates": {
            "method": "one-sided exact Clopper-Pearson binomial lower bound",
            "confidence_level": CONFIDENCE_LEVEL,
            "precision": {
                "point_threshold": PRECISION_THRESHOLD,
                "lower_bound_threshold": PRECISION_THRESHOLD,
                "minimum_perfect_denominator": minimum_denominators[
                    "precision_predicted_positives"
                ],
            },
            "recall": {
                "point_threshold": RECALL_THRESHOLD,
                "lower_bound_threshold": RECALL_THRESHOLD,
                "minimum_perfect_denominator": minimum_denominators["recall_human_positives"],
            },
            "ownership_exact": {
                "point_threshold": OWNERSHIP_THRESHOLD,
                "lower_bound_threshold": OWNERSHIP_THRESHOLD,
                "minimum_perfect_denominator": minimum_denominators["ownership_rows"],
            },
            "all_existing_machine_extraction_gates_must_pass": True,
            "raw_confusion_counts_required": True,
        },
        "planning_power_not_outcome": {
            "observed_feasibility_machine_positive_rate": observed_positive_rate,
            "expected_predicted_positives_at_640": expected_predicted_positives,
            "expected_denominator_max_false_positives_while_precision_lb_passes": (
                expected_precision_failures
            ),
            "guarantees_actual_denominator_or_pass": False,
            "underpowered_actual_denominator_blocks_admission": True,
        },
        "review_boundary": {
            "prediction_blind_packet_required": True,
            "independent_reviewer_required": True,
            "no_automated_or_ai_labeling_assistance": True,
            "prices_and_returns_forbidden": True,
            "same_label_definitions_as_original_packet": True,
        },
        "decision": "PROTOCOL_FROZEN_EXECUTION_CONDITIONAL_ON_ORIGINAL_POINT_GATE_PASS",
        "source_bindings": {
            "protocol": {"path": str(PROTOCOL.relative_to(ROOT)), "sha256": sha256_file(PROTOCOL)},
            "compact_input_receipt": {
                "path": str(INPUT_SNAPSHOT.relative_to(ROOT)),
                "sha256": sha256_file(INPUT_SNAPSHOT),
                "content_hash": snapshot["content_hash"],
            },
            **snapshot["raw_source_bindings"],
        },
        "claim_boundary": (
            "This receipt freezes a future disjoint classifier-confirmation design. It proves no "
            "classifier accuracy, human review, return, Sharpe, drawdown, correlation, capacity, "
            "or sleeve admission."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
