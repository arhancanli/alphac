#!/usr/bin/env python3
"""Seal the no-return merger-announcement v2 confirmatory design."""

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

INPUTS: Final = ROOT / "config" / "merger_announcement_confirmatory_design_inputs.json"
PROTOCOL: Final = ROOT / "docs" / "design" / "FEASIBILITY_MERGER_ANNOUNCEMENT_IDENTITY_V2.md"
OUTPUT: Final = (
    ROOT
    / "artifacts"
    / "feasibility"
    / "merger_arbitrage"
    / "announcement_confirmatory_design.json"
)
YEARS: Final = tuple(range(2006, 2016))
STRATA: Final = ("DEFM14A", "SC 14D9")
ROWS_PER_CELL: Final = 20
ROWS_PER_STRATUM: Final = len(YEARS) * ROWS_PER_CELL
TOTAL_ROWS: Final = len(STRATA) * ROWS_PER_STRATUM
CONFIDENCE_LEVEL: Final = 0.95
SELECTION_NAMESPACE: Final = "alphac-merger-announcement-confirmation-v2"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def minimum_successes_to_pass(
    trials: int, point_threshold: float, lower_bound_threshold: float
) -> int:
    for successes in range(trials + 1):
        point = successes / trials
        lower = exact_one_sided_lower_bound(successes, trials, CONFIDENCE_LEVEL)
        if point >= point_threshold and lower >= lower_bound_threshold:
            return successes
    raise ValueError("declared confidence gate cannot pass at the target denominator")


def build() -> dict[str, Any]:
    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    if (
        inputs.get("schema")
        != "canli.alphac-merger-announcement-confirmatory-inputs.v1"
        or inputs.get("status")
        != "SEALED_EXPLORATORY_INPUT_RECEIPT_CONFIRMATION_CORPUS_UNOPENED"
        or inputs.get("content_hash") != content_hash(inputs)
    ):
        raise ValueError("merger confirmatory input receipt is invalid")
    values = inputs["governed_values"]
    if (
        values["exploration_period"] != {"start": "2016-01-01", "end": "2025-12-31"}
        or values["confirmation_period"]
        != {"start": "2006-01-01", "end": "2015-12-31"}
        or values["confirmation_corpus_opened"] is not False
        or values["confirmation_documents_acquired"] != 0
        or values["confirmation_labels_completed"] != 0
        or values["return_data_opened"] is not False
        or values["return_hypotheses_spent"] != 0
        or values["forbidden_market_columns"] != []
    ):
        raise ValueError("confirmation or return boundary is already open")

    gate_specs = {
        "announcement_coverage": {"point": 0.80, "lower": 0.75},
        "same_transaction_link_accuracy": {"point": 0.95, "lower": 0.95},
        "acceptance_timestamp_accuracy": {"point": 0.90, "lower": 0.90},
        "outcome_marker_coverage": {"point": 0.70, "lower": 0.65},
    }
    confidence_gates = {
        key: {
            "point_threshold": spec["point"],
            "one_sided_exact_lower_95_threshold": spec["lower"],
            "target_denominator": ROWS_PER_STRATUM,
            "minimum_successes_at_target_denominator": minimum_successes_to_pass(
                ROWS_PER_STRATUM, spec["point"], spec["lower"]
            ),
        }
        for key, spec in gate_specs.items()
    }

    payload: dict[str, Any] = {
        "schema": "canli.alphac-merger-announcement-confirmatory-design.v1",
        "family": "merger_arbitrage",
        "project_owner": "Arhan Canli",
        "technical_authorship_approved": False,
        "authorship_disclosure": (
            "AI-assisted technical draft prepared under the project owner's direction; "
            "Arhan Canli has not yet reviewed or approved the exact design."
        ),
        "declared_on": "2026-08-26",
        "stage": "PROSPECTIVE_PRE_CORPUS_PRE_LABEL_PRE_RETURN_IDENTITY_REDESIGN",
        "exploratory_result_preserved_as_failed": True,
        "exploration_period": values["exploration_period"],
        "confirmation_period": values["confirmation_period"],
        "periods_disjoint": True,
        "protocol_frozen": True,
        "corpus_acquired": False,
        "corpus_frozen": False,
        "independent_labels_completed": 0,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "execution_authorized": False,
        "strata": {
            "values": list(STRATA),
            "reported_and_gated_separately": True,
            "aggregate_cannot_rescue_failed_stratum": True,
            "exploratory_measurements": values["strata"],
        },
        "selection": {
            "namespace": SELECTION_NAMESPACE,
            "rank_expression": (
                "sha256(namespace + '|' + year + '|' + stratum + '|' + accession)"
            ),
            "years": list(YEARS),
            "rows_per_year_stratum_cell": ROWS_PER_CELL,
            "rows_per_stratum": ROWS_PER_STRATUM,
            "target_rows": TOTAL_ROWS,
            "insufficient_cell_policy": "DATA_GATED_NO_CROSS_CELL_SUBSTITUTION",
            "exploratory_accessions_excluded": int(values["target_anchors"]),
            "selection_uses_document_text": False,
            "selection_uses_machine_prediction": False,
            "selection_uses_human_labels": False,
            "selection_uses_prices_or_returns": False,
            "selection_uses_realized_deal_outcome": False,
        },
        "resolver": {
            "lookback_calendar_days": 365,
            "candidate_sources": [
                "TARGET_8K_ITEM_1_01_7_01_OR_8_01_WITH_QUALIFYING_EXHIBIT",
                "TARGET_PREM14A_OR_DEFA14A_WITH_PARTIES_AND_CASH_TERMS",
                "BIDDER_SC_TO_T_LINKED_BY_SUBJECT_COMPANY_CIK",
            ],
            "qualifying_fields": [
                "target_cik",
                "one_named_counterparty",
                "one_cash_consideration",
                "binding_agreement_or_commenced_offer_language",
            ],
            "selection_rule": "EARLIEST_QUALIFYING_SEC_ACCEPTANCE_TIMESTAMP",
            "later_confirmation_may_backdate": False,
            "conflict_policy": "UNRESOLVED_CONFLICT",
            "states": [
                "RESOLVED_CASH_MERGER",
                "RESOLVED_CASH_TENDER",
                "UNRESOLVED_NO_QUALIFYING_SOURCE",
                "UNRESOLVED_CONFLICT",
                "OUT_OF_SCOPE_NON_CASH_OR_COMPLEX_CONSIDERATION",
            ],
        },
        "confidence_gates_per_stratum": confidence_gates,
        "lineage_gate": {
            "required_fields": [
                "cik",
                "accession",
                "form",
                "acceptance_timestamp",
                "primary_document",
                "archive_url",
                "document_sha256",
            ],
            "required_rate": 1.0,
        },
        "review_boundary": {
            "independent_reviewer_required": True,
            "prediction_blind_packet_required": True,
            "all_selected_anchors_labeled": True,
            "no_automated_or_ai_labeling_assistance": True,
            "prices_and_returns_forbidden": True,
            "raw_confusion_counts_required": True,
        },
        "activation": {
            "corpus_acquisition_requires_author_approval": True,
            "return_preregistration_requires_both_strata_to_pass": True,
            "return_preregistration_is_separate": True,
            "approval_recorded": False,
        },
        "technical_gates": {
            "exploratory_failure_preserved": True,
            "confirmation_period_disjoint": True,
            "both_strata_preserved": True,
            "strata_gated_separately": True,
            "selection_is_pre_text_pre_label_pre_return": True,
            "resolver_is_deterministic_and_fail_closed": True,
            "confidence_gates_are_predeclared": True,
            "market_and_return_columns_absent": True,
            "confirmation_corpus_unopened": True,
            "return_data_unopened": True,
            "return_hypotheses_unspent": True,
            "author_technical_approval_recorded": False,
        },
        "technical_decision": "PASS_PROSPECTIVE_NO_RETURN_CONFIRMATORY_DESIGN",
        "governance_decision": "AUTHOR_APPROVAL_REQUIRED",
        "decision": "AUTHOR_APPROVAL_REQUIRED",
        "candidate_status": "identity-redesign-required",
        "source_bindings": {
            "protocol": {
                "path": str(PROTOCOL.relative_to(ROOT)),
                "sha256": sha256_file(PROTOCOL),
            },
            "compact_input_receipt": {
                "path": str(INPUTS.relative_to(ROOT)),
                "sha256": sha256_file(INPUTS),
                "content_hash": inputs["content_hash"],
            },
            **inputs["raw_source_bindings"],
        },
        "claim_boundary": (
            "Freezes a disjoint no-return confirmation design for a materially new announcement "
            "identity. It proves no corpus coverage, resolver accuracy, return, Sharpe, drawdown, "
            "correlation, capacity, or sleeve admission."
        ),
    }
    technical_without_author = {
        key: value
        for key, value in payload["technical_gates"].items()
        if key != "author_technical_approval_recorded"
    }
    if not all(technical_without_author.values()):
        raise ValueError("prospective merger technical design does not pass")
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
