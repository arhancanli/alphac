#!/usr/bin/env python3
"""Prospectively audit the frozen Active Ownership human-label gate without returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE_DIR: Final = ROOT / "artifacts" / "feasibility" / "active_ownership_13d_item4_v3"
PACKET_DIR: Final = ROOT / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
PROTOCOL: Final = ROOT / "docs" / "design" / "FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4_V3.md"
AUDIT_PROTOCOL: Final = ROOT / "docs" / "design" / "ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT.md"
OUTPUT: Final = ROOT / "artifacts" / "analysis" / "active_ownership_human_gate_audit.json"

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


def _binomial_upper_tail(successes: int, trials: int, probability: float) -> float:
    return sum(
        math.comb(trials, count) * probability**count * (1.0 - probability) ** (trials - count)
        for count in range(successes, trials + 1)
    )


def exact_one_sided_lower_bound(
    successes: int, trials: int, confidence_level: float = CONFIDENCE_LEVEL
) -> float:
    """Return the one-sided Clopper-Pearson lower confidence bound."""

    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("successes and trials must satisfy 0 <= successes <= trials")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be strictly between zero and one")
    if successes == 0:
        return 0.0
    alpha = 1.0 - confidence_level
    low, high = 0.0, 1.0
    for _ in range(100):
        midpoint = (low + high) / 2.0
        if _binomial_upper_tail(successes, trials, midpoint) < alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def minimum_perfect_trials(target: float, confidence_level: float = CONFIDENCE_LEVEL) -> int:
    """Smallest all-success denominator whose exact lower bound reaches ``target``."""

    if not 0.0 < target < 1.0:
        raise ValueError("target must be strictly between zero and one")
    trials = 1
    while exact_one_sided_lower_bound(trials, trials, confidence_level) < target:
        trials += 1
    return trials


def _candidate_count(value: Any) -> int:
    if isinstance(value, str):
        parsed = json.loads(value) if value else []
        return len(parsed)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    return len(value)


def build_audit(
    source_dir: Path = SOURCE_DIR,
    packet_dir: Path = PACKET_DIR,
    protocol_path: Path = PROTOCOL,
) -> dict[str, Any]:
    labels_path = source_dir / "frozen_human_labels.csv"
    audit_path = source_dir / "document_audit.parquet"
    result_path = source_dir / "result.json"
    manifest_path = packet_dir / "manifest.json"

    labels = pd.read_csv(labels_path, dtype={"accession": str}, keep_default_na=False)
    human_columns = [str(column) for column in labels if str(column).startswith("human_")]
    labels_unopened = bool(human_columns) and all(
        labels[column].eq("").all() for column in human_columns
    )
    if not labels_unopened:
        raise ValueError("prospective gate audit requires all frozen human labels to remain blank")

    document_audit = pd.read_parquet(audit_path)
    document_audit["accession"] = document_audit["accession"].astype(str)
    merged = labels.merge(
        document_audit[
            [
                "accession",
                "specific_active_intent",
                "item4_extracted",
                "ownership_pct_candidates",
            ]
        ],
        on="accession",
        validate="one_to_one",
    )
    if len(merged) != 48 or merged["accession"].duplicated().any():
        raise ValueError("frozen human audit must contain 48 unique source rows")

    manifest = json.loads(manifest_path.read_text())
    result = json.loads(result_path.read_text())
    if manifest.get("content_hash") != content_hash(manifest):
        raise ValueError("blind-review manifest content hash mismatch")
    lineage = manifest.get("source_lineage", {})
    expected_lineage = {
        "frozen_labels_sha256": sha256_file(labels_path),
        "document_audit_sha256": sha256_file(audit_path),
        "result_sha256": sha256_file(result_path),
    }
    if lineage != expected_lineage:
        raise ValueError("blind-review manifest no longer binds the frozen source evidence")
    if manifest.get("prediction_blind") is not True or manifest.get("rows") != 48:
        raise ValueError("blind-review packet is not the governed 48-row prediction-blind packet")
    return_boundary_open = (
        manifest.get("return_data_opened") is not False
        or result.get("return_data_opened") is not False
    )
    if return_boundary_open:
        raise ValueError("return boundary was opened before the prospective gate audit")

    predicted_positive = int(merged["specific_active_intent"].astype(bool).sum())
    predicted_negative = len(merged) - predicted_positive
    extracted = int(merged["item4_extracted"].astype(bool).sum())
    candidate_counts = merged["ownership_pct_candidates"].map(_candidate_count)
    sole_candidate = int(candidate_counts.eq(1).sum())
    unresolved_by_machine_rule = len(merged) - sole_candidate
    years = sorted(int(year) for year in merged["year"].unique())
    year_counts = merged["year"].value_counts().sort_index()

    minimum_precision_tp = math.ceil(PRECISION_THRESHOLD * predicted_positive - 1e-12)
    maximum_precision_fp = predicted_positive - minimum_precision_tp
    minimum_ownership_exact = math.ceil(OWNERSHIP_THRESHOLD * len(merged) - 1e-12)
    maximum_ownership_mismatches = len(merged) - minimum_ownership_exact
    maximum_human_positives_for_recall_pass = math.floor(
        predicted_positive / RECALL_THRESHOLD + 1e-12
    )

    best_case_precision_lower = exact_one_sided_lower_bound(predicted_positive, predicted_positive)
    best_case_whole_packet_lower = exact_one_sided_lower_bound(len(merged), len(merged))
    minimum_perfect = {
        "precision_predicted_positives": minimum_perfect_trials(PRECISION_THRESHOLD),
        "recall_human_positives": minimum_perfect_trials(RECALL_THRESHOLD),
        "ownership_rows": minimum_perfect_trials(OWNERSHIP_THRESHOLD),
    }

    payload: dict[str, Any] = {
        "schema": "canli.alphac-active-ownership-human-gate-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "author": "Arhan Canli",
        "stage": "PROSPECTIVE_PRE_LABEL_PRE_RETURN_GATE_AUDIT",
        "governance": {
            "labels_opened": False,
            "return_data_opened": False,
            "return_hypotheses_spent": 0,
            "existing_point_thresholds_changed": False,
            "audit_may_rescue_known_outcome": False,
        },
        "frozen_design": {
            "rows": len(merged),
            "years": {"first": years[0], "last": years[-1], "count": len(years)},
            "rows_per_year": {str(year): int(count) for year, count in year_counts.items()},
            "machine_predicted_positive": predicted_positive,
            "machine_predicted_negative": predicted_negative,
            "item4_extracted": extracted,
            "item4_unresolved": len(merged) - extracted,
            "ownership_sole_candidate": sole_candidate,
            "ownership_unresolved_by_frozen_machine_rule": unresolved_by_machine_rule,
        },
        "point_gate_reachability": {
            "precision": {
                "threshold": PRECISION_THRESHOLD,
                "minimum_true_positives": minimum_precision_tp,
                "maximum_false_positives": maximum_precision_fp,
                "interpretation": (
                    f"With {predicted_positive} frozen predicted positives, the point gate passes "
                    f"only at {minimum_precision_tp}/{predicted_positive}; one false positive "
                    "fails."
                ),
            },
            "recall": {
                "threshold": RECALL_THRESHOLD,
                "human_positive_denominator_known_pre_label": False,
                "maximum_human_positives_that_can_still_pass": (
                    maximum_human_positives_for_recall_pass
                ),
                "interpretation": (
                    "The denominator is determined only by the independent labels. With eight "
                    "frozen predicted positives, eleven or more human-positive rows necessarily "
                    "make the 80% point-recall gate fail."
                ),
            },
            "ownership_exact": {
                "threshold": OWNERSHIP_THRESHOLD,
                "minimum_exact_rows": minimum_ownership_exact,
                "maximum_mismatches": maximum_ownership_mismatches,
                "interpretation": (
                    f"At least {minimum_ownership_exact}/48 exact outcomes are required; "
                    f"{maximum_ownership_mismatches} mismatches are permitted."
                ),
            },
            "operationally_reachable": True,
            "not_guaranteed_to_pass": True,
        },
        "statistical_establishment_audit": {
            "confidence_level_one_sided": CONFIDENCE_LEVEL,
            "method": "exact Clopper-Pearson binomial lower bound",
            "best_case_precision": {
                "successes": predicted_positive,
                "trials": predicted_positive,
                "point_estimate": 1.0,
                "lower_bound": best_case_precision_lower,
                "establishes_threshold": best_case_precision_lower >= PRECISION_THRESHOLD,
            },
            "best_case_whole_packet_accuracy": {
                "successes": len(merged),
                "trials": len(merged),
                "point_estimate": 1.0,
                "lower_bound": best_case_whole_packet_lower,
                "establishes_0_95": best_case_whole_packet_lower >= PRECISION_THRESHOLD,
            },
            "minimum_all_success_denominators": minimum_perfect,
            "conclusion": (
                "The 48-row packet can support a frozen feasibility point result but cannot, by "
                "itself, statistically establish 95% precision at one-sided 95% confidence. "
                "Passing point estimates must not be described as confidence-bound validation."
            ),
        },
        "decision": (
            "KEEP_FROZEN_48_ROW_POINT_GATE_FOR_RETURN_FEASIBILITY_AND_REQUIRE_DISJOINT_"
            "CONFIRMATORY_ACCURACY_BEFORE_SLEEVE_ADMISSION"
        ),
        "public_path": "/glassbox/active_ownership_human_gate_audit.json",
        "required_interpretation": {
            "if_point_gate_passes": (
                "May proceed only to the already-governed return preregistration stage. Report raw "
                "confusion counts, point metrics, and exact confidence bounds."
            ),
            "before_sleeve_admission": (
                "Freeze a disjoint independent confirmatory corpus sized by the relevant positive "
                "denominators and require one-sided 95% exact lower bounds to meet the declared "
                "precision, recall, and ownership thresholds."
            ),
            "if_point_gate_fails": (
                "The frozen classifier is data-gated. Do not tune it on these labels or open "
                "returns for this identity."
            ),
        },
        "source_bindings": {
            "generator": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "protocol": {
                "path": str(protocol_path.relative_to(ROOT)),
                "sha256": sha256_file(protocol_path),
            },
            "gate_audit_protocol": {
                "path": str(AUDIT_PROTOCOL.relative_to(ROOT)),
                "sha256": sha256_file(AUDIT_PROTOCOL),
            },
            "frozen_labels": {
                "path": str(labels_path.relative_to(ROOT)),
                "sha256": sha256_file(labels_path),
            },
            "document_audit": {
                "path": str(audit_path.relative_to(ROOT)),
                "sha256": sha256_file(audit_path),
            },
            "feasibility_result": {
                "path": str(result_path.relative_to(ROOT)),
                "sha256": sha256_file(result_path),
            },
            "blind_packet_manifest": {
                "path": str(manifest_path.relative_to(ROOT)),
                "sha256": sha256_file(manifest_path),
            },
        },
        "claim_boundary": (
            "This is a prospective gate-design and reachability audit. It uses frozen machine "
            "outputs but no human outcomes, prices, returns, or portfolio results. It proves "
            "neither classifier accuracy nor investment performance."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--packet-dir", type=Path, default=PACKET_DIR)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_audit(args.source_dir, args.packet_dir, args.protocol)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
