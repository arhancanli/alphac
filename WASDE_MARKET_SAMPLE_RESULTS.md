# Futures sample acquired and audited — 11 September 2026

The budget fix worked. All nine fixed requests completed: MBP-10 depth,
instrument definitions and trading-status records for the three preselected
windows. Fresh total retrieval estimate: $5.9667, below the $10 cap. The final
invoice amount has not been verified. All nine response hashes match their
receipts. No strategy return, P&L or Sharpe was calculated.

The full files and receipts are under
`evidence/wasde-market-sample-after-budget-fix/`. Earlier failed attempts and
the one-record diagnostic remain separately preserved. Future work should reuse
these successful files rather than repeat billable requests.

| Sample | Depth records | Bad receive-timestamp flags | Snapshot flags | Valid unflagged end-of-event rows in diagnostic minute: corn / wheat / soybeans |
|---|---:|---:|---:|---|
| January 2015 | 8,362,300 | 8,361,643 | 657 | 0 / 0 / 0 |
| August 2018 | 12,528,968 | 604 | 604 | 6,249 / 7,451 / 7,418 |
| August 2025 | 13,825,220 | 677 | 677 | 11,375 / 9,281 / 29,047 |

The diagnostic minute is 12:05–12:06 America/New_York on the indexed report date.
It tests data presence around the proposed window, not historical publication
availability. All three modern crop legs have usable-looking updates under the
row filters. Equal aggregate snapshot/bad-timestamp counts alone do not prove
that they flag exactly the same records. The older sample fails the current
receive-timestamp requirements and cannot be silently treated like modern data.

Across all samples, some books have missing, locked, crossed or empty sides.
Counts cover all returned instruments and initialization records, not just the
contract eventually selected for trading. Instrument-level continuity, snapshots,
sequence gaps, stale quotes, state carry-forward, execution latency and depth
consumption remain to be validated. Older event timestamps in initialization
records must not be mistaken for live updates inside the requested window.

Definition records contain expiration information but no field explicitly named
for first notice. The proposed contract rule therefore still needs an independent
dated first-notice source. Market-status files have been retrieved and decoded,
but a full trading-session state-machine validation is not claimed.

The streaming quality checker was extended to separate valid end-of-event,
unflagged quote rows from snapshots and bad books in the diagnostic window.
A focused test verifies filtering across chunks, locked books, receive-time
ordering and summer timezone conversion; it passes. Changed scripts pass Ruff.
`integrity.json`, `reference-summary.json` and `quality-2015.json`,
`quality-2018.json`, `quality-2025.json` record the actual checks.

Next: use the modern samples to implement and test contract-level quote/state
replay and conservative fills; obtain first-notice and report-version availability
evidence. Keep legacy-data results separate until their timestamp limitations
are resolved. Then finalize the single pre-return specification and formal trial
registration. Sample acquisition is complete; trading readiness and profitable
alpha are not established.

The separate equity search is documented in `DATA_SOURCE_AND_EQUITY_SEARCH.md`:
share-class pricing, expected earnings-announcement demand and recurring intraday
flow are investigation leads. No new sleeve has been admitted.

## Modern contract depth scenarios — continuation

The new `scripts/probe_wasde_execution_depth.py` resolves six diagnostic symbols
to unique instrument IDs using definitions received before each decision clock:
December corn and wheat, November soybeans, in 2018 and 2025. These maturities
were fixed before inspecting the depth results. They are not yet certified as
the nearest contracts satisfying the strategy's 20-session lifecycle rule.

For each instrument, the probe checks 12:05:00.250 New York time on the report
date and a separately specified following-session date (13 August in each sample).
The 250 ms offset and 1-second maximum age are diagnostic assumptions, not measured
order latency or authenticated report availability. The latest received observation
is selected before quality filtering; a bad latest row cannot expose an older good
book. Receive ordering is checked within and across chunks. Both event and receive
age must pass. Snapshots, incomplete events, bad timestamps/books, trade records,
resets, unavailable open status, invalid depth and crossed books block the scenario.

Buy and sell sizes of 1, 10 and 100 contracts are independent alternatives at each
of 12 contract/time points: 72 scenarios, not 72 trades. Price levels are consumed
once per scenario, at the ask for buys and bid for sells. Native quote units are
retained; no monetary conversion, fees, margin, impact or P&L is inferred.
`execution-depth-probe.json` stores outcomes, selected row timestamps/flags/sequence,
instrument IDs, and hashes of the six input files and implementation.

The initial run produced 63 full displayed-depth scenarios, three partial-depth
scenarios and six stale-book blocks. All six stale scenarios belong to the same
2018 corn exit-clock observation. The 2018 wheat entry-clock buy of 100 contracts
has only 88 displayed contracts across the ten levels. These outcomes do not
establish executable fills: displayed liquidity can disappear, trade/status
continuity is not certified, and entry/exit scenarios are not linked positions.
No return trial has been run and no threshold was tuned to remove these failures.

Twenty-two new tests cover side selection, partial depth, invalid inputs, future
and stale observations, bad flags, resets/trades, malformed books, and selection
across chunks including a later bad row and a future good row. Together with the
existing quality and signal tests, 35 tests pass. Changed Python files pass Ruff.

The field interpretation follows the [Databento MBP-10 documentation](https://databento.com/docs/schemas-and-data-formats/mbp-10).
The provider's capture timestamp is not our broker's arrival timestamp.
CME's [agricultural delivery explanation](https://www.cmegroup.com/education/articles-and-reports/agriculture-cash-settlement-vs-physical-delivery)
also identifies delivery exposure after first position day. Dated first-position,
first-notice and last-trade evidence and exchange calendars must therefore be
reviewed before final contract eligibility is certified; a current general
explanation does not prove historical dates.

Next work is the source evidence for those lifecycle dates and each original
report version's availability, then registered costs, sizing and linked exit
handling. Strategy execution remains blocked until that evidence exists.
