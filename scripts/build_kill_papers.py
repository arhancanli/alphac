"""Render one research paper per killed candidate, with every figure taken from the artifact.

WHY THESE ARE THE PAPERS WORTH PUBLISHING. Forty-six candidates have been killed and three have
survived. Almost nobody publishes the forty-six. A kill log is a table of names and numbers; a
paper says what the idea was, why it was worth the trial, and what specifically ended it -- which
is the part another researcher can actually use, and the part that cannot be faked.

⚠️ TRACEABLE IS NOT THE SAME AS HONEST. The guard below checks that every number in a paper comes
FROM the artifact. It cannot check that the number means what the column header says. Four probes
carried a hand-written 0.0 in a slot typed `float`, because "not separately measured" was
unsayable there -- and this generator faithfully rendered that sentinel as "Screen net Sharpe
0.0000", four decimals of precision nobody measured, in a table beside prose saying the candidate
screened at 1.47. The slot is `float | None` now, and a bare 0.0 in it is refused outright.

THE HONESTY CONSTRUCTION. Prose is written by hand. Every NUMBER is injected from the kill-log
entry through `_figure`, which reads the field and formats it, and is recorded as it goes. No
figure is ever typed into a template. `tests/unit/test_kill_papers_quote_their_artifact.py`
re-derives the set of numbers in each rendered paper and fails if any of them is absent from its
source entry -- so a hand-edited number cannot survive, which is the exact failure that put
withdrawn AlphaVintage figures on the site for six days.
"""

from __future__ import annotations

from typing import Any

__all__ = ["kill_paper_filename", "render_kill_paper", "render_kill_papers"]

# Hand-written framing: what the idea was and why it earned a trial. One per family, because the
# economic argument is a property of the family, not of the individual configuration.
_FAMILY_FRAMING: dict[str, str] = {
    "equity_quality": (
        "Quality investing is the claim that profitable, stable, low-accrual businesses earn "
        "more than their risk explains. It is among the best-documented anomalies in the "
        "literature and among the most heavily traded, which is exactly why it deserved a test "
        "on a survivorship-free universe with costs charged rather than assumed away. A premium "
        "that survives in a paper and dies in a fill is not a premium."
    ),
    "equity_value": (
        "Value is the oldest documented cross-sectional effect in equities and the one most "
        "likely to be already in the price. The question was never whether cheap stocks have "
        "outperformed at some point in history; it is whether a mechanical, point-in-time "
        "implementation still clears its own trading costs on a universe that includes the "
        "companies that went to zero."
    ),
    "equity_momentum": (
        "Cross-sectional momentum is the anomaly this book already trades, so a second "
        "momentum construction had to clear a harder bar than a novel idea: it must add "
        "something the existing sleeve does not already capture. A variant that merely "
        "re-expresses the same signal buys correlation, not breadth."
    ),
    "equity_momentum_variant": (
        "This tested one specific construction choice inside the momentum family. Construction "
        "variants are the cheapest possible trials and therefore the most dangerous: they are "
        "easy to generate in bulk, they are highly correlated with each other and with the "
        "sleeve already deployed, and every one of them raises the deflation hurdle for the "
        "whole book. The prior was that it would fail, and it was pre-registered anyway so the "
        "failure would be recorded rather than quietly abandoned."
    ),
    "equity_low_risk": (
        "The low-volatility effect is the observation that low-beta stocks have historically "
        "delivered better risk-adjusted returns than their beta predicts, usually explained by "
        "leverage constraints among institutional investors. It is a crowded trade and a "
        "structurally levered one, which makes the cost and financing assumptions load-bearing "
        "rather than incidental."
    ),
    "crypto_low_risk": (
        "The equity low-risk effect does not automatically transfer to crypto: the leverage "
        "constraint that is usually invoked to explain it barely binds in a market where "
        "retail can access high leverage directly. Testing it here was a test of the "
        "EXPLANATION, not only of the pattern, which is why a null is informative rather than "
        "merely disappointing."
    ),
}

_STAGE_FRAMING: dict[str, str] = {
    "screen_prototype": (
        "This died at the screen stage, before a full walk-forward was ever run. Screening "
        "exists so that ideas which cannot clear a coarse, cost-aware bar do not consume the "
        "far more expensive machinery behind it. A screen kill is a cheap kill, and it is "
        "published for the same reason as an expensive one: the trial was still spent, and it "
        "still raises the evidence bar for everything already in the book."
    ),
    "research_gauntlet": (
        "This ran the full pre-registered research gauntlet: a locked configuration, "
        "point-in-time data, costs charged, and pass/fail criteria fixed in writing before the "
        "result existed. Nothing about the specification was changed after the number arrived. "
        "That discipline is what makes the null trustworthy, and it is also what makes it "
        "final -- there is no version of this candidate that was 'nearly' admitted."
    ),
    "deployed_gauntlet": (
        "This one reached deployment before it was killed, which makes it the most expensive "
        "kind of kill and the most important to publish in full. A candidate that passed on the "
        "evidence available at the time and failed on better evidence later is not a process "
        "failure to be hidden; refusing to withdraw it would be."
    ),
}

_DEFAULT_FRAMING = (
    "This candidate was pre-registered, tested once on a locked configuration, and killed. It "
    "was never re-tuned and re-run: a configuration that is adjusted until it passes has not "
    "been tested, it has been fitted."
)

_BOUNDARY = (
    "## What this does and does not say\n\n"
    "It says this configuration, on this data, net of the costs we charge, did not clear the "
    "bar it pre-registered. It does not say the underlying economic effect does not exist, that "
    "no implementation of it works, or that someone with different data or different execution "
    "would reach the same conclusion. A null is evidence about a test, not a proof about a "
    "market.\n\n"
    "It also does not say the trial was free. Every hypothesis tested raises the deflated-Sharpe "
    "hurdle for every sleeve already in the book, including the ones that survived. That is why "
    "the kill count is published beside the survivor count rather than behind it."
)


def _figure(entry: dict[str, Any], field: str, fmt: str, quoted: list[str]) -> str:
    """Format one figure FROM the entry and record it. The only path a number may take."""
    value = entry.get(field)
    if value is None:
        return "not separately measured"
    rendered = format(value, fmt) if isinstance(value, (int, float)) else str(value)
    quoted.append(rendered)
    return rendered


def kill_paper_filename(entry: dict[str, Any]) -> str:
    return f"kill-{str(entry['name']).replace('_', '-')}.md"


def render_kill_paper(entry: dict[str, Any]) -> tuple[str, list[str]]:
    """Return the paper's markdown and the list of figures injected into it."""
    quoted: list[str] = []
    name = str(entry.get("readable_name") or entry["name"])
    framing = _FAMILY_FRAMING.get(str(entry.get("type", "")))
    if framing is None:
        framing = _STAGE_FRAMING.get(str(entry.get("stage", ""))) or _DEFAULT_FRAMING

    rows: list[tuple[str, str]] = []
    if "sharpe" in entry:
        rows.append(("Net Sharpe", _figure(entry, "sharpe", ".4f", quoted)))
    if "screen_net_sharpe" in entry:
        rows.append(("Screen net Sharpe", _figure(entry, "screen_net_sharpe", ".4f", quoted)))
    for label, field, fmt in (
        ("Annualized return", "cagr_pct", ".2f"),
        ("Total return", "return_pct", ".2f"),
        ("Annualized volatility", "vol_ann_pct", ".2f"),
        ("Maximum drawdown", "max_drawdown_pct", ".2f"),
        ("Annualized turnover", "turnover_ann", ".2f"),
        ("Trading days", "n_days", "d"),
        ("Final equity (USD)", "final_equity_usd", ",.2f"),
        ("Fees paid (USD)", "fees_paid_usd", ",.2f"),
        ("Funding, net (USD)", "funding_net_usd", ",.2f"),
    ):
        if field in entry:
            suffix = "%" if fmt == ".2f" and field.endswith("_pct") else ""
            rows.append((label, _figure(entry, field, fmt, quoted) + suffix))

    window = ""
    if entry.get("start_date") and entry.get("end_date"):
        start = _figure(entry, "start_date", "", quoted)
        end = _figure(entry, "end_date", "", quoted)
        window = f"\n**Test window:** {start} to {end}  "

    table = "\n".join(f"| {label} | {value} |" for label, value in rows)
    verdict = _figure(entry, "verdict", "", quoted)
    stage = str(entry.get("stage", "") or "").replace("_", " ")

    reason = str(
        entry.get("reason")
        or "No reason was recorded, which is itself a defect in the record."
    )

    # THE SPECIFIC FINDING LEADS. The family framing is shared by every candidate in a family, so
    # putting it first made all 32 screen-stage papers open with the same paragraph -- and the
    # site's description extractor takes the first prose paragraph, which gave 32 pages an
    # identical meta description. Duplicate descriptions are worth nothing in a search result and
    # less than nothing to a reader, who learns what this candidate was only after a paragraph
    # that could have been about any of them.
    body = f"""# {name}: a killed candidate

**Verdict:** {verdict}  {f"**Stage:** {stage}  " if stage else ""}{window}
**Identity:** `{entry["name"]}`

{reason}

## Why it was worth testing

{framing}

## The result

| Measure | Value |
|---|---|
{table}

{_BOUNDARY}
"""
    return body, quoted


def render_kill_papers(kill_log: dict[str, Any]) -> dict[str, str]:
    """Return {filename: markdown} for every killed candidate in the log."""
    entries = list(kill_log.get("killed_strategies", [])) + list(
        kill_log.get("screen_stage_kills", [])
    )
    papers: dict[str, str] = {}
    for entry in entries:
        markdown, _quoted = render_kill_paper(entry)
        papers[kill_paper_filename(entry)] = markdown
    return papers
