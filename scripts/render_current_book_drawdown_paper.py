#!/usr/bin/env python3
"""Render the current-composition drawdown paper from the study result.

Version 1.0 of docs/research/CURRENT_BOOK_DRAWDOWN_MODEL.md was typed by hand for the four-sleeve
book and kept its figures after record v4 restarted the book as three sleeves; the study result
moved and the prose did not. Every figure and every composition statement is now read from
artifacts/analysis/current_book_drawdown/result.json, so the paper changes when the study does.

    uv run python scripts/analyze_current_book_drawdown.py
    uv run python scripts/render_current_book_drawdown_paper.py
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
RESULT: Final = ROOT / "artifacts/analysis/current_book_drawdown/result.json"
PAPER: Final = ROOT / "docs/research/CURRENT_BOOK_DRAWDOWN_MODEL.md"

# Book curve keys (scripts/paper_trading_state.py: EQUITY_WF, MF_WF, VINTAGE_WF, CRYPTO_WF).
SLEEVE_NAMES: Final = {
    "k30_dn_63": "AlphaMax",
    "managed_futures": "AlphaTrend",
    "alphavintage_live": "AlphaVintage",
    "crypto_carry_wk": "AlphaForge",
}
LIMITATIONS: Final = {
    "COMMON_WINDOW_BEGINS_AFTER_COVID_AND_2022": "the common calibration window begins after COVID and 2022",
    "ABSENT_CRISIS_CANNOT_APPEAR_IN_BLOCK_BOOTSTRAP": "a block bootstrap cannot generate a crisis absent from its window",
    "REGIME_MODEL_HAS_NO_STRESS_VOLATILITY_MULTIPLIER": "the regime arm has no stress-volatility multiplier",
    "CONSTITUENT_INSTRUMENT_AND_LADDER_STATE_NOT_REPLAYED": "neither model replays constituent instruments or the drawdown ladder's state",
    "EXECUTION_GAPS_AND_LIQUIDITY_FEEDBACK_NOT_MODELED": "execution gaps and liquidity feedback are not modeled",
}
SHARE_WORDS: Final = {2: "one half", 3: "one third", 4: "one quarter", 5: "one fifth"}
NUMBER_WORDS: Final = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _whole_pct(value: float) -> str:
    text = f"{100 * value:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _count(n: int) -> str:
    return NUMBER_WORDS.get(n, str(n))


def _within(flag: bool, target: str) -> str:
    return (
        f"inside the governing {target} design objective"
        if flag
        else f"outside the governing {target} design objective"
    )


def render(result: dict[str, Any]) -> str:
    configuration = result["configuration"]
    aggregation = configuration["aggregation"]
    ladder = aggregation.get("book_level_drawdown_ladder")
    calibration = result["calibration"]
    design = result["design"]
    models = result["models"]
    objective = result["objective"]

    sleeves = list(configuration["sleeves"])
    unknown = [key for key in sleeves if key not in SLEEVE_NAMES]
    if unknown:
        raise ValueError(f"no public name for sleeve key(s): {', '.join(unknown)}")
    weights = configuration["weights"]
    names = sorted(SLEEVE_NAMES[key] for key in sleeves)
    equal = len({round(weights[key], 12) for key in sleeves}) == 1
    if equal:
        share = Fraction(weights[sleeves[0]]).limit_denominator(20)
        weight_text = f"equal weights of {SHARE_WORDS.get(share.denominator, str(share))} each"
    else:
        weight_text = "fixed weights " + ", ".join(
            f"{SLEEVE_NAMES[key]} {_whole_pct(weights[key])}" for key in sleeves
        )
    weight_lines = [
        f"- {SLEEVE_NAMES[key]} at {_whole_pct(weights[key])};"
        for key in sorted(sleeves, key=lambda k: SLEEVE_NAMES[k])
    ]
    tilt = _whole_pct(configuration["strategic_tilt_pct"])
    mix = configuration["strategic_tilt_mix"]
    mix_text = " and ".join(
        f"{_whole_pct(weight)} {asset}" for asset, weight in sorted(mix.items())
    )
    components = calibration["component_order"]
    target = _whole_pct(objective["expected_max_drawdown_target"])
    paths = f"{design['paths_per_model']:,}"
    primary = design["bootstrap_primary_block_days"]
    others = [block for block in design["bootstrap_sensitivity_block_days"] if block != primary]
    bootstrap = models["circular_moving_block_bootstrap"]
    main = bootstrap[str(primary)]
    regime = models["correlation_regime"]
    conservative = max(main["expected_max_drawdown"], regime["expected_max_drawdown"])
    if abs(conservative - objective["conservative_modeled_expected_max_drawdown"]) > 1e-12:
        raise ValueError(
            "the objective's conservative expectation is not the larger of the two model expectations"
        )
    expected_ok = objective["conservative_modeled_expected_within_target"]
    tail_ok = objective["conservative_modeled_p95_within_target"]
    verdict = (
        "Both are inside it."
        if expected_ok and tail_ok
        else "The expected result is therefore encouraging; the tail result is not."
        if expected_ok
        else "Neither is inside it."
    )
    limitations = [
        LIMITATIONS.get(code, code.lower().replace("_", " "))
        for code in result["failed_establishment_dimensions"]
    ]

    if ladder:
        ladder_line = (
            f"- the declared book-level drawdown ladder, active since {ladder['activated_on']}: half gross at "
            f"{_whole_pct(ladder['dd_half_frac'])} below the high-water mark and flat at {_whole_pct(ladder['dd_flat_frac'])}, "
            "absorbing until the owner rearms it. The models below do not replay its state;"
        )
        ladder_abstract = (
            f" It does apply the declared book-level drawdown ladder (half gross at {_whole_pct(ladder['dd_half_frac'])} "
            f"below the high-water mark, flat at {_whole_pct(ladder['dd_flat_frac'])}), active since {ladder['activated_on']}; "
            "the models do not replay the ladder's state, so they describe the book without it."
        )
    else:
        ladder_line = "- no ALPHAC-level drawdown ladder;"
        ladder_abstract = " It applies no book-level drawdown ladder."

    def arm_sentence(block: int) -> str:
        arm = bootstrap[str(block)]
        return f"the {block}-day arm gives {_pct(arm['expected_max_drawdown'])} expected / {_pct(arm['p95_max_drawdown'])} p95"

    arms = [bootstrap[str(block)] for block in design["bootstrap_sensitivity_block_days"]]
    all_expected_in = all(
        arm["expected_max_drawdown"] <= objective["expected_max_drawdown_target"] for arm in arms
    )
    all_tails_out = all(
        arm["p95_max_drawdown"] > objective["expected_max_drawdown_target"] for arm in arms
    )
    arms_summary = (
        f"All {_count(len(arms))} expected values are inside {target}; all {_count(len(arms))} tails exceed it."
        if all_expected_in and all_tails_out
        else f"Expected values inside {target}: {sum(a['expected_max_drawdown'] <= objective['expected_max_drawdown_target'] for a in arms)} of {len(arms)}; "
        f"tails inside it: {sum(a['p95_max_drawdown'] <= objective['expected_max_drawdown_target'] for a in arms)} of {len(arms)}."
    )

    def table(model: dict[str, Any]) -> str:
        return (
            "| statistic | maximum drawdown |\n|---|---:|\n"
            f"| expected | {_pct(model['expected_max_drawdown'])} |\n"
            f"| median | {_pct(model['median_max_drawdown'])} |\n"
            f"| p95 | {_pct(model['p95_max_drawdown'])} |\n"
            f"| Monte Carlo standard error of expected | {100 * model['max_drawdown_stderr']:.3f} percentage points |"
        )

    return f"""# Current-composition maximum-drawdown model

**Author:** {result["author"]}
**Affiliation:** Canli Capital / AlphaC Algorithms
**Version:** 2.0, generated from the study result
**Capital boundary:** research simulation over a paper-trading specification

## Abstract

This study estimates the two-year maximum-drawdown distribution of the current ALPHAC
composition: {_count(len(sleeves))} constituent sleeves ({_join(names)}) at {weight_text}, plus a
separately disclosed {tilt} strategic overlay ({mix_text}). Constituent strategies own their
internal sizing, and the composite applies no second book-level volatility target.{ladder_abstract}

Two zero-drift models were frozen before execution. A {paths}-path circular moving-block bootstrap
uses a {primary}-calendar-day primary block, with {_join([f"{b}-" for b in others[:-1]] + [f"{others[-1]}-day"])} sensitivity arms. A separate {paths}-path
regime model preserves observed component volatility and calm dependence while moving all {_count(len(components))}
weighted contributions to {design["regime_stress_correlation"]:.2f} stress correlation for a predeclared {_whole_pct(design["regime_stress_share"])} stress share and
{design["regime_mean_stress_run_days"]:.0f}-day mean stress run.

The conservative expected maximum drawdown is **{_pct(objective["conservative_modeled_expected_max_drawdown"])}**, {_within(expected_ok, target)}. The
conservative p95 maximum drawdown is **{_pct(objective["conservative_modeled_p95_max_drawdown"])}**, {_within(tail_ok, target)}. {verdict} Neither
establishes live expected drawdown.

Version 1.0 of this paper described the four-sleeve book that record v4 replaced (the record
restarted on 2026-09-24). From
version 2.0 every figure and composition statement here is generated from the study result by
`scripts/render_current_book_drawdown_paper.py`.

## 1. Exact specification mapped

The source builder reconstructs the same research book used by the public state:

{chr(10).join(weight_lines)}
- fixed-weight aggregation;
- no ALPHAC-level volatility target;
{ladder_line}
- missing daily constituent marks contribute zero; and
- a fixed +{tilt} strategic overlay, {mix_text}, outside constituent sizing.

The component contributions reconstruct the daily book return with a largest absolute error of
{calibration["exact_component_reconstruction_max_abs_error"]:.1e}. The study binds {len(result["source_bindings"])} input groups by SHA-256, including the live
fingerprint, the protocol, the book implementation and the sleeve-equity inputs; the full list is in
the machine artifact.

## 2. Calibration boundary

The exact common window contains {calibration["calendar_days"]:,} calendar days from {calibration["start"]} through {calibration["end"]}. In that
window the research book has {_pct(calibration["observed_book_annualized_volatility"])} annualized volatility and a {_pct(calibration["observed_book_max_drawdown"])} realized maximum
drawdown. Its {calibration["observed_book_sharpe_simulation_not_forward_evidence"]:.2f} Sharpe is labelled simulation, not forward evidence, and is not used as model
drift: every arm removes the sample mean before estimating drawdown.

This window begins after both COVID and 2022. That is a binding limitation. A block bootstrap
cannot generate a crisis absent from its source window.

## 3. Frozen models

### 3.1 Circular moving-block bootstrap

The primary {primary}-day arm produces:

{table(main)}

In the sensitivity arms, {_join([arm_sentence(b) for b in others])}. {arms_summary}

### 3.2 Correlation-regime model

The regime arm produces:

{table(regime)}

The model's simulated stress-day share is published in the machine artifact. It changes
dependence but deliberately does not invent a stress-volatility multiplier.

## 4. Decision

The protocol defines the conservative expected value as the larger of the primary bootstrap and
regime expectations. That value is {_pct(objective["conservative_modeled_expected_max_drawdown"])}, so the current-composition modeled expectation is
{"within" if expected_ok else "not within"} the {target} design objective. The mandatory p95 is {_pct(objective["conservative_modeled_p95_max_drawdown"])} and is {"" if tail_ok else "not "}within {target}.

Status:
`{result["status"]}`.

This is not statistical establishment. The live record is still short; {"; ".join(limitations[:-1])}; and {limitations[-1]}.
Those limitations are machine-readable failed establishment dimensions, not prose footnotes.

## 5. Reproduction

```text
uv run python scripts/analyze_current_book_drawdown.py
uv run python scripts/render_current_book_drawdown_paper.py
uv run python scripts/seal_forward_drawdown_evidence.py
uv run pytest -q tests/unit/test_current_book_drawdown.py tests/unit/test_forward_drawdown_evidence.py
```

Canonical machine result: `/glassbox/current_book_drawdown.json`
Sealed claim boundary: `/glassbox/forward_drawdown_evidence.json`
"""


def main() -> int:
    PAPER.write_text(render(json.loads(RESULT.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"rendered {PAPER.relative_to(ROOT)} from {RESULT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
