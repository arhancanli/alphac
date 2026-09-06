"""Pin the diagnostic evidence class before any code reads it (plan task 1, spec 2(a)).

A diagnostic scenario recomputes cost, execution, or capacity outcomes on top of the exact
decisions already sealed in a primary return path; it cannot become a new hypothesis identity.
`DIAGNOSTIC_SCENARIO_CLASSES` names the three list keys the v2 reservation template's
`diagnostic_scenarios` block declares (config/forward_full_evidence_reservation_v2_template.json).
`DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS` is config/sleeve_admission_contract.json's
`execution_evidence_policy.scenario_manifest_required_fields` minus `status` (a diagnostic has no
PASS/FAIL status of its own; the decision path binding is what makes it safe), plus the new
`primary_decision_path_sha256` binding.

This test pins in-repository constants and a pure function rather than reading either config
file, so it would not naturally carry any of the substrings `scripts/mutation_ledger.py`'s
`discover_guards` matches on. It is registered explicitly in `MUTATIONS` rather than relying on
that rule (spec section 5 item 8) -- the `config/sleeve_admission_contract.json` reference above
is exposition, not a runtime read, and only incidentally satisfies the substring rule too.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from alphaforge.validation.trial_reservation import (
    DIAGNOSTIC_SCENARIO_CLASSES,
    DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS,
    ReservationError,
    _validate_diagnostic_scenarios,
)

SEALED_PATH_SHA256 = "a" * 64


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _scenario(*, primary_decision_path_sha256: str = SEALED_PATH_SHA256) -> dict[str, Any]:
    assumptions = {"slippage_multiplier": 5.0}
    result = {"passed": True, "net_sharpe": 0.4}
    return {
        "scenario_id": "cost_stress_extreme_slippage",
        "assumptions": assumptions,
        "assumptions_sha256": _canonical_sha256(assumptions),
        "result": result,
        "result_sha256": _canonical_sha256(result),
        "primary_decision_path_sha256": primary_decision_path_sha256,
    }


def test_diagnostic_scenario_classes_match_the_v2_template() -> None:
    assert frozenset(
        {"cost_stress_scenarios", "execution_stress_scenarios", "capacity_scenarios"}
    ) == DIAGNOSTIC_SCENARIO_CLASSES


def test_diagnostic_scenario_required_fields_match_the_execution_evidence_policy() -> None:
    assert frozenset(
        {
            "scenario_id",
            "assumptions",
            "assumptions_sha256",
            "result",
            "result_sha256",
            "primary_decision_path_sha256",
        }
    ) == DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS


def test_absent_diagnostic_scenarios_is_valid_with_zero_count() -> None:
    result = _validate_diagnostic_scenarios(
        {}, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
    )
    assert result == {"diagnostic_scenario_count": 0}


def test_every_scenario_matching_the_sealed_path_counts() -> None:
    payload = {
        "diagnostic_scenarios": {
            "cost_stress_scenarios": [_scenario(), _scenario()],
            "capacity_scenarios": [_scenario()],
        }
    }
    result = _validate_diagnostic_scenarios(
        payload, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
    )
    assert result == {"diagnostic_scenario_count": 3}


def test_a_scenario_off_the_sealed_primary_decision_path_is_rejected() -> None:
    payload = {
        "diagnostic_scenarios": {
            "cost_stress_scenarios": [
                _scenario(),
                _scenario(primary_decision_path_sha256="b" * 64),
            ],
        }
    }
    with pytest.raises(ReservationError, match="does not match the sealed primary decision path"):
        _validate_diagnostic_scenarios(
            payload, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
        )


def test_an_unrecognized_scenario_class_is_rejected() -> None:
    payload = {"diagnostic_scenarios": {"not_a_real_class": [_scenario()]}}
    with pytest.raises(ReservationError, match="subset of"):
        _validate_diagnostic_scenarios(
            payload, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
        )


def test_a_scenario_missing_a_required_field_is_rejected() -> None:
    scenario = _scenario()
    del scenario["result_sha256"]
    payload = {"diagnostic_scenarios": {"cost_stress_scenarios": [scenario]}}
    with pytest.raises(ReservationError, match="must declare exactly"):
        _validate_diagnostic_scenarios(
            payload, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
        )


def test_a_tampered_result_hash_is_rejected() -> None:
    scenario = _scenario()
    scenario["result"] = {"passed": False, "net_sharpe": -9.0}
    payload = {"diagnostic_scenarios": {"cost_stress_scenarios": [scenario]}}
    with pytest.raises(ReservationError, match="result_sha256 does not match"):
        _validate_diagnostic_scenarios(
            payload, sealed_primary_decision_path_sha256=SEALED_PATH_SHA256
        )
