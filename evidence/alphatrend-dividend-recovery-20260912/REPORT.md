# Dividend recovery and cash revisions — September 12, 2026

Recovered 16 further payment dates, reducing the remaining gaps from 39 to 23.
There are now 1,325 matched payment dates in the original 1,348-dividend inventory.
Applied three corroborated cash corrections to a separate action snapshot, with
the other 1,355 action rows unchanged. No historical panel or return trial was run.

## SPY source recovery

The [State Street distribution page](https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions)
links the saved [historical workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx).
The parser requires the distribution sheet's expected headers, SPY's CUSIP
78462F103, unique ex-dates, nonnegative component totals and ordered dates.
Exact ex-date joins recover 16 older dates. Cash precision differences remain
marked for review; recovering a date does not approve the vendor cash amount.

One source row is quarantined: worksheet row 9108 reports SPY ex-date June 16,
2006, record date June 20, 2006, but payable date June 16, 2006. We do not accept
payment before the record date or replace it using an assumed quarterly rule.
`spy_gap_review.parquet` retains all 17 matches and their date decisions;
`spy_issuer_distributions.parquet` preserves the issuer's original dates and cash.

The initially discovered SSGA PDF contains DIA history, not the needed SPY
history. It is retained as an unsuccessful source lead, not used for joins.

## Applied cash revisions

Both the saved issuer table and Polygon raw response agree on the following
amounts and payment dates. None requires a pre-split share-basis assumption.

| Event | Original raw cash/share | Revised raw cash/share | Pay date |
| --- | ---: | ---: | --- |
| EEM 2010-12-29 | 0.050240 | 0.025122 | 2011-01-05 |
| TLT 2010-07-01 | 0.319660 | 0.309534 | 2010-07-08 |
| TLT 2010-11-01 | 0.309500 | 0.319415 | 2010-11-05 |

Primary references: [BlackRock EEM](https://www.blackrock.com/us/individual/products/239637/ishares-msci-emerging-markets-etf)
and [BlackRock TLT](https://www.blackrock.com/us/individual/products/239454/ishares-20-year-treasury-bond-etf).
`cash_corrections.json` binds each old event identity, old and new cash, actual
issuer observation time and issuer/Polygon evidence hashes. The script verifies
the prior evidence seal and the Polygon response hashes before agreement checks.

`revised_actions.parquet` is a derivative snapshot, not a replacement for the
original. Revised rows receive new event IDs and retain their original event ID
and source value. The normalization field explicitly identifies a reviewed raw
cash revision. Existing panels still bind the old snapshot and must be rebuilt
before this snapshot can be used. `coverage_v2.parquet` deliberately retains
original source cash comparisons; the revision JSON is the correction authority.

The correction function rejects stale identities/amounts, repeat application,
duplicate corrections, invalid cash, backdated revision observations and missing
distinct evidence hashes. It does not independently authenticate source contents;
the offline assembly script performs that verification. Neither component proves
historical first publication time.

## Remaining evidence needs

23 gaps remain: FXE 15, QQQ 3, and one each SPY, DBA, DBC, EFA and UUP.

An [FXE issuer filing for April 2007](https://www.sec.gov/Archives/edgar/data/1328598/000089706907001383/cmw2880.htm)
contains the early distribution amounts with a generic Date column, matching
the existing ex-dates. It does not establish distinct payable dates. The web
reader could inspect it, but the direct capture returned 403; that response is
retained and is not treated as a saved issuer filing. No FXE dates were imputed.
An [agriculture-fund filing](https://www.sec.gov/Archives/edgar/data/1383082/000119312510038971/d10k.htm)
is a further research lead for 2008 distributions, not accepted evidence yet.

The three historical price disputes, remaining cash precision differences and
historical observation-time requirements also remain open. No production or
paper-trading configuration changed. The strategy hypothesis union remains 238;
Sharpe 2 and 14+ qualified sleeves remain unmet objectives.

## Validation

Seven new cash-revision tests plus the action-normalization and prior extraction
tests pass: 19 total. The real-data replay verifies exactly three changed rows,
all 1,355 other original rows/columns unchanged, and the original source seal
intact. Ruff passes. `closure.json` binds implementation, tests, source evidence,
and outputs. The next bounded step is to resolve the anomalous SPY payable date
and retrieve explicit FXE payment records, then address the remaining seven
non-FXE/SPY events before rebuilding the complete historical panel.
