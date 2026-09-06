# ALPHAC literature frontier — 2026-08-16

Status: literature and data-feasibility screen only. No return series was opened and no
return identity was spent. The purpose is to find mechanisms that are economically distinct
from the current four sleeves: equity momentum, managed-futures trend, funding carry, and
point-in-time CPI surprise.

## Decision summary

Three candidates enter key-free feasibility:

1. **Treasury auction concession.** Repeated, scheduled balance-sheet demand around US
   Treasury coupon auctions; public auction lineage is available from Treasury. The primary
   falsification sample begins after the 2013 publication of the main study.
2. **CFTC hedging pressure.** Cross-sectional commodity risk transfer measured from reports
   that describe Tuesday positions but are released Friday. Any test must trade only after
   release and residualize both trend and futures-curve carry.
3. **Pre-FOMC announcement drift.** One replication identity only, with the post-2015
   publication period as the primary sample and the published disappearing-effect evidence
   treated as a reason to expect a kill, not as a footnote.

Four attractive themes remain deferred rather than promoted:

- **Closed-end-fund discount mean reversion:** mechanism is plausible, but historical,
  point-in-time NAV and distribution treatment need a feasibility audit before returns.
- **Corporate-bond ETF dislocation:** potentially episodic and diversifying, but executable
  NAV timing, stale bond marks, creation/redemption access, and crisis costs are load-bearing.
- **Catastrophe bonds:** strong diversification case, but indices and investable instruments
  are not adequate substitutes for executable security-level history.
- **Carbon allowances and freight derivatives:** economically distinct, but historical bid/ask,
  rolls, venue access, and contract-level data are commercial and currently unqualified.

Customer-supplier propagation and downside variance-premium research stay inside the existing
earnings-narrative and options workstreams, respectively; listing them as fresh sleeves would
double-count families already in the queue.

## Admission logic

Literature strength alone cannot admit a sleeve. Every promoted idea still needs immutable
point-in-time lineage, one locked return identity, realistic execution, capacity, deflated
Sharpe, PBO, ordinary and stressed correlations, and leave-one-year-out book contribution.
At publication, the portfolio Sharpe objective was 2.0–2.5; it was not evidence and could not
lower those gates. That target was withdrawn on 2026-08-21. The governing objective is now an
honest forward Sharpe of 1.5, with a 2.25–3.0 in-sample support band after the disclosed haircut;
it likewise is not admission evidence.

### Treasury auction concession

- Mechanism is scheduled inventory absorption, not trend or a static duration premium.
- Free source: the [US Treasury Fiscal Data Auctions Query API](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query).
- Optional conditioning data: the [New York Fed primary-dealer time-series catalogue](https://markets.newyorkfed.org/api/pd/list/timeseries.json).
- Main prior: Lou, Yan, and Zhang, [“Anticipated and Repeated Shocks in Liquid Markets”](https://doi.org/10.1093/rfs/hht034).
- Supporting market-structure prior: [“Trading Ahead of Treasury Auctions”](https://doi.org/10.2139/ssrn.2789988).
- Broader seasonality warning: [“Seasonal Variation in Treasury Returns”](https://doi.org/10.1561/104.00000021).
- Required falsification: post-publication performance, duration-beta hedge, reopenings versus
  new issues, auction-size conditioning, one-tick cost stress, and exclusion of unscheduled
  calendar changes.

### CFTC hedging pressure

- Mechanism is compensation for absorbing commercial net supply, not price continuation.
- Free source: [CFTC historical compressed Commitment of Traders files](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm).
- Main prior: Basu and Miffre, [“Capturing the risk premium of commodity futures: The role of hedging pressure”](https://doi.org/10.1016/j.jbankfin.2013.02.031).
- Fundamental context: Gorton, Hayashi, and Rouwenhorst, [“The Fundamentals of Commodity Futures Returns”](https://doi.org/10.3386/w13249).
- Replication-risk context: [“The predictive performance of commodity futures risk factors”](https://doi.org/10.1016/j.jbankfin.2016.06.011).
- Required falsification: Tuesday-observation/Friday-release lag, fixed contract map, revised
  report handling, trend and curve-carry residualization, limits, roll costs, and crisis spreads.

### Pre-FOMC announcement drift

- Free source: the Federal Reserve’s [FOMC calendars and historical materials](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).
- Original prior: Lucca and Moench, [“The Pre-FOMC Announcement Drift”](https://doi.org/10.1111/jofi.12196).
- Contrarian prior: [“The Disappearing Pre-FOMC Announcement Drift”](https://doi.org/10.2139/ssrn.3134546).
- Required falsification: post-2015 sample first, exact event-time bars, schedule revisions,
  overnight decomposition, ordinary beta control, spread/slippage stress, and announcement-gap
  tail loss. A weak post-publication result is a kill; there is no alternate window rescue.

## Deferred themes and why

### Closed-end-fund discounts

The literature directly studies mean reversion, but a tradable result requires the NAV that was
actually published at each decision time, not a restated series.

- [“Evidence on the Mean-Reverting Tendencies of Closed-End Fund Discounts”](https://doi.org/10.1111/1540-6288.00046)
- [“Mean-reversion in closed-end fund discount: evidence from half-life”](https://doi.org/10.1080/00036846.2013.791019)
- [“Noise Trading, Costly Arbitrage, and Asset Prices: Evidence from Closed-end Funds”](https://doi.org/10.1111/1540-6261.00506)
- Official holdings/NAV lineage starting point: [SEC Form N-PORT data sets](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets)

### Corporate-bond ETF dislocation

This may be a liquidity-provision sleeve rather than a credit-beta sleeve, but reported NAV can
inherit stale underlying marks and ordinary investors cannot assume authorized-participant
creation/redemption economics.

- [“Impacts of the Fed Corporate Credit Facilities through the Lenses of ETFs and CDX”](https://doi.org/10.21033/wp-2020-14)
- [“When Selling Becomes Viral: Disruptions in Debt Markets in the COVID-19 Crisis and the Fed’s Response”](https://doi.org/10.1093/rfs/hhaa145)
- [“Exchange Traded Funds (ETFs)”](https://doi.org/10.3386/w22829)

### Catastrophe bonds

The diversification evidence is relevant, but an index return is not an executable portfolio
and trigger/event modeling cannot be reconstructed from a retail ETF proxy.

- [“Diversification through Catastrophe Bonds: Lessons from the Subprime Financial Crisis”](https://doi.org/10.1057/gpp.2014.14)
- Chicago Fed primer, [“Catastrophe bonds: A primer and retrospective”](https://doi.org/10.21033/cfl-2018-405)
- [“The risk implications of insurance securitization: The case of catastrophe bonds”](https://doi.org/10.1016/j.jcorpfin.2014.01.004)

### Carbon allowances and freight derivatives

Both are structurally attractive because their physical and regulatory state variables differ
from the current book. Neither enters the active queue until contract-level history and venue
access are shown executable.

- [“Convenience Yields for CO2 Emission Allowance Futures Contracts”](https://doi.org/10.2139/ssrn.2894390)
- [“The Relationship between Spot and Futures CO2 Emission Allowance Prices in the EU ETS”](https://doi.org/10.7551/mitpress/9780262029285.003.0008)
- [“Liquidity effects and FFA returns in the international shipping derivatives market”](https://doi.org/10.1016/j.tre.2015.02.001)
- [“Economic information transmissions and liquidity between shipping markets: New evidence from freight derivatives”](https://doi.org/10.1016/j.tre.2016.12.007)

## Adjacent evidence, not new queue entries

- Customer/supplier propagation: Cohen and Frazzini, “Customer Momentum,” and
  [“Input Specificity and the Propagation of Idiosyncratic Shocks in Production Networks”](https://doi.org/10.1093/qje/qjw018). This belongs in the equity narrative/network family and
  requires point-in-time relationship data.
- Option downside compensation: [“Downside Variance Risk Premium”](https://doi.org/10.17016/feds.2015.020),
  [“The VIX Premium”](https://doi.org/10.1093/rfs/hhy062), and
  [“Option Return Predictability”](https://doi.org/10.1093/rfs/hhab067). These refine the existing
  options-dispersion/tail-budget program rather than create a cosmetically separate sleeve.

## Open questions

1. Does Treasury auction concession survive after publication and after hedging the exact
   duration exposure of each auction bucket?
2. Can CFTC legacy and disaggregated taxonomies be mapped without a hindsight bridge, and does
   hedging pressure survive trend/carry residualization?
3. Is any pre-FOMC premium left after publication, spread costs, and exact timing, or is the
   disappearing-effect paper the final answer?
4. Can closed-end-fund NAV publication timestamps be reconstructed deeply enough to justify a
   single return identity?
5. Which deferred market offers executable data before it offers an attractive backtest?

## Rerun inputs

- workflow requested: exhaustive deep research
- collection fallback: Crossref, OpenAlex, Semantic Scholar metadata, DOI landing pages, and
  official regulator APIs because Firecrawl credentials were not configured
- query families: Treasury auctions, dealer capacity, FOMC drift and decay, CFTC hedging
  pressure, commodity risk factors, closed-end-fund discounts, bond ETF dislocations,
  catastrophe bonds, carbon convenience yield, freight derivatives, production networks, and
  variance risk premia
- output: this Markdown review plus governed candidate entries in
  `config/sleeve_discovery.json`
