from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "build_fundamental_single_market_evidence.py"
    spec = importlib.util.spec_from_file_location("fundamental_single_market_evidence_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capacity_is_daily_bottlenecked_and_missing_adv_fails_closed() -> None:
    frame = pd.DataFrame(
        {
            "ts": [1, 1, 2],
            "prior_equity": [100_000.0, 100_000.0, 90_000.0],
            "raw_notional": [1_000.0, 2_000.0, 1_000.0],
            "adv_quote": [1_000_000.0, 1_000_000.0, float("nan")],
        }
    )
    result = _module().capacity_summary(frame, levels={"1pct": 0.01})
    assert result["fills_missing_point_in_time_adv"] == 1
    assert result["p05_usd_at_1pct_adv"] == 25_000.0
    assert result["median_usd_at_1pct_adv"] == 250_000.0


def test_generated_market_evidence_preserves_unfavorable_tail() -> None:
    path = (
        REPO
        / "artifacts"
        / "probe"
        / "fundamental_single_replays"
        / "1d2924f28fe31a9a"
        / "market_evidence.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["hypothesis_key"] == "1d2924f28fe31a9a"
    assert evidence["capacity"]["fills_missing_point_in_time_adv"] == 151
    assert evidence["capacity"]["p05_usd_at_1pct_adv"] == 0.0
    assert (
        evidence["execution_stress"]["stressed_annualized_sharpe"]
        < evidence["execution_stress"]["original_annualized_sharpe"]
        < 0.0
    )
