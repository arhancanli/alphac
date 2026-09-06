from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts/seal_operating_margin_corrected_reproduction.py"
    spec = importlib.util.spec_from_file_location("corrected_reproduction_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corrected_reproduction_preserves_kill_and_zero_trial_accounting() -> None:
    payload = _module().build()
    assert payload["decision"] == "CORRECTED_OPERATING_MARGIN_REPRODUCED_KILL_PRESERVED"
    assert payload["verdict"] == "KILL"
    assert payload["hypotheses_spent"] == 0
    assert payload["corrected_measurement"]["annualized_sharpe"] < 0
    assert payload["corrected_measurement"]["total_return"] < 0
    assert payload["difference"]["maximum_drawdown"] < 0
    assert payload["content_hash"].startswith("sha256:")
