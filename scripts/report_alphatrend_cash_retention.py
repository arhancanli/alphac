"""Report one completed cash-retention development trial; no additional return tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from alphaforge.validation.input_snapshot import validate_input_snapshot
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphatrend_cash_retention_20260912"
PRIOR = ROOT / "artifacts/analysis/alphatrend_cost_development_20260911_attempt2"


def main():
    result = json.loads((OUT / "comparison.json").read_text())
    previous = json.loads((PRIOR / "comparison.json").read_text())
    reservation = json.loads((OUT / "reservation.json").read_text())
    validate_reservation(reservation, trial_config=reservation["trial_config"], repo=ROOT)
    diagnostics = {}
    for arm in ["baseline", "candidate"]:
        validate_input_snapshot(OUT / arm / "input_snapshot")
        gross = []
        exposure = {}
        for leg in sorted((OUT / arm / "legs").glob("leg_*")):
            eq = pd.read_parquet(leg / "equity.parquet")
            positions = pd.read_parquet(leg / "positions.parquet")
            positions["abs_weight"] = positions.weight.abs()
            gross.extend(
                positions.groupby("ts").abs_weight.sum().reindex(eq.ts, fill_value=0).tolist()
            )
            for iid, weight in positions.groupby("instrument_id").abs_weight.sum().items():
                exposure[iid] = exposure.get(iid, 0) + float(weight)
        diagnostics[arm] = {
            "mean_marked_gross_including_flat": sum(gross) / len(gross),
            "maximum_marked_gross": max(gross),
            "leg_equity_observations": len(gross),
            "gross_exposure_shares": {
                iid: value / sum(exposure.values()) for iid, value in exposure.items()
            },
        }
    (OUT / "allocation_diagnostic.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
    metrics = [
        ("Net Sharpe", "sharpe", False),
        ("CAGR", "cagr", True),
        ("Maximum drawdown", "max_dd", True),
        ("Annualized volatility", "vol_ann", True),
        ("Annual turnover", "turnover_ann", False),
    ]
    lines = [
        "# AlphaTrend cash-retention test: rejected",
        "",
        "One new hypothesis, e05ed6acb9f4f880, was registered before returns as ordinal 231. "
        "The data, cost scenario, 21-session signal horizon, 10-session rebalance cadence and "
        "acceptance rule were unchanged from the previous development test.",
        "",
        "| Metric | Baseline | Previous filter | Cash-retention variant |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, key, percent in metrics:
        fmt = ".2%" if percent else ".3f"
        values = [result["baseline"][key], previous["candidate"][key], result["candidate"][key]]
        lines.append("| " + name + " | " + " | ".join(format(v, fmt) for v in values) + " |")
    lines += [
        "",
        "## Decision",
        "",
        "Reject under the frozen rule. Drawdown and turnover improved, but both Sharpe "
        "and CAGR fell below baseline. This is a negative development result, not an "
        "admission or untouched validation. No production allocation was changed.",
        "",
        f"Mean marked gross exposure, including flat observations, fell from {diagnostics['baseline']['mean_marked_gross_including_flat']:.2%} "  # noqa: E501
        f"to {diagnostics['candidate']['mean_marked_gross_including_flat']:.2%}. "
        "Lower drawdown alone therefore cannot establish a better algorithm. These are "
        "gross exposure measurements over saved leg equity observations, not invested-day "
        "averages or variance contributions.",
        "",
        "## What changed and what the test establishes",
        "",
        "The earlier filter removed signals before inverse-vol allocation. The allocator "
        "normalized the survivors, and the volatility overlay could scale them again. "
        "The new variant computes original allocations and the overlay first, then zeros "
        "rejected targets. No renormalization follows. A controlled strategy test verifies "
        "that surviving targets are identical at the same decision state and rejected targets "
        "are zero. Repeated decisions still use each arm's own risk history, so later weights "
        "are not promised identical to an independent baseline trajectory.",
        "",
        "This test supports the conclusion that redistribution was a risk mechanism in the "
        "previous variant, but removing it did not produce improved risk-adjusted returns. "
        "The cost threshold also removes trading activity and changes asset exposure. This "
        "comparison does not isolate every cause or prove that all cost-aware strategies fail.",
        "",
        "No second threshold, alternative hurdle or additional return trial was evaluated. "
        "The baseline equity values again exactly reproduced the preserved reference. "
        "Both input snapshots and reservation bindings verified after the run. The local "
        "selection union now counts 231 identities, preserving both unsuccessful variants.",
        "",
        "The prior trial's accounting packet was closed with explicit, hash-bound missing "
        "admission evidence. Accounting completeness is distinct from proof of capacity, "
        "independent execution, PBO, public publication or untouched performance. Those "
        "claims remain unestablished for this trial too.",
        "",
        "## Next research implication",
        "",
        "Keep the baseline unchanged and retire these two filters under this scenario. "
        "The next useful question is forecast quality and breadth: whether the signal's "
        "expected-return magnitudes predict realized outcomes across assets. Another "
        "threshold tweak is not justified by these results. Sharpe near 2 and 14+ independent "
        "sleeves remain objectives, not achieved or guaranteed outcomes.",
        "",
        "![Equity and drawdown](comparison.png)",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for directory, label, color in [
        (OUT / "baseline", "Baseline", "#245f9e"),
        (PRIOR / "candidate", "Prior filter (rejected)", "#ba4d36"),
        (OUT / "candidate", "Cash retention (rejected)", "#398260"),
    ]:
        frame = pd.read_parquet(directory / "equity.parquet")
        dates = pd.to_datetime(frame.ts, unit="ms", utc=True)
        eq = frame.equity
        axes[0].plot(dates, eq / eq.iloc[0], color=color, label=label, lw=1)
        axes[1].plot(dates, 100 * (eq / eq.cummax() - 1), color=color, lw=1)
    axes[0].set_title("AlphaTrend development evidence: both cost filters rejected")
    axes[0].set_ylabel("Equity / starting equity")
    axes[0].legend()
    axes[1].set_ylabel("Drawdown (%)")
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUT / "comparison.png", dpi=150)
    plt.close(fig)
    (OUT / "development_closure.json").write_text(
        json.dumps(
            {
                "schema": "alphac.development-comparison-closure.v1",
                "hypothesis_identity": reservation["hypothesis_identity"],
                "disposition": result["disposition"],
                "admitted": False,
                "new_market_return_hypotheses": 1,
                "selection_union_after": 231,
                "bindings": {
                    name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                    for name in [
                        "comparison.json",
                        "reservation.json",
                        "preregistration.json",
                        "REPORT.md",
                        "allocation_diagnostic.json",
                        "comparison.png",
                        "experiments.jsonl",
                    ]
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
