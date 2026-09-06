from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_crypto_multifactor_family.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_crypto_multifactor_family_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multifactor_packet_binds_exactly_the_seven_noncarry_matrix_trials() -> None:
    packet = _module().build()
    identities = packet["identities"]
    assert packet["summary"]["distinct_hypothesis_identities"] == len(identities) == 7
    assert {row["config_id"] for row in identities} == {
        "A_blend",
        "A_ml",
        "A_regime",
        "A_ml_regime",
        "C_rebal24",
        "C_band10",
        "C_mvo",
    }
    assert packet["summary"]["artifact_era_dsr_gate_passes"] == 0
    assert packet["summary"]["matrix_pbo"] == 0.8818
    assert packet["summary"]["deployment_verdict"] is False
    assert len({row["hypothesis_key"] for row in identities}) == 7
    assert all(len(row["artifact_sha256"]) == 64 for row in identities)
