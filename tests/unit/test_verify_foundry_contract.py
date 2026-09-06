from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_foundry_contract.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_foundry_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_foundry_local_contract_verifier_passes_without_claiming_deployment() -> None:
    receipt = _module().verify()
    assert receipt["status"] == "PASS"
    assert all(receipt["checks"].values())
    assert "not a Terraform plan" in receipt["claim_boundary"]
    assert len(receipt["files"]) == 25
    assert receipt["design_status"] == {
        "deployment": "PLANNED_NOT_APPLIED",
        "runtime": "FROZEN_NOT_DEPLOYED",
        "lifecycle": "DESIGN_FROZEN_NOT_DEPLOYED",
        "acceptance": "INCOMPLETE_NOT_OPERATIONAL",
    }
    assert receipt["acceptance"]["required_receipts"] == 11
    assert receipt["acceptance"]["public_receipts_attached"] == 0
    assert len(receipt["acceptance"]["missing_receipts"]) == 11
    assert receipt["architecture"]["broker_write_access"] is False
    assert receipt["architecture"]["execution_reachable_from_research"] is False
    assert receipt["first_migration"]["status"] == "PREPARED_NOT_IMPORTED_OR_REPLAYED"
    assert receipt["first_migration"]["preserved_state"] == "KILLED"
    assert receipt["content_hash"].startswith("sha256:")
