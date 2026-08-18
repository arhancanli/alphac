# Options dispersion: locked no-return data and execution-feasibility protocol

**Declared:** 2026-08-16  
**Return data:** prohibited  
**Hypotheses spent:** zero  
**Family trial account:** `options_dispersion`

## Question

Can one point-in-time S&P 500 index-versus-constituent option book be reconstructed with enough
quote, membership, corporate-action, settlement, and executable-cost fidelity to justify one later
return preregistration?

This stage may inspect schemas, timestamps, identifiers, bid/ask quotes, quote sizes, option terms,
index membership, dividends, rates, corporate actions, exercise/settlement rules, and missingness.
It may not calculate strategy P&L, forward realized variance, Sharpe ratio, drawdown, portfolio
correlation, or any return-conditioned threshold.

## Frozen research identity

- Underlying index: S&P 500 / SPX.
- Constituent basket: the 50 largest eligible optionable constituents using membership and float
  market capitalization known before that trading session.
- Measurement time: 3:45 p.m. New York for intraday quotes, or the vendor's documented 3:59 p.m.
  end-of-day snapshot. Sources cannot be mixed within a date.
- Target maturity: 30 calendar days, interpolated only between eligible near and next standard
  expirations bracketing 30 days.
- Quote construction: model-free OTM option strips, with the official Cboe valid-quote, two-zero-bid,
  and minimum-strike-count rules as the independent reference implementation.
- Missing constituent variances: never forward-filled. Available basket weight and excluded weight
  are both published; no date is eligible below the locked coverage gate.
- No sign, entry threshold, holding return, or performance criterion is selected in this audit.

## Frozen source hierarchy

1. OptionMetrics IvyDB US end-of-day option prices, permanent security IDs, rates, dividends,
   corporate actions, and surfaces from 1996 onward.
2. A point-in-time S&P constituent and float-weight history linked by permanent identifier.
3. Cboe DataShop one-minute NBBO and size for SPX and only the frozen constituent sample, used on
   a deterministic calibration-date sample rather than as a substitute history.
4. Official OCC/Cboe contract, adjustment, exercise, and settlement metadata.
5. Alpaca OPRA capture only for prospective paper/live evidence from February 2024 onward.

Indicative option feeds, today’s constituent list applied backward, midpoint-only bars, adjusted
contracts without deliverable lineage, and vendor surfaces without their timestamp/vintage are
inadmissible.

## Locked feasibility gates

All gates pass before a return protocol can be written:

1. At least 15 complete calendar years spanning 2008–2009, 2020, 2022, and 2024–2025.
2. At least 99% of research dates have point-in-time index membership and prior-known weights;
   Wilson 95% lower bound at least 98%.
3. At least 98% of dates have a valid SPX near/next strip and at least 90% of frozen basket weight
   has valid constituent near/next strips; Wilson lower bounds at least 97% and 88% respectively.
4. Every retained contract has bid, ask, quote timestamp, expiration, strike, call/put, multiplier,
   exercise style, settlement style, and deliverable identity; crossed or one-sided markets fail.
5. At least 99.5% of retained option rows link uniquely through symbol changes, splits, special
   dividends, mergers, spin-offs, and delistings; adjusted contracts remain separate identities.
6. Rates and discrete dividend forecasts are vintage-correct. American single-stock options use an
   early-exercise/assignment model; European cash-settled SPX options do not inherit that model.
7. On 250 deterministic overlap dates, the independent option-strip implementation agrees with
   the vendor surface within median 1.0 variance-volatility point and 95th percentile 3.0 points;
   disagreements are published, never averaged away.
8. On 250 deterministic Cboe-overlap dates, executable NBBO reconstruction retains at least 85%
   of target vega after size and valid-strip filters; Wilson lower bound at least 80%.
9. The accounting identity reconciles index variance, weighted constituent variance, excluded
   basket weight, and implied correlation without clipping except where the official benchmark
   definition explicitly clips its displayed index level.
10. A complete execution-state schema exists for commissions, exchange/clearing fees, half-spread,
    nonlinear size impact, partial and rejected fills, leg risk, cancel/replace latency, stale quotes,
    delta-hedge spread/impact, overnight gaps, early assignment, pin risk, dividends, borrow,
    margin, exercise, settlement, halts, exchange outages, and corporate actions.
11. A defined-loss construction is possible on every date without using future strikes or fills.
    Unavailable disaster wings make the date ineligible; they are never synthesized.
12. Return data opened and return identities spent remain exactly zero.

## Decisions

- `PASS_TO_RETURN_PREREGISTRATION`: every gate passes and all manifests are hash-bound.
- `DATA_GATED`: a named licensed dataset can resolve a failed lineage or quote-size gate.
- `KILL_FEASIBILITY`: the defined-loss basket or point-in-time replication is structurally
  unavailable at adequate coverage.
- `REJECT_GOVERNANCE`: returns were opened, samples changed after inspection, or a present-day
  constituent/contract state rewrote history.

Passing permits exactly one separately sealed 30-day return identity. It does not admit a sleeve.

## Credential boundary

No Alpaca key is requested for the historical decision because Alpaca's options history begins in
February 2024. The first useful access is OptionMetrics IvyDB US through a direct license or WRDS,
plus point-in-time S&P membership. Cboe DataShop is second, scoped to deterministic quote-size
calibration dates. Alpaca OPRA credentials become useful only after those gates pass, for prospective
capture and paper execution. Secrets must be supplied through environment variables and are never
written to source, artifacts, logs, or research pages.
