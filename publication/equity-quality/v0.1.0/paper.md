# Equity fundamental quality: 11 identities and no validated sleeve

**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `equity_fundamental_quality`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

ALPHAC recorded 11 distinct equity-quality return identities spanning gross profitability,
operating margin, return on equity, a quality composite, and a growth/profitability/earnings
quality composite. Immutable annualized Sharpe measurements range from -0.8316 to +0.7643. Nine
of 11 are negative. The two positives are both operating-margin variants over the shortest
2022–2026 history; the same signal over 2000–2026 is -0.4174. No family-wide persisted curves,
drawdowns, DSR values, capacity sweep, or broker-reconciled forward record survive for these
identities. The correct status is research-only, not a validated sleeve.

## Mechanism, literature, and overlap

Quality factors hypothesize that profitable, conservatively financed businesses earn returns not
fully explained by market beta, or that investors underweight persistent operating strength.
Novy-Marx's gross-profitability evidence provides an important prior
([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2013.01.003)). The Fama–French
five-factor model incorporates operating profitability and investment
([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2014.10.010)). Neither source
validates ALPHAC's point-in-time joins, universe, costs, or implementation.

Quality can overlap value, investment, momentum, sector structure, and defensive equity exposure.
The taxonomy assigns mixed price-momentum configurations to AlphaMax before fundamental labels;
the 11 rows here are therefore the quality-only family boundary, not every run containing a quality
feature. One family can contribute at most one independent sleeve.

## Complete trial lineage

| Signal group | Identities | Persisted Sharpe evidence |
|---|---:|---|
| `eq_gross_profitability` | 3 | -0.8214 to -0.2635 |
| `eq_operating_margin` | 3 | -0.4174 to +0.7643 |
| `eq_quality_composite` | 3 | -0.8316 to -0.5926 |
| `eq_qual_gpe` | 1 | -0.5856 |
| `eq_roe` | 1 | -0.7289 |
| **Total** | **11** | **2 positive; 9 negative** |

The machine packet publishes each exact hypothesis key, config hash, configuration, immutable
ledger source and source hash, observation count, Sharpe, skew, and kurtosis. History varies from
728 to 5,384 observations. That variation is material: the strongest result has only 728
observations and does not replicate in the longer operating-margin identity.

Several long-history measurements have implausibly extreme higher moments, including skew below
-24 and kurtosis above 969. Those values are evidence of unresolved return/data construction or
tail behavior, not performance achievements. Without the original curves, they cannot be repaired
or reinterpreted into credible drawdown and DSR estimates.

## Evidence boundary and decision

All 11 rows currently have immutable-ledger-summary evidence only. The audit deliberately reports
maximum drawdown and artifact-era DSR as missing. A Sharpe point estimate, even +0.7643, cannot pass
selection adjustment, tail-risk, capacity, diversification, or execution gates by itself.

There is no family capacity sweep, no admissible forward configuration, no Alpaca paper sleeve,
and no live return attributed to fundamental quality. Existing AlphaMax performance is momentum
performance and must not be relabeled as quality.

**Decision: NOT ESTABLISHED / RESEARCH ONLY.** Zero sleeves. A future quality candidate requires a
single preregistered formula, point-in-time fundamental availability, survivorship-inclusive issuer
lineage, persisted daily curves, costs and borrow, current-union deflation, capacity, crisis
correlation, and broker-reconciled forward evidence.

## Reproduction and credit

- `docs/design/PREREG_FUNDAMENTAL_SINGLES.md`: historical family specification.
- `scripts/audit_equity_fundamental_families.py`: deterministic taxonomy and ledger audit.
- [`/glassbox/equity_quality_family.json`](/glassbox/equity_quality_family.json): machine packet.
- [`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json): global union and
  remaining identity-packet debt.

The evidence and ALPHAC implementation were authored and directed by **Arhan Canli**, Founder of
Canli Capital. Explicit authorship does not imply peer review or independent verification.
