# Current-book drawdown study protocol

**Author:** Arhan Canli  
**Frozen:** 2026-08-23, before executing the study  
**Capital boundary:** research and paper trading only  
**Trial accounting:** existing-return risk remeasurement; zero new hypothesis identities

## Question

What two-year maximum-drawdown distribution is supported by the current ALPHAC composition: four
constituent sleeves at equal-quarter weights plus the separately disclosed 10% 50/50 BTC/SPY
overlay?

This is not the earlier fourteen-sleeve frontier question. ALPHAC compounds realized constituent
returns at its committed fixed-weight schedule and does not apply a second book-level volatility
target or drawdown ladder. Constituents retain their own sizing policies.

## Frozen inputs

- AlphaMax: `artifacts/walkforward/k30_dn_63/equity.parquet`;
- AlphaForge: `artifacts/walkforward/crypto_carry_wk/equity.parquet`;
- AlphaTrend: `artifacts/walkforward/managed_futures/equity.parquet`;
- AlphaVintage: `artifacts/probe/cpi_surprise_size/equity.parquet`;
- the market-factor definition and its BTC/SPY daily source lakes;
- `config/live_change_contract.json`; and
- the exact `combine_book` implementation used by `scripts/paper_trading_state.py`.

The study uses the common calendar-day window on which all four research curves exist. Missing
daily constituent observations follow production aggregation semantics and contribute zero.

## Frozen estimators

Every model removes the sample mean before resampling or simulation. The selected research-window
Sharpe is not borrowed as future drift to make drawdown look smaller.

### A. Circular moving-block bootstrap

- horizon: 730 calendar days;
- paths: 10,000;
- seed: 20260823;
- primary block: 63 calendar days;
- sensitivity blocks: 21 and 126 calendar days; and
- joint resampling of the already-combined daily return, preserving all dependence observed
  inside each sampled block.

The 63-day result is primary because it preserves roughly one quarter of local serial dependence;
21 and 126 expose sensitivity rather than offering an after-result choice.

### B. Correlation-regime model

- horizon: 730 calendar days;
- paths: 10,000;
- seed: 20260824;
- zero component means;
- component volatilities and calm correlation from the exact common-window weighted sleeve
  contributions plus the fixed overlay contribution;
- stress correlation: equicorrelation 0.50, matching the admission contract's permitted stressed
  pairwise ceiling;
- unconditional stress share: 12%; and
- mean stress run: 40 calendar days.

This model changes dependence but does not invent a stress-volatility multiplier. That limitation
must remain visible.

## Decision rule

Publish expected, median and p95 maximum drawdown plus Monte Carlo standard error for every arm.
The conservative modeled expectation is the larger of the primary block-bootstrap expectation and
the correlation-regime expectation. Compare it with the governing 11% expected-maximum-drawdown
objective; p95 is mandatory but is not substituted for the governing statistic.

The result cannot establish live expected maximum drawdown. The common four-sleeve window begins
after COVID and 2022, the bootstrap cannot contain a crisis absent from that window, and the regime
model does not replay each constituent's underlying instruments, execution gaps or dynamic ladder
state. Those are failed evidence dimensions, not caveats that can be averaged away.

## Prohibitions

- Do not change block lengths, seeds, horizon, path count or the selected primary arm after seeing
  results.
- Do not tune the model to cross 11%.
- Do not report either estimator as a guarantee, loss limit, funded result or statistically
  established live risk.
- Do not change allocation or live settings as part of this study.

