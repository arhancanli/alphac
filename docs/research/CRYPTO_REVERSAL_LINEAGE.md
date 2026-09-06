# Crypto short-horizon reversal: two decisive negative trials

**Short title:** Crypto residual reversal  
**Author:** Arhan Canli, Founder and Quantitative Researcher, Canli Capital  
**Family key:** `crypto_short_horizon_reversal` · **System:** ALPHAC / AlphaForge  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

Two historical identities test whether crypto perpetual-futures returns reverse after common
movement is removed. One uses a 24-hour residual signal; the other combines 24- and 72-hour
residuals. Both are strongly negative in the implemented direction. Their immutable annualized
Sharpe summaries are -2.1527 and -2.1140 across 1,574 observations. The result rejects the tested
reversal rule, but it does not automatically establish the opposite momentum trade. Exact curves,
maximum drawdowns, costs, funding attribution, and current-union DSR are not preserved at the
family level. The family contributes zero sleeves and remains in the trial union as a negative
result.

## Hypothesis and estimand

Residual reversal asks whether an asset-specific price move over a short horizon predicts an
opposite-signed subsequent return. The intended estimand is the net return to a rank portfolio
that is long recent residual losers and short recent residual winners, measured out of sample
under the recorded rebalance and portfolio rules.

Short-term reversal has precedent in conventional equities. Lehmann documents weekly return
reversals and considers whether they reflect market inefficiency or compensation for risk
([Journal of Finance](https://doi.org/10.1111/j.1540-6261.1990.tb05110.x)). That literature is a
prior, not a transport theorem. Crypto trades continuously; perpetual funding transfers value
between long and short positions; liquidations can create directional cascades; and venue-specific
microstructure can dominate a short-horizon signal. A residual estimated from historical returns
does not remove these channels.

## Frozen configurations

Both identities use rank allocation, a 24-bar rebalance interval, a 10-basis-point no-trade band,
a 6,048-bar training window, a 1,512-bar test window, and the same 58-instrument configuration
universe. This common construction makes the two rows related specifications of one mechanism.

| Identity | Signal set | Observations | Sharpe | Skew | Kurtosis |
|---|---|---:|---:|---:|---:|
| `7d65785e1ea4789e` | `mr_res_24` | 1,574 | -2.1527 | -0.0875 | 7.0956 |
| `9d39062d6525fdbb` | `mr_res_24`, `mr_res_72` | 1,574 | -2.1140 | -0.6294 | 8.8195 |

Adding the 72-hour component does not rescue the hypothesis. It changes the shape of the negative
return distribution, including more negative skew and higher kurtosis, while leaving the central
conclusion intact. Both identities are charged. Rounded similarity is not used to erase one trial,
and the horizon blend is not relabeled as a separate sleeve.

## Interpretation of the negative sign

A strongly negative reversal return is compatible with several explanations: short-horizon
continuation may dominate; residualization may remove the wrong common component; funding or
turnover may overwhelm gross mean reversion; or the universe and rebalance design may expose
liquidation trends rather than temporary dislocations. The summaries cannot distinguish among
these explanations.

Multiplying the return by minus one would create a new, selected momentum hypothesis. It would
need a new preregistration, config hash, trial charge, cost model, and out-of-sample test. The
negative result therefore remains a falsification of reversal, not evidence for an untested
opposite trade.

## Statistical and execution boundary

Only immutable first-summary moments are bound family-wide. The exact daily curves are not
available in this packet, so maximum drawdown, autocorrelation, clustered uncertainty, funding
exposure, and event concentration cannot be reconstructed. No artifact-era DSR survives for
either identity, and no current-union DSR is estimated from incomplete moments. Capacity is also
unmeasured. A 24-bar rebalance schedule could create substantial turnover and market impact, but
the family record does not contain enough execution detail to quantify them.

There is no broker-reconciled forward record and no Alpaca return attributed to this family. The
absence of forward evidence does not weaken the historical rejection. It limits the explanations
that can be defended.

## Reproduction and decision

[`crypto_reversal_family.json`](/glassbox/crypto_reversal_family.json) publishes the hypothesis
keys, configuration hashes, recorded signal sets, result moments, immutable ledger hash, and
evidence grade. [`trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json) keeps both
identities in the full research accounting.

**Decision: FAIL / zero sleeves.** The implemented residual-reversal direction failed twice. A
future study may test a different residual model or a separately preregistered continuation rule,
but it cannot rewrite these observations. The research and decision record were directed by
**Arhan Canli**.
