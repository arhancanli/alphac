# Pre-FOMC announcement drift — no-return feasibility protocol

**Declared:** 2026-08-16  
**Return data:** unopened  
**Hypotheses spent:** zero

## Question

Can the scheduled FOMC decision calendar and exact statement-release clock be reconstructed from
official Federal Reserve sources without using market prices or learning which events were
profitable?

## Locked audit

- Official Federal Reserve current calendar for 2021 onward.
- Official per-year historical meeting pages for 2016–2020.
- Regular meetings only; emergency conference calls and unscheduled actions are excluded.
- Exact HTML statement URL, decision date, release-time text, source hash, and retrieval lineage.
- No intraday bars, closes, spreads, returns, signals, positions, or performance statistics.

## Gates before any return identity

1. Eight regular scheduled decisions in ordinary complete years. The March 17–18, 2020 regular
   meeting was superseded during the emergency period; the unscheduled March 2/3 and March 15
   actions are excluded because a pre-announcement window was not knowable from the regular
   calendar. The resulting statement-event corpus should contain 79 decisions: eight in nine
   years and seven in 2020.
2. Statement release-time metadata coverage must be 100%.
3. The 2:00 p.m. ET release convention must be measured, not assumed.
4. Point-in-time schedule revisions/confirmations must be reconstructable. The current Federal
   Reserve calendar says each future meeting date is tentative until confirmed at the immediately
   preceding meeting; an ex-post list of final dates is not sufficient lineage.

Failure of gate 4 yields `CALENDAR_LINEAGE_REQUIRED`, not permission to open returns.

## Resolved schedule lineage

The follow-up audit binds ten official annual schedule press releases for 2016–2025. Each page
contains eight target-year meeting slots, is SHA-256 bound, and was published before the target
year. The minimum lead is 117 XNYS sessions. All 79 completed regular decisions match those 80
initially scheduled slots.

The sole schedule-only slot is March 17–18, 2020. The official 2020 history marks it cancelled,
and the March 15 emergency statement is bound at 5:00 p.m. EDT, two XNYS sessions before the
scheduled decision date. Dropping this event would create ex-post selection. Any return identity
must preserve it as `CANCELLED_NO_ENTRY_OR_FLATTEN_AT_NEXT_ELIGIBLE_OPEN`.

Decision: `PASS_TO_RETURN_PREREGISTRATION`. This is not return evidence. The single identity is
locked separately in `PREREG_PRE_FOMC_ANNOUNCEMENT_DRIFT.md`; returns remain unopened until the
market-input manifest and runner enforce that contract.

## Market-data readiness result

The locked event/control expansion produces 312 valid matched-control windows and 782 unique XNYS
session files. Every required object is visible in the Polygon SIP quote archive; no required date
is missing, and every completed event retains at least three controls. The cancelled March 2020
slot has no market window.

The available provider routes nevertheless fail implementation feasibility:

- The required full-day SIP quote files total 3,005.294 GiB compressed, far beyond the locked
  50 GiB ceiling for a bounded single-instrument research ingest.
- The configured flat-file credentials can list objects but return HTTP 403 to one-byte endpoint
  retrieval probes.
- The server-filtered Polygon historical SPY quote endpoint returns HTTP 403 `NOT_AUTHORIZED`.
- Databento consolidated US-equity depth begins in 2023 and cannot cover the frozen 2016–2025
  panel; single-venue history beginning in 2018 is not a substitute for consolidated NBBO.

Decision: `DATA_GATED`. No quote record was decompressed or parsed, no return was computed, and no
hypothesis was spent. Progress requires a server-filtered historical SIP quote entitlement (or a
vendor-supplied SPY-only export) covering 2015-12-29 through 2025-12-10 with bid, ask, sizes,
timestamps, conditions, sequence/order lineage, and corrections. Alpaca shadow data cannot replace
this historical research feed.
