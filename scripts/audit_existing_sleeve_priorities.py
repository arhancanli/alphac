"""Freeze existing evidence and prioritize repairs; no strategy runs or broker access."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SOURCES = {
    "quality": "artifacts/analysis/sleeve_quality_decomposition/result.json",
    "book": "artifacts/analysis/book_without_alphavintage/result.json",
    "stress": "artifacts/analysis/stressed_correlation/result.json",
    "cost": "artifacts/analysis/cost_model_realism/result.json",
    "trend": "artifacts/research/alphatrend_family.json",
    "max_replay": "artifacts/publication/alphamax_upstream_clean_workspace.json",
    "forge_correction": "artifacts/publication/crypto_carry_replay_correction.json",
    "execution_prototype": "scripts/prototypes/execution_cost_measurement.py",
    "equity_order_path": "scripts/live_cycle.py",
}


def freeze(root: Path, out: Path, path: str, bindings: dict) -> bytes:
    raw = (root / path).read_bytes()
    destination = out / "sources" / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    bindings[path] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "snapshot": str(destination.relative_to(out)),
    }
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite a prior evidence packet or operate on a trading database.
    args.output.mkdir(parents=True, exist_ok=False)
    bindings: dict = {}
    data = {}
    for name, path in SOURCES.items():
        raw = freeze(args.source_root, args.output, path, bindings)
        if path.endswith(".json"):
            data[name] = json.loads(raw)

    variants = []
    for identity in data["trend"]["identities"]:
        if identity["evidence_grade"] != "complete_walkforward_curve_config_and_validation":
            continue
        path = identity["artifact_path"]
        raw = freeze(args.source_root, args.output, path, bindings)
        if hashlib.sha256(raw).hexdigest() != identity["artifact_sha256"]:
            raise ValueError(f"Family source binding changed: {path}")
        variants.append(
            {
                "path": path,
                "hypothesis_key": identity["hypothesis_key"],
                "configuration": identity["configuration"],
                "result": identity["result"],
                "family_binding_verified": True,
            }
        )

    # Deliberately exclude legacy AlphaForge metrics from the usable comparison.
    quality = {r["sleeve"]: r for r in data["quality"]["sleeves"] if r["sleeve"] != "AlphaForge"}
    old_book = data["book"]["with_alphavintage"]
    common = {k: v for k, v in old_book["per_sleeve_sharpe"].items() if k != "AlphaForge"}
    correlations = {
        k: v for k, v in old_book["pairwise_correlations"].items() if "AlphaForge" not in k
    }
    result = {
        "schema": "alphac.existing-sleeve-priorities.v1",
        "scope": "Archived evidence audit; no new return trials or allocation changes",
        "source_root": str(args.source_root.resolve()),
        "source_bindings": bindings,
        "legacy_alphaforge": "QUARANTINED_FROM_THIS_AUDIT_COMPARISON",
        "current_portfolio_sharpe": None,
        "new_sleeves_admitted": 0,
        "historical_full_window_cost_decomposition": quality,
        "historical_common_window": {
            "calendar_days": data["book"]["common_window_days"],
            "per_sleeve_sharpe": common,
            "pairwise_joint_activity_correlations": correlations,
            "limitation": "Original four-sleeve window; not a recomputed three-sleeve book",
        },
        "alphatrend_family_summary": data["trend"]["summary"],
        "alphatrend_complete_variants": variants,
        "execution_measurement": "Offline prototype exists; live benchmark integration missing",
        "priority_order": [
            "Separate AlphaForge restart evidence from corrected legacy carry",
            "Integrate independent execution benchmarks using existing prototype",
            "Diagnose AlphaTrend signal and allocation losses before another parameter sweep",
            "Resolve AlphaMax replay provenance and prospective validation",
            "Evaluate AlphaVintage marginal contribution on a valid corrected book",
        ],
    }
    (args.output / "audit.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = [
        "# Existing-sleeve improvement audit",
        "",
        "Archived evidence reviewed on 2026-09-11. No new return trial, admission, "
        "portfolio reweighting or broker action. Source bytes and SHA-256 hashes are frozen "
        "in this packet; a frozen summary does not independently validate underlying data.",
        "",
        "## What to fix first",
        "",
        "1. **AlphaForge:** quarantine the disputed carry history in comparisons. "
        "The correction packet is not a validated replacement track record. "
        "The separate spot paper restart still needs runtime readiness and a clean epoch.",
        "2. **Shared execution measurement:** reuse the recent session's offline prototype. "
        "The equity order path still substitutes a padded limit for decision price. "
        "Capture independent decision/arrival benchmarks with verified feed, market and "
        "receive timestamps, cumulative fill observations and fee completeness. Preserve "
        "missing values; do not backfill a limit price as a market benchmark. "
        "Prototype integration is unfinished and has not been deployed.",
        "3. **AlphaTrend:** diagnose signal construction and allocation before tuning again. "
        "The existing family has 21 hypothesis identities and zero artifact-era gate passes. "
        "The table below exposes previously tested variants; retain their trial history.",
        "4. **AlphaMax:** the fresh-input author replay does not exactly reproduce the preserved "
        "curve. Freeze prospective inputs and evaluate a new epoch; the replay cannot "
        "replace the historical record or count as independent replication.",
        "5. **AlphaVintage:** low standalone Sharpe alone does not justify removal. "
        "The old removal comparison includes disputed AlphaForge returns, so its book "
        "Sharpe and drawdown changes cannot settle today's allocation.",
        "",
        "## Historical comparisons",
        "",
        "The full-history and common-window columns use different periods. They are "
        "historical simulation summaries, not forward paper or funded performance.",
        "",
        "| Sleeve | Full-history Sharpe | Original common-window Sharpe |",
        "| --- | ---: | ---: |",
    ]
    for sleeve, sr in common.items():
        full = (
            f"{quality[sleeve]['net_sharpe_published']:.3f}"
            if sleeve in quality
            else "Not in cost packet"
        )
        lines.append(f"| {sleeve} | {full} | {sr:.3f} |")
    trend = quality["AlphaTrend"]
    burden = trend["commission_sharpe_points_MEASURED"] + trend["spread_sharpe_points_MODELLED"]
    lines += [
        "",
        f"AlphaTrend's first-order commission plus modeled spread/latency burden is "
        f"{burden:.3f} Sharpe points. Adding it back yields approximately "
        f"{trend['residual_signal_sharpe']:.3f}; this is not an achievable cost saving "
        "or a true gross Sharpe because impact and compounding are not isolated.",
        "",
        "Historical pair correlations, measured on jointly active days:",
        "",
    ]
    lines += [f"- {pair.replace('|', ' / ')}: {corr:.3f}." for pair, corr in correlations.items()]
    lines += [
        "",
        "Stress samples in the source packet are only 14-16 common days. "
        "These samples and family proxies do not establish reliable tail diversification.",
        "",
        "## Previously completed AlphaTrend variants",
        "",
        "These are not a new selection contest. Windows and instruments differ; "
        "the real-futures variant has fewer observations. All source artifact hashes "
        "were checked against the family packet.",
        "",
        "| Existing variant | Observations | Sharpe | Annual turnover | Gate pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for variant in variants:
        r = variant["result"]
        lines.append(
            f"| {Path(variant['path']).parent.name} | {r['observations']} | "
            f"{r['annualized_sharpe']:.3f} | {r['annual_turnover']:.2f} | "
            f"{r['clears_artifact_era_dsr_gate']} |"
        )
    lines += [
        "",
        "## Next algorithm diagnostic",
        "",
        "Use the existing frozen AlphaTrend baseline to attribute losses by instrument, "
        "signal horizon, rebalance event and risk allocation, retaining the entire tested "
        "family denominator. First verify daily curve, fill and input bindings. Report "
        "missing attribution inputs instead of reconstructing them silently. Diagnostic "
        "results may motivate one explicit construction change; reserve its trial and "
        "unseen evaluation interval before inspecting new returns. Do not present a "
        "rebalance-frequency sweep or a switch to futures as an untested idea.",
        "",
        "Alphabet share-class research remains parked pending dated security-level "
        "borrow and defensible execution inputs. Quote/status feasibility is not "
        "proof of short availability or profitability. No new data purchase was made.",
        "",
        "The Sharpe-2 and 14+ sleeve targets remain unproven. This packet supplies "
        "repair priorities, not evidence that performance has improved.",
        "",
    ]
    (args.output / "AUDIT.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "bound_sources": len(bindings),
                "verified_trend_variants": len(variants),
                "new_trials": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
