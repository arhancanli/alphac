"""Render verified cost stress and corrected exposure diagnostics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "artifacts/analysis/alphatrend_directional_validation_20260912"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    amendment = json.loads((OUT / "exposure_calendar_amendment.json").read_text())
    assert sha(ROOT / "scripts/validate_alphatrend_directional.py") == protocol["script_sha256"]
    assert (
        sha(ROOT / "scripts/analyze_alphatrend_validation.py") == protocol["analysis_script_sha256"]
    )
    assert (
        sha(ROOT / "scripts/analyze_alphatrend_validation_corrected.py")
        == amendment["corrected_script_sha256"]
    )
    assert sha(OUT / "exposure_results.json") == amendment["discarded_result_sha256"]
    stress = json.loads((OUT / "cost_robustness.json").read_text())
    exposure = json.loads((OUT / "exposure_results_corrected.json").read_text())
    parent = json.loads((PARENT / "comparison.json").read_text())
    for arm in ["baseline", "candidate"]:
        reservation = json.loads((OUT / arm / "reservation.json").read_text())
        record = json.loads((OUT / arm / "experiments.jsonl").read_text().splitlines()[-1])
        assert record["config"] == reservation["trial_config"]
        packet_path = (
            ROOT / "artifacts/research/trial_packets" / f"{reservation['hypothesis_identity']}.json"
        )
        packet = json.loads(packet_path.read_text())
        body = {k: v for k, v in packet.items() if k != "content_hash"}
        assert (
            packet["content_hash"]
            == "sha256:"
            + hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        for section in packet["required_sections"].values():
            for row in section["evidence"]:
                assert sha(ROOT / row["path"]) == row["sha256"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for arm in ["baseline", "candidate"]:
        curve = pd.read_parquet(OUT / arm / "run/equity.parquet")
        axes[0].plot(
            pd.to_datetime(curve.ts, unit="ms"), curve.equity / curve.equity.iloc[0], label=arm
        )
    axes[0].set(title="Full engine replay: doubled modeled costs", ylabel="Equity / initial equity")
    axes[0].legend()
    eras = exposure["eras"]
    axes[1].bar([0, 1, 2], [r["baseline"]["sharpe"] for r in eras], width=0.35, label="baseline")
    axes[1].bar(
        [0.35, 1.35, 2.35], [r["candidate"]["sharpe"] for r in eras], width=0.35, label="candidate"
    )
    axes[1].set_xticks([0.175, 1.175, 2.175], [r["era"] for r in eras])
    axes[1].set(title="Original costs: improvement varies by era", ylabel="Annualized Sharpe")
    axes[1].legend()
    fig.suptitle("AlphaTrend validation on inspected history; not independent forward evidence")
    fig.savefig(OUT / "validation.png", dpi=160)
    plt.close(fig)
    lines = [
        "# AlphaTrend retained-candidate validation",
        "",
        "**Passed the fixed doubled-cost test; retain for further research, not admission.** "
        "The candidate remains better than the stressed baseline, but performance is uneven "
        "across eras and incremental exposure-adjusted evidence is uncertain.",
        "",
        "## Full engine cost stress",
        "",
        "The protocol fixed exactly one scenario before the replays: double commission "
        "(1 to 2 bp), halfspread (3 to 6 bp), latency (2 to 4 bp), square-root impact "
        "coefficient (1 to 2) and modeled annual borrow (50 to 100 bp). Financing stays zero. "
        "The actual engine recalculated orders, sizes, equity, risk state and fills using "
        "the original sealed forecasts, universe and settings. This is not a fixed-position "
        "cash haircut or a cost-threshold search.",
        "",
        "| Metric | Original baseline | Original candidate | 2x-cost baseline | 2x-cost candidate |",  # noqa: E501
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, key, fmt in [
        ("Net Sharpe", "sharpe", ".3f"),
        ("CAGR", "cagr", ".2%"),
        ("Maximum drawdown", "max_dd", ".2%"),
        ("Annual turnover", "turnover_ann", ".3f"),
    ]:
        values = [
            parent["baseline"][key],
            parent["candidate"][key],
            stress["arms"]["baseline"][key],
            stress["arms"]["candidate"][key],
        ]
        lines.append("| " + label + " | " + " | ".join(format(v, fmt) for v in values) + " |")
    lines += [
        "",
        "All six predeclared stress checks passed: higher candidate Sharpe and CAGR, no worse "
        "drawdown, lower turnover, and positive candidate Sharpe and CAGR. Drawdown nevertheless "
        "increased relative to the candidate at original costs. This single modeled scenario "
        "does not establish capacity, a maximum affordable fee level or robustness to missing borrow.",  # noqa: E501
        "",
        "The baseline stress identity `6f5e71ec657beef2` was ordinal 233; the candidate stress "
        "identity `4d7793cfffb17091` was ordinal 234. Each was registered before its returns, "
        "recorded with the complete cost settings and closed with explicit admission limitations. "
        "The full experiment union is now **234**, including every earlier rejected construction.",
        "",
        "## Exposure and uncertainty",
        "",
        "The original candidate increased average marked net exposure from 15.86% to 39.01%, "
        "while average gross exposure stayed about 94.77%. Net exposure across this multi-asset "
        "ETF basket is not the same thing as equity-market beta.",
        "",
        "The fixed descriptive regression uses raw daily strategy returns against SPY, IEF, GLD "
        "and UUP close returns plus an intercept. It uses 4,900 complete observations from "
        "March 5, 2007 to August 24, 2026; 290 earlier observations are unavailable because of "
        "factor coverage. No forward fill is used. Standard errors use Bartlett Newey-West "
        "with 21 lags and an n/(n-k) adjustment.",
        "",
        "| Proxy coefficient | Baseline | Candidate | Candidate minus baseline |",
        "| --- | ---: | ---: | ---: |",
    ]
    for i, factor in enumerate(["SPY", "IEF", "GLD", "UUP"], 1):
        values = [
            exposure["regression"][arm]["coefficients"][i]
            for arm in ["baseline", "candidate", "difference"]
        ]
        lines.append("| " + factor + " | " + " | ".join(f"{v:.4f}" for v in values) + " |")
    diff = exposure["regression"]["difference"]
    ci = diff["intercept_95_interval_annualized"]
    boot = exposure["parent_sharpe_difference_95_block_interval"]
    lines += [
        "",
        f"The incremental regression intercept is **{diff['intercept_annualized_arithmetic']:.2%} "
        f"annualized**, with a descriptive 95% interval of **{ci[0]:.2%} to {ci[1]:.2%}**. "
        "It does not establish positive incremental alpha after these exposure controls. "
        "This is a raw-return, arithmetic annualization, not CAGR or an excess-return alpha; "
        "the proxy model is incomplete and cannot causally separate timing skill from market exposures.",  # noqa: E501
        "",
        f"The paired 63-session block bootstrap puts the original Sharpe difference in "
        f"**[{boot[0]:.3f}, {boot[1]:.3f}]** at the descriptive 95% level "
        "(2,000 draws, fixed seed). This uses the same inspected sample and is not adjusted "
        "for the complete research selection history. It is not an admission significance test.",
        "",
        "| Original-cost era | Baseline Sharpe | Candidate Sharpe |",
        "| --- | ---: | ---: |",
    ]
    for era in eras:
        lines.append(
            f"| {era['era']} | {era['baseline']['sharpe']:.3f} | {era['candidate']['sharpe']:.3f} |"
        )
    lines += [
        "",
        "The candidate improved in 2006-2012 and 2020-2026 but underperformed in 2013-2019. "
        "These fixed era diagnostics share the same inspected history and are not independent tests.",  # noqa: E501
        "",
        "## Calendar correction and verification",
        "",
        "The first exposure diagnostic incorrectly mapped closes to the next UTC midnight. "
        "The engine instead maps each close to the next exchange-session open timestamp, including "
        "weekends and holidays. The original regression is discarded and preserved as "
        "`exposure_results.json`; all conclusions here use `exposure_results_corrected.json`. "
        "The hash-bound amendment was recorded before the corrected calculation. Factors, "
        "lag count, era splits and stress scenario were unchanged. Cost replays were unaffected.",
        "",
        "Both stress input snapshots verified, and their forecast frames match the corresponding "
        "parent frames exactly. Recorded cost settings equal the actual resolved engine settings. "
        "Reservation, immutable ledger, packet and source hashes were checked. Completing evidence "
        "accounting does not mean admission evidence is complete.",
        "",
        "## What remains before promotion",
        "",
        "Keep the candidate frozen. The next phase is independent/prospective validation with "
        "properly timed prices and borrow evidence, plus portfolio-level overlap analysis against "
        "qualified complementary sleeves. No new thresholds, leverage changes or asset deletions "
        "are justified by this check. Cost stress and an in-sample regression do not supply that "
        "missing evidence. The strategy is not promoted and does not increase the independent sleeve count.",  # noqa: E501
        "",
        "The fixed historical ETF basket, retrospective adjustments, modeled borrow, absent "
        "capacity study and absence of untouched performance remain limits. No data were purchased, "  # noqa: E501
        "orders sent, public artifacts published or production profiles changed. Sharpe near 2 "
        "with 14+ independent sleeves remains a portfolio research target, not an achieved result.",
        "",
        "![Validation charts](validation.png)",
        "",
        "[Frozen protocol](protocol.json) · [Cost results](cost_robustness.json) · "
        "[Corrected exposure results](exposure_results_corrected.json) · "
        "[Calendar amendment](exposure_calendar_amendment.json)",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    files = [
        OUT / name
        for name in [
            "protocol.json",
            "cost_robustness.json",
            "exposure_results_corrected.json",
            "exposure_observations_corrected.parquet",
            "exposure_calendar_amendment.json",
            "REPORT.md",
            "validation.png",
        ]
    ]
    files += [Path(__file__)]
    (OUT / "validation_closure.json").write_text(
        json.dumps(
            {
                "disposition": "RETAIN_DEVELOPMENT_CANDIDATE_NOT_ADMITTED",
                "cost_stress": stress["disposition"],
                "independent_alpha_established": False,
                "union_hypotheses": 234,
                "files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
