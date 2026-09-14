"""Publish the completed, fixed-scenario development comparison without another trial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphatrend_cost_development_20260911_attempt2"


def main():
    result = json.loads((OUT / "comparison.json").read_text())
    diagnostic = json.loads((OUT / "allocation_diagnostic.json").read_text())
    reservation = json.loads((OUT / "reservation.json").read_text())
    rows = [
        ("Net Sharpe", "sharpe", False),
        ("CAGR", "cagr", True),
        ("Maximum drawdown", "max_dd", True),
        ("Annualized volatility", "vol_ann", True),
        ("Annual turnover", "turnover_ann", False),
    ]
    lines = [
        "# AlphaTrend development result: reject this cost filter",
        "",
        "One cost scenario was registered before returns as hypothesis "
        + reservation["hypothesis_identity"]
        + ", reservation ordinal 230. This is development evidence on already-inspected data, "
        "not untouched validation or admission. No threshold search followed the result.",
        "",
        "| Metric | Baseline | Candidate |",
        "| --- | ---: | ---: |",
    ]
    for name, key, percent in rows:
        a, b = result["baseline"][key], result["candidate"][key]
        fmt = ".2%" if percent else ".3f"
        lines.append(f"| {name} | {a:{fmt}} | {b:{fmt}} |")
    lines += [
        "",
        "On an initial $100,000, final simulated equity was "
        f"${result['baseline']['final_equity']:,.2f} versus ${result['candidate']['final_equity']:,.2f}. "  # noqa: E501
        "The small CAGR increase came with lower Sharpe and substantially larger volatility "
        "and drawdown. Commission fell from $1,566.94 to $795.40; that field excludes "
        "spread, impact and borrow, which were separately modeled in both runs.",
        "",
        "The predeclared keep rule required higher Sharpe and CAGR, no worse maximum "
        "drawdown, and lower turnover. The candidate fails that rule and is rejected under "
        "this scenario. No trading profile was changed.",
        "",
        "## What the allocation diagnostic shows",
        "",
        f"Average held names on invested sessions fell from {diagnostic['baseline']['average_held_names_when_invested']:.2f} "  # noqa: E501
        f"to {diagnostic['candidate']['average_held_names_when_invested']:.2f}. "
        "UNG and USO together accounted for about 90.8% of the candidate's summed absolute "
        "session-weight exposure. These are capital-exposure shares, not variance or PnL contributions. "  # noqa: E501
        "The filter left a much narrower book; lower turnover did not produce better risk-adjusted returns.",  # noqa: E501
        "",
        "This supports investigating the interaction between return-magnitude filtering and "
        "allocation breadth. It does not prove an optimal replacement threshold or justify "
        "removing or retaining individual ETFs based on hindsight.",
        "",
        "## Scenario and verification",
        "",
        "The hurdle used 1 bp commission, 3 bp half-spread and 2 bp latency per side, "
        "square-root impact at a reference 0.1% of ADV and 2% daily volatility, and 50 bp "
        "annual borrow for a reference 30 calendar days on shorts. The resulting hurdle was "
        "24.65 bp for longs and 28.76 bp for shorts. The expected-return horizon was the "
        "configured 21 trading sessions; rebalance cadence remained 10 sessions.",
        "",
        "Both execution engines retained the same NextOpenFill model, actual order-size/lagged "
        "ADV/volatility impact, modeled borrow and zero financing. Reference hurdle costs "
        "are scenario assumptions, not observed historical lending or execution quotes.",
        "",
        "The baseline equity values reproduced the preserved reference exactly (maximum "
        "difference $0.00). Both runs contain 42 legs. Their input snapshots verified after "
        "completion, and reservation/source bindings revalidated. The local selection union "
        "increased from 229 to 230 identities; the production ledger was not edited.",
        "",
        "An earlier preparation attempt failed on a metadata key before reservation validation "
        "or return computation. Its failure receipt is preserved. No market-return retry or "
        "parameter change occurred after either result was seen.",
        "",
        "Full admission evidence such as capacity, independent execution validation and "
        "untouched evaluation is not claimed complete. This report closes the development "
        "decision; it is not a completed admission packet.",
        "",
        "![Equity and drawdown comparison](comparison.png)",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for arm, color in [("baseline", "#245f9e"), ("candidate", "#ba4d36")]:
        df = pd.read_parquet(OUT / arm / "equity.parquet")
        dates = pd.to_datetime(df.ts, unit="ms", utc=True)
        eq = df.equity.astype(float)
        axes[0].plot(dates, eq / eq.iloc[0], label=arm.title(), color=color, lw=1.1)
        axes[1].plot(dates, 100 * (eq / eq.cummax() - 1), color=color, lw=1.1)
    axes[0].set_ylabel("Equity / initial equity")
    axes[0].legend()
    axes[1].set_ylabel("Drawdown (%)")
    axes[0].set_title(
        "AlphaTrend: fixed-scenario development comparison\nAlready-inspected data; candidate rejected"  # noqa: E501
    )
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUT / "comparison.png", dpi=150)
    plt.close(fig)
    closure = {
        "schema": "alphac.development-comparison-closure.v1",
        "hypothesis_identity": reservation["hypothesis_identity"],
        "disposition": result["disposition"],
        "admitted": False,
        "canonical_admission_packet_complete": False,
        "new_market_return_hypotheses": 1,
        "selection_union_after": 230,
        "bindings": {
            name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
            for name in [
                "preregistration.json",
                "reservation.json",
                "reservation_validation.json",
                "comparison.json",
                "allocation_diagnostic.json",
                "experiments.jsonl",
                "REPORT.md",
                "comparison.png",
            ]
        },
    }
    (OUT / "development_closure.json").write_text(json.dumps(closure, indent=2) + "\n")
    print(OUT / "REPORT.md")


if __name__ == "__main__":
    main()
