"""The filled-reservation audit refuses evidence that cannot be measured or cannot fail.

WHY. crypto_carry_portable_v1 closed INCOMPLETE because the supplemental evidence was discovered
to be unfrozen after the primary result. The v2 protocol's acceptance test is that every gate can
be answered from pre-result bytes. These tests build one complete reservation in a temporary
repository (the same bytes the audit would read in production, minus any return) and then break
it one field at a time: a stress scenario equal to its baseline, a capacity curve without the
governing capital point, a one-column batch, an execution dimension neither applicable nor
excused, an outcome key. Each break must be named by the audit, not averaged away.

Reads no return data, spends no hypothesis, establishes nothing. Registered explicitly in
scripts/mutation_ledger.py (spec section 5 item 8).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "filled_reservation_audit", REPO / "scripts" / "audit_forward_full_evidence_reservation.py"
)
assert _SPEC is not None and _SPEC.loader is not None
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scenario(scenario_id: str, assumptions: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "assumptions": assumptions,
        "assumptions_sha256": _canonical(assumptions),
    }


def _repo(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A governed repository with a promoted template and one complete two-column reservation."""
    contract = json.loads((REPO / "config" / "sleeve_admission_contract.json").read_text())
    template = json.loads(
        (REPO / "config" / "forward_full_evidence_reservation_v2_template.json").read_text()
    )
    template["status"] = "IN_FORCE"
    template_path = _write(tmp_path / MOD.TEMPLATE, json.dumps(template))
    receipt: dict[str, Any] = {
        "schema": MOD.RECEIPT_SCHEMA,
        "promoted_at": "2026-09-14",
        "promoted_template_sha256": _sha(template_path),
        "effective_on_or_after_reservation_ordinal": 348,
    }
    receipt["content_hash"] = MOD._content_hash(receipt)
    receipt_path = _write(tmp_path / MOD.RECEIPT, json.dumps(receipt))
    _write(tmp_path / MOD.CONTRACT, json.dumps(contract))
    dims = list(contract["execution_dimensions"])
    applicable = dims[:4]
    excused = dims[4:]
    excuse_evidence = _write(tmp_path / "docs" / "excuses.md", "why each dimension does not apply")
    manifest = {
        dim: [_scenario(f"{dim}_{i}", {"multiplier": 1.0 + i}) for i in range(1, 4)]
        for dim in applicable
    }
    manifest_path = _write(tmp_path / "artifacts" / "exec_manifest.json", json.dumps(manifest))
    files = {
        name: _write(tmp_path / "artifacts" / f"{name}.json", json.dumps({"name": name}))
        for name in ("snapshot", "mask", "ddspec", "overlay", "pit", "runner", "project", "lock")
    }
    policy = contract["diversification_evidence_policy"]
    thresholds = contract["thresholds"]
    hashes = ["a" * 64, "b" * 64]
    baseline = {"fee_bps": 15.0, "spread_bps": 5.0, "borrow_annual": 0.03}
    reservation: dict[str, Any] = {
        "schema": MOD.RESERVATION_SCHEMA,
        "status": "RETURN_IDENTITY_RESERVED",
        "return_identity_id": "narrative_item1a",
        "hypothesis_identity": hashes[0],
        "identity_batch": {
            "batch_id": "narrative_batch_1",
            "identity_hashes": hashes,
            "batch_content_hash": "sha256:" + "c" * 64,
        },
        "diagnostic_scenarios": {
            "cost_stress_scenarios": [
                _scenario("cost_baseline", baseline),
                _scenario("cost_x2", {"fee_bps": 30.0, "spread_bps": 10.0, "borrow_annual": 0.06}),
            ],
            "execution_stress_scenarios": [
                _scenario("fill_half", {"fill_ratio": 0.5, "fee_bps": 15.0})
            ],
            "capacity_scenarios": [
                _scenario("cap_500k", {"capital_usd": 500000}),
                _scenario("cap_5m", {"capital_usd": 5000000}),
                _scenario("cap_25m", {"capital_usd": 25000000}),
            ],
        },
        "evidence": {
            "runner": {"path": "artifacts/runner.json", "sha256": _sha(files["runner"])},
            "python_project": {"path": "artifacts/project.json", "sha256": _sha(files["project"])},
            "locked_environment": {"path": "artifacts/lock.json", "sha256": _sha(files["lock"])},
        },
        "full_evidence": {
            "template_path": MOD.TEMPLATE,
            "template_sha256": _sha(template_path),
            "promotion_receipt_path": MOD.RECEIPT,
            "promotion_receipt_sha256": _sha(receipt_path),
            "primary_estimator": template["primary_estimator"],
            "pbo_matrix": {
                "identity_columns": hashes,
                "return_alignment": template["pbo_matrix"]["return_alignment"],
                "n_splits": 16,
                "maximum_combinations": 12870,
                "seed": 20260914,
                "undefined_policy": template["pbo_matrix"]["undefined_policy"],
            },
            "diagnostic_policy": {
                "selection_permitted": False,
                "all_scenarios_must_publish": True,
                "baseline_scenario_id": "cost_baseline",
                "minimum_capacity_points": thresholds["capacity_curve_min_points"],
                "required_capacity_usd": thresholds["capacity_usd_min"],
                "scenario_hashes_frozen_before_returns": True,
            },
            "book_evidence": {
                "book_return_snapshot_path": "artifacts/snapshot.json",
                "book_return_snapshot_sha256": _sha(files["snapshot"]),
                "book_series_ids": ["a", "b", "c", "d"],
                "candidate_weight": 0.10,
                "alignment_rule": template["book_evidence"]["alignment_rule"],
                "stress_mask_path": "artifacts/mask.json",
                "stress_mask_sha256": _sha(files["mask"]),
                "bootstrap": {
                    "samples": policy["default_bootstrap_samples"],
                    "block_size": policy["default_block_size"],
                    "seed": policy["default_seed"],
                    "one_sided_confidence": policy["confidence_level_one_sided"],
                },
                "leave_one_period_definition": "calendar year",
            },
            "book_drawdown": {
                "simulation_specification_path": "artifacts/ddspec.json",
                "simulation_specification_sha256": _sha(files["ddspec"]),
                "expected_maximum_drawdown_required": True,
                "p95_maximum_drawdown_required": True,
                "overlay_configuration_path": "artifacts/overlay.json",
                "overlay_configuration_sha256": _sha(files["overlay"]),
            },
            "execution_evidence": {
                "applicable_dimensions": applicable,
                "not_applicable_dimensions": {
                    dim: {
                        "reason": f"{dim} does not apply to a daily long-short equity book",
                        "evidence_path": "docs/excuses.md",
                        "evidence_sha256": _sha(excuse_evidence),
                    }
                    for dim in excused
                },
                "minimum_scenarios_per_applicable_dimension": thresholds[
                    "minimum_execution_scenarios_per_dimension"
                ],
                "scenario_manifest_path": "artifacts/exec_manifest.json",
                "scenario_manifest_sha256": _sha(manifest_path),
            },
            "data_and_environment": {
                "point_in_time_data_manifest_path": "artifacts/pit.json",
                "point_in_time_data_manifest_sha256": _sha(files["pit"]),
                "runner_path": "artifacts/runner.json",
                "runner_sha256": _sha(files["runner"]),
                "project_sha256": _sha(files["project"]),
                "lockfile_sha256": _sha(files["lock"]),
                "input_snapshot_required_before_first_execution_leg": True,
                "public_redistribution_rights_established": False,
            },
        },
    }
    return tmp_path, reservation


def _audit(repo: Path, reservation: dict[str, Any]) -> dict[str, Any]:
    path = _write(repo / "artifacts" / "reservation.json", json.dumps(reservation))
    return MOD.audit(path, repo)


def test_a_complete_two_column_reservation_is_satisfiable_and_admit_is_reachable(
    tmp_path: Path,
) -> None:
    repo, reservation = _repo(tmp_path)
    document = _audit(repo, reservation)
    assert document["status"] == "SATISFIABLE_RETURN_BLIND", document["failures"]
    assert document["admit_reachable"] is True
    assert document["disposition_ceiling"] == "ADMIT"
    assert document["pbo_columns"] == 2
    assert document["stress_scenarios_that_can_fail"] == 2
    assert document["capacity_points"] == [500000.0, 5000000.0, 25000000.0]
    assert document["fail_closed_checks"]["returns_computed"] is False
    assert document["content_hash"] == MOD._content_hash(document)


def test_a_one_column_batch_cannot_reach_admit(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    reservation["identity_batch"]["identity_hashes"] = ["a" * 64]
    reservation["full_evidence"]["pbo_matrix"]["identity_columns"] = ["a" * 64]
    document = _audit(repo, reservation)
    assert document["disposition_ceiling"] == "INCOMPLETE"
    assert document["admit_reachable"] is False
    assert any("ADMIT is unreachable" in f for f in document["failures"])


def test_a_stress_scenario_equal_to_its_baseline_cannot_fail(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    scenarios = reservation["diagnostic_scenarios"]["cost_stress_scenarios"]
    scenarios[1] = _scenario("cost_x2", dict(scenarios[0]["assumptions"]))
    document = _audit(repo, reservation)
    assert any("equals the baseline and cannot fail" in f for f in document["failures"])


def test_a_scenario_that_only_relabels_the_baseline_cannot_fail(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    scenarios = reservation["diagnostic_scenarios"]["cost_stress_scenarios"]
    scenarios[1] = _scenario(
        "cost_x2", {"fee_bps": 15.0, "spread_bps": 5.0, "borrow_annual": 0.03, "note": "same"}
    )
    document = _audit(repo, reservation)
    assert any("restates the baseline's numbers" in f for f in document["failures"])


def test_capacity_without_the_governing_point_or_above_it_is_refused(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    reservation["diagnostic_scenarios"]["capacity_scenarios"] = [
        _scenario("cap_100k", {"capital_usd": 100000}),
        _scenario("cap_200k", {"capital_usd": 200000}),
        _scenario("cap_300k", {"capital_usd": 300000}),
    ]
    document = _audit(repo, reservation)
    failures = " | ".join(document["failures"])
    assert "governing capacity point" in failures
    assert "no capital point above the governing point" in failures


def test_an_execution_dimension_neither_applicable_nor_excused_is_refused(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    execution = reservation["full_evidence"]["execution_evidence"]
    dropped = next(iter(execution["not_applicable_dimensions"]))
    del execution["not_applicable_dimensions"][dropped]
    document = _audit(repo, reservation)
    assert any(f"neither applicable nor excused: {dropped}" in f for f in document["failures"])


def test_an_applicable_dimension_with_too_few_scenarios_is_refused(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    manifest_path = repo / "artifacts" / "exec_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    first = reservation["full_evidence"]["execution_evidence"]["applicable_dimensions"][0]
    manifest[first] = manifest[first][:2]
    manifest_path.write_text(json.dumps(manifest))
    reservation["full_evidence"]["execution_evidence"]["scenario_manifest_sha256"] = _sha(
        manifest_path
    )
    document = _audit(repo, reservation)
    assert any(f"applicable dimension {first} has fewer than" in f for f in document["failures"])


def test_a_moved_bound_file_is_refused(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    (repo / "artifacts" / "mask.json").write_text('{"name": "mask", "edited": true}')
    document = _audit(repo, reservation)
    assert any("stress mask: sha256 does not match" in f for f in document["failures"])


def test_an_outcome_key_anywhere_is_refused_before_anything_else(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    reservation["full_evidence"]["book_evidence"]["sharpe"] = 2.0
    with pytest.raises(MOD.FilledReservationAuditError, match="outcome keys"):
        _audit(repo, reservation)


def test_an_unpromoted_template_authorizes_nothing(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    template_path = repo / MOD.TEMPLATE
    template = json.loads(template_path.read_text())
    template["status"] = "TEMPLATE_NOT_IN_FORCE_NO_RETURN_AUTHORIZATION"
    template_path.write_text(json.dumps(template))
    reservation["full_evidence"]["template_sha256"] = _sha(template_path)
    document = _audit(repo, reservation)
    assert any("not in force" in f for f in document["failures"])
    assert document["status"] == "UNSATISFIABLE_AS_WRITTEN"


def test_the_audit_is_deterministic_over_its_inputs(tmp_path: Path) -> None:
    repo, reservation = _repo(tmp_path)
    first = _audit(repo, copy.deepcopy(reservation))
    second = _audit(repo, copy.deepcopy(reservation))
    assert first["content_hash"] == second["content_hash"]
