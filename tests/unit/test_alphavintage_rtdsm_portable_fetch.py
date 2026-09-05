from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "seal_alphavintage_rtdsm_portable_fetch.py"


def _module():
    spec = importlib.util.spec_from_file_location("rtdsm_seal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_rtdsm_receipt_is_current_and_fail_closed() -> None:
    module = _module()
    receipt = module.validate_published()
    assert receipt["status"] == "PASS_PUBLIC_MACRO_COMPONENT_PORTABLE"
    assert receipt["passes"] is True
    assert receipt["execution"]["workspace_outside_repository"] is True
    assert len(receipt["comparisons"]) == 2
    assert all(item["tables_equal"] for item in receipt["comparisons"])
    assert receipt["market_data_component_replayed"] is False
    assert receipt["alphavintage_result_recomputed"] is False
    assert receipt["independent_replication"] is False
