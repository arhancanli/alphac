# Prospective crypto observation instrumentation

Status: design specification, not installed. Preserve all existing cycle labels and historical records. Add versioned observation records; do not repurpose the legacy columns.

The inspected production `TradingLoop.run_cycle` reads its clock once and passes that same `now` through persistence and completion. Consequently `cycles.finished_ms` does not independently measure completion time. `TradingStore` declares quote money in USDT. `PaperBroker.position_marks_at` retains only price/source tuples. `_mark_or_entry` labels a successfully fetched book `order_book_mid`, although `_book_mid` can choose one side or fall back to entry price for an empty book. That label alone does not prove a two-sided observed midpoint.

Required records:

| Record | Fields and binding |
|---|---|
| Observation envelope | Unique observation ID, schema version, host/process/boot identity, logical cycle label, actual request/start/completion wall timestamps and monotonic timestamps, clock-sample reference and uncertainty; monotonic durations only within one host/boot |
| Price receipt | Venue, instrument and contract identity, base/quote/settlement currencies, source timestamp with semantics, sequence identifier when supplied, local request/receipt times, retained raw payload hash, bid/ask prices and sizes, exact selected mark rule and fallback reason |
| Account state | Account/partition identity, snapshot sequence, explicit currency balances, quantities, contract multiplier and exposure convention, receivables/liabilities, funding/fees and external/internal flow IDs, source and receipt times |
| Valuation binding | Exact account-state and price-receipt IDs used in arithmetic, declared cut and calendar, pending-event inventory and completeness evidence, currency conversion receipt and method for any USD reporting |
| Persistence | Append-only observation IDs and exclusive evidence objects; commit the valuation-to-receipt bindings transactionally. Retain interrupted observations with incomplete status. Never infer completeness from a terminal cycle label |

Use source numeric strings/decimals prospectively where supported. A conversion of legacy binary floats does not create exact original accounting. Verify contract valuation semantics before treating a perpetual position's notional as account equity. Stablecoin identity does not imply a one-dollar conversion; absent a bound conversion, retain quote-denominated accounting and reject USD aggregation.

The book reader must distinguish two-sided midpoint, bid-only, ask-only, empty-book entry fallback and missing-book fallback. Unsupported, stale or ambiguous marks remain evidence but cannot pass the valuation contract. Each mark must reference the exact received book, not a later refetch. Record actual completion clocks at completion rather than copying the initial sample. Do not invent source timestamps when the provider omits them.

Implementation acceptance cases: delayed cycle versus logical cut; positive measured duration; wall-clock reversal and reboot boundaries; missing/stale/one-sided/empty books; immutable price receipt reuse; partial persistence/crash; changed account state during collection; duplicate flows and delayed funding; USDT/USD conversion absent; contract multiplier mismatch; successful complete fixture with exact accounting. No runtime installation until separately reviewed integration evidence exists.

REST request durations alone cannot justify a relaxed valuation freshness limit. First establish source timestamp semantics, clock quality and account event coverage. The current midnight UTC draft remains out of force; any replacement policy must be prospective and preserve the prior baseline.
