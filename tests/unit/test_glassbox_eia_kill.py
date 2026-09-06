from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    script = REPO / "scripts" / "glassbox_export.py"
    spec = importlib.util.spec_from_file_location("glassbox_eia_kill_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eia_kill_prose_is_rendered_from_replay_result() -> None:
    module = _module()
    result = json.loads(
        (REPO / "artifacts/probe/eia_petroleum_inventory/result.json").read_text()
    )
    identifier, _, sharpe, reason, stage = module.eia_petroleum_inventory_kill()

    assert identifier == "commodity_inventory_seasonal"
    assert stage == "research_gauntlet"
    assert sharpe == result["metrics"]["net_sharpe"]
    assert f"average correlation {result['correlation']['average']:+.4f}" in reason
    assert f"maximum pair {result['correlation']['max_pair']:+.4f}" in reason
    assert f"improved by {result['book']['delta_sharpe']:.3f}" in reason
    assert f"{result['book']['common_days']}-session common window" in reason
    assert f"max drawdown {result['metrics']['max_drawdown']:.1%}" in reason
