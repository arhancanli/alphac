# Later-window feasibility and research handoff

The outcome-free audit selects January 2012 as the first full calendar year after the last unresolved price/payment event. Through September 11, 2026, all 17 ETFs have exactly 3,694 XNYS sessions: 62,798 rows, zero flagged prices, zero zero-volume bars, 830 dividends with payment-date references and four splits. Existing source seals verified before reading. No strategy forecasts, IC estimates or returns were computed.

This resolves the question of whether the six old disputes must block every research window. They need not. It does not establish point-in-time data or independently verify every cash amount or volume. The USO volume difference and retained dividend precision differences remain limitations.

All 834 action observations postdate their economic dates. The existing runner refuses this at payment validation; the payable ledger repeats that check. The inherited engine action loader also calls `require_known_before_boundary`, and its reader applies an `available_at` cutoff. Merely allowing late payments in the runner would leave execution incorrect or blocked. Original code and actual observation timestamps remain unchanged.

## Concrete implementation sequence

1. Add an explicitly retrospective execution path that uses the sealed current-vintage action/payment schedule. Preserve observed timestamps and bind the selected vintage in results. Keep prospective and default settlement behavior strict. Verify split quantities, long/short receivables, exact payable dates, financing boundaries, terminal pending cash, and rejection of incomplete schedules. Ensure every expected action applies exactly once, including records observed after the simulated end date.
2. Rebuild synthetic prices from the first 2012 raw bar. Do not simply reuse full-history signal levels or the old 2004 IC anchor. Restart rolling state; freeze a new anchor and label release grid. Draft warmup is 2012–2014, with evaluation beginning in 2015. This is a new development comparison, not an untouched test; dates were selected without reading outcome files in this audit.
3. Bind identical reviewed data, 17 instruments, 63/126/252 signals, 21-session labels, 10-session rebalance cadence, continuous books, and parent modeled base costs for baseline/candidate. Resolve and freeze all settings and comparison criteria before registration. Preserve actual source capture timestamps. Any observed-cost inputs need their own valid availability evidence.
4. Register each actual decision path before computing signals/IC/returns. A doubled-cost gate that changes decisions requires separate identity accounting. Report 252-session metrics, after-cost performance, drawdown, turnover and sensitivity. Do not substitute historical Sharpe from the parent construction.

Registration is pending executable retrospective accounting and complete configuration binding. This artifact is a feasibility audit, not a reservation or performance result. Hypothesis union remains 238; no admission or activation follows from this audit.

The companion vendor requests are concrete drafts and have not been sent. Sending messages requires explicit user authorization; local preparation and research can continue independently.

## Validation

The audit verifies both prior seals, exact per-symbol XNYS calendar coverage, unique sessions, feature routing and equality of dividend/reference event keys. Two initial audit attempts failed on calendar API date handling before any output was written; corrected use of timezone-naive calendar bounds and its generated session index passed. This script does not prepare executable runner inputs.
