from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_forward_evidence_maturity.py"
    spec = importlib.util.spec_from_file_location("cost_disclosure_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cost_disclosure_retains_contract_omissions_when_state_omits_them() -> None:
    module = _module()
    state = {"cost_charges": {"sleeves": {
        "alphaforge": {"status": "CHARGED_AT_SOURCE"},
        "alphamax": {"status": "CHARGED_BY_MODEL", "not_charged": ["extra_unpriced_cost"]},
    }}}
    before = json.dumps(state, sort_keys=True)
    report = module._cost_realism(state, "cost_charged_curve")
    assert report["sleeves"]["alphaforge"]["not_charged"] == [
        "cash_yield_on_idle_capital", "financing_margin_interest", "latency_slippage",
    ]
    assert "extra_unpriced_cost" in report["sleeves"]["alphamax"]["not_charged"]
    assert "fx_conversion" in report["sleeves"]["alphamax"]["not_charged"]
    assert report["sleeves"]["managed_futures"]["status"] == "NOT_PUBLISHED"
    assert report["sleeves"]["managed_futures"]["total_charged_usd"] is None
    assert json.dumps(state, sort_keys=True) == before
