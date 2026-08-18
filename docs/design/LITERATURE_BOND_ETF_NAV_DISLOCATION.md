# Bond-ETF NAV dislocation — literature and mechanism review

**Reviewed:** 2026-08-16. **Stage:** source review only. No market observations, returns, signs,
thresholds, horizons, or portfolio statistics were inspected.

## Mechanism under review

Corporate-bond ETFs can trade away from their reported net asset value because ETF shares trade
continuously while many underlying bonds trade infrequently and are valued using evaluated marks.
The creation/redemption mechanism is also not a frictionless full-holdings arbitrage: bond ETF
baskets can be fractional, change through time, and differ systematically between creations and
redemptions. Liquidity and dealer balance-sheet constraints can therefore permit persistent
price/NAV gaps.

That observation does not establish a secondary-market alpha. A discount may mean the ETF is
discovering the value of stale underlying marks rather than that the ETF is mispriced. Authorized
participants have creation/redemption access and basket information that an ordinary brokerage
account does not. ALPHAC must not label a long/short ETF trade as AP arbitrage or assume convergence
to an accounting NAV is executable.

## Adversarial evidence

- Federal Reserve research finds ETF arbitrage efficacy depends on liquidity, with stronger and
  more persistent effects for less-liquid bond ETFs.
- BIS work documents fractional and high-turnover bond baskets and links persistent premiums and
  discounts partly to slow NAV adjustment to ETF prices.
- The March 2020 episode is not clean proof of ETF underpricing: bond ETF prices could incorporate
  information faster than stale constituent marks.
- Public iNAV/indicative values are not necessarily real-time executable portfolio values and may
  reuse stale evaluated prices.

## Source implications

A credible historical test needs synchronized point-in-time records for ETF NBBO/trades, official
NAV and publication time, holdings and creation/redemption baskets, bond identifiers and corporate
actions, underlying TRACE trades, executable spread/impact estimates, and valuation timestamps.
Daily premium/discount data alone cannot identify which side of the gap contains the information.

FINRA offers transaction-level historical TRACE data with execution time, price, size, and yield,
but historical products require agreements and fees. Rule 6c-11 requires recent daily ETF website
disclosures and a chart for the most recently completed calendar year/current quarters; it does not
create a free permanent ten-year archive.

## Primary sources

- Federal Reserve, *Arbitrage and Liquidity: Evidence from a Panel of Exchange Traded Funds*:
  https://www.federalreserve.gov/econres/feds/arbitrage-and-liquidity-evidence-from-panel-of-exchange-traded-funds.htm
- BIS, *The anatomy of bond ETF arbitrage*:
  https://www.bis.org/publ/qtrpdf/r_qt2103d.htm
- BIS, *ETFs, illiquid assets, and fire sales*:
  https://www.bis.org/publ/work975.htm
- SEC Rule 6c-11 adopting release:
  https://www.sec.gov/files/rules/final/2019/33-10695.pdf
- FINRA TRACE historical-data information:
  https://www.finra.org/industry/trace-historic-academic-data

## Claim boundary

The literature supports a real price-discovery and market-structure question, not a return claim.
No evidence here establishes sign, timing, net profitability, diversification, capacity, or sleeve
admissibility.
