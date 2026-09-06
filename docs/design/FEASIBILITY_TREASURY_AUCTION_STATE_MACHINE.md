# Treasury auction concession: point-in-time schedule state machine

**Prepared:** 2026-08-26  
**Stage:** no-price, no-return identity redesign  
**Family trial account:** `treasury_auction_concession`  
**Author technical approval:** not yet recorded  
**Return execution authorized:** no

## Why the identity needs a state machine

The original literature identity enters a relative-value position ten XNYS sessions before each
fixed-rate 2-year Treasury auction, reverses after the auction, and exits ten sessions later. That
clock is not observable from formal auction announcements alone. The sealed archive audit proves
145 of 156 auction dates at least ten sessions ahead, but it also preserves five tentative-date
changes, two late exact captures, three post-event exact captures, and one missing month.

A historical test cannot replace those states with the final auction calendar. This protocol keeps
the economic direction and ten-session windows fixed while declaring how an implementable process
would react to the calendar information available at each decision time.

This document does not select prices, load returns, claim a premium, or admit a sleeve. It prepares
one identity for Arhan Canli's technical review.

## Frozen event and decision clock

- Eligible event: nominal, fixed-rate 2-year US Treasury note auction.
- Research interval: 2013-01-01 through 2025-12-31 for the sealed historical audit.
- Trading calendar: XNYS sessions. The eventual instrument calendar and execution timestamps must
  be bound separately in the return preregistration.
- Tentative entry: XNYS close ten sessions before the latest authoritative tentative auction date
  observable by that close.
- Formal confirmation: the official Treasury auction announcement date.
- Auction confirmation: the official auction occurrence and result publication.
- Post entry: XNYS close on the confirmed auction date, after the 1 p.m. auction.
- Post exit: XNYS close ten sessions after the confirmed auction date.
- Price, return, P&L, Sharpe, drawdown, and portfolio-correlation fields are prohibited here.

The state machine does not infer when an archive document was originally published. Historical
knowability uses only a sealed official release date or a Wayback capture timestamp. A capture is an
upper bound on when a date was observable, never evidence that it was known earlier.

## Position identity carried forward

The state machine changes only the event clock. It does not alter the literature direction:

1. The pre-auction leg is the locked short on-the-run 2-year note position against the declared
   duration-matched 6-month-bill and 10-year-note hedge.
2. The post-auction leg is the locked opposite relative-value position.
3. No missing or revised schedule permits an inverted sign, a shorter substitute window, an ETF
   directional proxy, or a different maturity.
4. Exact instruments, hedge ratios, rolls, timestamps, commissions, bid/ask costs, market impact,
   and margin remain mandatory fields in the later return preregistration.

## States

`UNOBSERVED`
: No usable tentative date is known. No pre-auction position is allowed.

`TENTATIVE_ARMED`
: A fixed-rate 2-year date is source-bound at least ten XNYS sessions ahead. The T−10 entry is
scheduled but no position exists.

`PRE_ACTIVE`
: The locked pre-auction leg was entered at the scheduled T−10 close.

`REARMED`
: An authoritative schedule update changed the date before entry and the replacement date still
has at least ten sessions of lead. The old entry is cancelled and a new T−10 entry is scheduled.

`PRE_CANCELLED`
: A date changed or an auction was cancelled after entry. The pre leg exits at the next XNYS close;
the strategy never holds it merely because the original tentative date was convenient.

`POST_ONLY`
: The exact date arrived with fewer than ten sessions of lead, after the event, or without a usable
tentative schedule. The pre leg is skipped. A post leg remains possible only after the auction is
formally confirmed and occurs.

`CONFIRMED`
: The official announcement confirms the date. If the pre leg is active and unchanged, it remains
active through the auction-day close.

`POST_ACTIVE`
: The confirmed auction occurred. The pre leg, if any, is closed and the opposite post leg is
entered at the auction-day close.

`CLOSED`
: The post leg exits at T+10. Event attribution and all costs remain attached to that event identity.

## Transition rules

| Current state | Point-in-time event | Required action | Next state |
| --- | --- | --- | --- |
| `UNOBSERVED` | Usable tentative date with at least ten sessions of lead | Schedule the exact T−10 close | `TENTATIVE_ARMED` |
| `UNOBSERVED` | Formal announcement with fewer than ten sessions of lead | Do not chase the pre leg | `POST_ONLY` |
| `TENTATIVE_ARMED` | T−10 close arrives with no conflicting update | Enter the locked pre leg | `PRE_ACTIVE` |
| `TENTATIVE_ARMED` | Date changes and replacement still has ten sessions | Cancel old entry and schedule the replacement | `REARMED` |
| `TENTATIVE_ARMED` | Date changes with fewer than ten sessions remaining | Cancel the old entry; do not enter late | `POST_ONLY` |
| `PRE_ACTIVE` | Date changes or auction is cancelled | Exit at the next XNYS close; never invert | `PRE_CANCELLED` |
| `PRE_CANCELLED` | Replacement date later becomes observable with ten sessions | A fresh pre entry is allowed only at its exact T−10 close | `REARMED` |
| `PRE_CANCELLED` | Replacement remains late | No replacement pre leg | `POST_ONLY` |
| `PRE_ACTIVE` | Formal announcement confirms the same date | Keep the pre leg through auction-day close | `CONFIRMED` |
| any pre state | No official announcement by the auction-day decision cutoff | Exit or remain flat; no post leg | `CLOSED` |
| `CONFIRMED` or `POST_ONLY` | Auction occurs and the official result is published | Enter the locked post leg at the XNYS close | `POST_ACTIVE` |
| `POST_ACTIVE` | T+10 close | Exit | `CLOSED` |

An announcement or update without an intraday publication timestamp is treated conservatively as
actionable at the next XNYS close. A replacement pre leg is never backdated.

## Revisions in the sealed 2013–2025 panel

The five known tentative-date changes receive deterministic treatment:

- Four dates had already crossed their tentative T−10 entry before the formal revision. Their pre
  legs are cancelled at the next XNYS close and are not re-opened because fewer than ten sessions
  remain before the confirmed date.
- One revision was announced before the tentative T−10 entry. Its stale entry is cancelled and the
  event becomes post-only because the confirmed date is already inside T−10.
- The two late exact captures, three post-event captures, and one missing month are also post-only.
- The remaining 145 events use the exact source-bound tentative date and can follow the complete
  pre-and-post path.

These classifications are inputs, not performance-based exclusions. Every skipped or shortened pre
leg remains in the event ledger.

## Overlap policy

Monthly T−10/T+10 windows can overlap. No event is dropped because a neighboring event exists.
Each event retains its own state and gross target. The later execution preregistration must aggregate
simultaneous targets into one net order while preserving event-level theoretical legs, realized
fills, allocated fees, and any cancellation. It may not keep only the more profitable attribution.

## Fail-closed conditions

The event closes without a post leg if the auction is cancelled, the official announcement or
result cannot be source-bound by the decision cutoff, the auction date is not a valid declared
trading session, or the relevant instrument cannot be traded under the frozen execution contract.
Missing records are never replaced by the final calendar.

## Technical gates

The no-return audit passes only when:

1. All 156 sealed events map to exactly one state path.
2. The 145 exact-date proofs and 11 unresolved-date classifications reconcile to the source audits.
3. Every tentative entry, cancellation session, auction-day transition, and T+10 exit is
   deterministic under the XNYS calendar.
4. Revised, late, post-event, and missing schedules have explicit behavior.
5. Overlap handling and event-level attribution are declared.
6. No source input contains market prices or returns.
7. Return data opened and return hypotheses spent remain zero.
8. The protocol and every source artifact are SHA-256 bound.

Passing these technical gates means only that the calendar identity is executable without final-date
hindsight. The candidate remains `identity-redesign-required` until Arhan records technical approval.
Even after approval, a separate checksum-bound return preregistration is required before any market
data is opened.

## Approval boundary

Prepared for review; not approved. Arhan must independently confirm the position identity, decision
timing, cancellation rule, post-only treatment, overlap accounting, and kill conditions. Automation
may test and package this protocol but may not supply that approval or authorize a return run.
