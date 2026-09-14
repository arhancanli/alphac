"""Describe both saved registered runs; no strategy execution or selection."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from attribute_alphatrend_baseline import attribute_leg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/analysis/alphatrend_retrospective_comparison_20260912"
OUT = ROOT / "evidence/alphatrend-retrospective-attribution-20260912"


def main():
    hashes = {}

    def read(path):
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return pd.read_parquet(path)

    results = {}
    rows = []
    for arm in ("baseline", "candidate"):
        run = SOURCE / arm / "run"
        meta = run / "run_meta.json"
        hashes[str(meta.relative_to(ROOT))] = hashlib.sha256(meta.read_bytes()).hexdigest()
        config = json.loads(meta.read_text())["config"]
        fills = read(run / "fills.parquet")
        positions = read(run / "positions.parquet")
        equity = read(run / "equity.parquet")
        actions = read(run / "corporate_actions.parquet")
        result = attribute_leg(fills, positions, equity, config)
        assert abs(actions.cashflow_quote.sum() - result["corporate_action_cashflow"]) < 1e-6
        cash = actions.groupby("instrument_id").cashflow_quote.sum()
        for item in result.pop("instruments"):
            item["arm"] = arm
            item["action_cashflow"] = float(cash.get(item["instrument_id"], 0))
            item["contribution_before_borrow"] = (
                item["pnl_after_commission_before_borrow"] + item["action_cashflow"]
            )
            rows.append(item)
        results[arm] = result
    table = pd.DataFrame(rows)
    pivot = table.pivot(index="instrument_id", columns="arm", values="contribution_before_borrow")
    pivot["candidate_minus_baseline"] = pivot.candidate - pivot.baseline
    pivot = pivot.sort_values("candidate_minus_baseline")
    yearly = read(SOURCE / "yearly_returns.parquet").pivot(
        index="year", columns="arm", values="compounded_return"
    )
    yearly["candidate_minus_baseline"] = yearly.candidate - yearly.baseline
    for arm in results:
        reconciled = table.loc[table.arm == arm, "contribution_before_borrow"].sum()
        reconciled += results[arm]["borrow_cashflow"] + results[arm]["financing_cashflow"]
        assert abs(reconciled - results[arm]["equity_change"]) < 1e-6
    lines = [
        "# AlphaTrend saved-run attribution",
        "",
        "The latest directional candidate remains rejected. This diagnostic describes both existing registered paths (239/240); it computes no new strategy variant and does not change the experiment union of 240.",
        "",
        "Dollar contributions include realized and terminal unrealized price P&L, recorded commissions and corporate-action cash flows. Borrow is retained at portfolio level because these files do not allocate it by instrument. Spread, latency and impact are embedded in fills and are not separately identified; fees alone are not total execution drag.",
        "",
        "## Reconciled portfolio accounting",
        "",
        "| Arm | Equity gain ($) | Borrow cash flow ($) | Action cash flow ($) | Residual ($) |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm, r in results.items():
        lines.append(f"| {arm} | {r['equity_change']:.2f} | {r['borrow_cashflow']:.2f} | {r['corporate_action_cashflow']:.2f} | {r['reconciliation_residual']:.10f} |")
    lines += ["", "## All instrument contributions before portfolio borrow", "", "| Instrument | Baseline ($) | Candidate ($) | Difference ($) |", "|---|---:|---:|---:|"]
    for name, r in pivot.iterrows():
        lines.append(f"| {name} | {r.baseline:.2f} | {r.candidate:.2f} | {r.candidate_minus_baseline:.2f} |")
    lines += ["", "## All calendar-year slices", "", "2026 is partial through September 11. Differences are descriptive percentage points, not additive lifetime attribution or independent validation.", "", "| Year | Baseline (%) | Candidate (%) | Difference (pp) |", "|---|---:|---:|---:|"]
    for year, r in yearly.iterrows():
        lines.append(f"| {year} | {100*r.baseline:.3f} | {100*r.candidate:.3f} | {100*r.candidate_minus_baseline:.3f} |")
    lines += ["", "## Next research step", "", "Audit the retained forecast and exposure histories for the instruments with the largest contribution differences, including short exposure and covariance allocation. Do not drop losing instruments or select favorable years from this diagnostic. Any changed strategy needs a distinct economic hypothesis and preregistration before returns. No evidence here establishes Sharpe 2, independent alpha, executable live returns, or a new qualified sleeve.", "", "Both portfolios reconcile to saved final equity within $0.000001. Input SHA-256 hashes are retained in attribution.json. Historical source availability, borrow availability and omitted cash interest remain limitations inherited from the parent comparison."]
    OUT.mkdir(parents=True, exist_ok=False)
    table.to_csv(OUT / "instrument_accounting.csv", index=False)
    pivot.to_csv(OUT / "instrument_comparison.csv")
    yearly.to_csv(OUT / "yearly_comparison.csv")
    hashes[str(Path(__file__).relative_to(ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT / "attribution.json").write_text(json.dumps({"arms": results, "source_sha256": hashes}, indent=2, allow_nan=False) + "\n")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(pivot.to_string())
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
