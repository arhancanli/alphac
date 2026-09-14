# Agricultural revision candidate v1 — pre-return specification

Status: research implementation exists; historical availability, execution costs
and formal trial admission remain unresolved. This document fixes one proposed
hypothesis before looking at return outcomes. It does not reserve a formal trial
or bypass the canonical admission contract.

Hypothesis: after a published reduction in U.S. stocks-to-use, grain prices may
continue adjusting upward; an increase may predict downward adjustment. This is
a delayed-response hypothesis, not a surprise-versus-consensus measure. The
published revision could already be fully priced, making this hypothesis fail.
Wheat, corn and soybeans are one candidate family.

The proposed direction is minus the sign of the same-crop-year stocks-to-use
change. Each crop receives one-third signed research notional, unchanged values
receive zero, and unused weight stays cash. There is no threshold search,
ranking, volatility optimization or sign reversal in v1. Every attempted later
variant must enter the research trial accounting.

Require all three crops from one original report, a comparable prior crop year,
and independently established availability of both versions. Corrections and
new-crop introductions do not open positions. The decision is five minutes
after verified release availability, and entry eligibility expires after fifteen
minutes. Scheduled noon and today's download time are not substitutes for
historical availability. A late or unavailable crop blocks the whole basket.
The Python signal component validates caller-supplied timestamps; it does not
authenticate source evidence or route orders.

Execution proposal, not yet implemented: use listed outright ZC, ZW and ZS
futures; select the nearest contract with at least twenty exchange business days
to first notice or last trading, whichever comes first. Use definitions and
calendars known at the decision. Hold to the same local-clock time in the next
scheduled trading session. Never substitute a continuous adjusted series for
executable contracts. No delivery exposure, optimized roll rule or unmodeled
forced fill is permitted. Session closures, price limits, absent books and
unresolved exits must remain visible failures rather than dropped losing trades.

Convert research notionals to integer contracts under account margin, gross
exposure and observed depth constraints. Entry buys cross the ask and sells
cross the bid; exits reverse that accounting. Use timestamped depth after a
fixed latency allowance, account-specific commissions and dated exchange fees.
Do not use a default flat slippage constant to declare feasibility. Fill/cost
logic, latency and integer sizing must be fixed before returns are requested.
The target capacity remains the canonical $500,000 minimum with a measured
capacity curve; metadata alone cannot establish it.

Evaluation proposal: chronological walk-forward analysis with the existing
756 OOS daily-observation and DSR/PBO/correlation gates unchanged. Report distinct
monthly events and dependent crop legs separately from daily portfolio marks.
Assess incremental net return against fixed trend/carry/seasonality controls;
control definitions, fitting windows and cost stress tests must be finalized
before the trial. No held-out return has been examined in this work. No Sharpe,
capacity or admission claim is made.

## Market-data feasibility evidence

Authenticated metadata requests succeeded using the existing saved Databento
credential. GLBX.MDP3 lists MBP-1, MBP-10, instrument definitions and market
status over the intended historical range. MBO begins May 21, 2017. These are
provider metadata assertions, not per-event quality or entitlement-to-redistribute
proof. Databento documents the older FIX/FAST source and a change to MDP 3.0 in
May 2017. [Provider dataset documentation](https://databento.com/docs/venues-and-datasets).

Three fixed sample windows, covering all three futures parents, received these
MBP-10 plus definition/status estimates:

| UTC window (end exclusive) | Estimated retrieval cost |
|---|---:|
| 2015-01-12 to 2015-01-15 | $1.44 |
| 2018-08-10 to 2018-08-15 | $2.15 |
| 2025-08-12 to 2025-08-15 | $2.38 |

These are sample retrieval estimates, not full-study or trading costs. The first
and third windows span three calendar days; the middle spans five. Do not
extrapolate to all events without enumerating the complete retrieval scope.
No market records were downloaded and no purchases submitted. Evidence:
`evidence/wasde-market-feasibility/metadata.json` and `sample-cost-summary.json`.

The provider reports missing capture timestamps in data before May 21, 2017,
and has reported older partial-day request and bar-aggregation defects. Whole
UTC-day sampling avoids relying on arbitrary short request boundaries but does
not prove data quality. Separate legacy-data validation is required before
including 2015–2017 in an execution study.
[Provider catalog](https://databento.com/catalog/cme/GLBX.MDP3/futures/6B),
[Provider issue record](https://issues.databento.com/b/6vrl98vl/feature-ideas/order-messages-missed-and-not-processed-on-certain-dates-bbo-gets-stuck-occasionally-affecting-mbp-1-mbp-10-and-tbbo).

## What is implemented and verified

`src/alphaforge/validation/wasde_signal.py` produces research weights only.
The combined extraction/signal suite passes 28 tests. Invalid availability,
stale events, missing crops, malformed revisions and corrections are rejected.
An audit of all 131 real report groups produces zero weights because the
availability or comparison inputs are not verified. The fixed audit clock is
only a missing-input check, not simulated historical execution.

Next action: resolve availability evidence or explicitly separate an assumption-
based exploratory study from an admissible historical trial. Then validate a
small, fixed data-quality sample before acquiring all events. Full fill logic,
costs, portfolio controls and formal trial registration remain required.

## Subsequent evidence status

The fixed sample has now been acquired; the earlier no-download statement above
is historical. See `WASDE_MARKET_SAMPLE_RESULTS.md` for the 72 independent depth
scenarios and `WASDE_TIMING_AND_LIFECYCLE.md` for the timing audit. Archive HTML
12:00 UTC fields, PDF creation dates and HTTP Last-Modified headers are not
accepted as verified public-availability timestamps. Four contract expiration
dates have retrospective CME corroboration; this does not certify the required
pre-decision calendar or first-notice rule. Original strategy gates remain intact.
