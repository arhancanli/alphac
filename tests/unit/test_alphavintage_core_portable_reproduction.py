from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "seal_alphavintage_core_portable_reproduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("alphavintage_core_seal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_alphavintage_core_receipt_is_current_and_bounded() -> None:
    receipt = _module().validate_published()
    assert receipt["status"] == "PASS_DECISION_REPRODUCTION_NUMERICALLY_NEAR_IDENTICAL_CORE_ONLY"
    assert receipt["passes"] is True
    assert receipt["execution"]["workspace_outside_repository"] is True
    assert all(receipt["exact_decision_checks"].values())
    assert all(
        item["within_publication_display_precision"]
        for item in receipt["metric_comparisons"]
    )
    assert {item["symbol"] for item in receipt["market_input_comparisons"]} == {
        "IWM",
        "SPY",
        "QQQ",
    }
    assert receipt["acceptance_criterion"]["prospectively_preregistered"] is False
    assert receipt["raw_vendor_files_released"] is False
    assert receipt["full_diversification_checks_replayed"] is False
    assert receipt["independent_human_reproduction_completed"] is False
