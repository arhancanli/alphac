# Historical dividend adjudication — September 12, 2026

Recovered 208 payment dates from current issuer histories and QQQ's former ticker.
The 1,348-event source inventory now has 1,309 matched payment dates and 39 gaps,
down from 247. This is a reference reconciliation, not an approved payment schedule
or evidence of improved strategy performance. Original actions and panels remain intact.

## Sources and method

Saved six BlackRock product pages, extracted 1,065 distribution rows from the
HTML-escaped `componentprops.distributionTableData` field, and joined exact symbol
and ex-date. Payable dates come from `payableDate`; cash comes from
`totalDistribution`, preserving income and capital-gain components separately.
Some old component values are missing or rounded: missing values remain missing,
and differences between the published total and component sum remain recorded.
The largest component-sum discrepancy is $0.000045 in published share units.

Primary pages: [EEM](https://www.blackrock.com/us/individual/products/239637/ishares-msci-emerging-markets-etf),
[IEF](https://www.blackrock.com/us/individual/products/239456/ishares-710-year-treasury-bond-etf),
[SHY](https://www.blackrock.com/us/individual/products/239452/ishares-13-year-treasury-bond-etf),
[TLT](https://www.blackrock.com/us/individual/products/239454/ishares-20-year-treasury-bond-etf),
[EFA](https://www.blackrock.com/us/individual/products/239623/ishares-msci-eafe-etf),
[IWM](https://www.blackrock.com/us/individual/products/239710/ishares-russell-2000-etf).

One bounded Polygon QQQQ request returned 23 records without pagination. The
saved Sharadar lifecycle row confirms the QQQQ→QQQ change on March 24, 2011.
The alias applies only before that date, and all 23 records fill previous gaps.
Issuer histories recover the other 185 dates: EEM 6, EFA 4, IEF 53, IWM 16,
SHY 53, TLT 53. Acquisition receipts preserve actual observation times and hashes.
Bare product-ID URLs returned 403; the full public product URLs returned 200.
Those unsuccessful responses are also preserved. No subscription purchase occurred.

## Duplicate groups and cash differences

The issuer total confirms that these are combined distributions, not rows to drop:

| Fund and ex-date | Issuer total per share | Payment date |
| --- | ---: | --- |
| EEM 2019-12-16 | 0.929022 | 2019-12-20 |
| IEF 2009-11-02 | 0.769909 | 2009-11-06 |
| SHY 2009-11-02 | 0.190131 | 2009-11-06 |
| SHY 2009-12-01 | 0.580181 | 2009-12-07 |

The last SHY row comprises income 0.084858, short-term gain 0.098608 and
long-term gain 0.396715. Polygon's CD classification does not describe these
components accurately. The retained [OCC notice](https://www.miaxglobal.com/sites/default/files/alert-files/EEM_Distribution_46168.pdf)
independently confirms EEM's 0.266326 special component. A
[CME notice](https://www.cmegroup.com/tools-information/lookups/advisories/clearing/files/Chadv09-483.pdf)
confirms IEF's 0.508986 long-term gain; direct download timed out, so the saved
issuer table is the reproducible local source for the complete IEF event.

Two source cash disagreements exceed one cent per share:

| Event | Sharadar raw cash | Issuer total, also matching Polygon |
| --- | ---: | ---: |
| EEM 2010-12-29 | 0.050240 | 0.025122 |
| TLT 2010-07-01 | 0.319660 | 0.309534 |

Across the newly reviewed histories, 144 values exceed a strict comparison
tolerance of 0.000006 multiplied by the later split factor (minimum factor one).
Only 12 exceed $0.001/share, including those two. These counts are not 144 proven
economic errors: many reflect variable source precision. TLT 2010-11-01 is a
further substantive disagreement: 0.309500 versus issuer 0.319415.
All differences remain in `cash_conflicts.parquet`; none are silently accepted.

For pre-split issuer amounts, comparison uses the existing later-split product.
This share-basis interpretation is explicitly flagged as inferred, not newly
proven by issuer documentation. Payment-date matching does not depend on it.

## Remaining work and safeguards

The 39 unmatched events are SPY 17, FXE 15, QQQ 3, and one each DBA, DBC, EFA,
UUP. An unmatched source event might itself be erroneous; do not invent a payment
date. QQQ 2010-06-25 and EFA 2003-12-16 particularly need issuer review.

Actual first publication times are still unproven. Today's issuer pages cannot
be assigned historical observation timestamps. The current runner's settlement
contract therefore remains closed, as do the three historical price disputes.
No real strategy signals, returns or IC were computed, no trading profile was
activated, and the hypothesis union remains 238. Sharpe 2 and 14+ qualified
sleeves remain objectives, not achieved results.

The offline script validates source hashes, unique ex-dates, equal column lengths,
valid date ordering, nonnegative totals, alias bounds and lifecycle evidence.
Six extractor tests pass, including tampering, malformed dates/lengths, signed
cash rejection, combined distributions and missing-component preservation.
Ruff passes. `closure.json` binds the script, tests, original input tables and
all local evidence files. Next: issuer verification of the 39 gaps and a reviewed
cash-correction overlay before rebuilding any historical panel.
