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


def _percentage(value: float, places: int) -> str:
    rendered = f"{value:.{places}%}"
    return rendered.replace("-", chr(0x2212))


def synchronize(evidence: dict[str, Any], readme: str) -> str:
    record = evidence["record"]
    drawdown = evidence["drawdown_evidence"]
    diversification = evidence["diversification_evidence"]
    snapshot_date = str(evidence["generated_at"])[:10]
    provenance_passes = bool(evidence["provenance_gate"]["passes"])
    provenance_summary = (
        "provenance currently passes the publication gate"
        if provenance_passes
        else "provenance currently fails closed on incomplete crypto position attribution"
    )
    provenance_sentence = (
        "its provenance gate currently passes."
        if provenance_passes
        else (
            "its provenance gate remains closed until crypto position attribution is deployed "
            "and verified."
        )
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
        f"**{_percentage(float(record['cumulative_return']), 5)}**; {provenance_summary} |",
    )
    readme = _replace_once(
        readme,
        r"^\| Drawdown \|.*$",
        "| Drawdown | Realized "
        f"**{_percentage(float(drawdown['realized_live_max_drawdown']), 5)}** to date, "
        "descriptive only; the current-composition model estimates "
        f"**{expected_drawdown} expected / {p95_drawdown} "
        "p95**, neither established by live evidence |",
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
