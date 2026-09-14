"""Audit retained exposures and forecasts without generating a return variant."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_retrospective_comparison_20260912"
OUT = ROOT / "evidence/alphatrend-baseline-review-20260912"


def main():
    bindings = {}

    def read(path):
        bindings[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return pd.read_parquet(path)

    rows, summaries = [], {}
    for arm in ("baseline", "candidate"):
        equity = read(SOURCE / arm / "run/equity.parquet")
        positions = read(SOURCE / arm / "run/positions.parquet")
        signals = read(SOURCE / arm / "signals.parquet")
        assert not equity.ts.duplicated().any()
        assert not positions.duplicated(["ts", "instrument_id"]).any()
        assert set(positions.ts) <= set(equity.ts)
        assert np.isfinite(positions.weight).all()
        weights = positions.pivot(index="ts", columns="instrument_id", values="weight")
        weights = weights.reindex(equity.ts).fillna(0)
        signals = signals.reset_index()
        signals = signals.loc[signals.ts_open.between(equity.ts.min(), equity.ts.max())]
        assert not signals.duplicated(["ts_open", "instrument_id"]).any()
        gross = weights.abs().sum(axis=1)
        net = weights.sum(axis=1)
        summaries[arm] = {
            "sessions": len(weights), "mean_gross": float(gross.mean()),
            "mean_net": float(net.mean()),
            "mean_long": float(weights.clip(lower=0).sum(axis=1).mean()),
            "mean_short_absolute": float(-weights.clip(upper=0).sum(axis=1).mean()),
        }
        for iid in weights:
            w = weights[iid]
            mu = signals.loc[signals.instrument_id == iid, "mu_ann"].dropna()
            assert np.isfinite(mu).all()
            rows.append({"arm": arm, "instrument_id": iid,
                         "mean_weight": float(w.mean()),
                         "mean_absolute_weight": float(w.abs().mean()),
                         "short_session_fraction": float((w < 0).mean()),
                         "long_session_fraction": float((w > 0).mean()),
                         "finite_forecasts": len(mu),
                         "mean_mu_ann": float(mu.mean()),
                         "positive_forecast_fraction": float((mu > 0).mean())})
    frame = pd.DataFrame(rows)
    assert all(v["sessions"] == 2940 for v in summaries.values())
    lines = ["# AlphaTrend baseline and exposure review", "",
             "Saved observations only; no new strategy return paths or trial reservations.", "",
             "## Portfolio exposure", "",
             "| Arm | Mean gross | Mean net | Mean long | Mean absolute short |",
             "|---|---:|---:|---:|---:|"]
    for arm, r in summaries.items():
        lines.append(f"| {arm} | {r['mean_gross']:.4f} | {r['mean_net']:.4f} | {r['mean_long']:.4f} | {r['mean_short_absolute']:.4f} |")
    lines += ["", "## Every instrument", "",
              "Weights and short fractions use all 2,940 equity sessions, including flat sessions. Forecast means use finite saved daily forecasts in the evaluation interval, not only executed decision dates. They are descriptive and cannot identify causal trade attribution.", "",
              "| Arm | Instrument | Mean weight | Mean absolute weight | Short sessions (%) | Mean annual forecast |",
              "|---|---|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['arm']} | {r['instrument_id']} | {r['mean_weight']:.4f} | {r['mean_absolute_weight']:.4f} | {100*r['short_session_fraction']:.2f} | {r['mean_mu_ann']:.4f} |")
    lines += ["", "## Baseline decision and prospective design", "",
              "Keep the original centered baseline as the historical control; it is not an adequate sole acceptance benchmark for the combined-portfolio objective. The directional candidate remains rejected under its original rules. Stronger future comparators should include a dated cash-return reference, a simple predeclared risk-balanced trend control, and the exact existing combined book with and without the proposed change. These are proposed new comparisons, not measured results.", "",
              "Separate the signal question from the allocator question. Inspecting the retained paired-price allocator shows covariance/shrinkage sizing, volatility scaling, position clipping and the drawdown ladder between expected returns and final targets. Therefore a normalization change is not a clean demonstration of a better economic edge. Do not attribute the observed losses to covariance without an isolated registered comparison.", "",
              "Before a new experiment, freeze the economic hypothesis, unchanged signal/control definitions, benchmark cash series and available-at-decision rules, portfolio composition/weights, common sample and calendars, net excess-return Sharpe, drawdown horizons, cost/borrow/financing stress, effective trial accounting and untouched/prospective evaluation. Keep zero-benchmark statistics explicitly separate. Freeze success rules around combined-book value; lower turnover alone is not a universal requirement if net returns, capacity and portfolio risk improve.", "",
              "A revised baseline is permitted when economically justified, but requires a new version and reservation before return computation. All older failed comparisons and identities remain in the record. No losing instrument is removed based on this table. Full-book Sharpe above 2 and maximum drawdown at most 11% remain unestablished."]
    for path in [Path(__file__), ROOT / "src/alphaforge/portfolio/paired_price_strategy.py"]:
        bindings[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=False)
    frame.to_csv(OUT / "all_instrument_exposures.csv", index=False)
    (OUT / "audit.json").write_text(json.dumps({"summaries": summaries, "source_sha256": bindings}, indent=2, allow_nan=False) + "\n")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
