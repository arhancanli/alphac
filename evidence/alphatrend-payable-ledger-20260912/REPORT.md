# Payable-date dividend ledger — September 12, 2026

Added PayableDividendLedger as an opt-in subclass of the real backtest Ledger. It reuses normal fill, split, fee, funding and financing behavior while separating ex-date dividend income from settled cash. The legacy ledger and event-driven engine remain unchanged.

Each dividend must match an explicit, timely payment-date record. Entitlement is fixed once from the signed pre-ex position. Economic equity includes the outstanding receivable or payable, but cash and AccountState.cash_quote exclude it until the exact supplied payment timestamp. Selling the position or a later split does not change an already earned entitlement. Duplicate accrual and settlement calls do not double count.

The adapter uses the separately tested Decimal settlement component for pending balances. It fails on unknown, duplicate, mismatched or late-observed payment events. A skipped payment timestamp fails rather than silently changing the financing base. Financing intervals crossing a payment must be split, including when a caller tries to apply a spanning accrual after settlement.

## Validation

Ten new tests cover long/short cash and equity identities, payment timing and replay, sale before payment, split after accrual, missing/mismatched schedules, invalid schedules, skipped boundaries and actual financing calculations before and after payment. The combined new/legacy ledger, settlement and corporate-action suite passes 56 tests. Ruff passes for both new files.

In the long-position fixture, buying 10 shares at 100 leaves 9,000 cash. A dividend of 2 creates a 20 receivable; cash stays 9,000 and equity stays 10,000 when the stock marks at 98. Payment changes cash to 9,020 and receivables to zero without creating another gain. The short fixture mirrors the signed obligation. These are fabricated accounting scenarios, not investment-performance results.

## Data and remaining integration

All 25 dividends in the preserved recent Polygon packet include pay_date. Their receipts are current-vintage observations, not proof that the records were known before historical ex-dates. The full Sharadar ACTIONS history lacks payment dates. No dates or availability timestamps were inferred to make the ledger accept that history.

The ledger is not wired into the engine loop yet. The caller must merge payment timestamps with ex-date actions and fills, settle at those timestamps, and split financing intervals accordingly. Ledger marks, fills and other operations still rely on the caller's chronological event schedule. Constructor tests use generic ledger instruments to isolate accounting; equity-calendar end-to-end behavior is not yet certified. The existing engine result schema also needs separate cash-settlement reporting: inherited corporate-action cashflow_quote records represent economic accrual, and dividend_settlements() holds the distinct paid cashflows.

Full runner integration, lifecycle handling, historical availability and the three disputed source-price records remain pending. No performance comparison, candidate admission or orders occurred. No new strategy hypothesis was added; union remains 238.
