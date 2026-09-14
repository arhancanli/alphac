# Prospective payment ledger requirements

Draft; not installed or retroactively applied.

Each event must bind a simulated account/epoch, instrument and contract version, event type, quote/settlement currency, signed amount, effective time, original source time and local receipt time. Funding additionally requires source event identity, settlement schedule, position quantity at the applicable boundary, rate and exact mark receipt used in the calculation. Fee, transfer, correction and accrual events require explicit types; do not infer them from cash residuals.

Use a unique account/epoch/source/event key. An identical replay is a no-op; conflicting content under that key blocks. Commit the event, applied cash mutation and resulting account-state reference in one transaction. A crash before commit leaves all unapplied; a crash after commit must not apply cash again. Durable source-page cursors and interval manifests describe what was queried, including failures and delayed postings. Exhausted pages are not proof of final settlement.

Represent initial balances separately from flows. Persist corrections as linked reversing/replacement events, preserving original evidence. Unknown event types, absent position vintages, missing rate/price evidence, mixed currencies or unsupported multipliers block reconciliation. Positive and negative funding and fee rebates must retain signs. Do not require a nonzero payment to prove that a query succeeded; zero and missing are distinct.

Reconcile opening cash plus signed booked events to closing cash, and opening positions plus fills to closing positions. Bind liabilities/accruals separately from settled cash. USD reporting requires a dated conversion receipt. Report completeness per source and interval, never as a blanket claim based on the ending balance alone.

Acceptance tests must cover duplicate/conflicting events, process exit before/after commit, repeated recovery, funding around position changes, zero payments, late/corrected events, partial pagination, fees and transfers, missing source data and currency mismatch. Preserve legacy evidence and establish a separately dated prospective ledger boundary only after integration validation.
