# Current-book diversification: the confidence-bound result

**Author:** Arhan Canli  
**Program:** ALPHAC / AlphaC Algorithms  
**Study classification:** retrospective existing-return risk remeasurement  
**Capital:** research simulation over a paper-trading specification

## Result

The exact current four-sleeve research specification is diversified, but it does **not** meet the
program's governing average-correlation point gate. Across the 1,061-row common window from
2023-07-07 through 2026-06-01:

| Measurement | Result | Governing comparison | Outcome |
|---|---:|---:|---|
| Average pairwise sleeve correlation | +0.0248 | at most 0.00 | **fails** |
| 95% upper bound, 63-row block bootstrap | +0.0487 | at most +0.10 | passes |
| Maximum ordinary pairwise correlation | +0.2098 | at most +0.35 | passes |
| Maximum ordinary pair upper 95% bound | +0.3025 | at most +0.35 | passes |
| Stressed design correlation | +0.50 | at most +0.50 | passes at the boundary |
| Sleeve-only diversification ratio | 1.8153 | diagnostic | not a gate |
| Effective independent sleeves | 3.8988 of 4 | diagnostic | not a gate |

The long-run portfolio objective is approximately −0.03 average correlation. The current measured
point is 0.0548 above it. Calling +0.0248 “near zero” may be descriptively reasonable, but it does
not turn a positive value into a pass against a non-positive gate.

## What was measured

The study reconstructs the same exact current book used by the current-composition drawdown study:

- `alphavintage_live`, 25%;
- `crypto_carry_wk`, 25%;
- `k30_dn_63`, 25%;
- `managed_futures`, 25%; and
- the separately disclosed 10% strategic overlay split between BTC and SPY.

Sleeve correlation uses the four sleeve returns only. The strategic overlay remains separate and
is included in full-book and marginal-Sharpe diagnostics. The reconstructed sleeve contributions
plus overlay equal the book return with zero numerical residual.

## Confidence procedure

The primary uncertainty estimate uses 10,000 synchronized circular moving-block resamples, each as
long as the observed 1,061-row window, with seed `20260825` and a 63-row block. Resampling the four
columns together preserves contemporaneous cross-sleeve dependence. The one-sided upper bound is
the empirical 95th percentile.

| Block length | Bootstrap mean average correlation | Upper 95% | Maximum pair upper 95% |
|---:|---:|---:|---:|
| 21 rows | +0.0245 | +0.0484 | +0.2861 |
| 63 rows, primary | +0.0247 | +0.0487 | +0.3025 |
| 126 rows | +0.0244 | +0.0491 | +0.3086 |

The primary upper-bound Monte Carlo standard error is approximately 0.00030. Block-length
sensitivity does not change the conclusion: the point gate fails and the confidence-bound gates
pass.

## Pairwise structure

The six observed pairwise correlations are:

| Pair | Correlation |
|---|---:|
| AlphaVintage / crypto carry | +0.0393 |
| AlphaVintage / equity momentum | −0.0620 |
| AlphaVintage / managed futures | −0.0444 |
| Crypto carry / equity momentum | −0.0134 |
| Crypto carry / managed futures | +0.0197 |
| Equity momentum / managed futures | +0.2098 |

The equity-momentum / managed-futures pair is the largest ordinary dependence. Its primary
bootstrap upper bound remains below the prospective 0.35 ordinary-pair ceiling.

## Marginal historical diagnostics

For each diagnostic, one sleeve's committed contribution is replaced by cash while every other
weight and the strategic overlay remain unchanged. These are in-window research diagnostics, not
reweighting instructions:

| Sleeve replaced by cash | Full-book research Sharpe | Without sleeve | Marginal delta |
|---|---:|---:|---:|
| AlphaVintage | 1.7846 | 1.7909 | −0.0063 |
| Crypto carry | 1.7846 | 1.2520 | +0.5326 |
| Equity momentum | 1.7846 | 1.6378 | +0.1468 |
| Managed futures | 1.7846 | 1.8755 | −0.0908 |

Negative historical marginal values do not authorize deletion. The data were known before this
protocol, the comparison is in-sample for this purpose, and existing sleeves predate the
prospective admission contract. Any allocation change would require a new declared evidence epoch.

## What this establishes—and what it does not

This study establishes a reproducible description of the exact current research composition. It
shows that most pairwise and confidence-bound controls are inside their prospective ceilings, while
the governing average-correlation point gate is not.

It does not establish live-forward diversification. The frozen research curves end before the
broker-reconciled forward record begins; the returns were known before the protocol; no independent
human replication exists; and the window is not crisis-complete. It proves neither alpha nor the
1.5 forward-Sharpe objective and spends zero new hypothesis identities.

## Reproduction

```bash
uv run python scripts/analyze_current_book_diversification.py
```

The machine-readable result is
`artifacts/analysis/current_book_diversification/result.json`. Its content hash is
`sha256:42971513076f2ff21024e343c2ef771a78cbaeb2b3b6160f7d28a526dd4da256`.
