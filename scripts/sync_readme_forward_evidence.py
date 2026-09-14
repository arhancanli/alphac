#!/usr/bin/env python3
"""Synchronize README forward headlines with the canonical maturity artifact."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "artifacts" / "engineering" / "forward_evidence_maturity.json"
README = REPO / "README.md"


def _replace_once(text: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"README synchronization expected one match, found {count}: {pattern}")
    return updated


def _target_text(target: float) -> str:
    """2.0 stays 2.0 and 2.25 stays 2.25: one decimal at least, never a bare integer."""
    text = f"{target:.4f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def _target_in_force(sharpe: dict[str, Any]) -> str:
    """Name when the governing target took force, from the contract's own history."""
    history = sharpe.get("target_history") or []
    current = [entry for entry in history if float(entry["target"]) == float(sharpe["target"])]
    if not current:
        return "target history not published"
    return f"in force from {current[-1]['in_force_from']}"


def _epoch_clause(record: dict[str, Any]) -> str:
    """Name the evidence epoch when a declared live change split the record (never pooled)."""
    epoch = record.get("evidence_epoch")
    priors = record.get("prior_epochs") or []
    if not epoch or not priors:
        return ""
    prior = priors[-1]
    return (
        f"; evidence epoch since {epoch['starts_on']}, the prior epoch's "
        f"{prior['daily_return_observations']} returns from {prior['first_mark']} through "
        f"{prior['last_mark']} are published separately and not pooled"
    )


def _percentage(value: float, places: int) -> str:
    rendered = f"{value:.{places}%}"
    return rendered.replace("-", chr(0x2212))


def synchronize(evidence: dict[str, Any], readme: str) -> str:
    record = evidence["record"]
    drawdown = evidence["drawdown_evidence"]
    diversification = evidence["diversification_evidence"]
    snapshot_date = str(evidence["generated_at"])[:10]
    provenance = evidence["provenance_gate"]
    provenance_passes = bool(provenance["passes"])
    failed_checks = set(provenance.get("failed_checks", []))
    attribution_stale_only = failed_checks == {"crypto_position_attribution_covers_last_mark"}
    if provenance_passes:
        provenance_summary = "provenance currently passes the publication gate"
        provenance_sentence = "its provenance gate currently passes."
    elif attribution_stale_only:
        provenance_summary = (
            "provenance fails closed because crypto attribution does not cover the latest mark"
        )
        provenance_sentence = (
            "its provenance gate remains closed because the latest composite mark is newer "
            "than the last attributed crypto cycle."
        )
    else:
        provenance_summary = "provenance currently fails closed on incomplete evidence"
        provenance_sentence = (
            "its provenance gate remains closed on the failed checks named in the evidence "
            "artifact."
        )
    expected_drawdown = _percentage(
        float(drawdown["current_composition_conservative_expected_max_drawdown"]), 3
    )
    p95_drawdown = _percentage(
        float(drawdown["current_composition_conservative_p95_max_drawdown"]), 3
    )

    readme = _replace_once(
        readme,
        r"^\*\*Evidence snapshot:\*\* \d{4}-\d{2}-\d{2}\.",
        f"**Evidence snapshot:** {snapshot_date}.",
    )
    readme = _replace_once(
        readme,
        r"^\| Paper sleeves \|.*$",
        "| Paper sleeves | "
        f"**{diversification['current_sleeves']} / {diversification['target_total_sleeves']} "
        "planned** — funding carry, equity momentum, managed-futures trend, PIT macro surprise |",
    )
    readme = _replace_once(
        readme,
        r"^\| Forward record \|.*$",
        "| Forward record | "
        f"**{record['daily_return_observations']} daily returns** from {record['first_mark']} "
        f"through {record['last_mark']}; cumulative return "
        f"**{_percentage(float(record['cumulative_return']), 5)}**; {provenance_summary}"
        f"{_epoch_clause(record)} |",
    )
    sharpe = evidence["sharpe_evidence"]
    target = _target_text(float(sharpe["target"]))
    if sharpe.get("annualized_point_estimate") is None:
        sharpe_row = (
            "| Forward Sharpe | **Not reportable** — "
            f"{int(sharpe['estimate_minimum'])} observations are required for an estimate and "
            f"{int(sharpe['establishment_minimum'])} for the project's establishment test; the "
            f"governing forward target is **{target}** (owner goal, "
            f"{_target_in_force(sharpe)}) |"
        )
    else:
        probability = sharpe.get("probability_true_sharpe_exceeds_target")
        sharpe_row = (
            "| Forward Sharpe | Point estimate "
            f"**{float(sharpe['annualized_point_estimate']):.2f}** against the governing target "
            f"**{target}**; probability the true Sharpe exceeds it "
            f"**{float(probability):.1%}**; status {sharpe['status']}, not a real-money result |"
        )
    readme = _replace_once(readme, r"^\| Forward Sharpe \|.*$", sharpe_row)
    readme = _replace_once(
        readme,
        r"^\| Drawdown \|.*$",
        "| Drawdown | Realized "
        f"**{_percentage(float(drawdown['realized_live_max_drawdown']), 5)}** to date against "
        f"the owner's realized bound of **{float(drawdown['realized_max_drawdown_bound']):.0%}**, "
        "descriptive only; the current-composition model estimates "
        f"**{expected_drawdown} expected / {p95_drawdown} "
        "p95**, neither established by live evidence |",
    )
    cost = evidence.get("cost_realism") or {}
    if cost.get("sleeves"):
        charged = {
            key: row
            for key, row in cost["sleeves"].items()
            if row.get("cumulative_drag_bps_of_base") is not None
        }
        drag_text = ", ".join(
            f"{key} **{float(row['cumulative_drag_bps_of_base']):.1f} bp**"
            for key, row in sorted(charged.items())
        )
        readme = _replace_once(
            readme,
            r"^\| Cost drag \|.*$",
            "| Cost drag | The evaluated curve is the "
            f"**{cost.get('curve_basis', 'live_curve').replace('_', ' ')}**: model-charged "
            "commission, spread, impact and borrow on every Alpaca fill, cumulative drag on the "
            f"base {drag_text}; latency, financing and cash yield are not charged "
            "(config/cost_realism_contract.json) |",
        )
    readme = _replace_once(
        readme,
        r"^\| Diversification \|.*$",
        "| Diversification | Research-curve average pairwise correlation "
        f"**{float(diversification['average_pairwise_correlation']):+.5f}** across "
        f"{diversification['current_sleeves']} sleeves; live-forward diversification is not "
        "established |",
    )
    readme = _replace_once(
        readme,
        r"The \d+-return record is too short,[\s\S]*?(?=Historical simulations,)",
        f"The {record['daily_return_observations']}-return record is too short, and "
        f"{provenance_sentence}\n",
    )
    return readme


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    before = README.read_text(encoding="utf-8")
    after = synchronize(evidence, before)
    if after != before:
        README.write_text(after, encoding="utf-8")
        print(f"updated {README}")
    else:
        print(f"already current: {README}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
