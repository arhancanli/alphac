# Current-composition maximum-drawdown model

**Author:** Arhan Canli  
**Affiliation:** Canli Capital / AlphaC Algorithms  
**Version:** 1.0, 2026  
**Capital boundary:** research simulation over a paper-trading specification

## Abstract

This study estimates the two-year maximum-drawdown distribution of the current ALPHAC
composition: four constituent sleeves at equal-quarter weights plus a separately disclosed 10%
50/50 BTC/SPY strategic overlay. It corrects a category error in the earlier frontier study. The
15% volatility target belongs to constituent `BlendStrategy` instances; the ALPHAC composite
applies no second book-level volatility target or drawdown ladder.

Two zero-drift models were frozen before execution. A 10,000-path circular moving-block bootstrap
uses a 63-calendar-day primary block, with 21- and 126-day sensitivity arms. A separate 10,000-path
regime model preserves observed component volatility and calm dependence while moving all five
weighted contributions to 0.50 stress correlation for a predeclared 12% stress share and 40-day
mean stress run.

The conservative expected maximum drawdown is **9.32%**, inside the governing 11% design
objective. The conservative p95 maximum drawdown is **16.45%**, outside 11%. The expected result is
therefore encouraging; the tail result is not. Neither establishes live expected drawdown.

## 1. Exact specification mapped

The source builder reconstructs the same research book used by the public state:

- AlphaMax, AlphaForge, AlphaTrend and AlphaVintage at 25% each;
- fixed-weight aggregation;
- no ALPHAC-level volatility target;
- no ALPHAC-level drawdown ladder;
- missing daily constituent marks contribute zero; and
- a fixed +10% strategic overlay, 50% BTC and 50% SPY, outside constituent sizing.

The component contributions reconstruct the daily book return with zero numerical residual. The
study binds the live fingerprint, contracts, protocol, book implementation, market-factor
implementation, four sleeve-equity inputs and the market-factor source corpus by SHA-256.

## 2. Calibration boundary

The exact common window contains 1,061 calendar days from 2023-07-07 through 2026-06-01. In that
window the research book has 5.21% annualized volatility and a 4.51% realized maximum drawdown. Its
1.78 Sharpe is labelled simulation, not forward evidence, and is not used as model drift: every
arm removes the sample mean before estimating drawdown.

This window begins after both COVID and 2022. That is a binding limitation. A block bootstrap
cannot generate a crisis absent from its source window.

## 3. Frozen models

### 3.1 Circular moving-block bootstrap

The primary 63-day arm produces:

| statistic | maximum drawdown |
|---|---:|
| expected | 7.83% |
| median | 7.35% |
| p95 | 13.35% |
| Monte Carlo standard error of expected | 0.029 percentage points |

The 21-day sensitivity arm gives 7.96% expected / 14.11% p95. The 126-day arm gives 7.41%
expected / 12.15% p95. All three expected values are inside 11%; all three tails exceed it.

### 3.2 Correlation-regime model

The regime arm produces:

| statistic | maximum drawdown |
|---|---:|
| expected | 9.32% |
| median | 8.59% |
| p95 | 16.45% |
| Monte Carlo standard error of expected | 0.038 percentage points |

The model's simulated stress-day share is published in the machine artifact. It changes
dependence but deliberately does not invent a stress-volatility multiplier.

## 4. Decision

The protocol defines the conservative expected value as the larger of the primary bootstrap and
regime expectations. That value is 9.32%, so the current-composition modeled expectation is within
the 11% design objective. The mandatory p95 is 16.45% and is not within 11%.

Status:
`CURRENT_COMPOSITION_EXPECTED_WITHIN_OBJECTIVE_HISTORICAL_TAIL_COVERAGE_INCOMPLETE`.

This is not statistical establishment. The live record is still short, the common calibration
window omits major crises, the regime arm has no stress-volatility multiplier, and neither model
replays constituent instruments, execution gaps, liquidity feedback or dynamic ladder state.
Those limitations are machine-readable failed establishment dimensions, not prose footnotes.

## 5. Reproduction

```text
uv run python scripts/analyze_current_book_drawdown.py
uv run python scripts/seal_forward_drawdown_evidence.py
uv run pytest -q tests/unit/test_current_book_drawdown.py tests/unit/test_forward_drawdown_evidence.py
```

Canonical machine result: `/glassbox/current_book_drawdown.json`  
Sealed claim boundary: `/glassbox/forward_drawdown_evidence.json`

