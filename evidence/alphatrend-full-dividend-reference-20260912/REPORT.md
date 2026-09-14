# Full-history dividend reference acquisition — September 12, 2026

Seventeen bounded Polygon dividend-reference GETs succeeded, one per fixed ETF, with dates 2003-01-01 through 2026-09-11 and a 1,000-record request limit. All responses reported complete pagination. Exact responses, request metadata without credentials, receipt timestamps and source hashes are retained. No subscription change was made.

Returned 1,111 records; the earliest returned ex-date is 2006-12-18, despite the requested 2003 start. Complete responses therefore do not imply complete economic history. Compared with 1,348 normalized Sharadar dividends, 1,101 have a unique same-symbol/ex-date reference record containing pay_date. 247 lack such a unique match, including four groups with multiple records. Missing matches are preserved in unresolved_payment_dates.parquet.

Multiple-record groups are EEM 2019-12-16, IEF 2009-11-02, SHY 2009-11-02 and SHY 2009-12-01. Their component records share a payment date and their cash sums are close to the Sharadar amounts, but they remain unmerged pending component/basis review. Two unique cash differences exceed the descriptive one-cent review threshold: EEM 2010-12-29 (0.05024 raw Sharadar versus 0.025122 reference) and TLT 2010-07-01 (0.31966 versus 0.309534). A threshold flag is not a correctness verdict or approval of all smaller differences.

This materially expands payment-date evidence beyond the previously retained 25 recent records. It does not prove original publication timing, resolve all cash units or approve a complete executable historical schedule. Receipt times remain actual acquisition times. No performance trial or new hypothesis occurred; union remains 238.
