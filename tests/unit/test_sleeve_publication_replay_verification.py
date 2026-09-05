from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_sleeve_publication_replays.py"
RECEIPT = ROOT / "artifacts/audit/sleeve_publication_replay_verification.json"
ISOLATED_RECEIPT = ROOT / "artifacts/audit/sleeve_publication_isolated_replay_verification.json"


def _module():
    spec = importlib.util.spec_from_file_location("sleeve_publication_replay", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_internal_replay_receipt_is_honest_and_current() -> None:
    module = _module()
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["passes"] is True
    assert receipt["status"] == "PASS_INTERNAL_AUDIT_REPLAY_NOT_CLEAN_ENVIRONMENT"
    assert receipt["commands_executed"] == 13
    assert receipt["sleeves_with_audit_command_executed"] == 14
    assert receipt["sleeves_deferred"] == ["alphamax_equity_momentum"]
    assert receipt["unique_released_result_objects_verified"] == 33
    assert receipt["result_hash_changes"] == []
    assert receipt["experiment_ledger_hash_changes"] == []
    assert all(row["returncode"] == 0 for row in receipt["command_receipts"])
    assert receipt["content_hash"] == module._content_hash(receipt)

    bindings = receipt["source_bindings"]
    assert bindings["evidence_catalog"]["sha256"] == _sha256(module.CATALOG)
    for relative, digest in bindings["result_objects"].items():
        assert _sha256(ROOT / relative) == digest
    for relative, digest in bindings["experiment_ledgers"].items():
        assert _sha256(ROOT / relative) == digest


def test_replay_receipt_does_not_overstate_scope() -> None:
    receipt = json.loads(RECEIPT.read_text())
    boundary = receipt["claim_boundary"].lower()
    assert "not a clean-environment replay" in boundary
    assert "not independent replication" in boundary
    assert "does not execute the deferred alphamax" in boundary


def test_isolated_dependency_replay_receipt_is_honest_and_current() -> None:
    module = _module()
    receipt = json.loads(ISOLATED_RECEIPT.read_text())
    assert receipt["passes"] is True
    assert receipt["status"] == ("PASS_ISOLATED_FROZEN_DEPENDENCY_REPLAY_NOT_PORTABLE_WORKSPACE")
    assert receipt["dependency_environment"] == "UV_ISOLATED_FROZEN"
    assert receipt["isolated_dependency_environment_completed"] is True
    assert receipt["portable_clean_workspace_replay_completed"] is False
    assert receipt["raw_input_portability_established"] is False
    assert receipt["independent_replication"] is False
    assert receipt["commands_executed"] == 13
    assert receipt["sleeves_with_audit_command_executed"] == 14
    assert receipt["sleeves_deferred"] == ["alphamax_equity_momentum"]
    assert receipt["unique_released_result_objects_verified"] == 33
    assert receipt["result_hash_changes"] == []
    assert receipt["experiment_ledger_hash_changes"] == []
    assert all(
        row["execution_command"].startswith("uv run --isolated --frozen ")
        for row in receipt["command_receipts"]
    )
    assert receipt["content_hash"] == module._content_hash(receipt)

    bindings = receipt["source_bindings"]
    assert bindings["evidence_catalog"]["sha256"] == _sha256(module.CATALOG)
    assert bindings["verification_script"]["sha256"] == _sha256(SCRIPT)
    for relative, digest in bindings["result_objects"].items():
        assert _sha256(ROOT / relative) == digest
    for relative, digest in bindings["experiment_ledgers"].items():
        assert _sha256(ROOT / relative) == digest


def test_isolated_dependency_receipt_does_not_overstate_scope() -> None:
    receipt = json.loads(ISOLATED_RECEIPT.read_text())
    boundary = receipt["claim_boundary"].lower()
    assert "not a portable clean-workspace replay" in boundary
    assert "does not prove raw data portability" in boundary
    assert "not independent replication" in boundary
