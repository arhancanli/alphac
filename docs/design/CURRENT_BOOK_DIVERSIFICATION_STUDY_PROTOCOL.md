# Current-book diversification study protocol

**Owner and author:** Arhan Canli  
**Frozen:** 2026-08-23  
**Classification:** retrospective existing-return risk remeasurement; zero new hypothesis identities

## Question

How diversified is the exact current four-sleeve ALPHAC research specification, how uncertain is
its average pairwise correlation, and which current sleeves improved or reduced the historical
common-window book Sharpe?

This is not a blind preregistration. The sleeve curves and earlier point-correlation summaries were
already visible before this protocol was written. The protocol therefore cannot establish a new
return edge or turn an in-sample relationship into forward evidence.

## Frozen inputs and composition

Use the same four blessed sleeve equity inputs, common calendar window, fixed 25% sleeve weights,
zero-on-missing-mark aggregation and separate 10% BTC/SPY strategic overlay used by
`scripts/analyze_current_book_drawdown.py`. Fail if the current live-configuration fingerprint,
aggregation policy, sleeve order, weight vector, overlay or exact component reconstruction differs
from the sealed current-book drawdown study.

The four sleeve return series—not the strategic overlay—define sleeve pairwise correlation. The
overlay is reported separately and remains in full-book Sharpe and marginal-Sharpe calculations.

## Measurements

Report:

1. the full four-by-four sleeve correlation matrix and all six pairwise values;
2. average pairwise sleeve correlation;
3. the maximum ordinary pairwise correlation;
4. a 95% upper confidence bound for the average and for every pair;
5. diversification ratio for the equal-quarter sleeve allocation before the overlay;
6. correlation-matrix participation ratio as an effective-independent-sleeve diagnostic;
7. the full exact-composition historical Sharpe, labelled research simulation only; and
8. each sleeve's marginal historical book-Sharpe delta when that sleeve is replaced by cash while
   all other committed sleeve weights and the strategic overlay remain unchanged.

Marginal deltas are diagnostics, not reweighting instructions. No sleeve is removed, resized or
admitted from this study.

## Confidence procedure

Use a synchronized circular moving-block bootstrap over the four sleeve return columns so every
resample preserves contemporaneous cross-sleeve dependence. Run 10,000 resamples with seed
`20260825`. The primary block length is 63 calendar rows; sensitivity block lengths are 21 and 126.
Each resample has the same 1,061-row length as the observed common window. The one-sided 95% upper
bound is the empirical 95th percentile. Report Monte Carlo standard errors for average-correlation
means and upper quantiles.

## Governing comparisons

Read every threshold from `config/sleeve_admission_contract.json`:

- minimum correlation observations: 504;
- average pairwise point gate: at most 0.00;
- average pairwise upper-95 gate: at most 0.10;
- ordinary pairwise point gate: at most 0.35;
- ordinary pairwise upper-95 gate: at most 0.35; and
- stressed pairwise ceiling: 0.50.

The stressed value is a design comparison imported from the current drawdown regime model, not an
observed crisis estimate. Existing sleeves predate the prospective admission contract, so a failed
comparison is a disclosed portfolio objective gap, not a retroactive sleeve-admission verdict.

## Establishment boundary

The study never establishes live-forward diversification because its common window is the frozen
research corpus ending 2026-06-01, not the broker-reconciled forward record beginning 2026-08-07.
It also lacks a human-independent replication and crisis-complete forward observations. The output
must list these failed establishment dimensions and must never convert diversification into proof
of alpha or the 1.5 forward-Sharpe objective.
