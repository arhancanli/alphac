# Breadth source review — 11 September 2026

Agricultural forecast revisions remain the first data-development priority.
Drug exclusivity needs historical disclosure evidence before a signal can be
specified. Convertible issuance pressure is parked pending a stronger return
identity and execution access. This pass admitted zero sleeves and ran zero
return trials. Sharpe 2 and 14+ independent sleeves remain objectives, not results.

## Agricultural forecast revisions

The fixed 2015–2025 audit retrieved 15 official archive index pages, preserving
HTML and SHA-256 hashes. It found 131 distinct date labels across 130 of 132
calendar months. These are index entries, not 131 verified original reports.
January 2019 and October 2025 have no indexed entry. December 2018 has two.
The evidence is `evidence/breadth-source-audit/wasde-release-index.json`.
[Official archive](https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates).

Both December entries were downloaded. Both identify report 584; their text
begins at page 8. The December 14 file changes two values in the U.S. milk table
relative to December 11: projected commercial exports 11.0 to 10.0 and domestic
commercial use 215.3 to 216.3. The full text diff is preserved. They are distinct
versions of one monthly report; the later values must not replace earlier
values in an earlier decision. Exact correction publication time is unverified.
[December 11 file](https://esmis.nal.usda.gov/sites/default/release-files/3t945q76s/0r967743q/2227mt437/latest.txt),
[December 14 file](https://esmis.nal.usda.gov/sites/default/release-files/3t945q76s/4q77fw19m/m039k909f/latest.txt).

USDA's January 2025 report notes that January 2019 was not published because
of the partial government shutdown. November 2025 reports funding disruption
and limited inputs, with comparisons to September. The missing October archive
entry is consistent with that interruption; a separate October cancellation
notice has not been verified. Neither gap should be interpolated into a release.
[January 2025 report](https://esmis.nal.usda.gov/sites/default/release-files/3t945q76s/2801rc34n/1z40nn26q/wasde0125.pdf),
[November 2025 report](https://esmis.nal.usda.gov/sites/default/release-files/795643/wasde1125.pdf).

Next specification: reconstruct original U.S. corn, wheat and soybean balance
sheets using report ID, version, crop year, geography, units and publication
availability. Treat these crops as one provisional family, not three sleeves.
Separate forecast revisions from market surprises: no historical consensus
series has been established. A dated forecast revision alone is not evidence
of delayed repricing. Do not compare different crop years or revised prior-month
columns as if they were original releases. Verify archived PDFs where text
omits narrative and timing information. Post-release bid/ask, depth, commissions,
contract selection and rolls remain required before any return test. Trend,
carry and seasonality overlap remains unresolved.

## Drug exclusivity transitions

The targeted current API probe retrieved ten records containing patents:
31 patent entries, seven missing submission dates, and three exclusivity entries.
This is a convenience sample, not a population completeness estimate. Its
metadata says last updated 2026-09-11. The frozen response and schema summary
are in `evidence/breadth-source-audit/orangebook-existing-patents.json` and
`orangebook-schema-audit.json`. Two earlier date-filter requests failed; an
existence query recovered schema evidence, not historical coverage.
[API query](https://api.fda.gov/drug/orangebook.json?search=_exists_%3Apatents&limit=10).

FDA defines patent submission date as receipt by the agency, which does not
establish public dissemination time. Expiry dates likewise do not record when
investors first knew them. Current records include much newer patent submissions
than the original drug approval: backdating the entire record to approval would
introduce hindsight. [FDA data definitions](https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files).

FDA describes changes in ownership/marketing status, possible exclusivity
waivers, and multiple patent considerations. Therefore an expiry-only calendar
cannot identify actual generic launch or issuer revenue loss. Current applicant
names also cannot supply historical listed-parent ownership automatically.
[FDA preface, sections 1.8 and 1.11–1.13](https://www.fda.gov/drugs/development-approval-process-drugs/orange-book-preface).

Decision: historical-vintage and issuer-mapping gate remains. Require dated
monthly snapshots, first-public change evidence, application/product identifiers,
then-current economic ownership and disclosed product revenue. A complete
historical archive was not established in this pass. Preserve this as a data
lead; do not invent a backtest from today's records or revive killed earnings
narrative variants under a new name.

## Convertible issuance pressure

Reviewed the targeted methods and results of Choi, Getmansky and Tookes,
*Convertible Bond Arbitrage, Liquidity Externalities and Stock Prices*,
September 2006 draft. The main sample covers 1991–2005, using SDC issuance
information and monthly exchange short-interest data. Its section 6.3 finds
bond/stock exposures and autocorrelated fund returns, but no relationship of
returns to past flows, arbitrage activity or proceeds in those regressions.
This weakens the proposed flow-based return identity; it does not disprove every
convertible strategy. Monthly changes in short interest around issuance are
explanatory measurements and cannot simply be used as information available
on the issuance date. The downloaded paper is hashed; this is a targeted review,
not a completed replication or review of every later publication.
[Original paper](https://users.nber.org/~confer/2006/mmf06/tookes.pdf).

Current FINRA schedules distinguish position settlement dates from publication
dates. Historical analysis needs historically applicable publication schedules;
today's schedule cannot be imposed on the older sample.
[FINRA reporting schedule](https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest).

Decision: park return testing. Reopening requires dated issue terms and public
announcement timing, executable bond/equity prices, borrow availability/cost,
financing and hedge accounting, plus evidence of incremental return beyond
credit, volatility and liquidity exposure. This is not an Alpaca spot sleeve.

## Verification and effect on the goal

The new archive auditor passes Ruff. Offline replay against all 15 hashed pages
reproduces every indexed release record, the two gaps and the December duplicate.
Empty archive responses and oversized bodies fail collection. Verification is
recorded in `evidence/breadth-source-audit/audit-verification.json`.
These checks validate collection behavior, not historical timestamp authenticity.

The research frontier and next actions were updated. Existing admission criteria
and failed-family history remain intact. No market prices were opened for these
leads, no performance results were generated, and no broker orders were sent.
The concrete gain is a reproducible archive inventory, an observed report-version
hazard, a quantified FDA schema limitation, and a weaker convertible hypothesis
removed from immediate testing priority.
