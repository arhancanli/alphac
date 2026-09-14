# Paper gap recovery — phase complete

**No missing combined-portfolio mark was recovered.** The bounded search found no August 9/10 crypto equity observations in the current sole-writer VPS database, its retained deployment backup, or the inspected local copies. The three Alpaca equity sleeves do have August 10 session observations stored under August 11 timestamps. These findings must remain distinct.

## Search and retained evidence

Eight local databases and two remote databases were inspected with read-only SQLite transactions. Queries retained August 7–12 equity rows, cycle statuses and details, and database timestamp bounds. The remote query used the existing known host/key, strict host-key checking and a 25-second outer timeout. It succeeded. No service, account, environment, market data or production configuration was changed.

| Sources | Evidence |
|---|---|
| Current local crypto DB; VPS staging mirror; September 11 sleeve-review snapshot | No August 9/10 crypto marks. Four failed August 10 cycles are retained. |
| June 29 restart backup; August 7 archived crypto DB | Predate the missing interval. Preserved for inventory completeness; cannot establish what happened later. |
| Live VPS crypto DB; August 25 deployment backup | No August 9/10 crypto marks; same retained failures in the query window. These are copies of one execution lineage, not independent trading observations. |
| AlphaMax, AlphaTrend and AlphaVintage local DBs | Each retains the August 10 session close under the August 11 midnight timestamp. August 9 was a closed equity session, not a missing expected equity mark. |

On August 10, the crypto cycle evidence contains one ingest-lock failure and three interruptions resolved on restart. There are no August 9 cycles in the inspected query results. That establishes absence in these sources, not a definitive explanation of why no process ran on August 9. Unlisted backups or provider records were not searched, so this is not a claim of universal unrecoverability.

`local-query-results.json` and `remote-query-result.json` retain the bounded records. `remote_query.py` is the exact query executed on the VPS. Ten canonical query-result hashes were independently recomputed during classification. Five source files were snapshotted with hashes. `classification.json` records per-source, per-day outcomes without changing raw dates or values.

## Correction to the recovery premise

The prior phase correctly found that the **published composite** jumps from August 8 to August 11. This should not be described as missing data on every account. The earlier project correction `CORRECTION_ALPACA_SESSION_DATE_CONTINUITY.md` already documents Alpaca's retained D-close/D+1-midnight convention. This phase confirms that distinction against actual local rows and the remote crypto writer.

The continuity audit applies this economic-session mapping, but the inspected composite builder labels every sleeve mark by its raw UTC date. Relabeling rows alone would change attribution timing and interact with the committed allocation schedule: the legacy book used equal thirds before AlphaVintage joined on August 10, then equal quarters. It would therefore be a versioned reconstruction, not recovery of an original combined NAV.

The builder also selects output dates from sleeve-return dates, not the overlay's dates, and uses zero contribution for a missing sleeve return. Thus available overlay prices alone cannot restore a trustworthy synchronized combined observation. Repricing old positions today could create a separately labeled reconstruction; it would not prove an observed historical mark and was not performed.

## Decision

- Retain the complete legacy paper curve, the three-day return and all failure records.
- Keep the isolated irregular-record Sharpe gate. A continuity audit permitting up to 20% missing expected marks is an operational threshold, not statistical clearance for consecutive daily sampling.
- Do not backfill crypto with flat returns, borrow another account's marks, shift the allocation schedule, or silently restart the displayed performance history.
- Plan a **separate prospective measurement stream**, contingent on timing, source and accounting readiness. Retain the legacy record beside it; creating a measurement stream would not itself restart trading or reset actual capital. No new epoch was started in this phase.

## Next phase specification

Prepare and test a portfolio valuation/evaluation contract before collecting a qualifying stream or running a new portfolio variant:

1. Retain each raw timestamp, economic session, observation/receipt timestamp, source/account binding and configuration epoch. A date-only re-label is insufficient.
2. Freeze a common valuation convention for the equity sleeves, 24/7 crypto, cash and overlay. Explicitly distinguish an exchange closure with a permitted valuation rule from an unobserved open-market mark. Missing required inputs must remain unavailable, not zero returns.
3. Bind the committed allocation schedule and the separate overlay. Record actual cash, flows, fees, borrow and financing; identify where a return is an account observation versus a normalized analytical composite.
4. Define net excess-return Sharpe with a dated cash benchmark; specify the evaluation calendar, uncertainty method and minimum evidence. Preserve zero-benchmark historical statistics as historical, not comparable qualification claims.
5. Define the combined 11% maximum-drawdown assessment over explicit horizons and stress scenarios; include initial capital, financing, gaps and execution risk. Report observed, modeled expected and tail losses separately.
6. Evaluate a proposed sleeve/change against the same frozen book and capital/cost assumptions, keeping the original comparator and trial union. The >2 Sharpe, <=11% drawdown and 15+ qualified-sleeve goals apply to the combined portfolio.

These are the required next-phase deliverables, not an activated policy or a completed launch contract. Numerical data-age limits, scenario grids, benchmark source and a start date remain to be established from capability and evidence rather than selected to pass today's record.

## Verification and progress

Three existing calendar regressions pass: Alpaca midnight session mapping, weekend snapshot exclusion and XNYS holiday handling. Seven unrelated artifact tests were deselected, not run. Both recovery/classification scripts pass Ruff. The saved query hashes and source snapshots verify; no account identifier, credential or order submission was required.

Progress: the gap's ownership and source availability are established for the inspected stores, including the remote authority. **No strategy performance improvement, new sleeve admission or original missing mark recovery is claimed.** Stop at this phase boundary.
