from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "audit_inflation_breakeven_feasibility.py"
    spec = importlib.util.spec_from_file_location("inflation_breakeven_feasibility_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_signal_depth_does_not_masquerade_as_executable_return_data() -> None:
    module = _module()
    payload = module.build()
    assert payload["decision"] == "DATA_GATED"
    assert payload["return_data_opened"] is False
    assert payload["market_return_files_opened"] == []
    assert payload["return_hypotheses_spent"] == 0
    assert payload["aligned_5y_10y"]["rows"] >= 5914
    assert payload["cpi_vintage_inventory"]["true_first_releases"] == 335
    assert payload["gates"]["aligned_5y_10y_signal_at_least_three_years"] is True
    assert payload["gates"]["all_atlas_maturities_present"] is False
    assert payload["gates"]["historical_signal_vintages_preserved"] is False
    assert payload["gates"]["executable_instrument_history_present"] is False
    assert set(payload["failed_gates"]) == {
        "all_atlas_maturities_present",
        "historical_signal_vintages_preserved",
        "executable_instrument_history_present",
    }
    assert payload["content_hash"] == module.content_hash(payload)


def test_persisted_result_matches_current_source_audit() -> None:
    module = _module()
    persisted = json.loads(module.OUT.read_text())
    assert persisted == module.build()
