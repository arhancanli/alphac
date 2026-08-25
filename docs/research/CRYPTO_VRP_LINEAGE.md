# Crypto volatility risk premium: one proxy trial and a published null

**Short title:** AlphaForge crypto VRP proxy lineage  
**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `crypto_volatility_risk_premium`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

AlphaForge tested one preregistered BTC/ETH volatility-risk-premium timing rule from 2021-03-24
through 2026-06-01. It compared Deribit DVOL closes with a seven-day Yang–Zhang realized-
volatility estimate, entered only when the spread exceeded two volatility points, charged 10 basis
points on signal turnover, and evaluated 1,492 expanding-window out-of-sample days after a
365-day warmup. The proxy produced annualized Sharpe -0.633, Deflated Sharpe Ratio 0.000, PSR
0.066, skew -9.517, and raw kurtosis 132.65. It failed.

The diagnostic also illustrates why average variance premium is not timing alpha. BTC's mean
DVOL-minus-realized spread was +0.044 and positive on 72.99% of days; an always-short variance
proxy showed Sharpe 2.4818 but skew -5.4874. ETH's corresponding always-short proxy showed Sharpe
0.5309 and skew -10.6795. Those attractive averages coexist with catastrophic left tails. This
family is not a sleeve, is not in an Alpaca account, and has no broker-reconciled forward record.

## Claim boundary

This paper establishes the economic question, exact historical proxy, one charged identity,
persisted null, and source hashes. It does **not** establish executable option P&L, option-surface
history, capacity, live execution, expected maximum drawdown, forward Sharpe, or future return.
DVOL is an index and the variance-swap expression is a signal-validity proxy. It omits the option
strip, tradable quotes and sizes, strike interpolation, margin, hedging, jumps, and gap execution.

## Mechanism and falsifiable hypothesis

Option-implied variance can exceed subsequently realized variance because sellers of convex
downside insurance require compensation. Carr and Wu formalize model-free variance-swap rates and
document variance risk premia ([Review of Financial Studies](https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057)).
That literature is a prior, not validation of AlphaForge's data, timing rule, or execution.

The tested hypothesis was narrower: a large positive difference between DVOL and recent realized
volatility should identify days when short-variance compensation exceeds crash and trading costs.
The hypothesis is falsified if the preregistered timing return is negative, remains deeply
left-skewed, or fails selection adjustment. All three occurred.

For currency `i` and day `t`, the implementation was:

```text
VRP(i,t)      = DVOL(i,t) - YangZhangRV_7d(i,t)
signal(i,t)   = max(0, VRP(i,t) - 0.02)
gross(i,t+1)  = DVOL(i,t)^2 / 365 - log_return(i,t+1)^2
proxy_return  = signal(i,t) * gross(i,t+1) - 0.001 * abs(change(signal))
```

DVOL was stamped available after its source bar; realized volatility used only contemporaneously
available OHLC. BTC and ETH proxy returns were equal weighted, normalized by a one-day-lagged
expanding standard deviation, and scored only after the warmup. The direction was never inverted
after seeing the result.

## Complete trial accounting

The union contains exactly one identity in `crypto_volatility_risk_premium`:

| Hypothesis key | Configuration hash | Observations | Sharpe | DSR | Decision |
|---|---|---:|---:|---:|---|
| `bd4688c240711a16` | `99596bbb5b6f8e38` | 1,492 | -0.633 | 0.000 | fail |

The run originally used a global trial count of 84. The current union contains 228 identities;
the historical DSR cannot be reconstructed honestly from rounded summary statistics alone and is
therefore labeled artifact-era evidence, not a current-union restatement. The identity remains
charged to the union regardless of its failure.

## Result and risk interpretation

| Measure | Persisted value |
|---|---:|
| Annualized net proxy Sharpe | -0.633 |
| Artifact-era DSR / PSR | 0.000 / 0.066 |
| Skew | -9.517 |
| Raw kurtosis | 132.65 |
| OOS observations | 1,492 days |

No maximum drawdown was persisted for this summary-only proxy, so none is invented here. The
extreme skew and kurtosis are more decision-relevant than the appealing always-short average.
Timing failed to transform the premium into admissible expected return.

The historical proxy likely understates implementation difficulty. DVOL and seven-day realized
volatility do not share a perfectly matched horizon; a variance-swap formula is not a fillable
option strip; and the 10-basis-point signal-turnover charge is not a full options execution,
hedging, and margin model. These limitations weaken positive claims. They do not rehabilitate a
negative result.

## Capacity, overlap, and sleeve decision

No options capacity sweep exists. There is no historical bid/ask surface, quote size, portfolio
margin replay, delta-hedging ledger, or broker-reconciled forward option record. Capacity is
**unmeasured**.

Short volatility is also not presumed diversifying. It can load on the same crash, liquidity, and
deleveraging states that hurt carry and risky-asset trend books. The artifact left correlation
against live sleeves pending; no independence claim is made.

**Decision: FAIL / RESEARCH ONLY.** Do not admit a VRP sleeve. A future return identity would need
a separately preregistered, point-in-time options-surface implementation with executable quotes,
defined-loss construction, hedging and margin costs, capacity, current-union deflation, and
forward broker reconciliation. It would be a new charged trial, not a revision of this null.

## Reproduction and authorship

- `scripts/exp2_crypto_vrp.py`: frozen proxy construction and original measurement driver.
- `artifacts/exp2/20260625T094710Z/exp2_metrics.json`: persisted historical report.
- `scripts/audit_crypto_vrp_family.py`: deterministic ledger-to-report audit.
- `artifacts/research/crypto_vrp_family.json`: generated family evidence packet.
- [`/glassbox/crypto_vrp_family.json`](/glassbox/crypto_vrp_family.json): public machine packet.
- [`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json): global identity
  join and remaining identity-level packet debt.

Reproduction requires the pinned AlphaForge environment and underlying Binance/Deribit data lake.
The public packet exposes exact configuration, immutable keys, source paths, and SHA-256 hashes so
that missing private market data is disclosed rather than confused with public byte reproducibility.

This research record and its ALPHAC implementation were authored and directed by **Arhan Canli**,
Founder of Canli Capital. Authorship does not convert an internal result into peer review or
independent verification.

## Conclusion

The contribution is the rejection, not a strategy claim. A positive average crypto variance
premium and a high naive Sharpe did not survive timing, costs, tail-risk inspection, or deflation.
The honest sleeve count contributed by this family is zero.
