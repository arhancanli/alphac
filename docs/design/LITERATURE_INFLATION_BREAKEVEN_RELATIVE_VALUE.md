# Inflation breakeven relative value — literature and claim boundary

**Short title:** Inflation breakeven relative value: literature  
**Author:** Arhan Canli  
**Reviewed:** 2026-08-22  
**Research state:** source feasibility only; no market returns opened.

## Economic mechanism

Breakeven inflation is the spread between comparable nominal Treasury and inflation-indexed
Treasury yields. It is inflation compensation, not a clean expectation: expected inflation,
inflation-risk premia, and relative TIPS liquidity all enter the observed spread. A relative-value
identity can therefore be economically coherent only if it names which component it expects to
mean-revert or persist and neutralizes duration, carry, index lag, seasonality, funding, and
liquidity. A level spread with an attractive chart is not yet a trade.

The local atlas originally named two universes—2Y/5Y and 5Y/10Y—and three horizons. Those six cells
are a search space, not six free trials. Before returns, this review narrows what the held source
can actually support: daily 5Y and 10Y inflation-compensation signals plus vintage CPI. It does not
support a 2Y leg, inflation swaps, or executable nominal/TIPS baskets.

## Primary literature

- Gürkaynak, Sack, and Wright, *The TIPS Yield Curve and Inflation Compensation*, documents the
  fitted real-yield curve and shows that inflation compensation is affected by time-varying
  inflation-risk and early-sample liquidity premia. It supplies measurement foundations, not a
  trading rule: https://www.federalreserve.gov/pubs/feds/2008/200805/200805pap.pdf
- D'Amico, Kim, and Wei, *Tips from TIPS*, estimates an explicit TIPS-liquidity factor. Their
  central warning is load-bearing here: treating breakevens as expected inflation without
  liquidity and risk-premium controls distorts the signal materially:
  https://www.federalreserve.gov/pubs/feds/2010/201019/201019pap.pdf
- Kim, Walsh, and Wei's 2019 update writes the decomposition directly as expected inflation plus
  inflation-risk premium minus TIPS-liquidity premium and shows the components move through time:
  https://www.federalreserve.gov/econres/notes/feds-notes/tips-from-tips-update-and-discussions-20190521.html
- The Federal Reserve's public TIPS-curve page defines the matched-maturity breakeven and warns
  that the estimates can be delayed, revised, or changed methodologically. It records a specific
  2022 historical revision, so a current download is not itself a historical-vintage archive:
  https://www.federalreserve.gov/data/tips-yield-curve-and-inflation-compensation.htm
- FRED defines `T5YIE` and `T10YIE` as spreads built from constant-maturity nominal and
  inflation-indexed Treasury series. These are daily market-derived estimates, not security-level
  transaction prices, cashflows, bid/ask quotes, or total returns:
  https://fred.stlouisfed.org/series/T5YIE and
  https://fred.stlouisfed.org/series/T10YIE

## What follows for ALPHAC

The literature forbids three flattering shortcuts. First, a breakeven-minus-realized-inflation
residual cannot be labelled a pure expectation error. Second, current historical estimates cannot
be labelled point-in-time merely because each row has an observation date. Third, changes in a
constant-maturity estimate cannot stand in for a tradable, duration/carry-neutral basket without
security-level pricing and cashflow evidence.

A later return preregistration must choose one identity before opening prices, define whether it
trades cash bonds, inflation swaps, futures, or an explicitly acknowledged ETF proxy, and charge
every alternate universe, horizon, sign, and implementation to one family-wise trial account. It
must also specify liquidity controls, 2008 stress, indexation lag, seasonality, financing,
transaction costs, capacity, DSR/PBO, and the fixed-book diversification tests. No source cited
here establishes edge, sign, Sharpe, drawdown, capacity, or admission.

