from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/seal_crypto_carry_portable_v1_admission_closure.py"
    spec = importlib.util.spec_from_file_location("crypto_carry_admission_closure_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_closure_is_final_incomplete_without_retroactive_scenarios() -> None:
    module = _module()
    document = module.build(ROOT)
    assert document["status"] == "FINAL_INCOMPLETE_NOT_ADMITTED_EVIDENCE_ACCOUNTING_COMPLETE"
    assert document["decision"] == {
        "disposition": "INCOMPLETE",
        "final_for_admission": True,
        "admitted": False,
        "killed": False,
        "technically_eligible": False,
        "identity_may_be_regraded_later": False,
        "gate_changes_after_result": 0,
        "additional_return_paths_executed_after_primary": 0,
    }
    finding = document["governance_finding"]
    assert finding["trial_policy_window_only_exemption"] == ["start", "end"]
    assert set(finding["required_but_unfrozen_fields"]) == set(module.UNFROZEN_SCENARIO_FIELDS)
    assert document["evidence_accounting"]["unmeasured_values_treated_as_pass"] is False
    assert document["prospective_correction_required"]["applies_to_this_known_result"] is False
    assert (
        document["prospective_correction_required"]["applies_to_future_reservations_only"] is True
    )
    assert document["content_hash"] == module._content_hash(document)


def test_closure_fails_if_a_scenario_field_is_retroactively_inserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    original = module._verified_hashed_json

    def mutate(path: Path, schema: str):
        value = original(path, schema)
        if path.name == "crypto_carry_portable_v1_run.json":
            value = json.loads(json.dumps(value))
            value["capacity_capital_points"] = [100_000, 500_000, 1_000_000]
        return value

    monkeypatch.setattr(module, "_verified_hashed_json", mutate)
    with pytest.raises(module.AdmissionClosureError, match="scenario fields are now present"):
        module.build(ROOT)


def test_closure_fails_if_primary_disposition_is_promoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    original = module._verified_hashed_json

    def mutate(path: Path, schema: str):
        value = original(path, schema)
        if path.name == "crypto_carry_portable_v1_result.json":
            value = json.loads(json.dumps(value))
            value["disposition"]["value"] = "ADMIT"
        return value

    monkeypatch.setattr(module, "_verified_hashed_json", mutate)
    with pytest.raises(module.AdmissionClosureError, match="not INCOMPLETE"):
        module.build(ROOT)
