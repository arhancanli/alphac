#!/usr/bin/env python3
"""Audit the non-active full-evidence reservation template without reading returns."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
TEMPLATE: Final = Path("config/forward_full_evidence_reservation_v2_template.json")
PROTOCOL: Final = Path("docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md")
CONTRACT: Final = Path("config/sleeve_admission_contract.json")
OUTPUT: Final = Path("artifacts/audit/forward_full_evidence_reservation_v2_template.json")
SCHEMA: Final = "canli.alphac-forward-full-evidence-template-audit.v1"
FORBIDDEN_OUTCOME_KEYS: Final = frozenset(
    {
        "admission_result",
        "cagr",
        "drawdown_result",
        "dsr_result",
        "equity",
        "final_equity",
        "max_drawdown",
        "pbo_result",
        "pnl",
        "psr_result",
        "return_result",
        "returns",
        "sharpe",
        "stress_result",
        "verdict",
    }
)
REQUIRED_NULL_PATHS: Final = (
    ("identity_batch", "family_trial_account"),
    ("identity_batch", "batch_id"),
    ("identity_batch", "direction_locked"),
    ("identity_batch", "economic_hypothesis"),
    ("pbo_matrix", "n_splits"),
    ("pbo_matrix", "maximum_combinations"),
    ("pbo_matrix", "seed"),
    ("diagnostic_scenarios", "baseline_scenario_id"),
    ("book_evidence", "book_return_snapshot_path"),
    ("book_evidence", "book_return_snapshot_sha256"),
    ("book_evidence", "candidate_weight"),
    ("book_evidence", "stress_mask_path"),
    ("book_evidence", "stress_mask_sha256"),
    ("book_evidence", "leave_one_period_definition"),
    ("book_drawdown", "simulation_specification_path"),
    ("book_drawdown", "simulation_specification_sha256"),
    ("book_drawdown", "overlay_configuration_path"),
    ("book_drawdown", "overlay_configuration_sha256"),
    ("execution_evidence", "scenario_manifest_path"),
    ("execution_evidence", "scenario_manifest_sha256"),
    ("data_and_environment", "point_in_time_data_manifest_path"),
    ("data_and_environment", "point_in_time_data_manifest_sha256"),
    ("data_and_environment", "runner_path"),
    ("data_and_environment", "runner_sha256"),
    ("data_and_environment", "project_sha256"),
    ("data_and_environment", "lockfile_sha256"),
    ("data_and_environment", "public_redistribution_rights_established"),
    ("decision", "contract_sha256"),
)
REQUIRED_EMPTY_LIST_PATHS: Final = (
    ("identity_batch", "identity_configs"),
    ("pbo_matrix", "identity_columns"),
    ("diagnostic_scenarios", "cost_stress_scenarios"),
    ("diagnostic_scenarios", "execution_stress_scenarios"),
    ("diagnostic_scenarios", "capacity_scenarios"),
    ("book_evidence", "book_series_ids"),
    ("execution_evidence", "applicable_dimensions"),
    ("execution_evidence", "not_applicable_dimensions"),
)


class TemplateAuditError(RuntimeError):
    """The prospective template is unsafe, stale, or accidentally active."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TemplateAuditError(f"required JSON is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise TemplateAuditError(f"required JSON is not an object: {path}")
    return cast(dict[str, Any], value)


def _nested(value: dict[str, Any], path: tuple[str, str]) -> Any:
    parent = value.get(path[0])
    if not isinstance(parent, dict) or path[1] not in parent:
        raise TemplateAuditError("missing template path: " + ".".join(path))
    return parent[path[1]]


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


def build(repo: Path = ROOT) -> dict[str, Any]:
    repo = repo.resolve()
    template = _load(repo / TEMPLATE)
    contract = _load(repo / CONTRACT)
    if template.get("schema") != "canli.alphac-forward-full-evidence-reservation-template.v2":
        raise TemplateAuditError("unexpected template schema")
    if template.get("status") != "TEMPLATE_NOT_IN_FORCE_NO_RETURN_AUTHORIZATION":
        raise TemplateAuditError("template is active or has an unsafe status")
    scope = template.get("scope")
    if scope != {
        "applies_to_known_results": False,
        "earliest_possible_reservation_ordinal": 230,
        "requires_separate_policy_promotion": True,
    }:
        raise TemplateAuditError("prospective scope is not fail-closed")
    for path in REQUIRED_NULL_PATHS:
        if _nested(template, path) is not None:
            raise TemplateAuditError("unfilled template field is not null: " + ".".join(path))
    for path in REQUIRED_EMPTY_LIST_PATHS:
        if _nested(template, path) != []:
            raise TemplateAuditError("unfilled template list is not empty: " + ".".join(path))
    forbidden = sorted(_walk_keys(template) & FORBIDDEN_OUTCOME_KEYS)
    if forbidden:
        raise TemplateAuditError(
            "template contains forbidden outcome keys: " + ", ".join(forbidden)
        )

    thresholds = contract.get("thresholds")
    policy = contract.get("diversification_evidence_policy")
    if not isinstance(thresholds, dict) or not isinstance(policy, dict):
        raise TemplateAuditError("active contract is missing required policy blocks")
    derived_checks = {
        "minimum_oos_observations": (
            template["primary_estimator"]["minimum_oos_observations"],
            thresholds["minimum_oos_observations"],
        ),
        "capacity_curve_min_points": (
            template["diagnostic_scenarios"]["minimum_capacity_points"],
            thresholds["capacity_curve_min_points"],
        ),
        "capacity_usd_min": (
            template["diagnostic_scenarios"]["required_capacity_usd"],
            thresholds["capacity_usd_min"],
        ),
        "bootstrap_samples": (
            template["book_evidence"]["bootstrap"]["samples"],
            policy["default_bootstrap_samples"],
        ),
        "bootstrap_block_size": (
            template["book_evidence"]["bootstrap"]["block_size"],
            policy["default_block_size"],
        ),
        "bootstrap_seed": (
            template["book_evidence"]["bootstrap"]["seed"],
            policy["default_seed"],
        ),
        "bootstrap_confidence": (
            template["book_evidence"]["bootstrap"]["one_sided_confidence"],
            policy["confidence_level_one_sided"],
        ),
    }
    drifted = {
        name: {"template": values[0], "contract": values[1]}
        for name, values in derived_checks.items()
        if values[0] != values[1]
    }
    if drifted:
        raise TemplateAuditError(f"template drifted from active contract: {drifted}")
    if template["decision"] != {
        "contract_path": str(CONTRACT),
        "contract_sha256": None,
        "admit_requires_every_applicable_gate": True,
        "possible_dispositions": ["ADMIT", "KILL", "INCOMPLETE", "INVALID"],
        "known_result_may_not_fill_template": True,
    }:
        raise TemplateAuditError("decision boundary is incomplete")
    expected_promotions = {
        "SATISFIABILITY_AUDIT_PASSES",
        "TRIAL_ACCOUNTING_BATCH_AND_DIAGNOSTIC_CLASSIFICATION_PROMOTED",
        "SERIALITY_GUARD_SUPPORTS_PREDECLARED_BATCH",
        "PUBLIC_PROJECTION_TESTS_PASS",
        "OWNER_PROMOTION_RECORDED",
    }
    if set(template.get("required_promotion_before_use", [])) != expected_promotions:
        raise TemplateAuditError("promotion gates are incomplete")
    protocol_text = (repo / PROTOCOL).read_text(encoding="utf-8")
    for phrase in (
        "not in force; no return authorization",
        "cannot be used to regrade any known result",
        "suppress interim result access",
        "Null may never be converted to zero",
    ):
        if phrase not in protocol_text:
            raise TemplateAuditError(f"protocol boundary is missing: {phrase}")

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_TEMPLATE_FAIL_CLOSED_NOT_ACTIVE_ZERO_RETURN",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "template": {
            "path": str(TEMPLATE),
            "bytes": (repo / TEMPLATE).stat().st_size,
            "sha256": _sha256(repo / TEMPLATE),
            "schema": template["schema"],
            "status": template["status"],
        },
        "protocol": {
            "path": str(PROTOCOL),
            "bytes": (repo / PROTOCOL).stat().st_size,
            "sha256": _sha256(repo / PROTOCOL),
        },
        "contract_reference": {
            "path": str(CONTRACT),
            "sha256": _sha256(repo / CONTRACT),
            "schema": contract["schema"],
            "derived_checks": {name: values[0] for name, values in sorted(derived_checks.items())},
        },
        "fail_closed_checks": {
            "known_results_excluded": True,
            "null_required_fields": len(REQUIRED_NULL_PATHS),
            "empty_required_lists": len(REQUIRED_EMPTY_LIST_PATHS),
            "outcome_keys_present": [],
            "return_artifacts_read": 0,
            "returns_computed": False,
            "hypotheses_spent": 0,
            "active_policy_changed": False,
            "return_authorized": False,
        },
        "remaining_before_promotion": template["required_promotion_before_use"],
        "claim_boundary": (
            "This audit proves the design template is fail-closed, return-blind, and aligned with "
            "selected current contract constants. It does not promote the template, alter the "
            "active policy, authorize a reservation, validate a candidate, or compute returns."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _serialized(document: dict[str, Any]) -> bytes:
    return json.dumps(document, indent=2, sort_keys=True).encode() + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write and args.check:
        raise SystemExit("choose either --write or --check")
    document = build(ROOT)
    path = ROOT / OUTPUT
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_serialized(document))
    elif args.check:
        if not path.is_file() or path.read_bytes() != _serialized(document):
            raise TemplateAuditError(f"template audit is stale or missing: {OUTPUT}")
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
