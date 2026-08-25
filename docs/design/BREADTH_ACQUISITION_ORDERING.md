# Breadth acquisition ordering — which data to buy first, and whether it moves the constraint

> **Historical analysis, superseded 2026-08-21.** This document diagnoses the v4 target/gate
> mismatch that led to the v6 contract. Its 2.0–2.5 target and 0.15 correlation gate are not in
> force. The governing target is forward Sharpe 1.5; v7 uses a non-positive candidate-average
> gate plus strict improvement in book-wide average correlation, while the portfolio objective is
> -0.03.

Reproducible at `scripts/analyze_breadth_acquisition.py` →
`artifacts/analysis/breadth_acquisition/result.json`. Zero hypotheses consumed, no data read,
no backtest run, ledger asserted unmoved before and after.

**Claim boundary, stated first.** This document orders work that has not been done. It contains
no measurement of any candidate's correlation, sign, or return, and nothing here is evidence that
any candidate has alpha. Every classification below is a quotation from
`config/sleeve_discovery.json` — the program's own kill criteria — not a judgement added on top.

## 1. The admission gate bars the objective it sits beside

`config/sleeve_discovery.json` declares, in one file:

- `objective.portfolio_sharpe_target` = **2.0 – 2.5**, `target_sleeve_count` = **14**
- `admission_gates.average_pairwise_correlation_max` = **0.15**

Book Sharpe is `s̄·√N_eff` with `N_eff = N/(1+(N−1)ρ̄)`. At N=14 and ρ̄ = 0.15:

| s̄ | book Sharpe | reaches 2.0? |
|---|---|---|
| 0.464 | 1.011 | no |
| 0.529 *(measured 3-sleeve)* | 1.152 | no |
| 0.700 | 1.525 | no |
| 0.800 | 1.743 | no |
| **0.900** | **1.961** | **no** |

**At the gate's own ceiling, a 14-sleeve book cannot reach 2.0 even if every sleeve had a
standalone Sharpe of 0.90** — better than anything in the book today (AlphaMax, the best, is 0.91
and its honest DSR is 0.213). A candidate can pass all 75+ evidence checks and the resulting book
still cannot reach the target.

The correction is not to loosen a bar. **It is to tighten `average_pairwise_correlation_max` from
0.15 toward 0.00** — roughly a 7x tightening. Whenever the instinct is "adjust the gates so we can
reach the target", for correlation the arithmetic points the other way, and that must be said
plainly rather than quietly accommodated.

## 2. What ρ̄ is actually required

The PSD floor on average pairwise correlation is `−1/(N−1)` = **−0.0769** at N=14. Negative ρ̄ is
therefore admissible at this count in a way it is not at 250 (floor −0.004), which is why the
"no negative ρ̄" ruling written for a 250-sleeve framing must not be reused here.

| s̄ | ρ̄ needed for 2.0 | ρ̄ needed for 2.5 |
|---|---|---|
| 0.529 (measured, 3-sleeve) | **−0.0016** | **−0.0287** |
| 0.565 (mean of 4 published standalone Sharpes) | **+0.0090** | **−0.0219** |

**The legacy snapshot used by this superseded analysis measured ρ̄ at +0.0274.** The later exact
current-composition study uses a 1,061-row common window and measures +0.0248; both miss the
-0.03 objective, and both would have failed v6's retired ≤0.00 global point gate. On the historical
snapshot, reaching the
*bottom* of the target range requires cutting current average correlation by about a third of its
value again — and reaching the top requires going negative. This is the program. Sleeve count is
not the program.

Two consequences that follow directly and are easy to get backwards:

- **"Find uncorrelated sleeves" is not sufficient.** A sleeve at ρ̄ = 0 to a positively correlated
  book does not lower its average below zero; it dilutes toward zero at best. The requirement is *anti-correlated
  or convex* return sources.
- **Quality relaxes the correlation requirement faster than count does.** Moving s̄ from 0.529 to
  0.565 moves the 2.0 requirement from −0.0016 to +0.0090 — from impossible-today to nearly
  reachable — without adding a single sleeve.

## 3. The queue, ordered

Two axes, both read from the config rather than asserted:

- **DATA** — does the candidate's own `provider_options` name a public authority (SEC EDGAR, CFTC,
  EIA, NOAA, PJM, ERCOT, US Treasury Fiscal Data, Federal Reserve, FINRA TRACE)? If so its primary
  source is free and the cost of opening it is engineering time, not a subscription.
- **RISK ITS OWN KILL NAMES** — three *different* failures, which an earlier draft of the analysis
  wrongly merged into one bucket:
  - `SLEEVE-OVERLAP` — the kill names a sleeve we actually trade. **This is the ρ̄ risk.**
  - `TAIL` — the kill worries about crisis behaviour. This is the *stressed*-correlation risk: the
    sleeve may decorrelate on average and fail in exactly the episode diversification exists for.
  - `GENERIC-FACTOR` — the kill says it may reduce to beta, seasonality, quality or momentum. That
    is an *alpha* risk, not a correlation risk.

| candidate | data | risk its own kill names | hyp |
|---|---|---|---|
| credit_equity_relative_value | PUBLIC | GENERIC-FACTOR | 3 |
| electricity_load_weather_spread | PUBLIC | GENERIC-FACTOR | 2 |
| merger_arbitrage | PUBLIC | TAIL | 2 |
| pre_fomc_announcement_drift | PUBLIC | TAIL | 1 |
| active_ownership_escalation | PUBLIC | SLEEVE-OVERLAP | 2 |
| cftc_hedging_pressure | PUBLIC | SLEEVE-OVERLAP | 1 |
| repurchase_issuance_flow | PUBLIC | SLEEVE-OVERLAP | 1 |
| treasury_auction_concession | PUBLIC | SLEEVE-OVERLAP | 1 |
| earnings_narrative_change | PUBLIC | SLEEVE-OVERLAP | 2 *(return-killed)* |
| index_reconstitution_flow | INSTITUTIONAL | none named | 2 |
| securities_lending_supply | INSTITUTIONAL | none named | 2 |
| options_dispersion | INSTITUTIONAL | TAIL | 3 |
| analyst_revision_drift | INSTITUTIONAL | SLEEVE-OVERLAP | 2 |

**Nine of thirteen candidates have a free primary source.** Only four require an institutional
subscription, and two of those (`analyst_revision_drift`, `options_dispersion`) say in their own
feasibility notes that free history is insufficient — `options_dispersion` is explicitly
`INSTITUTIONAL_HISTORY_NOT_CONFIGURED` and needs 15 years where the available free history starts
2024-02.

### The honest tension in this table

The only two candidates whose kill criteria name **no diversification risk at all** —
`index_reconstitution_flow` and `securities_lending_supply` — are both institutional. The cleanest
prospective diversifiers are the ones that cost money. That is not a reason to skip them; it is a
reason to state the trade rather than let "9 of 13 are free" imply the free ones are equivalent.

Against that: four public-source candidates carry no SLEEVE-OVERLAP risk
(`credit_equity_relative_value`, `electricity_load_weather_spread`, `merger_arbitrage`,
`pre_fomc_announcement_drift`), and `electricity_load_weather_spread` is the only mechanism in the
entire queue whose driver is **physical rather than financial** — weather and grid load do not
know what equities did. Its `source_collection_complete` is currently `false`.

## 4. Two independent blockers, and neither is code

1. **Trial budget.** `config/trial_accounting.json` — 162 hypothesis identities against a 160
   budget, `research_status = PAUSED_BUDGET_REVIEW`. No new return identity may be registered.
   The active queue's declared budget is 24 hypotheses and every one is allocated. At the measured
   6.5% hit rate, ten new sleeves implies on the order of 150 trials, and each one raises the
   deflation hurdle for the four sleeves already in the book. **Owner decision, by the program's
   own rule.**
2. **Data.** Eleven of thirteen candidates are data-gated. Nine of those gates open with
   engineering time against public authorities; four need a subscription.

These are independent. Opening the data without the budget produces candidates that cannot be
registered; opening the budget without the data produces trials with nothing to run.

## 5. What this does not settle

Nothing here measures a correlation. The ordering is a prior over *which work to do*, derived from
the program's own declared mechanisms and kill conditions. The admission sequence is unchanged: a
candidate still earns its place only by clearing every gate on evidence, and `sleeve_discovery.json`
is right that "a target never creates a sleeve."
