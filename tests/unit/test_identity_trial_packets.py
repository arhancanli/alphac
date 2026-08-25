from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    script = REPO / "scripts" / "build_identity_trial_packets.py"
    spec = importlib.util.spec_from_file_location("identity_trial_packets_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_identity_has_one_fail_closed_hashed_packet() -> None:
    module = _module()
    packets, index = module.build_packets()
    assert len(packets) == 228
    assert index["summary"] == {
        "distinct_hypothesis_identities": 228,
        "published_identity_packets": 228,
        "complete_identity_packets": 2,
        "incomplete_identity_packets": 226,
        "packets_with_partial_historical_curve_evidence": 37,
        "audited_not_currently_completable": 221,
        "audited_exact_replay_candidates": 0,
        "audited_exact_replays_failed_data_quality": 4,
        "audited_exact_replays_failed_reproduction": 0,
        "audited_corrected_reproductions_kill_preserved": 1,
        "incomplete_not_yet_audited": 0,
    }
    assert set(packets) == {row["hypothesis_key"] for row in index["packets"]}
    complete = [packet for packet in packets.values() if packet["complete"]]
    assert {packet["hypothesis_key"] for packet in complete} == {
        "8446702cb8dd1768",
        "e2b76a7604131f00",
    }
    assert all(packet["packet_status"] == "COMPLETE_EVIDENCED_KILL" for packet in complete)
    assert all(packet["missing_sections"] == [] for packet in complete)
    assert all(len(packet["verified_sections"]) == 11 for packet in complete)
    assert sum(not packet["complete"] for packet in packets.values()) == 226
    assert all(packet["verified_sections"] for packet in packets.values())
    assert all(packet["missing_sections"] for packet in packets.values() if not packet["complete"])
    assert all(packet["content_hash"].startswith("sha256:") for packet in packets.values())
    partial_curves = [packet for packet in packets.values() if packet["partial_sections"]]
    assert len(partial_curves) == 37
    assert all(
        packet["schema"] == "canli.alphac-identity-trial-packet.v2" for packet in packets.values()
    )
    assert all(
        packet["partial_sections"] == ["result_uncertainty_stress_capacity_and_diversification"]
        for packet in partial_curves
    )
    assert all(
        packet["required_sections"]["result_uncertainty_stress_capacity_and_diversification"][
            "status"
        ]
        == "PARTIAL_IDENTITY_LEVEL_EVIDENCE"
        for packet in partial_curves
    )
    assert all(
        "result_uncertainty_stress_capacity_and_diversification" in packet["missing_sections"]
        for packet in partial_curves
    )
    for row in index["packets"]:
        assert (
            row["packet_file_sha256"]
            == hashlib.sha256(module._serialized_packet(packets[row["hypothesis_key"]])).hexdigest()
        )
    audited = {
        key: packet["completion_assessment"]
        for key, packet in packets.items()
        if packet["completion_assessment"]["status"] == "AUDITED_NOT_CURRENTLY_COMPLETABLE"
    }
    deep_audit_identities = {
        "4eb98b8f5dad412c",
        "6c08c11a04ef43c5",
        "6d151a184bf3e743",
        "7c522581b35475e3",
        "97dec5f23e5fcf27",
        "c6100630d688b4d7",
        "cb54117502489bf8",
        "d614fdc1daa2906c",
    }
    assert len(audited) == 221
    assert deep_audit_identities.issubset(audited)
    assert audited["131745bc21f41d5f"]["family_audit"] == (
        "artifacts/research/crypto_momentum_family.json"
    )
    assert audited["0a85fa2eca9afeb8"]["forensic_reconciliation"] == (
        "artifacts/audit/trial_debt_reconciliation.json"
    )
    carry_codes = {item["code"] for item in audited["6d151a184bf3e743"]["blockers"]}
    assert "PREREGISTRATION_POSTDATES_FIRST_MEASUREMENT" in carry_codes
    assert "CARRY_SPECIFIC_CAPACITY_UNMEASURED" in carry_codes
    replay_candidates = {
        key
        for key, packet in packets.items()
        if packet["completion_assessment"]["status"] == "AUDITED_EXACT_REPLAY_CANDIDATE"
    }
    assert replay_candidates == set()
    assert packets["e5f48adc25065ce9"]["completion_assessment"]["status"] == (
        "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
    )
    assert packets["e5f48adc25065ce9"]["missing_sections"] == [
        "execution_and_cost_model",
        "result_uncertainty_stress_capacity_and_diversification",
    ]
    assert all(
        packets[key]["completion_assessment"]["status"]
        == "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
        for key in ("1d2924f28fe31a9a", "2d966892fb5db520")
    )


def test_sealed_packet_tree_fails_closed_on_index_hash_drift(monkeypatch) -> None:
    module = _module()
    original = module._sha256

    def drift(path: Path) -> str:
        if path.name == "index.json" and "trial_packets" in str(path):
            return "0" * 64
        return original(path)

    monkeypatch.setattr(module, "_sha256", drift)
    with pytest.raises(ValueError, match="identity-packet index file hash mismatch"):
        module.build_packets()


def test_sealed_packet_tree_fails_closed_on_packet_hash_drift(
    monkeypatch,
) -> None:
    module = _module()
    original = module._sha256

    def drift(path: Path) -> str:
        if path.name == "e5f48adc25065ce9.json" and "trial_packets" in str(path):
            return "0" * 64
        return original(path)

    monkeypatch.setattr(module, "_sha256", drift)
    with pytest.raises(ValueError, match="identity-packet file hash mismatch"):
        module.build_packets()


def test_pending_fundamental_support_artifacts_have_valid_embedded_hashes() -> None:
    module = _module()
    probe = REPO / "artifacts/probe/fundamental_single_replays/1d2924f28fe31a9a"
    for name in (
        "curve_evidence",
        "diversification",
        "input_data_manifest",
        "market_evidence",
        "replay_environment",
    ):
        path = probe / f"{name}.json"
        module._validate_embedded_content_hash(
            "1d2924f28fe31a9a",
            path,
            json.loads(path.read_text()),
        )


def test_embedded_hash_validator_rejects_semantic_mutation() -> None:
    module = _module()
    path = REPO / "artifacts/probe/fundamental_single_replays/1d2924f28fe31a9a/curve_evidence.json"
    payload = json.loads(path.read_text())
    payload["verdict"] = "KEEP"
    with pytest.raises(ValueError, match="embedded content hash mismatch"):
        module._validate_embedded_content_hash("1d2924f28fe31a9a", path, payload)


def test_published_identity_packet_trees_are_byte_identical() -> None:
    left = REPO.parent / "meridian" / "public" / "glassbox" / "trial-packets"
    right = REPO.parent / "meridian-app" / "public" / "glassbox" / "trial-packets"
    left_files = {path.name: path.read_bytes() for path in left.glob("*.json")}
    right_files = {path.name: path.read_bytes() for path in right.glob("*.json")}
    index = json.loads(left_files["index.json"])
    legacy_files = {f"{row['hypothesis_key']}.json" for row in index["packets"]}
    prospective_files = {
        "da5f5f47f99f9bd2.json",
        "crypto_carry_portable_v1.json",
    }
    assert set(left_files) == legacy_files | prospective_files | {"index.json"}
    assert left_files["da5f5f47f99f9bd2.json"] == left_files["crypto_carry_portable_v1.json"]
    assert left_files == right_files
