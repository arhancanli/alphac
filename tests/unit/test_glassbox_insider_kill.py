from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    script = REPO / "scripts" / "glassbox_export.py"
    spec = importlib.util.spec_from_file_location("glassbox_insider_kill_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_insider_kill_prose_is_rendered_from_current_replay_and_boundary() -> None:
    module = _module()
    result = json.loads(
        (REPO / "artifacts/probe/insider_purchase_clusters/result.json").read_text()
    )
    identifier, _, sharpe, reason, stage = module.insider_purchase_clusters_kill()

    assert identifier == "insider_purchase_clusters"
    assert stage == "research_gauntlet"
    assert sharpe == result["metrics"]["net_sharpe"]
    assert f"average correlation {result['correlation']['average']:+.3f}" in reason
    assert f"changed combined-book Sharpe by {result['book']['delta_sharpe']:.3f}" in reason
    assert f"adds {result['ledger_reconciliation']['observation_delta']} sessions" in reason
    assert "not an exact reproduction" in reason
    assert "identity packet remains incomplete" in reason
