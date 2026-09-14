# AlphaTrend retained-candidate validation

**Passed the fixed doubled-cost test; retain for further research, not admission.** The candidate remains better than the stressed baseline, but performance is uneven across eras and incremental exposure-adjusted evidence is uncertain.

## Full engine cost stress

The protocol fixed exactly one scenario before the replays: double commission (1 to 2 bp), halfspread (3 to 6 bp), latency (2 to 4 bp), square-root impact coefficient (1 to 2) and modeled annual borrow (50 to 100 bp). Financing stays zero. The actual engine recalculated orders, sizes, equity, risk state and fills using the original sealed forecasts, universe and settings. This is not a fixed-position cash haircut or a cost-threshold search.

| Metric | Original baseline | Original candidate | 2x-cost baseline | 2x-cost candidate |
| --- | ---: | ---: | ---: | ---: |
| Net Sharpe | 0.327 | 0.677 | 0.150 | 0.542 |
| CAGR | 1.11% | 2.63% | 0.45% | 2.07% |
| Maximum drawdown | 10.24% | 9.63% | 12.35% | 10.50% |
| Annual turnover | 9.691 | 8.605 | 9.681 | 8.601 |

All six predeclared stress checks passed: higher candidate Sharpe and CAGR, no worse drawdown, lower turnover, and positive candidate Sharpe and CAGR. Drawdown nevertheless increased relative to the candidate at original costs. This single modeled scenario does not establish capacity, a maximum affordable fee level or robustness to missing borrow.

The baseline stress identity `6f5e71ec657beef2` was ordinal 233; the candidate stress identity `4d7793cfffb17091` was ordinal 234. Each was registered before its returns, recorded with the complete cost settings and closed with explicit admission limitations. The full experiment union is now **234**, including every earlier rejected construction.

## Exposure and uncertainty

The original candidate increased average marked net exposure from 15.86% to 39.01%, while average gross exposure stayed about 94.77%. Net exposure across this multi-asset ETF basket is not the same thing as equity-market beta.

The fixed descriptive regression uses raw daily strategy returns against SPY, IEF, GLD and UUP close returns plus an intercept. It uses 4,900 complete observations from March 5, 2007 to August 24, 2026; 290 earlier observations are unavailable because of factor coverage. No forward fill is used. Standard errors use Bartlett Newey-West with 21 lags and an n/(n-k) adjustment.

| Proxy coefficient | Baseline | Candidate | Candidate minus baseline |
| --- | ---: | ---: | ---: |
| SPY | -0.0905 | -0.0670 | 0.0235 |
| IEF | 0.0226 | 0.0346 | 0.0121 |
| GLD | 0.0302 | 0.0551 | 0.0249 |
| UUP | 0.0604 | 0.0599 | -0.0004 |

The incremental regression intercept is **0.59% annualized**, with a descriptive 95% interval of **-0.75% to 1.94%**. It does not establish positive incremental alpha after these exposure controls. This is a raw-return, arithmetic annualization, not CAGR or an excess-return alpha; the proxy model is incomplete and cannot causally separate timing skill from market exposures.

The paired 63-session block bootstrap puts the original Sharpe difference in **[0.028, 0.592]** at the descriptive 95% level (2,000 draws, fixed seed). This uses the same inspected sample and is not adjusted for the complete research selection history. It is not an admission significance test.

| Original-cost era | Baseline Sharpe | Candidate Sharpe |
| --- | ---: | ---: |
| 2006-2012 | 0.139 | 0.619 |
| 2013-2019 | 0.487 | 0.351 |
| 2020-2026 | 0.339 | 0.705 |

The candidate improved in 2006-2012 and 2020-2026 but underperformed in 2013-2019. These fixed era diagnostics share the same inspected history and are not independent tests.

## Calendar correction and verification

The first exposure diagnostic incorrectly mapped closes to the next UTC midnight. The engine instead maps each close to the next exchange-session open timestamp, including weekends and holidays. The original regression is discarded and preserved as `exposure_results.json`; all conclusions here use `exposure_results_corrected.json`. The hash-bound amendment was recorded before the corrected calculation. Factors, lag count, era splits and stress scenario were unchanged. Cost replays were unaffected.

Both stress input snapshots verified, and their forecast frames match the corresponding parent frames exactly. Recorded cost settings equal the actual resolved engine settings. Reservation, immutable ledger, packet and source hashes were checked. Completing evidence accounting does not mean admission evidence is complete.

## What remains before promotion

Keep the candidate frozen. The next phase is independent/prospective validation with properly timed prices and borrow evidence, plus portfolio-level overlap analysis against qualified complementary sleeves. No new thresholds, leverage changes or asset deletions are justified by this check. Cost stress and an in-sample regression do not supply that missing evidence. The strategy is not promoted and does not increase the independent sleeve count.

The fixed historical ETF basket, retrospective adjustments, modeled borrow, absent capacity study and absence of untouched performance remain limits. No data were purchased, orders sent, public artifacts published or production profiles changed. Sharpe near 2 with 14+ independent sleeves remains a portfolio research target, not an achieved result.

![Validation charts](validation.png)

[Frozen protocol](protocol.json) · [Cost results](cost_robustness.json) · [Corrected exposure results](exposure_results_corrected.json) · [Calendar amendment](exposure_calendar_amendment.json)
