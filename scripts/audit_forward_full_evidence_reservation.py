#!/usr/bin/env python3
"""Return-blind satisfiability audit of ONE filled v2 full-evidence reservation.

WHY. The template audit (audit_forward_full_evidence_reservation_v2_template.py) proves the
empty template is fail-closed. This audit answers the protocol's acceptance question for a FILLED
reservation, from pre-result bytes only: can the complete conjunction of gates be measured, and
can every scenario actually fail? A stress scenario identical to its baseline cannot fail; a
capacity curve without the governing capital point cannot decide capacity; a batch with one
column cannot define PBO and can never ADMIT; an execution dimension that is neither applicable
nor excused cannot be evaluated. Each of those is refused here, before a return exists, so that
INCOMPLETE is never discovered after the primary result the way crypto_carry_portable_v1 was.

The audit opens the reservation, the template, the promotion receipt, the admission contract and
the files the reservation binds by hash. It opens no return, no price, no equity curve, and it
writes nothing but its receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
TEMPLATE: Final[str] = "config/forward_full_evidence_reservation_v2_template.json"
RECEIPT: Final[str] = "config/forward_full_evidence_reservation_v2_promotion.json"
CONTRACT: Final[str] = "config/sleeve_admission_contract.json"
SCHEMA: Final[str] = "canli.alphac-forward-full-evidence-reservation-audit.v1"
RECEIPT_SCHEMA: Final[str] = "canli.alphac-forward-full-evidence-v2-promotion.v1"
RESERVATION_SCHEMA: Final[str] = "canli.alphac-forward-trial-reservation.v1"
FORBIDDEN_OUTCOME_KEYS: Final[frozenset[str]] = frozenset(
    {
        "admission",
        "capacity_result",
        "drawdown",
        "dsr",
        "max_drawdown",
        "metrics",
        "pnl",
        "psr",
        "result",
        "returns",
        "sharpe",
        "stress_result",
        "verdict",
        "t_stat",
        "pbo",
    }
)
FULL_EVIDENCE_BLOCKS: Final[tuple[str, ...]] = (
    "template_path",
    "template_sha256",
    "promotion_receipt_path",
    "promotion_receipt_sha256",
    "primary_estimator",
    "pbo_matrix",
    "diagnostic_policy",
    "book_evidence",
    "book_drawdown",
    "execution_evidence",
    "data_and_environment",
)


class FilledReservationAuditError(ValueError):
    """The reservation cannot be measured as written; nothing was computed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _content_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "content_hash"}
    return "sha256:" + _canonical_sha256(body)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FilledReservationAuditError(f"not a JSON object: {path}")
    return value


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _walk_keys(item)
    return keys


def _bound_file(repo: Path, relative: Any, claimed: Any, what: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise FilledReservationAuditError(f"{what}: path must be a repository-relative string")
    path = (repo / relative).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError as error:
        raise FilledReservationAuditError(f"{what}: path escapes the repository") from error
    if not path.is_file():
        raise FilledReservationAuditError(f"{what}: bound file is missing: {relative}")
    if _sha256(path) != claimed:
        raise FilledReservationAuditError(f"{what}: sha256 does not match the file on disk")
    return path


def _numeric_items(assumptions: dict[str, Any]) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in assumptions.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


def _scenario_index(block: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for scenario_class in (
        "cost_stress_scenarios",
        "execution_stress_scenarios",
        "capacity_scenarios",
    ):
        for scenario in block.get(scenario_class, []) or []:
            scenarios[str(scenario["scenario_id"])] = {**scenario, "class": scenario_class}
    return scenarios


def audit(reservation_path: Path, repo: Path = ROOT) -> dict[str, Any]:
    repo = repo.resolve()
    reservation = _load(reservation_path)
    failures: list[str] = []

    def fail(message: str) -> None:
        failures.append(message)

    if reservation.get("schema") != RESERVATION_SCHEMA:
        raise FilledReservationAuditError("reservation schema is not the v1 reservation schema")
    forbidden = sorted(_walk_keys(reservation) & FORBIDDEN_OUTCOME_KEYS)
    if forbidden:
        raise FilledReservationAuditError(
            "reservation contains outcome keys before any return: " + ", ".join(forbidden)
        )
    full = reservation.get("full_evidence")
    if not isinstance(full, dict) or tuple(sorted(full)) != tuple(sorted(FULL_EVIDENCE_BLOCKS)):
        raise FilledReservationAuditError(
            "full_evidence must carry exactly: " + ", ".join(FULL_EVIDENCE_BLOCKS)
        )

    # --- the promoted template and its receipt -------------------------------------------
    if full["template_path"] != TEMPLATE or full["promotion_receipt_path"] != RECEIPT:
        raise FilledReservationAuditError(
            "full_evidence must bind the canonical template and receipt"
        )
    template_file = _bound_file(repo, TEMPLATE, full["template_sha256"], "template")
    receipt_file = _bound_file(repo, RECEIPT, full["promotion_receipt_sha256"], "promotion receipt")
    template = _load(template_file)
    receipt = _load(receipt_file)
    if template.get("status") != "IN_FORCE":
        fail("the v2 template is not in force; no reservation can be authorized under it")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("content_hash") != _content_hash(
        receipt
    ):
        fail("the promotion receipt is invalid")
    elif receipt.get("promoted_template_sha256") != full["template_sha256"]:
        fail("the promotion receipt does not bind the template this reservation binds")
    contract = _load(repo / CONTRACT)
    thresholds = contract["thresholds"]
    policy = contract["diversification_evidence_policy"]

    # --- the batch and the PBO matrix ----------------------------------------------------
    batch = reservation.get("identity_batch")
    if not isinstance(batch, dict):
        raise FilledReservationAuditError("a v2 reservation must be a member of an identity_batch")
    columns = batch.get("identity_hashes")
    pbo = full["pbo_matrix"]
    if pbo.get("identity_columns") != columns:
        fail("pbo_matrix.identity_columns must be exactly the batch's identity hashes, in order")
    minimum_columns = int(template["pbo_matrix"]["minimum_identity_columns"])
    admit_reachable = isinstance(columns, list) and len(columns) >= minimum_columns
    if not admit_reachable:
        fail(
            f"the batch has {len(columns) if isinstance(columns, list) else 0} column(s); PBO "
            f"needs {minimum_columns}, so ADMIT is unreachable and the ceiling is INCOMPLETE"
        )
    for key in ("n_splits", "maximum_combinations", "seed"):
        value = pbo.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            fail(f"pbo_matrix.{key} must be a positive integer frozen before returns")
    if isinstance(pbo.get("n_splits"), int) and pbo["n_splits"] % 2:
        fail("pbo_matrix.n_splits must be even (combinatorially symmetric cross-validation)")
    if pbo.get("return_alignment") != template["pbo_matrix"]["return_alignment"]:
        fail("pbo_matrix.return_alignment must match the template")
    if pbo.get("undefined_policy") != template["pbo_matrix"]["undefined_policy"]:
        fail("pbo_matrix.undefined_policy must match the template")
    if full["primary_estimator"] != template["primary_estimator"]:
        fail("primary_estimator must equal the promoted template's frozen estimator")

    # --- diagnostics: every scenario must be able to fail --------------------------------
    diagnostics = reservation.get("diagnostic_scenarios")
    diagnostic_policy = full["diagnostic_policy"]
    if not isinstance(diagnostics, dict):
        fail("diagnostic_scenarios must be declared before the first return")
        diagnostics = {}
    scenarios = _scenario_index(diagnostics)
    baseline_id = diagnostic_policy.get("baseline_scenario_id")
    baseline = scenarios.get(str(baseline_id))
    if baseline is None:
        fail("diagnostic_policy.baseline_scenario_id must name a declared scenario")
    if diagnostic_policy.get("selection_permitted") is not False:
        fail("diagnostic_policy.selection_permitted must be false: a diagnostic never wins")
    if diagnostic_policy.get("all_scenarios_must_publish") is not True:
        fail("diagnostic_policy.all_scenarios_must_publish must be true")
    if diagnostic_policy.get("scenario_hashes_frozen_before_returns") is not True:
        fail("diagnostic_policy.scenario_hashes_frozen_before_returns must be true")
    stress_count = 0
    if baseline is not None:
        base_numeric = _numeric_items(baseline["assumptions"])
        for scenario_id, scenario in scenarios.items():
            if scenario_id == baseline_id or scenario["class"] == "capacity_scenarios":
                continue
            if scenario["assumptions"] == baseline["assumptions"]:
                fail(f"stress scenario {scenario_id} equals the baseline and cannot fail")
                continue
            # Direction is instrument-specific (a lower fill ratio is stricter, a higher fee is
            # stricter), so the return-blind test is difference, not direction: a scenario that
            # restates every number the baseline carries and adds nothing measurable is a
            # relabelled baseline and cannot fail.
            numeric = _numeric_items(scenario["assumptions"])
            shared = set(numeric) & set(base_numeric)
            new_measurable = set(numeric) - set(base_numeric)
            if shared and all(numeric[k] == base_numeric[k] for k in shared) and not new_measurable:
                fail(
                    f"stress scenario {scenario_id} restates the baseline's numbers and adds "
                    "nothing measurable; it cannot fail"
                )
                continue
            stress_count += 1
    if stress_count == 0:
        fail("no stress scenario is declared beyond the baseline")
    capacity = [s for s in scenarios.values() if s["class"] == "capacity_scenarios"]
    minimum_points = int(diagnostic_policy.get("minimum_capacity_points", 0) or 0)
    required_usd = float(diagnostic_policy.get("required_capacity_usd", 0) or 0)
    if minimum_points != int(thresholds["capacity_curve_min_points"]):
        fail("diagnostic_policy.minimum_capacity_points must equal the contract's")
    if required_usd != float(thresholds["capacity_usd_min"]):
        fail("diagnostic_policy.required_capacity_usd must equal the contract's")
    capitals: list[float] = []
    for scenario in capacity:
        value = scenario["assumptions"].get("capital_usd")
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            fail(f"capacity scenario {scenario['scenario_id']} must declare capital_usd > 0")
        else:
            capitals.append(float(value))
    if len(capitals) < minimum_points:
        fail(f"capacity needs at least {minimum_points} capital points; {len(capitals)} declared")
    if capitals and required_usd not in capitals:
        fail("the governing capacity point (required_capacity_usd) is not a declared capital point")
    if capitals and max(capitals) <= required_usd:
        fail("no capital point above the governing point: the curve cannot show where it breaks")
    if capitals != sorted(capitals) or len(set(capitals)) != len(capitals):
        fail("capacity capital points must be strictly increasing")

    # --- book evidence and drawdown ------------------------------------------------------
    book = full["book_evidence"]
    try:
        _bound_file(
            repo,
            book.get("book_return_snapshot_path"),
            book.get("book_return_snapshot_sha256"),
            "book snapshot",
        )
        _bound_file(
            repo, book.get("stress_mask_path"), book.get("stress_mask_sha256"), "stress mask"
        )
    except FilledReservationAuditError as error:
        fail(str(error))
    series = book.get("book_series_ids")
    if not isinstance(series, list) or not series or len(set(series)) != len(series):
        fail("book_series_ids must be a non-empty list of distinct series identifiers")
    weight = book.get("candidate_weight")
    if not isinstance(weight, int | float) or isinstance(weight, bool) or not 0.0 < weight <= 0.5:
        fail("candidate_weight must be a fraction in (0, 0.5]")
    if book.get("alignment_rule") != template["book_evidence"]["alignment_rule"]:
        fail("book_evidence.alignment_rule must match the template")
    expected_bootstrap = {
        "samples": policy["default_bootstrap_samples"],
        "block_size": policy["default_block_size"],
        "seed": policy["default_seed"],
        "one_sided_confidence": policy["confidence_level_one_sided"],
    }
    if book.get("bootstrap") != expected_bootstrap:
        fail("book_evidence.bootstrap must equal the contract's diversification policy defaults")
    if (
        not isinstance(book.get("leave_one_period_definition"), str)
        or not book["leave_one_period_definition"]
    ):
        fail("leave_one_period_definition must be stated")
    drawdown = full["book_drawdown"]
    try:
        _bound_file(
            repo,
            drawdown.get("simulation_specification_path"),
            drawdown.get("simulation_specification_sha256"),
            "drawdown simulation specification",
        )
        _bound_file(
            repo,
            drawdown.get("overlay_configuration_path"),
            drawdown.get("overlay_configuration_sha256"),
            "overlay configuration",
        )
    except FilledReservationAuditError as error:
        fail(str(error))
    for key in ("expected_maximum_drawdown_required", "p95_maximum_drawdown_required"):
        if drawdown.get(key) is not True:
            fail(f"book_drawdown.{key} must be true")

    # --- execution evidence: every dimension applicable or excused, never neither --------
    execution = full["execution_evidence"]
    dimensions = list(contract["execution_dimensions"])
    applicable = execution.get("applicable_dimensions")
    excused = execution.get("not_applicable_dimensions")
    if not isinstance(applicable, list) or not isinstance(excused, dict):
        fail(
            "execution_evidence needs applicable_dimensions (list) and "
            "not_applicable_dimensions (object)"
        )
        applicable, excused = [], {}
    overlap = set(applicable) & set(excused)
    if overlap:
        fail("execution dimensions both applicable and excused: " + ", ".join(sorted(overlap)))
    missing = set(dimensions) - set(applicable) - set(excused)
    if missing:
        fail("execution dimensions neither applicable nor excused: " + ", ".join(sorted(missing)))
    unknown = (set(applicable) | set(excused)) - set(dimensions)
    if unknown:
        fail("execution dimensions the contract does not list: " + ", ".join(sorted(unknown)))
    for dimension, excuse in excused.items():
        if not isinstance(excuse, dict) or len(str(excuse.get("reason", ""))) < 20:
            fail(f"not-applicable dimension {dimension} needs a stated reason")
            continue
        try:
            _bound_file(
                repo,
                excuse.get("evidence_path"),
                excuse.get("evidence_sha256"),
                f"not-applicable evidence for {dimension}",
            )
        except FilledReservationAuditError as error:
            fail(str(error))
    minimum_scenarios = int(execution.get("minimum_scenarios_per_applicable_dimension", 0) or 0)
    if minimum_scenarios != int(thresholds["minimum_execution_scenarios_per_dimension"]):
        fail("minimum_scenarios_per_applicable_dimension must equal the contract's")
    manifest: dict[str, Any] = {}
    try:
        manifest_file = _bound_file(
            repo,
            execution.get("scenario_manifest_path"),
            execution.get("scenario_manifest_sha256"),
            "execution scenario manifest",
        )
        manifest = _load(manifest_file)
    except FilledReservationAuditError as error:
        fail(str(error))
    if manifest:
        scenario_ids: set[str] = set()
        for dimension in applicable:
            declared = manifest.get(dimension)
            if not isinstance(declared, list) or len(declared) < minimum_scenarios:
                fail(
                    f"applicable dimension {dimension} has fewer than {minimum_scenarios} scenarios"
                )
                continue
            for scenario in declared:
                if not isinstance(scenario, dict) or set(scenario) != {
                    "scenario_id",
                    "assumptions",
                    "assumptions_sha256",
                }:
                    fail(
                        f"execution scenario in {dimension} must carry exactly scenario_id, "
                        "assumptions, assumptions_sha256"
                    )
                    continue
                if _canonical_sha256(scenario["assumptions"]) != scenario["assumptions_sha256"]:
                    fail(f"execution scenario {scenario['scenario_id']} assumptions hash mismatch")
                if scenario["scenario_id"] in scenario_ids:
                    fail(f"duplicate execution scenario_id {scenario['scenario_id']}")
                scenario_ids.add(str(scenario["scenario_id"]))
        extra = set(manifest) - set(applicable)
        if extra:
            fail(
                "execution manifest declares scenarios for non-applicable dimensions: "
                + ", ".join(sorted(extra))
            )

    # --- data and environment ------------------------------------------------------------
    data = full["data_and_environment"]
    evidence = reservation.get("evidence", {})
    try:
        _bound_file(
            repo,
            data.get("point_in_time_data_manifest_path"),
            data.get("point_in_time_data_manifest_sha256"),
            "point-in-time data manifest",
        )
        _bound_file(repo, data.get("runner_path"), data.get("runner_sha256"), "runner")
    except FilledReservationAuditError as error:
        fail(str(error))
    if data.get("runner_sha256") != evidence.get("runner", {}).get("sha256"):
        fail("data_and_environment.runner_sha256 must equal the reservation's runner evidence")
    if data.get("project_sha256") != evidence.get("python_project", {}).get("sha256"):
        fail(
            "data_and_environment.project_sha256 must equal the reservation's python_project "
            "evidence"
        )
    if data.get("lockfile_sha256") != evidence.get("locked_environment", {}).get("sha256"):
        fail(
            "data_and_environment.lockfile_sha256 must equal the reservation's "
            "locked_environment evidence"
        )
    if data.get("input_snapshot_required_before_first_execution_leg") is not True:
        fail("input_snapshot_required_before_first_execution_leg must be true")
    if not isinstance(data.get("public_redistribution_rights_established"), bool):
        fail(
            "public_redistribution_rights_established must be decided (true or false) before "
            "returns"
        )

    status = "SATISFIABLE_RETURN_BLIND" if not failures else "UNSATISFIABLE_AS_WRITTEN"
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "status": status,
        "author": "Arhan Canli",
        "reservation": {
            "path": str(reservation_path.resolve().relative_to(repo))
            if reservation_path.resolve().is_relative_to(repo)
            else str(reservation_path),
            "sha256": _sha256(reservation_path),
            "return_identity_id": reservation.get("return_identity_id"),
            "hypothesis_identity": reservation.get("hypothesis_identity"),
            "batch_id": batch.get("batch_id"),
            "batch_content_hash": batch.get("batch_content_hash"),
        },
        "admit_reachable": admit_reachable and not failures,
        "disposition_ceiling": "ADMIT" if admit_reachable else "INCOMPLETE",
        "pbo_columns": len(columns) if isinstance(columns, list) else 0,
        "stress_scenarios_that_can_fail": stress_count,
        "capacity_points": capitals,
        "applicable_execution_dimensions": len(applicable),
        "excused_execution_dimensions": len(excused),
        "failures": failures,
        "fail_closed_checks": {
            "return_artifacts_read": 0,
            "returns_computed": False,
            "hypotheses_spent": 0,
            "outcome_keys_present": forbidden,
        },
        "claim_boundary": (
            "A return-blind audit of whether the reservation's evidence conjunction can be "
            "measured and whether every scenario can fail. It computes no return, promotes "
            "nothing, and decides nothing about the candidate."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reservation", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="write the receipt here")
    args = parser.parse_args(argv)
    document = audit(args.reservation)
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(
        document["status"],
        f"ceiling={document['disposition_ceiling']}",
        f"failures={len(document['failures'])}",
    )
    for failure in document["failures"]:
        print("  -", failure)
    return 0 if document["status"] == "SATISFIABLE_RETURN_BLIND" else 1


if __name__ == "__main__":
    sys.exit(main())
