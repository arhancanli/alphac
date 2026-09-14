from __future__ import annotations

import importlib.util
import math
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

    # The family's size is whatever the union holds (21 at first build, 49 after the 2026-09-14
    # external-ledger import); it is derived here from the same ledgers the packet reads, never
    # typed. The artifact-backed and report-backed subsets are fixed sets of config hashes, so
    # their counts stay pinned; everything else is a ledger-only identity.
    records = _module()._first_records()
    assert len(records) >= 21
    assert summary["distinct_hypothesis_identities"] == len(identities) == len(records)
    assert len({row["hypothesis_key"] for row in identities}) == len(records)
    assert summary["complete_walkforward_artifacts"] == 6
    assert summary["persisted_summary_only_identities"] == 7
    assert summary["immutable_ledger_only_identities"] == len(records) - 6 - 7
    assert summary["finite_sharpe_identities"] == sum(
        1 for record, _ in records.values() if math.isfinite(record.sharpe_ann)
    )
    assert summary["identities_with_artifact_era_dsr"] == 13
    assert summary["artifact_era_dsr_gate_passes"] == 0
    assert summary["capacity_status"].startswith("UNMEASURED_")
    assert all(
        row["artifact_sha256"] is None or len(row["artifact_sha256"]) == 64 for row in identities
    )
