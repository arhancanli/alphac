# Daily fee annotations and retained-balance comparison

Implemented date-level annotations and applied them to four retained paper captures. All nine executed USD fee records group under provider date September 11, preserving signed amounts and original record hashes. The dedicated spot scan contains no fees. None of the four captures establishes daily fee reconciliation.

The first and last account response receipts are approximately 1.47–2.04 seconds apart. They contain unchanged cash observations and fields for cash, equity, accrued fees and pending regulatory/TAF fees. They are not daily opening and closing balances. `last_equity` is not substituted for missing prior cash/accrual state. Unchanged cash over seconds does not explain fee recognition on the preceding provider date.

The annotation module retains balance fields separately, reports missing fields as unavailable rather than zero, and leaves the provider-date timezone unresolved. It does not sum accrued and pending fee fields into a liability or subtract them from equity: inclusion and overlap are not yet established. It reports no extra NAV deduction, no supported posting interval and no reconciliation clearance. Unknown activity/status/currency combinations remain unclassified rather than discarded.

**38 focused tests passed**, including four new annotation tests, with Ruff clean. Tests cover signed rebates, pending fees, missing accrual fields and avoiding double deduction. Existing mapping, evidence and payment-ledger tests remain passing. All four original capture hashes are checked before annotation; private annotation hashes and source-record membership are independently verified. Raw balances and record identities remain in owner-only private files.

This phase completes annotation and diagnostic comparison of the available observations, not a historical daily accounting bridge. Required missing evidence: boundary cash/holdings/liabilities, complete intervening flows, provider fee-field inclusion semantics and date-to-posting reconciliation. The empty scan is not evidence that these dependencies are satisfied.

No new broker calls, production changes, cash mutations, epochs, backfills or strategy trials occurred. The nine fees are not newly applied payments. Next proposed bounded phase: inventory retained daily account statements or balance snapshots and verify fee/accrual field semantics, before attempting a supported opening-to-closing cash bridge. Combined performance targets and the crypto cash residual remain unresolved.
