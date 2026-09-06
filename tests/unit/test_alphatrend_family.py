from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_alphatrend_family.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_alphatrend_family_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alphatrend_packet_binds_all_identities_without_inventing_missing_evidence() -> None:
    packet = _module().build()
    summary = packet["summary"]
    identities = packet["identities"]

    assert summary["distinct_hypothesis_identities"] == len(identities) == 21
    assert len({row["hypothesis_key"] for row in identities}) == 21
    assert summary["complete_walkforward_artifacts"] == 6
    assert summary["persisted_summary_only_identities"] == 7
    assert summary["immutable_ledger_only_identities"] == 8
    assert summary["finite_sharpe_identities"] == 19
    assert summary["identities_with_artifact_era_dsr"] == 13
    assert summary["artifact_era_dsr_gate_passes"] == 0
    assert summary["capacity_status"].startswith("UNMEASURED_")
    assert all(
        row["artifact_sha256"] is None or len(row["artifact_sha256"]) == 64
        for row in identities
    )
