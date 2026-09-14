"""Replay measurement changes on frozen paper marks; no new portfolio construction."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRIOR = ROOT / "evidence/combined-baseline-audit-20260912"
OUT = ROOT / "evidence/baseline-measurement-corrections-20260912"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def main():
    bindings = json.loads((PRIOR / "audit.json").read_text())["source_bindings"]
    for relative, expected in bindings.items():
        assert sha(PRIOR / "sources" / relative) == expected["sha256"]
    old_path = PRIOR / "sources/scripts/evaluate_forward_evidence_maturity.py"
    new_path = ROOT / "scripts/evaluate_forward_evidence_maturity.py"
    old = module("old_forward_measurement", old_path)
    new = module("new_forward_measurement", new_path)
    state_path = PRIOR / "sources/data/paper/state.json"
    state = json.loads(state_path.read_text())
    curve = old._curve_from_state(state)
    curve_before = json.dumps(curve, sort_keys=True)
    # Frozen contract statistics from the exact prior receipt, not today's live files.
    maturity_path = PRIOR / "sources/artifacts/engineering/forward_evidence_maturity.json"
    maturity = json.loads(maturity_path.read_text())
    recorded = maturity["sharpe_evidence"]
    contract = {
        "minimum_daily_returns_for_estimate": recorded["estimate_minimum"],
        "minimum_daily_returns_for_establishment": recorded["establishment_minimum"],
        "annualization_days": recorded["annualization_days"],
        "forward_sharpe_target": recorded["target"],
        "target_exceedance_probability_min": recorded["target_exceedance_probability_min"],
    }
    old_returns, old_dd, _, _ = old._curve_metrics(curve)
    new_returns, new_dd, _, _ = new._curve_metrics(curve)
    intervals = new._curve_intervals(curve)
    old_sharpe = old._sharpe_evidence(old_returns, contract)
    new_sharpe = new._sharpe_evidence(
        new_returns, contract, consecutive_daily_marks=intervals["consecutive_daily_marks"])
    assert old_returns.size == maturity["record"]["daily_return_observations"] == 34
    assert old_sharpe["status"] == recorded["status"]
    assert old_dd == new_dd
    assert json.dumps(curve, sort_keys=True) == curve_before
    one_day_mask = np.array([
        (new.dt.date.fromisoformat(b["date"]) - new.dt.date.fromisoformat(a["date"])).days == 1
        for a, b in itertools.pairwise(curve)])
    assert np.array_equal(new_returns, old_returns[one_day_mask])
    old_book_path = PRIOR / "sources/src/alphaforge/portfolio/book.py"
    new_book_path = ROOT / "src/alphaforge/portfolio/book.py"
    synthetic = {}
    for label, path in [("original", old_book_path), ("corrected", new_book_path)]:
        book_module = module(f"{label}_book_measurement", path)
        book = book_module.combine_book(
            [book_module.SleeveCurve("fixture", [0, 86400000, 172800000], [100, 90, 90])],
            scheme="fixed", fixed_weights={"fixture": 1.0})
        synthetic[label] = {"drawdown_magnitude": -book.maxdd,
                            "equity": book.equity_curve.tolist(),
                            "returns": book.book_returns.tolist()}
    assert synthetic["original"]["equity"] == synthetic["corrected"]["equity"]
    assert synthetic["original"]["returns"] == synthetic["corrected"]["returns"]
    assert synthetic["original"]["drawdown_magnitude"] == 0
    assert abs(synthetic["corrected"]["drawdown_magnitude"] - .1) < 1e-12
    sources = [old_path, new_path, old_book_path, new_book_path, state_path, maturity_path,
               Path(__file__), ROOT / "tests/unit/test_portfolio_book.py",
               ROOT / "tests/unit/test_forward_evidence_maturity.py"]
    result = {
        "schema": "canli.alphac-measurement-correction-comparison.v1",
        "scope": "FROZEN_PAPER_MARKS_AND_SYNTHETIC_REGRESSION_ONLY",
        "original_daily_observation_claim": len(old_returns),
        "corrected_one_day_observations": len(new_returns),
        "original_sharpe_evidence": old_sharpe,
        "corrected_sharpe_evidence": new_sharpe,
        "interval_coverage": intervals,
        "paper_cumulative_return_unchanged": curve[-1]["equity"] / curve[0]["equity"] - 1,
        "paper_observed_drawdown_unchanged": new_dd,
        "marks_and_one_day_returns_unchanged": True,
        "synthetic_initial_loss": synthetic,
        "historical_full_book_recomputed": False,
        "new_market_return_trials": 0,
        "production_modified": False,
        "limits": "Measurement comparison, not a fresh broker or provenance evaluation. "
                  "Frozen historical target retained for comparability, not revised owner goals. "
                  "Missing intra-gap marks leave actual within-gap drawdown unknown.",
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sources},
    }
    OUT.mkdir(exist_ok=False)
    (OUT / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for path in [new_path, new_book_path, Path(__file__), *sources[-2:]]:
        target = OUT / "implementation" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    print(json.dumps({k: result[k] for k in ["original_daily_observation_claim",
                                          "corrected_one_day_observations",
                                          "paper_cumulative_return_unchanged",
                                          "paper_observed_drawdown_unchanged"]}, indent=2))
    print("Corrected status:", new_sharpe["status"])


if __name__ == "__main__":
    main()
