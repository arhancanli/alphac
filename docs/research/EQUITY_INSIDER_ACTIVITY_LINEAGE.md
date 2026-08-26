# Clustered insider purchases: a corrected preregistered null

**Short title:** Clustered insider purchases  
**Author:** Arhan Canli, Founder and Quantitative Researcher, Canli Capital  
**Family key:** `equity_insider_activity` · **System:** ALPHAC / AlphaForge  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

This record examines whether clustered open-market purchases by corporate insiders predict
issuer returns after a realistic filing delay. Two immutable identities are charged because the
return aggregation was corrected before publication. The preliminary implementation produced
annualized Sharpe -0.9931; the corrected first measurement produced -0.2433 over 2,669
observations. A later replay on an advanced input snapshot measured Sharpe -0.2315 over 2,674
observations, Newey-West t-statistic -0.7490, DSR 1.83e-7, and maximum drawdown 24.84%. The strategy
had low correlation with the existing book but reduced observed book Sharpe at a 10% weight. Six
of twelve preregistered research checks passed. The verdict is KILL and the family contributes
zero sleeves.

## Mechanism and timing question

Purchases by officers and directors can reveal information about valuation, operating conditions,
or managerial confidence. A cluster may be more informative than one transaction because several
decision makers commit personal capital independently. Lakonishok and Lee study the information
content of insider trading
([Review of Financial Studies](https://doi.org/10.1093/rfs/14.1.79)).

The empirical question is narrower than that prior. It asks whether a public investor could trade
a specified Form 4 cluster after allowing for filing and implementation delay, then earn a
beta-hedged net return. Results depend on transaction coding, amendments, issuer identity, the
public timestamp, survivorship controls, and whether the portfolio weights simple returns
correctly. A favorable literature result does not validate any of those details.

## Frozen probe

The preregistered cluster requires at least two insiders purchasing within 30 days and at least
$100,000 of aggregate value. The position is held for 63 sessions after a two-session filing delay.
Issuer exposure is equal-notional at gross one and is hedged using trailing 252-session SPY beta,
clamped between zero and three. One-way costs are 6 basis points for the issuer leg and 1 basis
point for SPY. The out-of-sample period begins in 2016.

One configuration was tested, so PBO is not defined inside the probe. Both recorded
implementations remain charged to the global trial union.

## Correction and immutable trial accounting

The preliminary implementation linearly combined adjusted log returns. The canonical curve and
cost contracts require weighted simple returns. The correction changed implementation, not the
economic parameters, and retained the same KILL verdict. It was assigned a distinct auditable
configuration rather than overwriting the first result.

| Identity | Implementation state | Observations | Sharpe | Skew | Kurtosis |
|---|---|---:|---:|---:|---:|
| `7c522581b35475e3` | Preliminary log-return aggregation | 2,669 | -0.9931 | -0.3088 | 16.4671 |
| `d614fdc1daa2906c` | Corrected simple-return aggregation | 2,669 | -0.2433 | 0.2909 | 17.1010 |

The large change in Sharpe shows why the correction matters. Preserving both identities prevents
an implementation fix from silently erasing the research path.

## Corrected replay result

The later replay contains five additional observations from an advanced data lake. It is an
out-of-sample extension, not an exact reproduction of the immutable first measurement.

| Measure | Value |
|---|---:|
| Net annualized Sharpe | -0.2315 |
| Newey-West t-statistic | -0.7490 |
| Probabilistic Sharpe ratio | 0.2260 |
| Deflated Sharpe ratio, 228-trial union | 1.83e-7 |
| Maximum drawdown | 24.84% |
| Annualized turnover | 2.91x |
| Net Sharpe at twice costs | -0.2850 |
| Realized SPY beta | 0.0455 |

The return remains negative after correction and at twice costs. The low realized market beta
shows that broad equity exposure is not an adequate explanation for the failure.

## Diversification, capacity, and decision gates

Average ordinary correlation with the four comparison sleeves was -0.0655; the largest ordinary
pair was 0.0570 and the largest stressed pair was 0.1414. These are favorable overlap statistics.
At a 10% test weight, however, observed common-window book Sharpe fell from 1.2236 to 1.1301, a
change of -0.0934. Every leave-one-year-out change from 2023 through 2026 was negative.

The fifth-percentile proxy capacity at 1% of ADV was $5.31 million, which passed the probe floor.
This is model evidence, not a capacity certification. Capacity and diversification cannot admit a
strategy with negative standalone return and an adverse observed portfolio contribution.

Six of twelve preregistered research checks passed. Beta, correlation, mean-zero portfolio delta,
and proxy capacity checks passed; minimum Sharpe, DSR, Newey-West significance, twice-cost Sharpe,
observed book contribution, and leave-one-year-out stability did not. The machine verdict is
`KILL`.

## Reproduction and claim boundary

The current-snapshot command is:

```text
uv run python scripts/probe_insider_clusters.py
```

The preregistration, input manifest, runner, environment lock, and admission contract are
SHA-256-bound. Because the current snapshot contains five more observations, this command audits
the unchanged corrected implementation but does not recreate the exact first curve. There is no
broker-reconciled forward record and no Alpaca return attributed to this family.

[`equity_insider_family.json`](/glassbox/equity_insider_family.json) preserves both immutable
identities; the related probe result preserves the corrected extension and explicit reproduction
boundary.

**Decision: FAIL / zero sleeves.** The correction improved the estimate but did not create a
positive result. Research, correction governance, and implementation were directed by
**Arhan Canli**.
