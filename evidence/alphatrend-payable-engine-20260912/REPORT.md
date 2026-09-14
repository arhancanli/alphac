# Payable-date event-loop integration — September 12, 2026

Implemented an opt-in PayableEquityBacktester using the payable ledger inside a chronological daily-equity loop. The legacy engine source is unchanged and its exact source at the fork is retained. The new class forks run/action ordering and inherits existing execution, sizing, data-reading and result helpers. loop_changes.diff shows the changes to the retained methods.

## Event order

The preserved loop financed an interval before replaying orders stamped at its start, and passed the later loop timestamp to dividend accrual. The new loop applies ex-date splits/entitlements at the exact session boundary, settles payments due there, then fills the queued orders. It finances the resulting cash balance through each subsequent payment boundary, settles that payment, and continues through the modeled interval end. Borrow charges use post-fill holdings and session-open marks. Missing union sessions and delayed ex-date replay fail instead of skipping event time.

Payment boundaries can fall on a weekend or holiday. No artificial trading bar is inserted. A purchase on the ex-date earns no prior entitlement; selling before payment preserves the earned amount. Terminal receivables/payables remain in economic equity without entering settled cash. Missing payment schedules fail; there is no ex-date cash fallback.

Results retain separate dividend_settlements, terminal_pending_dividends and terminal_settled_cash fields in config, alongside the payment-schedule digest. The existing corporate-action log remains the economic accrual log.

## Validation

Eight new tests run on actual XNYS session dates. They cover exact legacy parity without actions/financing, a Saturday payment following a Friday sale, financing split at that payment, post-purchase financing cash, no entitlement for an ex-date purchase, unpaid terminal entitlement, a short payment obligation, same-day ex/payment, a missing schedule and a missing union session. Several tests assert multiple related properties.

135 tests pass across the new loop, payable ledger and existing engine, ledger, fills, settlement and quality gate. Ruff passes for both new files. No-dividend/no-financing fills and equity match the retained loop exactly.

The saved fabricated fixture buys 100 shares before the ex-date and sells before a Saturday payment. It records a 200 economic entitlement at the ex-date and a separate 200 cash payment on Saturday. Financing contains nine segments, including the weekend split. Fills, equity, accruals, financing and configuration are retained as audit artifacts; these are not AlphaTrend strategy results. Initial test-fixture construction errors (instrument market type, enum spelling and a keyword-only provider argument) were corrected before the passing run.

## Limits and next work

The class remains opt-in and supports daily equities only. It retains the existing engine's midnight session-label time model; it does not certify exact exchange-open or broker posting timestamps. Financing quotes are selected at each segment start, and interest is booked at segment boundaries. This explicit convention and the changed post-fill borrow timing require a separately registered candidate before a performance comparison.

This completes payment-ledger wiring into an executable engine variant, not full AlphaTrend activation. The new raw-label signal service and full synthetic feature panel still need runner-level binding to this engine. Source quality gates must cover feature, marking and forced-exit paths as well as queued fills. Full historical payment-date/availability evidence, lifecycle handling and the three disputed source prices remain unresolved. The current-vintage history is not passed off as historically known data.

No historical AlphaTrend performance/IC comparison, candidate admission or orders occurred. No new strategy hypothesis was evaluated; union remains 238. The Sharpe 2 / 14+ qualified sleeve target remains unmet.
