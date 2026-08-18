# Treasury auction concession — published-identity timing audit

## Why this stage exists

The official event manifest passed its metadata gates, but the primary paper's tradable identity
starts ten trading days before a 2-year note auction. A return test may use that entry only if the
auction date was knowable at the time. This audit compares the published window with formal
announcement lead time without loading any price or return data.

## Locked interpretation

- Primary literature identity: short the on-the-run 2-year note against a duration-matched
  6-month-bill/10-year-note hedge for ten trading days before the auction, reverse on auction day,
  and hold the opposite relative-value position for ten trading days after.
- Formal auction announcements do not retroactively justify trades placed before announcement.
- A recurring monthly pattern is not sufficient lineage. The exact auction date must come from a
  point-in-time source available by the entry date.
- Treasury says six-month tentative schedules are released at each quarterly refunding. Those
  historical schedule documents are the required next corpus.

## Decision rule

`CALENDAR_LINEAGE_REQUIRED` if formal announcements do not support the ten-session entry or the
historical tentative-schedule archive has not been sealed. Do not shorten the window, change the
sign, substitute a directional ETF trade, or open returns to work around this gate. Such a change
would spend a different identity.

## Sealed empirical checkpoint — 2026-08-16

The no-return audit sealed the official quarterly-refunding archive page, each linked release page,
and the machine-readable tentative schedules available from the current Treasury archive path.
The source event manifest was also corrected to retain Treasury's `floating_rate` field. This
separates fixed-rate 2-year notes from 2-year FRNs; the earlier manifest had incorrectly made the
two records auctioned on 2015-01-28 appear ambiguous. The corrected manifest contains 2,037 coupon
auctions, including 153 floating-rate notes, with complete fixed/floating classification and SHA-256
`594cd1df7acbb6b91c3a778cfea0abd7bdec290d418b073c954ead858b22c285`.

For the locked 2013–2025 fixed-rate 2-year-note panel:

- 156 auction dates are unique after the FRN exclusion.
- 23 of 52 quarterly tentative schedules are available through the current official XML path.
- Those schedules bind 68 auctions, or 43.59% of the locked panel.
- Every bound auction had at least 13 XNYS sessions between schedule publication and auction,
  exceeding the published ten-session requirement where provenance exists.
- The 29 missing official-XML quarters are 2013Q1 through 2020Q1.

The archive workflow audited both original Treasury formats: machine-readable `auctions.xml` and
the separately captured `auctions.pdf`. The Internet Archive CDX index yielded 16 distinct XML
captures and 26 distinct PDF captures. Every payload and extracted PDF text is SHA-256 bound. The
PDF parser accepts only fixed-rate `2-Year NOTE` rows, excludes `2-Year FRN`, selects the auction
date from the three-date row, and cross-checks it against the sealed official event manifest. A
capture counts only when it proves the exact final auction date at least ten XNYS sessions before
the auction. Six tentative dates that differ from the final manifest are preserved as schedule
revisions and excluded from proof.

- Archived XML binds 47 of the 88 historical auctions through 2020Q1.
- Archived PDF binds 73 of 88; the XML/PDF union binds 77 without double counting.
- Combined with current official XML, 145 of 156 auctions are bound: 92.95% coverage.
- Eleven auction dates remain unproven; late captures are explicitly rejected as hindsight.
- The CDX corpus hash is
  `de2968f5dcffab2ffb4f72ac2d132c13a9537463448087087842a9e15a6c0800`.
- No price or return data was opened and zero return hypotheses were spent.

The unresolved-date revision audit then classified all 11 failures directly from 251 hash-bound
archive event rows and the official announcement dates:

- Five auctions had a different same-month tentative date visible at least ten sessions ahead.
- Two exact dates appeared in archive captures only three to eight sessions ahead.
- Three exact dates appeared only in post-event captures.
- One month had no captured schedule.
- Every formal announcement arrived only two to four XNYS sessions before auction.

Decision: `IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED`. More searching cannot turn a documented
tentative-date revision into exact T-10 knowledge. The family may not proceed to return testing
unless a new point-in-time schedule-revision state machine is registered with explicit cancel,
roll, late-announcement, and missing-update behavior. Otherwise the ten-session identity must be
retired. This is a lineage redesign, not permission to shorten the entry horizon after seeing
returns.

The sealed machine-readable result is published at
`/glassbox/treasury_tentative_schedule_audit.json`; the archive-only audit is published at
`/glassbox/treasury_wayback_schedule_audit.json`, and the PDF audit at
`/glassbox/treasury_wayback_pdf_schedule_audit.json`. The revision classification is published at
`/glassbox/treasury_calendar_revision_audit.json`.
