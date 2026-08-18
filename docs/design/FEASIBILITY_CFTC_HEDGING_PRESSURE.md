# CFTC hedging pressure — no-return feasibility protocol

## Scope

This stage audits only identifiers, dates, market labels and commodity classifications from the
CFTC Disaggregated Futures Only dataset (`72hh-3qpy`). It deliberately excludes producer,
dealer, managed-money and other position columns; it loads no prices and calculates no returns.

## Point-in-time constraint

CFTC says each report normally contains Tuesday positions and is released Friday at 3:30 p.m.
Eastern, with holiday exceptions. CFTC also says a complete history of actual release dates does
not exist and only the recent 13 months are available. Therefore `report_date + 6 days` is stored
only as a conservative Monday default; it is not called a verified release timestamp.

## Locked gates

1. At least 100,000 metadata rows and 15 calendar years.
2. At least 99% completeness for identity, report date, market and commodity identifiers.
3. Dataset IDs are unique even though CFTC does not warrant a formal primary key.
4. At least 98% of report dates are Tuesdays.
5. Exact historical release lineage covers at least 95% of observations.
6. A separately reviewed mapping from CFTC market codes to liquid tradable contracts is sealed.

The last two gates fail closed until evidenced. A structurally clean dataset cannot pass to a
return test without them.

## Next action and kill rules

If metadata gates pass but release lineage fails, publish `DATA_GATED`. A future branch may use
archived CFTC pages to reconstruct release dates or preregister a lag conservative enough to cover
known disruptions, but it must do so before returns are opened. Kill if release timing remains
unverifiable, contract mapping is unstable, lagged positions add nothing beyond trend and curve
carry, stressed costs fail, or correlation to AlphaTrend exceeds 0.35. No failed return identity
may be rescued by changing the sign, lag, normalization or market set.
