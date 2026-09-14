"""Verify and report the registered direction-preserving development comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from alphaforge.validation.input_snapshot import validate_input_snapshot
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    result = json.loads((OUT / "comparison.json").read_text())
    reservation = json.loads((OUT / "reservation.json").read_text())
    prereg = json.loads((OUT / "preregistration.json").read_text())
    validate_reservation(reservation, trial_config=reservation["trial_config"], repo=ROOT)
    for row in prereg["implementation_evidence"].values():
        if sha(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Implementation binding drift")
    a, b = result["baseline"], result["candidate"]
    criteria = {
        "higher_net_sharpe": b["sharpe"] > a["sharpe"],
        "higher_cagr": b["cagr"] > a["cagr"],
        "no_worse_drawdown": b["max_dd"] <= a["max_dd"],
        "lower_turnover": b["turnover_ann"] < a["turnover_ann"],
    }
    keep = all(criteria.values())
    expected = "RETAIN_FOR_FURTHER_TESTING" if keep else "REJECT_UNDER_FROZEN_SCENARIO"
    assert result["disposition"] == expected
    assert result["baseline_reference_max_equity_difference"] == 0
    diagnostics = {}
    signals = {}
    curves = {}
    for arm in ["baseline", "candidate"]:
        manifest = validate_input_snapshot(OUT / arm / "input_snapshot")
        signals[arm] = pd.read_parquet(OUT / arm / "input_snapshot/derived_signal_frame.parquet")
        curves[arm] = pd.read_parquet(OUT / arm / "equity.parquet")
        gross, net, exposure = [], [], {}
        for leg in sorted((OUT / arm / "legs").glob("leg_*")):
            eq = pd.read_parquet(leg / "equity.parquet")
            p = pd.read_parquet(leg / "positions.parquet")
            gross.extend(p.weight.abs().groupby(p.ts).sum().reindex(eq.ts, fill_value=0))
            net.extend(p.weight.groupby(p.ts).sum().reindex(eq.ts, fill_value=0))
            for iid, weight in p.weight.abs().groupby(p.instrument_id).sum().items():
                exposure[iid] = exposure.get(iid, 0.0) + float(weight)
        diagnostics[arm] = {
            "verified_files": manifest["file_count"],
            "mean_marked_gross": float(np.mean(gross)),
            "mean_marked_net": float(np.mean(net)),
            "gross_exposure_share": {k: v / sum(exposure.values()) for k, v in exposure.items()},
        }
    prior = ROOT / "artifacts/analysis/alphatrend_cash_retention_20260912"
    pd.testing.assert_frame_equal(
        signals["baseline"],
        pd.read_parquet(prior / "baseline/input_snapshot/derived_signal_frame.parquet"),
        check_exact=True,
    )
    old_eq = pd.read_parquet(prior / "baseline/equity.parquet")
    pd.testing.assert_frame_equal(curves["baseline"], old_eq, check_exact=True)
    sample = pd.read_parquet(
        ROOT
        / "artifacts/analysis/alphatrend_forecast_audit_20260912"
        / "forecast_observations.parquet"
    ).set_index(["ts_open", "instrument_id"])
    candidate_sample = signals["candidate"].reindex(sample.index)
    np.testing.assert_array_equal(
        np.sign(candidate_sample.alpha_blend), np.sign(sample.pre_centering_blend)
    )
    rms2 = signals["candidate"].alpha_blend.pow(2).groupby(level=0).mean().dropna()
    np.testing.assert_allclose(rms2, 1.0, atol=1e-12)
    sign_pairs = pd.concat(
        [
            signals["baseline"].mu_ann.rename("base"),
            signals["candidate"].mu_ann.rename("candidate"),
        ],
        axis=1,
    ).dropna()
    diagnostics["signal_validation"] = {
        "baseline_signal_and_equity_exact": True,
        "audited_raw_direction_matches": len(sample),
        "directional_rms_squared_mean_max_error": float((rms2 - 1).abs().max()),
        "full_complete_signal_pairs": len(sign_pairs),
        "full_complete_sign_difference_fraction": float(
            (np.sign(sign_pairs.base) != np.sign(sign_pairs.candidate)).mean()
        ),
        "note": "Full signal span includes warmup; audited sample is separately defined.",
    }
    (OUT / "allocation_diagnostic.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, layout="constrained")
    for arm, curve in curves.items():
        ts = pd.to_datetime(curve.ts, unit="ms", utc=True)
        eq = curve.equity / curve.equity.iloc[0]
        axes[0].plot(ts, eq, label=arm)
        axes[1].plot(ts, 100 * (eq / eq.cummax() - 1), label=arm)
    axes[0].set(
        ylabel="Equity / initial equity",
        title="AlphaTrend directional blend: registered development comparison",
    )
    axes[1].set(
        ylabel="Drawdown (%)",
        xlabel="Already-inspected history; modeled execution and borrow costs",
    )
    axes[0].legend()
    fig.savefig(OUT / "comparison.png", dpi=160)
    plt.close(fig)
    metrics = [
        ("Net Sharpe", "sharpe", ".3f"),
        ("CAGR", "cagr", ".2%"),
        ("Maximum drawdown", "max_dd", ".2%"),
        ("Annual turnover", "turnover_ann", ".3f"),
        ("Annualized volatility", "vol_ann", ".2%"),
        ("Final equity", "final_equity", ",.2f"),
    ]
    lines = [
        "# AlphaTrend direction-preserving development test",
        "",
        "**Disposition: "
        + expected
        + "**. This is development evidence, not admission or untouched validation.",
        "",
        f"Hypothesis `{reservation['hypothesis_identity']}`, ordinal 232, was validated before returns. "  # noqa: E501
        "The complete selection union now contains "
        + str(result["union_hypotheses_after"])
        + " identities.",
        "",
        "| Metric | Baseline | Directional RMS |",
        "| --- | ---: | ---: |",
    ]
    for label, key, fmt in metrics:
        lines.append(f"| {label} | {a[key]:{fmt}} | {b[key]:{fmt}} |")
    lines += ["", "## Frozen decision rule", ""]
    for label, passed in criteria.items():
        lines.append("- " + label.replace("_", " ") + ": " + ("PASS" if passed else "FAIL"))
    lines += [
        "",
        "All four conditions must pass. No rule or parameter was changed after returns. "
        + (
            "Retain only for further validation; no allocation promotion."
            if keep
            else "Reject this construction under the frozen rule; no allocation promotion."
        ),
        "",
        "## Implementation and interpretation",
        "",
        "The candidate keeps the same 63/126/252 momentum factors and causal IC blend weights. "
        "It divides the weighted blend by cross-sectional RMS without subtracting its mean. "
        "This preserves each asset's weighted trend sign. At least five complete PIT members "
        "are required; zero RMS remains missing. Unlike centered z-scores, unanimous nonzero "
        "trends remain usable. This changes signal construction; it is not a newly independent sleeve.",  # noqa: E501
        "",
        "The existing trend allocator, 10-session cadence, 21-session signal horizon, portfolio "
        "limits, volatility overlay and risk controls are identical. Neither arm has a cost gate. "
        "Both use next-open execution with 1 bp commission, 3 bp halfspread, 2 bp latency, "
        "impact coefficient 1 applied to lagged order size/ADV/volatility, 50 bp modeled annual "
        "borrow and zero financing. Each arm has its own resulting risk and position history.",
        "",
        "The preserved baseline signal frame and full timestamped equity frame reproduce exactly. "
        "Both snapshots and all preregistered implementation bindings verify. The candidate "
        f"matches the pre-centering direction in all {len(sample):,} audited observations; "
        "per-date mean squared normalized signals equal one to numerical precision.",
        "",
        "| Exposure diagnostic | Baseline | Candidate |",
        "| --- | ---: | ---: |",
        f"| Mean marked gross | {diagnostics['baseline']['mean_marked_gross']:.2%} | "
        f"{diagnostics['candidate']['mean_marked_gross']:.2%} |",
        f"| Mean marked net | {diagnostics['baseline']['mean_marked_net']:.2%} | "
        f"{diagnostics['candidate']['mean_marked_net']:.2%} |",
        "",
        "Exposure averages include flat leg observations; they are not risk contributions. "
        "Higher return alone can reflect changed market direction exposure and cannot establish "
        "a better diversified portfolio. This comparison includes no beta attribution or "
        "incremental portfolio diversification test.",
        "",
        "## Evidence limits and next step",
        "",
        "The data were already inspected and use a fixed ETF basket and retrospective price "
        "adjustments. Historical stock-loan availability, capacity, stress sweeps, independent "
        "reproduction and untouched evaluation remain unestablished. Reserved public URLs were "
        "not published. No live or paper orders, production changes or new data purchases occurred.",  # noqa: E501
        "",
        (
            "Next: separately design and register validation of this retained development candidate. "  # noqa: E501
            "Do not treat the result as a qualified sleeve or promise Sharpe 2."
            if keep
            else "Next: preserve this rejection. Do not rescue the result by changing the drawdown or "  # noqa: E501
            "turnover rule. Review the exposure tradeoff and independent sleeve research before "
            "registering another return identity."
        ),
        "",
        "The first preparation failed reservation schema validation before any returns: extra "
        "implementation hashes were moved into preregistration. Its files are preserved in the "
        "sibling alphatrend_directional_20260912 directory; the hypothesis and parameters were unchanged.",  # noqa: E501
        "",
        "![Comparison](comparison.png)",
        "",
        "[Preregistration](preregistration.json) · [Measured results](comparison.json) · "
        "[Allocation and signal diagnostics](allocation_diagnostic.json)",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    closure = {
        "criteria": criteria,
        "disposition": expected,
        "admission": "INCOMPLETE_NOT_ADMITTED",
        "files": [
            {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
            for p in [
                Path(__file__),
                OUT / "REPORT.md",
                OUT / "comparison.png",
                OUT / "comparison.json",
                OUT / "allocation_diagnostic.json",
                OUT / "preregistration.json",
                OUT / "reservation.json",
                OUT / "experiments.jsonl",
            ]
        ],
    }
    (OUT / "development_closure.json").write_text(json.dumps(closure, indent=2) + "\n")
    print(json.dumps({"criteria": criteria, "diagnostics": diagnostics}, indent=2))


if __name__ == "__main__":
    main()
