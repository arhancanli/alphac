"""Render the completed descriptive audit without changing its frozen results."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphatrend_forecast_audit_20260912"


def main():
    bindings = json.loads((OUT / "bindings.json").read_text())
    for row in bindings["files"]:
        if hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Audit artifact changed: " + row["path"])
    r = json.loads((OUT / "results.json").read_text())
    q = r["tables"]["quintile"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout="constrained")
    means = [r["mean_alpha_rank_ic"], r["mean_mu_rank_ic"]]
    bounds = [r["alpha_rank_ic_block_95_interval"], r["mu_rank_ic_block_95_interval"]]
    axes[0].errorbar(
        means,
        [1, 0],
        xerr=[
            [m - b[0] for m, b in zip(means, bounds, strict=True)],
            [b[1] - m for m, b in zip(means, bounds, strict=True)],
        ],
        fmt="o",
        capsize=5,
    )
    axes[0].axvline(0, color="gray", linestyle="--")
    axes[0].set_yticks([1, 0], ["Standardized signal", "Expected return"])
    axes[0].set(
        title="Weak ranking evidence",
        xlabel="Mean cross-sectional Rank IC\n95% date-block intervals",
    )
    axes[1].plot(
        range(1, 6), [x["mean_abs_prediction_bps"] for x in q], "o-", label="Prediction magnitude"
    )
    axes[1].plot(
        range(1, 6),
        [x["mean_signed_forward_log_bps"] for x in q],
        "o-",
        label="Signed gross log return",
    )
    axes[1].axhline(0, color="gray", linewidth=0.7)
    axes[1].set(
        title="Magnitude is not calibrated proof",
        xlabel="Absolute forecast quintile (weak → strong)",
        ylabel="Mean basis points over 21 sessions",
        xticks=range(1, 6),
    )
    axes[1].legend(fontsize=8)
    axes[2].bar(range(1, 6), [100 * x["direction_hit_rate"] for x in q], color="#407b9f")
    axes[2].axhline(50, color="gray", linestyle="--")
    axes[2].set(
        title="Hit rates do not rise with strength",
        xlabel="Absolute forecast quintile",
        ylabel="Direction hit rate (%)",
        ylim=(40, 60),
        xticks=range(1, 6),
    )
    fig.suptitle(
        "AlphaTrend forecast audit · 247 dates · 17 ETFs · inspected history, not net performance"
    )
    fig.savefig(OUT / "forecast_audit.png", dpi=170)
    plt.close(fig)
    lines = [
        "# AlphaTrend forecast-quality audit — September 12, 2026",
        "",
        "**The audit is complete; no strategy is promoted.** The current forecasts have weak "
        "ranking evidence, and the signal implementation changes some underlying trend directions. "
        "The next justified experiment is a separately registered direction-preserving blend, "
        "not another cost-threshold adjustment.",
        "",
        "All 593 sealed baseline input files verified. Reconstructing the existing forecast "
        "pipeline reproduced the archived signal frame exactly, including missing values. "
        "The diagnostic uses 4,036 complete instrument/date observations on 247 nonoverlapping "
        "21-session dates, January 3, 2006-July 20, 2026, across all 17 existing ETFs. "
        "There was no new portfolio return trial; the existing 231 strategy identities remain counted.",  # noqa: E501
        "",
        "## Findings",
        "",
        "| Forecast | Mean cross-sectional Rank IC | Descriptive 95% interval |",
        "| --- | ---: | ---: |",
        f"| Standardized blend | {means[0]:.4f} | {bounds[0][0]:.4f} to {bounds[0][1]:.4f} |",
        f"| Annualized expected return | {means[1]:.4f} | {bounds[1][0]:.4f} to {bounds[1][1]:.4f} |",  # noqa: E501
        "",
        "Both intervals include zero. They use 2,000 circular bootstrap draws in blocks of "
        "12 consecutive sampled dates, preserving each date's cross-section. These intervals "
        "are descriptive and do not adjust for the project's full research selection history.",
        "",
        "| Strength quintile | Mean predicted magnitude, bp | Mean signed gross log return, bp | Hit rate |",  # noqa: E501
        "| --- | ---: | ---: | ---: |",
    ]
    for row in q:
        lines.append(
            f"| {row['quintile']} | {row['mean_abs_prediction_bps']:.2f} | "
            f"{row['mean_signed_forward_log_bps']:.2f} | {row['direction_hit_rate']:.1%} |"
        )
    lines += [
        "",
        "Quintiles rank absolute expected return within each sampled date; ties remain together. "
        "The strongest quintile has larger average signed outcomes but a lower hit rate "
        "(51.2%) than the weakest (54.3%). The pattern is not monotonic across all five groups. "
        "Higher absolute expected returns also reflect higher volatility and asset identity. "
        "This is insufficient evidence for treating forecast magnitude as a calibrated tradable edge. "  # noqa: E501
        "Log-return outcomes and modeled expected-return magnitudes are compared diagnostically; "
        "they are not identical estimands or a fitted calibration model.",
        "",
        "Mean forecast magnitude is only 8.21 bp over 21 sessions. That helps explain why the "
        "earlier roughly 25-29 bp cost hurdle discarded so much exposure. Gross label outcomes "
        "must not be subtracted mechanically from those hurdles to claim a portfolio net return.",
        "",
        "**Direction changes:** The original horizon factors are directional, volatility-scaled "
        "time-series momentum. The existing blend then subtracts the cross-sectional mean and "
        "standardizes the result. Its sign differs from the pre-centering weighted blend in "
        f"**{r['sign_changed_by_centering_fraction']:.2%}** of audited complete observations. "
        "An asset with a positive trend can therefore receive a negative forecast if its trend "
        "is below the cross-sectional average. This conflicts with the profile's stated "
        "own-trend direction interpretation; it does not prove the directional alternative earns more.",  # noqa: E501
        "",
        "## Asset coverage and market conditions",
        "",
        "| ETF | Observations | Within-asset Rank IC | Direction hit rate | Signed gross log return, bp |",  # noqa: E501
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in r["tables"]["instrument_id"]:
        ticker = row["instrument_id"].split(":")[-1][:-3]
        lines.append(
            f"| {ticker} | {row['rows']} | {row['time_series_rank_ic']:.4f} | "
            f"{row['direction_hit_rate']:.1%} | {row['mean_signed_forward_log_bps']:.2f} |"
        )
    lines += [
        "",
        "There are positive and negative within-asset relationships. No ETF is removed using "
        "these rankings. UNG's large average signed outcome alongside negative within-asset "
        "Rank IC illustrates why directional average gains and magnitude calibration are different questions.",  # noqa: E501
        "",
        "| Diagnostic group | Dates | Hit rate | Mean signed gross log return, bp |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ["era", "market_direction", "market_volatility"]:
        for row in r["tables"][key]:
            lines.append(
                f"| {key}: {row[key]} | {row['dates']} | {row['direction_hit_rate']:.1%} | "
                f"{row['mean_signed_forward_log_bps']:.2f} |"
            )
    lines += [
        "",
        "Market direction uses SPY's trailing 252-session return. High/low volatility uses "
        "its trailing 63-session volatility relative to the expanding median known before "
        "the decision date. Groups were fixed before statistics were calculated. Only 41 "
        "sampled dates are in down-market conditions; these slices are not independent sleeves.",
        "",
        "## Next experiment and claim limits",
        "",
        "Freeze one opt-in managed-futures-only variant that preserves the sign of the existing "
        "weighted directional blend. Keep horizons, weight estimation, universe, rebalance cadence, "  # noqa: E501
        "risk constraints and execution costs fixed. Register it before evaluating any candidate "
        "returns; compare against the exact baseline. Require higher net Sharpe and CAGR and "
        "no worse maximum drawdown; explicitly freeze the turnover rule before running. "
        "No candidate return series or new performance result has been generated here.",
        "",
        "Even a successful development result must pass separate validation and paper observation "
        "before promotion. This audit does not advance the qualified sleeve count or establish "
        "Sharpe near 2. Three horizons on the same ETF universe do not constitute three independent sleeves.",  # noqa: E501
        "",
        "The fixed ETF basket and retrospectively adjusted data limit historical inference. "
        "Labels enter at the exact next session open and exit 21 sessions later, without "
        "bridging missing endpoint bars; all prices after the original run cutoff are excluded. "
        "Missing forecasts and labels are excluded and counted in results.json. Labels omit "
        "execution friction, borrow and financing. Dates are nonoverlapping, but serial dependence "
        "and common market exposure remain. Data and derived observations remain private.",
        "",
        "![Forecast diagnostics](forecast_audit.png)",
        "",
        "Machine-readable evidence: [protocol](protocol.json), [results](results.json), "
        "[bindings](bindings.json), and forecast/date Parquet files in this directory.",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    (OUT / "report_bindings.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(p.relative_to(ROOT)),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                    for p in [
                        Path(__file__),
                        OUT / "REPORT.md",
                        OUT / "forecast_audit.png",
                        OUT / "bindings.json",
                    ]
                ]
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
