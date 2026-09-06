from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_author_protocol_review_packets.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("author_protocol_packets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_approval_gated_protocol_gets_a_blank_bound_packet(tmp_path: Path) -> None:
    module = _module()
    output_root = tmp_path / "protocol_packets"
    manifest = module.generate(output_root)

    assert manifest["status"] == "PASS_BLANK_PROTOCOL_PACKETS_ZERO_AUTHOR_APPROVALS"
    assert manifest["packets"] == 2
    assert manifest["questions"] == 12
    assert manifest["answers_completed"] == 0
    assert manifest["technical_checks"] == 12
    assert manifest["technical_checks_confirmed"] == 0
    assert manifest["author_approvals"] == 0
    assert manifest["content_hash"] == module.content_hash(manifest)
    assert {record["review_key"] for record in manifest["records"]} == {
        "merger-announcement-identity-v2",
        "treasury-auction-state-machine",
    }

    for record in manifest["records"]:
        packet = json.loads((output_root / record["packet"]).read_text())
        assert packet["author"] == "Arhan Canli"
        assert packet["status"] == "AWAITING_ARHAN_REVIEW_NO_APPROVAL_CLAIMED"
        assert packet["answers_completed"] == 0
        assert packet["technical_checks_confirmed"] == 0
        assert packet["author_approval_claimed"] is False
        assert packet["external_review_claimed"] is False
        assert packet["identity_proof_claimed"] is False
        assert all(question["answer"] is None for question in packet["author_questions"])
        assert all(check["author_confirmed"] is None for check in packet["technical_checks"])
        assert packet["approval"]["decision"] is None
        assert packet["activation_boundary"]["next_stage_authorized"] is False
        assert packet["activation_boundary"]["return_data_opened"] is False
        assert packet["activation_boundary"]["return_hypotheses_spent"] == 0
        assert packet["content_hash"] == module.content_hash(packet)


def test_registered_sources_are_current_self_verifying_approval_gates() -> None:
    module = _module()
    for item in module.load_registry()["reviews"]:
        protocol, artifact_path, artifact = module._bound_sources(item)
        assert protocol.is_file()
        assert artifact_path.is_file()
        assert artifact["decision"] == "AUTHOR_APPROVAL_REQUIRED"
        assert artifact["return_data_opened"] is False
        assert artifact["content_hash"] == module.content_hash(artifact)
        assert artifact["content_hash"] == item["evidence_content_hash"]


def test_persisted_manifest_and_packets_match_current_sources(tmp_path: Path) -> None:
    module = _module()
    persisted = json.loads(module.OUTPUT.read_text())
    assert persisted == module.generate(tmp_path / "fresh-packets")
    assert persisted["content_hash"] == module.content_hash(persisted)
    assert persisted["author_approvals"] == 0
