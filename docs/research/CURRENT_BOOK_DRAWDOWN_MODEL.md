# Current-composition maximum-drawdown model

**Author:** Arhan Canli
**Affiliation:** Canli Capital / AlphaC Algorithms
**Version:** 2.0, generated from the study result
**Capital boundary:** research simulation over a paper-trading specification

## Abstract

This study estimates the two-year maximum-drawdown distribution of the current ALPHAC
composition: three constituent sleeves (AlphaMax, AlphaTrend and AlphaVintage) at equal weights of one third each, plus a
separately disclosed 10% strategic overlay (50% BTC and 50% SPY). Constituent strategies own their
internal sizing, and the composite applies no second book-level volatility target. It does apply the declared book-level drawdown ladder (half gross at 5% below the high-water mark, flat at 10%), active since 2026-09-15; the models do not replay the ladder's state, so they describe the book without it.

Two zero-drift models were frozen before execution. A 10,000-path circular moving-block bootstrap
uses a 63-calendar-day primary block, with 21- and 126-day sensitivity arms. A separate 10,000-path
regime model preserves observed component volatility and calm dependence while moving all four
weighted contributions to 0.50 stress correlation for a predeclared 12% stress share and
40-day mean stress run.

The conservative expected maximum drawdown is **8.99%**, inside the governing 11% design objective. The
conservative p95 maximum drawdown is **15.86%**, outside the governing 11% design objective. The expected result is therefore encouraging; the tail result is not. Neither
establishes live expected drawdown.

Version 1.0 of this paper described the four-sleeve book that record v4 replaced (the record
restarted on 2026-09-24). From
version 2.0 every figure and composition statement here is generated from the study result by
`scripts/render_current_book_drawdown_paper.py`.

## 1. Exact specification mapped

The source builder reconstructs the same research book used by the public state:

- AlphaMax at 33.3%;
- AlphaTrend at 33.3%;
- AlphaVintage at 33.3%;
- fixed-weight aggregation;
- no ALPHAC-level volatility target;
- the declared book-level drawdown ladder, active since 2026-09-15: half gross at 5% below the high-water mark and flat at 10%, absorbing until the owner rearms it. The models below do not replay its state;
- missing daily constituent marks contribute zero; and
- a fixed +10% strategic overlay, 50% BTC and 50% SPY, outside constituent sizing.

The component contributions reconstruct the daily book return with a largest absolute error of
1.7e-18. The study binds 8 input groups by SHA-256, including the live
fingerprint, the protocol, the book implementation and the sleeve-equity inputs; the full list is in
the machine artifact.

## 2. Calibration boundary

The exact common window contains 1,061 calendar days from 2023-07-07 through 2026-06-01. In that
window the research book has 5.11% annualized volatility and a 4.63% realized maximum
drawdown. Its 1.17 Sharpe is labelled simulation, not forward evidence, and is not used as model
drift: every arm removes the sample mean before estimating drawdown.

This window begins after both COVID and 2022. That is a binding limitation. A block bootstrap
cannot generate a crisis absent from its source window.

## 3. Frozen models

### 3.1 Circular moving-block bootstrap

The primary 63-day arm produces:

| statistic | maximum drawdown |
|---|---:|
| expected | 8.79% |
| median | 8.19% |
| p95 | 15.47% |
| Monte Carlo standard error of expected | 0.035 percentage points |

In the sensitivity arms, the 21-day arm gives 8.45% expected / 14.89% p95 and the 126-day arm gives 8.62% expected / 14.36% p95. All three expected values are inside 11%; all three tails exceed it.

### 3.2 Correlation-regime model

The regime arm produces:

| statistic | maximum drawdown |
|---|---:|
| expected | 8.99% |
| median | 8.35% |
| p95 | 15.86% |
| Monte Carlo standard error of expected | 0.036 percentage points |

The model's simulated stress-day share is published in the machine artifact. It changes
dependence but deliberately does not invent a stress-volatility multiplier.

## 4. Decision

The protocol defines the conservative expected value as the larger of the primary bootstrap and
regime expectations. That value is 8.99%, so the current-composition modeled expectation is
within the 11% design objective. The mandatory p95 is 15.86% and is not within 11%.

Status:
`CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_HISTORICAL_TAIL_COVERAGE_INCOMPLETE`.

This is not statistical establishment. The live record is still short; the common calibration window begins after COVID and 2022; a block bootstrap cannot generate a crisis absent from its window; the regime arm has no stress-volatility multiplier; neither model replays constituent instruments or the drawdown ladder's state; and execution gaps and liquidity feedback are not modeled.
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
