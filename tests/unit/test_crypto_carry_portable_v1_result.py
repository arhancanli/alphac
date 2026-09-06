from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/seal_crypto_carry_portable_v1_result.py"
    spec = importlib.util.spec_from_file_location("crypto_carry_portable_result_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_result_is_sealed_without_false_admission_or_dsr_kill() -> None:
    module = _module()
    receipt, packet = module.build(ROOT)
    primary = receipt["immutable_primary_result"]
    assert receipt["status"] == "SEALED_PRIMARY_RESULT_ADMISSION_INCOMPLETE"
    assert receipt["classification"]["evidence_type"] == "HISTORICAL_WALK_FORWARD_SIMULATION"
    assert primary["summary"]["sharpe"] == pytest.approx(0.9688980432905521)
    assert primary["summary"]["max_dd"] == pytest.approx(0.12303511718661964)
    assert primary["validation"]["dsr"] == pytest.approx(0.09141260613462271)
    assert primary["dsr_interpretation"]["candidate_killed_by_dsr_alone"] is False
    assert primary["dsr_interpretation"]["reservation_bound_v7_role"] == (
        "MEASURE_AND_PUBLISH_NOT_PER_SLEEVE_GATE"
    )
    assert receipt["disposition"] == {
        "value": "INCOMPLETE",
        "admitted": False,
        "killed": False,
        "blocking_reason": "The preregistered v7 admission evidence suite is not complete.",
        "gate_changes_after_result": 0,
        "seriality_at_primary_result_seal": {
            "next_forward_identity_blocked": True,
            "unblock_condition": "COMPLETE_HASH_VALID_IDENTITY_PACKET",
        },
    }
    assert receipt["identity"]["hypotheses_spent"] == 1
    assert receipt["identity"]["unregistered_variants_executed"] == 0
    assert packet["hypothesis_key"] == "da5f5f47f99f9bd2"
    assert packet["complete"] is True
    assert packet["missing_sections"] == []
    assert packet["packet_status"] == "COMPLETE_EVIDENCED_FINAL_INCOMPLETE_NOT_ADMITTED"
    assert packet["completion_assessment"]["candidate_evidence_complete_for_admission"] is False
    assert packet["completion_assessment"]["packet_evidence_accounting_complete"] is True
    assert packet["content_hash"] == module._content_hash(packet)
    assert receipt["content_hash"] == module._content_hash(receipt)


def test_result_reconciles_all_same_path_stability_diagnostics() -> None:
    module = _module()
    receipt, _ = module.build(ROOT)
    stability = receipt["stability_diagnostics_from_same_immutable_path"]
    assert stability["leg_summary"]["count"] == 25
    assert len(stability["walkforward_legs"]) == 25
    assert len(stability["calendar_year_results"]) == 5
    assert len(stability["leave_one_calendar_year_out"]) == 5
    assert (
        sum(
            row["retained_daily_observations"]
            < receipt["immutable_primary_result"]["validation"]["n_obs"]
            for row in stability["leave_one_calendar_year_out"]
        )
        == 5
    )


def test_result_fails_closed_on_walkforward_metric_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    original = module._load_json

    def drift(path: Path):
        value = original(path)
        if path.name == "walkforward.json":
            value = json.loads(json.dumps(value))
            value["summary"]["sharpe"] += 0.1
        return value

    monkeypatch.setattr(module, "_load_json", drift)
    with pytest.raises(module.ResultSealError, match="equity-derived Sharpe"):
        module.build(ROOT)


def test_result_fails_closed_on_contract_role_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    original = module._load_json

    def drift(path: Path):
        value = original(path)
        if path.name == "sleeve_admission_contract.json":
            value = json.loads(json.dumps(value))
            value["deflation_policy"]["per_sleeve_is_measured_not_gated"] = False
        return value

    monkeypatch.setattr(module, "_load_json", drift)
    with pytest.raises(module.ResultSealError, match="per-sleeve DSR role"):
        module.build(ROOT)


def test_trial_paper_quotes_the_sealed_result_and_boundary() -> None:
    receipt = json.loads(
        (ROOT / "artifacts/research/crypto_carry_portable_v1_result.json").read_text()
    )
    paper = (ROOT / "docs/research/CRYPTO_CARRY_PORTABLE_V1.md").read_text()
    assert "**Author:** Arhan Canli" in paper
    assert "0.9689" in paper
    assert "0.0914" in paper
    assert "12.30%" in paper
    assert "INCOMPLETE / NOT ADMITTED" in paper
    assert "not externally submitted or" in paper
    assert "not a standalone admission gate" in paper
    assert "PBO is null" in paper
    assert str(receipt["content_hash"]) in paper
    assert receipt["disposition"]["admitted"] is False
    assert receipt["disposition"]["killed"] is False
