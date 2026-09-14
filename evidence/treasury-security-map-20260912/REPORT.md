# Treasury security and hedge reference mapping

September 12, 2026. Issued-security reference candidates now cover all 3,039 event-session rows across 156 auctions and 2,975 dates. This completes a metadata diagnostic, not a tradable on-the-run portfolio. No prices, returns, orders or paid data were used; hypothesis union remains 240. Sharpe 2 and 14+ qualified sleeves remain unmet.

## Sources and selection

The original source-bound manifest matches its prior SHA-256 and retains the full 156-event panel. The original raw download already contains 5,794 bill records, but its derived manifest excludes bills and its selected fields omit inflation classification. A free Treasury Fiscal Data request returned all 4,903 identity records for 2012-01-01 through 2026-01-31, including the inflation-indexed flag. The response's field labels and pagination count are captured with the raw bytes and request receipt. No auction yields, prices, bid-to-cover or return fields were requested. [Official endpoint](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query).

Version 2 selects nominal fixed-rate two-year notes by current auction term, six-month bills by current 26-week term, and new nominal ten-year issues by original term. It requires announcement and auction dates before the decision date, issuance on or before it, and maturity afterward. Among eligible records it selects the latest issue date then auction date and refuses ties. This is an explicitly conservative issued-reference convention; it is not a verified market benchmark transition rule. Date-only fields and today's retrospective database do not prove historical information availability.

The 170 inflation-indexed records in the downloaded interval are excluded explicitly. All 156 event issue/maturity/auction dates agree with the earlier manifest; announcement dates agree with the sealed state-machine events.

## Findings

Nine two-year auctions reopened existing securities originally issued with five- or seven-year terms. Version 1 stopped on its incorrect new-two-year-issue assumption. Its source and failed protocol are preserved. Version 2 keeps these events and their CUSIP lineage; it does not discard them or substitute different auctions.

There are 1,118 pre-auction event-session rows before formal announcement. These continue to depend on the separately audited tentative-calendar state machine, not hindsight from the current event database.

There are 673 post-auction rows before the auction tranche's issue date. Source lineage divides them into 636 before the security's first issuance and 37 where the CUSIP already existed but the reopening tranche had not settled. `v2/issue_lineage.json` makes this distinction explicit. The older field `auction_security_issued` in `v2/mapping.json` refers only to the auction tranche and must not be treated as proof that the CUSIP itself was unavailable.

When-issued trading takes place after announcement and before issuance. Settlement differs from ordinary trading of already-issued securities. These mechanics explain why a date/CUSIP lookup alone is insufficient. [New York Fed WI explanation](https://libertystreeteconomics.newyorkfed.org/2020/11/treasury-market-when-issued-trading-activity/), [New York Fed auction process](https://www.newyorkfed.org/medialibrary/media/research/current_issues/ci11-2.html).

Within individual event phases, daily candidate references change 156 times for two-year notes, 609 for bills and 50 for ten-year notes. These are reference changes, not executed rolls or unique trading days. Reusing them as an automatic daily rolling strategy would introduce an unregistered rule and unmeasured costs. Likewise, the previously identified 64 overlapping sessions cannot yet be netted: quantities, settlement and actual instrument identities remain missing.

## Validation

Ten version 2 tests pass. Coverage includes TIPS/FRN/unknown-classification exclusions, reopened bills, fungible two-year reopenings, future/unissued/matured records, ambiguous selection and invalid chronology. Ruff passes the current mapper, audit, verifier and tests. The independent pandas verifier agrees on all 9,117 reference assignments across 8,925 distinct date/bucket combinations. Both protocol source bindings verify. The supplemental issue-lineage check uses earliest issue dates in the source-bound original manifest; it is not an independently archived security master.

## Next phase

Write one explicit trade-identity specification covering the existing literature position: pre-auction short two-year exposure, hedged with a six-month bill and ten-year note, reversed after auction. Resolve the on-the-run/when-issued transition, whether positions retain or roll CUSIPs, Treasury trading and settlement calendars, and overlap handling. Then bind the historical security/quote source and duration inputs needed to calculate hedge weights, financing and execution costs. Weights remain null; assigning equal notionals would not duration-match the hedge.

The existing author-review record remains unchanged. This diagnostic does not supply an independent technical review, a return preregistration or permission to claim a passing sleeve. There is no reason to purchase additional Databento credits for the completed metadata work.
