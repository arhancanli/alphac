# Options dispersion: literature and implementation boundary

**Reviewed:** 2026-08-16  
**Family:** `options_dispersion`  
**Claim state:** mechanism supported; investable return untested  
**Return identities spent:** zero

## What the evidence supports

The defensible mechanism is a priced difference between index correlation/variance insurance and
the corresponding single-stock option basket. It is not a generic claim that any difference
between index and constituent implied volatilities is arbitrage.

Driessen, Maenhout, and Vilkov document a materially higher average option-implied correlation
than realized correlation in S&P 500 and DJ30 data and interpret the gap as a negative correlation
risk premium. Their implementation combines index and constituent option-implied variances with
point-in-time index weights. The study uses OptionMetrics options data, CRSP returns, historical
index composition, and 30-, 60-, and 91-day standardized maturities. Missing constituent variance
estimates are handled by rescaling available weights, a choice ALPHAC will report explicitly rather
than inherit silently.

- [Driessen, Maenhout, and Vilkov, *Option-Implied Correlations and the Price of Correlation Risk*](https://www.netspar.nl/assets/uploads/061_Driessen.pdf)
- [Published Journal of Finance record](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2009.01467.x)

Carr and Wu establish the model-free option-strip construction used to synthesize variance-swap
rates. This supports the measurement layer, not a net trading return: discrete strikes, stale or
zero bids, dividends, rates, jumps, and execution all remain implementation problems.

- [Carr and Wu, *Variance Risk Premiums*](https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057)

Buss and Vilkov show that option-implied correlations can improve forward-looking beta estimates.
That is useful evidence that option cross-sections carry information, but it is adjacent evidence;
it does not prove a dispersion portfolio earns an implementable premium.

- [Buss and Vilkov, *Measuring Equity Risk with Option-Implied Correlations*](https://gsefm.eu/fileadmin/user_upload/dateien_schuelermarketing/mimeo_2012_Buss.pdf)

Marshall directly studies dispersion trading and finds that candidate opportunities decline as
transaction costs rise. The sample is only 2005–2007, so it is a warning about friction sensitivity,
not adequate evidence for a modern strategy.

- [Marshall, *Dispersion trading: Empirical evidence from U.S. options markets*](https://doi.org/10.1016/j.gfj.2009.06.003)

## The exchange benchmark is a measurement reference, not a backtest

The Cboe S&P 500 Dispersion Index (`DSPX`) measures 30-day expected dispersion as the square root
of the nonnegative difference between a float-market-cap-weighted basket of constituent expected
variances and VIX squared. Its universe requires S&P 500 index options and eligible constituent
options; valid constituent variances require near- and next-term strips and at least three valid
out-of-the-money calls and puts in each strip. The methodology filters invalid and zero-bid quotes.

This is an excellent independent accounting reference, but three boundaries matter:

1. DSPX is an indicator, not a self-financing, executable options portfolio.
2. Its published back-tested history starts in June 2014, while the live index launched in
   September 2023.
3. Live levels may pull a constituent variance forward from a recent valid observation, whereas
   the back-tested end-of-day series does not. ALPHAC may never treat a pulled-forward value as a
   contemporaneously tradable quote.

The methodology also changes option classes for splits, special dividends, mergers, spin-offs,
and delistings. Those are mandatory lineage events in our implementation.

- [Official Cboe/S&P DJI Dispersion Index methodology](https://cdn.cboe.com/resources/indices/documents/methodology-the-dispersion-index.pdf)
- [Official Cboe DSPX overview](https://www.cboe.com/us/indices/dispersion/)

## Data conclusion

Alpaca is suitable for prospective OPRA capture and paper execution, but its official historical
options coverage begins only in February 2024. That is too short to estimate a correlation-risk
premium across calm, crisis, rate, volatility, and liquidity regimes.

- [Alpaca historical option-data coverage](https://docs.alpaca.markets/us/docs/historical-option-data)

OptionMetrics IvyDB US is the preferred research spine because it provides end-of-day bid/ask,
volume, open interest, option sensitivities, rates, dividends, corporate actions, permanent IDs,
and volatility surfaces from January 1996. Cboe DataShop quote intervals are the preferred
execution-calibration source because they include historical NBBO and sizes from January 2012;
the full one-minute market is very large and must be scoped to the frozen basket.

- [OptionMetrics IvyDB US product specification](https://optionmetrics.com/data-products/)
- [Cboe DataShop Option Quote Intervals](https://datashop.cboe.com/option-quote-intervals)

## ALPHAC interpretation

The conventional position—long constituent variance and short index variance—is short implied
correlation and can lose sharply when correlations and index downside insurance reprice together.
It is therefore not presumed near-uncorrelated to AlphaMax, equity beta, or existing volatility
exposure. Admission requires crisis conditional correlations and expected shortfall, not merely a
low full-sample correlation.

The first eligible return identity, if the no-return data audit passes, is one 30-calendar-day,
monthly-rebalanced, point-in-time S&P 500 top-50 basket. Legs are ex-ante vega balanced. Every
short option exposure must have frozen disaster wings; daily delta hedging, early assignment,
dividends, gaps, margin, partial fills, quote size, and corporate actions are charged explicitly.
Seven-day, 60-day, sector-basket, reverse-direction, and threshold variants remain in the same
family trial account and cannot be presented as independent discoveries.

## Contrarian conclusion

This family is economically credible but operationally hostile. Its many legs create a large gap
between a clean implied-correlation chart and an executable portfolio. If institutional history,
point-in-time membership, quote-size calibration, or defined-loss replication cannot be sealed,
the correct result is `DATA_GATED` or `KILL_FEASIBILITY`, not a midpoint backtest.

## Rerun inputs

- workflow requested: `firecrawl-research-papers`
- collection result: Firecrawl unavailable because `FIRECRAWL_API_KEY` was not configured
- fallback: original papers, publisher records, official Cboe methodology, and official vendor docs
- return data opened: no
- return hypotheses spent: zero
