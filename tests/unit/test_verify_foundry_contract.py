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
