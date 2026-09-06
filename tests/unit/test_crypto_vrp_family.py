from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_crypto_vrp_family.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_crypto_vrp_family_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vrp_packet_is_complete_about_the_null_and_proxy_boundary() -> None:
    packet = _module().build()
    result = packet["identity"]["result"]
    assert packet["summary"]["distinct_hypothesis_identities"] == 1
    assert packet["summary"]["artifact_era_dsr_gate_passes"] == 0
    assert packet["implementation"]["is_deployable_option_pnl"] is False
    assert result["annualized_sharpe"] == -0.633
    assert result["skew"] == -9.517
    assert result["raw_kurtosis"] == 132.65
    assert len(packet["identity"]["artifact_sha256"]) == 64
