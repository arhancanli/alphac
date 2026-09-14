# Issuer payment reconciliation — September 12, 2026

Recovered 19 of the previous 23 missing payment dates. Cross-checking previously
matched records also exposed three FXE date disagreements, which are now
quarantined. There are **seven unresolved events: four unmatched and three
conflicting**, with 1,341 accepted date matches out of 1,348 source dividends.
Date acceptance here is a current-vintage reference decision, not approval of
a historical execution schedule or a point-in-time data claim.

## New evidence

The [FXE product page](https://www.invesco.com/us/en/financial-products/etfs/invesco-currencyshares-euro-trust.html)
publishes the URL template for its public distribution API in its component
configuration. Its metadata identifies the CUSIP and currency. The saved
[FXE response](https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138K103/distribution?idType=cusip&productType=ETF)
contains 102 events, with explicit ex-date, record date, pay date and cash total,
including all 15 previously unmatched FXE events from 2006 through March 2007.
The issuer cash matches those source events within $0.000002/share.

The same issuer mechanism supplies DBA, DBC, UUP and QQQ histories. Five saved
responses contain 215 events in total. Exact joins recover DBC's December 2008
payment and QQQ's December 2003 payment as well. No near-date matching, interpolation,
payment-cycle assumption or deletion of unmatched dividends is used.

Each capture retains its response bytes, actual observation time and SHA-256.
Product-page ticker/CUSIP metadata is checked against the response identity.
The parser requires USD, unique ex-dates, complete dates in chronological order,
and finite nonnegative cash. Missing component fields remain missing; cash comes
from the explicit distribution total.

## Filing adjudications

The current Invesco API says December 31, 2008 for DBA and UUP. Their issuer
filings explicitly report payment to shareholders on December 30, 2008.
We accept December 30 for those two events and retain both competing values:

- [DBA issuer 2009 Form 10-K](https://www.sec.gov/Archives/edgar/data/1383082/000119312510038971/d10k.htm): $0.45/share, record date December 17, payment December 30, 2008.
- [UUP issuer 2009 Form 10-K](https://www.sec.gov/Archives/edgar/data/1383151/000119312510038999/d10k.htm): $0.17/share, same record and payment dates.

The filings were inspected through the web reader. Direct downloads returned
403; those responses are preserved and are not mislabeled as filings.
`filing_date_adjudications.json` retains a short, whitespace-normalized quotation,
source URL, actual review time, conflicting feed date and explicit decision for
each. Its hash binds the review note, not the unavailable full filing bytes.
These are manual source adjudications; rerunning the offline script checks their
joins and amounts, but does not re-fetch or independently authenticate the quotations.

## Existing payment conflicts

| FXE ex-date | Previous Polygon date | Invesco date |
| --- | --- | --- |
| 2007-04-02 | 2007-04-09 | 2007-04-10 |
| 2008-07-01 | 2008-07-08 | 2008-07-09 |
| 2011-10-03 | 2011-10-11 | 2011-10-10 |

These three were previously counted as matched. All now have a null adjudicated
date in `coverage_v3.parquet`; the earlier dates remain in original evidence and
`existing_payment_conflicts.parquet`. No source is automatically preferred simply
because it is the issuer or the most recently downloaded feed.

## Four unmatched events

- EFA 2003-12-16, source cash $0.47001/share.
- QQQ 2010-06-25, source cash $0.089/share.
- QQQ 2011-12-27, source cash $0.049/share.
- SPY 2006-06-16: issuer workbook places payment before record date; still quarantined.

The saved QQQ issuer history contains June 18, 2010 ($0.0893, paid July 30) and
December 16, 2011 ($0.16052, paid December 30). Those events already have their
own source records. They do not justify moving or removing the extra unmatched
rows without further evidence. Secondary SPY histories suggest July 31, 2006;
no primary confirmation was found in this pass, so the issuer inconsistency remains open.

## Validation and next work

22 targeted tests pass: nine new issuer-parser cases plus prior cash-revision
and distribution-extraction checks. Tests cover missing payments, wrong identity
or currency, duplicate dates, invalid totals, date ordering and missing component
preservation. Ruff passes, and the offline replay verifies the prior evidence seal.

The three previously applied cash revisions remain in the separate snapshot
from the preceding phase; no new cash edits or price-panel rebuild occurred.
Three historical price disputes and historical publication-time requirements
still block a complete backtest. No real signals, IC or strategy returns were
computed, and the hypothesis union remains 238. Sharpe 2 and 14+ qualified
sleeves remain unmet objectives.

Next: explicit confirmation of the three FXE disputed payment dates and the
SPY date, then determine whether the three unmatched EFA/QQQ source events are
valid distributions. The reconstruction must preserve that uncertainty until
the evidence supports a correction.
