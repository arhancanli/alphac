"""Correct session annualization from sealed equity; never rerun or rewrite trials."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from alphaforge.analytics.session_metrics import summarize_equity_sessions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    arms = {}
    for arm in ["baseline", "candidate"]:
        d = OUT / arm
        equity = pd.read_parquet(d / "run/equity.parquet").set_index("ts").equity
        fills = pd.read_parquet(d / "run/fills.parquet")
        result = summarize_equity_sessions(equity, fills=fills)
        metrics = {
            k: float(getattr(result, k))
            for k in [
                "sharpe",
                "cagr",
                "max_dd",
                "turnover_ann",
                "vol_ann",
                "fees_paid",
                "final_equity",
            ]
        }
        arms[arm] = {
            "metrics": metrics,
            "source_bindings": {
                str(p.relative_to(ROOT)): sha(p)
                for p in [
                    d / "run/equity.parquet",
                    d / "run/fills.parquet",
                    d / "experiments.jsonl",
                    d / "result.json",
                ]
            },
        }
    a, b = arms["baseline"]["metrics"], arms["candidate"]["metrics"]
    criteria = {
        "higher_sharpe": b["sharpe"] > a["sharpe"],
        "higher_cagr": b["cagr"] > a["cagr"],
        "no_worse_drawdown": b["max_dd"] <= a["max_dd"],
        "lower_turnover": b["turnover_ann"] < a["turnover_ann"],
        "positive_sharpe": b["sharpe"] > 0,
        "positive_cagr": b["cagr"] > 0,
    }
    correction = {
        "scope": "REPORTING_CORRECTION_NO_NEW_RETURN_TRIAL",
        "reason": "Legacy summarize drops non-session days but annualizes with 365. "
        "Use 252 for XNYS session Sharpe, volatility, Sortino and turnover. "
        "Elapsed-time CAGR, drawdown, fees and final equity are unchanged.",
        "supersedes_metric_claims": [
            "comparison.json",
            "baseline/result.json",
            "candidate/result.json",
            "both immutable first-measurement sharpe_ann fields",
        ],
        "original_records_preserved": True,
        "arms": arms,
        "criteria": criteria,
        "disposition": "PASS_FIXED_DEVELOPMENT_COMPARISON"
        if all(criteria.values())
        else "IMPROVEMENT_NOT_ESTABLISHED",
        "annualization": 252,
        "union_hypotheses": 236,
        "admitted": False,
        "implementation": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                Path(__file__),
                ROOT / "src/alphaforge/analytics/session_metrics.py",
                ROOT / "tests/unit/test_session_metrics.py",
            ]
        },
    }
    with (OUT / "metric_correction.json").open("x") as f:
        json.dump(correction, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    print(json.dumps({arm: data["metrics"] for arm, data in arms.items()}, indent=2))


if __name__ == "__main__":
    main()
