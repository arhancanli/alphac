from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    script = REPO / "scripts" / "audit_equity_fundamental_families.py"
    spec = importlib.util.spec_from_file_location("audit_equity_fundamental_families_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_and_value_packets_preserve_all_ledger_identities_and_missing_evidence() -> None:
    module = _module()
    quality = module.build_family("equity_fundamental_quality")
    value = module.build_family("equity_fundamental_value_investment")
    assert len(quality["identities"]) == quality["summary"]["distinct_hypothesis_identities"] == 11
    assert len(value["identities"]) == value["summary"]["distinct_hypothesis_identities"] == 13
    assert quality["summary"]["nonfinite_sharpe_identities"] == 0
    assert value["summary"]["nonfinite_sharpe_identities"] == 2
    assert quality["summary"]["complete_walkforward_artifacts"] == 0
    assert value["summary"]["complete_walkforward_artifacts"] == 0
    assert all(row["result"]["maximum_drawdown"] is None for row in quality["identities"])
    assert len({row["hypothesis_key"] for row in quality["identities"] + value["identities"]}) == 24
