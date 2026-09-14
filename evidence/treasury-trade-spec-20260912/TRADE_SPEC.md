# Proposed Treasury phase-held implementation

Prepared September 12, 2026. This is a concrete proposed implementation of the existing economic direction, not a replication claim, completed return preregistration or trading authorization. Phase-held securities and quantities are explicit implementation choices; the prior calendar audit did not establish them. All real market inputs remain unopened.

## Event and security decisions

Retain the 156-event revision-aware calendar and ten-XNYS-session windows without retuning. There are 149 pre phases and 156 post phases. The scheduled decision remains 16:00 America/New_York on the recorded date. It is usable only when an independently verified historical Treasury venue calendar permits trading then. Early closures or missing calendar evidence block that event; never fabricate a 16:00 fill or move it to another day. Historical half-day/holiday effects must be audited before registration, retaining every exclusion in the denominator.

At each phase entry, require a source-observed, timestamped benchmark-to-CUSIP mapping for each tenor. The issued-reference candidates in phase_plan.json are data-request hints only. They must not be substituted for verified benchmarks. A benchmark transition on auction day must be established by source evidence available by the decision; neither issue date nor the final auction CUSIP proves the transition. Resolve the nine fungible two-year reopenings with their original security lineage.

Select each security once at entry; retain its CUSIP and face quantity until the phase exit or the existing revision-cancellation exit. No daily benchmark roll or duration rebalance occurs inside the phase. Coupon cash and settlement changes are accounted for without silently replacing the security. A security can therefore require off-the-run quotes before exit. At reversal, close the pre positions and separately select and size the post positions. Retain both event attributions even if execution instructions can combine.

Pre: short the two-year note, long the six-month bill and ten-year note hedge. Post: opposite signs. Do not infer positions from scalar pre/post counts.

## Hedge arithmetic and capital boundary

Inputs are contemporaneous settlement-consistent dirty prices per $100 face and modified durations in years, each with source and observation timestamp. Macaulay duration, remaining maturity and a generic tenor are not interchangeable with modified duration. Conversion must use the documented yield convention and coupon basis. The three price/duration inputs must share a consistent valuation basis; cash requirements on distinct settlement dates remain separately financed.

For signed two-year market value V and durations Db < Dt < Dl:

- Ten-year market value: -V × (Dt − Db) / (Dl − Db).
- Bill market value: -V minus the ten-year market value.
- Face amount for each leg: 100 × signed market value / dirty price.

This solves zero initial marked market value and zero first-order parallel dollar-duration exposure exactly. It does not hedge key-rate twists, convexity, funding or liquidity risk. Zero marked value does not imply zero invested capital. Synthetic $1m examples are unit fixtures, not a selected strategy allocation.

The implemented helper returns exact rational faces. An execution implementation still requires venue lot increments, rounding policy, residual-risk limits, margin/haircut capital and portfolio allocation. These are explicit blockers, not permission to execute fractional face values. No Sharpe calculation is defined until a positive capital denominator and financing model are fixed.

## Settlement and execution identity

Regular settlement in this proposed route is the next verified Fedwire Securities settlement session after trade date. WI for a new security settles on first issue date. Reopening-tranche trading settles on the tranche issue date; ordinary trading of the already-issued CUSIP remains a distinct route. Every settlement date must be an open date in a source-bound historical calendar. No generic weekday calendar or current holiday list is accepted as historical proof.

The pure validator checks supplied dates and regimes. It does not establish that a supplied calendar is complete or that a broker permits the route. Entry announcements, quote observation, market state, order cutoffs and broker eligibility require separate evidence. Fedwire Securities operating days and cutoff rules are separate from exchange trading sessions. [Federal Reserve operating schedule](https://www.frbservices.org/resources/financial-services/securities/operating-hours).

Execution aggregation operates on one decision batch only. Keys include CUSIP, settlement date/regime, venue, account, USD currency and financing identity. Different keys remain separate. Identical keys combine signed face instructions while preserving per-event quantities, including zero-net groups. This is instruction aggregation, not an assertion of legal settlement netting or costless crossing. No retrospective cancellation of already-executed trades is permitted.

Missing synchronized executable quotes, size, short availability, financing, market status or a required close blocks execution modeling. Never replace missing data with midpoint fills, auction yields, ETF returns or continuous futures returns. A failed close is an unresolved liability rather than an erased position.

## Required before any return run

Verify benchmark history, cash quote coverage including bills/WI/off-the-run notes, calendars, settlement conventions, coupon cash flows, modified durations, borrow/repo, latency/legging costs, lot rounding, capital and risk limits. Freeze actual security identities, source checksums, date exclusions, fill rules, financing and holdout design in a separate registration. Preserve the original post-publication, cost-stress, duration-beta and AlphaTrend-correlation criteria; do not change signs or horizons after failure. The existing author-review record remains unmodified.
