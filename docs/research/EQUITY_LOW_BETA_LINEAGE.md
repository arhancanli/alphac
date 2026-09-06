# Equity low beta: two negative identities and no defensive sleeve

**Short title:** Equity low beta  
**Author:** Arhan Canli, Founder and Quantitative Researcher, Canli Capital  
**Family key:** `equity_low_beta` · **System:** ALPHAC / AlphaForge  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

Two historical identities test a 252-session equity beta rank. The implemented portfolio seeks a
long-low-beta, short-high-beta spread under rank allocation. The shorter configuration reports
annualized Sharpe -0.5995 over 728 observations. A deep-history configuration reports -0.0679 over
5,384 observations, with skew 8.2898 and kurtosis 311.7071. Neither estimate supports a defensive
sleeve. The extreme higher moments in the longer summary also make a curve-level audit mandatory;
they are not treated as evidence of an attractive positive tail. Exact curves, maximum drawdown,
current-union DSR, capacity, and forward execution are not established. The family contributes
zero sleeves.

## Hypothesis and economic prior

The low-beta hypothesis asks whether equities with low trailing exposure to the market earn a
better risk-adjusted return than high-beta equities after portfolio scaling and implementation
costs. Frazzini and Pedersen connect a betting-against-beta premium to leverage constraints:
investors unable or unwilling to lever low-risk assets may overpay for high-beta securities
([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2013.10.005)).

That mechanism does not imply that every beta-ranked long-short portfolio should work. Results can
depend on beta estimation, volatility scaling, financing, short availability, sector composition,
microcaps, delistings, corporate actions, and the universe definition. A low-beta rank can also
overlap quality, profitability, size, and market-timing exposures. ALPHAC therefore treats the two
rows as implementations of one defensive family, not separate sleeves.

## Recorded designs

Both identities use signal `eq_bab_252`, rank allocation, 252 training bars, 63 test bars, and a
10-basis-point no-trade band. They differ in historical scope and rebalance cadence.

| Identity | Recorded start | Rebalance | Configured IDs | Observations | Sharpe | Skew | Kurtosis |
|---|---|---:|---:|---:|---:|---:|---:|
| `1db3096d8f18eef5` | 2022-07-01 | 21 bars | 375 | 728 | -0.5995 | 0.2439 | 6.8348 |
| `6c08c11a04ef43c5` | 2000-01-01 | 63 bars | 6,880 | 5,384 | -0.0679 | 8.2898 | 311.7071 |

The configured identifier count is a lineage field, not a claim that every identifier was
simultaneously eligible or traded. Point-in-time membership and exact position histories require
the missing curve-level packet.

The shorter result is plainly negative. The longer result is closer to zero, but its extreme skew
and kurtosis show that the annualized Sharpe is not a sufficient description. A small number of
large observations, stale prices, corporate-action discontinuities, changing universe coverage,
or genuine jump returns could generate such moments. The summary cannot adjudicate among those
possibilities.

## Why the longer sample does not rescue the signal

A longer date range increases chronology, not automatically identification. The deep-history
configuration changes the available universe and rebalance cadence alongside the sample period.
It is therefore not a clean extension of the 375-identifier test. Comparing -0.5995 with -0.0679
does not isolate a time effect, a breadth effect, or a cadence effect.

The extreme moments also prevent a conventional Gaussian interpretation of Sharpe uncertainty.
Without daily returns, block dependence, event concentration, and drawdown cannot be measured.
No DSR is reconstructed from summary moments, and no favorable sign is inferred from the positive
skew. A strategy can have rare positive jumps and still be unusable or incorrectly measured.

## Execution and portfolio boundary

The family packet does not establish borrow availability, short rebates, financing, market impact,
turnover, or capacity. Those omissions are especially material for the high-beta short leg, where
borrow and distress risk can be concentrated. There is also no identity-matched portfolio
correlation study. Conceptual distinctness from AlphaMax momentum or equity quality is not measured
diversification.

No broker-reconciled forward record exists for either identity. No AlphaMax return, Alpaca paper
return, or other sleeve result is relabeled as low beta.

## Reproduction path and next valid test

[`equity_low_beta_family.json`](/glassbox/equity_low_beta_family.json) binds the two hypothesis
keys, config hashes, signal names, first ledger summaries, and immutable ledger hash. It also marks
maximum drawdown, capacity, and broker-forward evidence as unestablished.

A valid new study would freeze one point-in-time equity universe, define the beta estimator and
missing-data rules, retain exact daily positions and returns, model borrow and financing, test
corporate-action integrity, and preregister the decision thresholds before inspecting results. It
would be a new charged identity, not a repair of either historical row.

**Decision: FAIL / zero sleeves.** Both recorded implementations are non-positive and the longer
one contains unresolved extreme moments. Research and implementation were directed by
**Arhan Canli**.
