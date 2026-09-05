# Stablecoin par dislocations: literature and implementation boundary

**Short title:** Stablecoin par dislocations: literature

**Reviewed:** 2026-08-16  
**Family:** `stablecoin_dislocation`  
**Claim state:** economic mechanism supported; investable return untested  
**Return identities spent:** zero

## Abstract

Fiat-backed stablecoins have a two-tier market. A limited set of eligible institutions can transact
with the issuer near par, while everyone else trades in secondary markets. That segmentation can
create temporary discounts, but the discount is not a free mean-reversion signal: it prices direct
redemption access, reserve uncertainty, banking hours, transfer latency, compliance controls, chain
risk, and exchange credit and liquidity.

The only identity worth a later ALPHAC preregistration is secondary-to-primary USDC redemption by
an entity that has already proven its legal and operational ability to redeem. A candle-based rule
that buys any token below one dollar is rejected. Algorithmic, crypto-collateralized, bridged, and
wrapped tokens are separate mechanisms and cannot be pooled into this family.

## Key evidence

Ma, Zeng, and Zhang model stablecoins as a two-layer market and document that primary-market access
is concentrated. More efficient arbitrage tightens secondary prices but can accelerate redemptions
and reserve liquidation during a run. Their six-stablecoin evidence supports a limits-to-arbitrage
mechanism; it does not establish a tradeable premium for an investor without issuer access.

- [Ma, Zeng, and Zhang, *Stablecoin Runs and the Centralization of Arbitrage* (working paper)](https://bfi.uchicago.edu/wp-content/uploads/2025/06/BFI_WP_2025-76.pdf)
- [NBER working-paper record](https://www.nber.org/papers/w33882)

The Federal Reserve's granular study of the March 2023 USDC event identifies the failure of Silicon
Valley Bank and interruption of primary-market conversion over the weekend as contributors to the
secondary-market depeg. This is decisive implementation evidence: the option to redeem is
state-dependent exactly when a historical midpoint backtest would value it most.

- [Federal Reserve, *In the Shadow of Bank Runs: Lessons from the Silicon Valley Bank Failure and Its Impact on Stablecoins*](https://www.federalreserve.gov/econres/notes/feds-notes/in-the-shadow-of-bank-run-lessons-from-the-silicon-valley-bank-failure-and-its-impact-on-stablecoins-20251217.html)

Circle's current terms separate institutional Circle Mint customers from ordinary holders. Direct
redemption requires an eligible account in good standing and remains subject to law, compliance,
blocklisting, fees where applicable, and operational interruption or delay. Circle Mint is not a
bank account and balances are not government-insured. Terms observed today cannot be applied
backward; every historical test needs the version effective at each decision time.

- [Circle USDC terms](https://www.circle.com/legal/usdc-terms)
- [Circle Mint product and eligibility boundary](https://www.circle.com/circle-mint)

Tether's terms independently confirm that a nominal one-dollar redemption promise is conditional:
direct issue or redemption requires verified-customer status, pays par less applicable fees, and is
subject to issuer requirements. This supports the general segmentation mechanism, but USDT is not
silently substituted into the frozen USDC identity.

- [Tether legal terms](https://tether.to/en/legal/)
- [Tether relevant-information document](https://tether.to/public/Relevant_Information_Document_-_Tether_International%2C_S.A._de_C.V..pdf)

## Data evidence and its limits

Binance publishes checksum-addressed spot trades, aggregate trades, and candles. Coinbase exposes
historical candles but warns that intervals without ticks are absent and historical data can be
incomplete. These sources can audit timestamps, pair availability, coarse deviations, and missing
periods. They cannot reconstruct historical queue position, withdrawals, fiat conversion state,
account eligibility, or executable depth during a run.

- [Binance public-data specification](https://github.com/binance/binance-public-data/blob/master/README.md)
- [Coinbase Exchange historical-candle documentation](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)

Institutional tick trades and order-book snapshots are available from vendors such as Kaiko and
Coin Metrics. A vendor feed still needs independent venue-status, symbol, fee-tier, and revision
lineage; breadth alone does not prove execution.

- [Kaiko data dictionary](https://docs.kaiko.com/explore-our-data/data-dictionary)
- [Coin Metrics API documentation](https://docs.coinmetrics.io/api/v4/)

## Consensus and disagreement

The sources agree on three points: secondary prices can deviate from par; direct issuer access is
restricted; and arbitrage capacity weakens or changes during stress. Research disagrees less about
the existence of deviations than about whether transparency, reserve design, and arbitrage access
improve price stability at the cost of run fragility. That debate reinforces the need to model the
issuer and redemption state, not just lagged price.

## ALPHAC interpretation

The candidate is not presumed independent of the existing crypto funding sleeve. During ordinary
periods it may resemble low-volatility cash management; during crises it can become concentrated
exposure to crypto venues, banking partners, issuer reserves, and 24/7 liquidity. Full-sample linear
correlation is therefore uninformative. Any later test must report correlations and expected
shortfall conditional on crypto drawdowns, banking stress, exchange outages, weekends, and named
depeg windows.

The evidence presently supports `DATA_GATED`. It does not support a sign, entry threshold, holding
period, Sharpe ratio, or admission claim. The family remains outside the active return queue and
spends zero return hypotheses.

## Open questions

1. Can Canli Capital obtain and continuously maintain direct Circle Mint redemption eligibility in
   its legal jurisdiction and operating entity?
2. Can historical effective-dated terms, fee schedules, bank cutoffs, chain support, and conversion
   interruptions be reconstructed without hindsight?
3. Can synchronized multi-venue books and venue-status events cover every mandatory stress window?
4. Does a defined-loss or prefunded construction survive issuer, venue, banking, and chain failure,
   or is the apparent edge inseparable from unbounded principal risk?

## Rerun inputs

- workflow requested: `firecrawl-research-papers`
- collection result: Firecrawl unavailable because `FIRECRAWL_API_KEY` was not configured
- fallback: working papers, official regulator research, issuer terms, and official data docs
- inaccessible or excluded: no paywalled paper is used as sole support for a major claim
- return data opened: no
- return hypotheses spent: zero

