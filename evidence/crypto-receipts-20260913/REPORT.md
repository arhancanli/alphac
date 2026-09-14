# Crypto price receipts and clock diagnosis

Implemented opt-in decoded-book receipt recording in the isolated research paper broker. Separate durable START/END events bind the logical cycle label to independently sampled local start/completion times, declared host/boot identity and a recording-session ID. Each completed mark includes the decoded book, selected price/rule and content hashes. Exclusive private database creation and insert-only event writes preserve earlier records; synchronous commits retain START before the source call. Interrupted processes may leave incomplete records. No record confers valuation clearance.

The broker exposes receipt IDs for its last successful account mark without refetching the book. Source labels now distinguish two-sided midpoint, bid-only, ask-only, empty-book entry fallback and missing-book entry fallback. Numerical mark rules and simulated fill pricing are preserved. A failed durable write prevents returning a mark with a claimed receipt. A failed account mark invalidates the successful-mark timestamp cache.

This is the price-receipt portion of the prior specification. Currency, contract and account bindings remain explicitly absent in these receipts. Retained books are decoded legacy float values, not raw wire data or original decimal accounting. Reported book timestamps remain semantically unverified; caller-stamped timestamps are not promoted into authenticated source times. Host/boot identifiers are declarations. Recording a clock reversal does not make it acceptable for valuation.

The recorder is opt-in via `PaperBroker(receipt_recorder=...)`; no scheduler or production loop installs it. It records observation completion independently but does not rewrite the legacy cycle completion column. Durable transactional account-to-price binding, full flows/accruals, USD conversion, contract semantics and live-source timestamp instrumentation remain outstanding. A receipt ID cache alone is not durable account reconciliation. No production database migration, market-return trial, epoch or admission occurred.

## Read-only clock findings

Three bounded SNTP samples against `time.apple.com` reported:

| Sample | Offset (ms) | Uncertainty (ms) | Existing limits |
|---|---:|---:|---|
| 1 | +322.781 | 463.998 | Both fail |
| 2 | +411.627 | 303.947 | Both fail |
| 3 | +402.458 | 287.073 | Both fail |

Policy limits remain absolute offset ≤50 ms and uncertainty ≤100 ms. These unauthenticated samples confirm both failures, not their cause or the true clock correction needed. No system clock adjustment or threshold relaxation was attempted. Raw outputs are retained in `clock-diagnosis.json`.

## Verification and phase boundary

**79 tests passed**, including 11 new receipt tests plus existing broker, funding, clock and acquisition tests. Ruff passed. Tests exercise exact price labels, retained decoded books, missing/failed reads, cancellation, clock reversal, exclusive persistence, cache reuse and failed END writes. A synthetic two-event receipt and its hashes were independently checked. Production `execution/paper.py` still matches the previous phase hash. Validation logs, source snapshots and a manifest accompany this report.

The initial test run caught a keyword-only constructor error in the new fixture; it was corrected before the passing run. No failed strategy result was regraded. The combined Sharpe >2, max drawdown ≤11% and 15+ qualified sleeve goals remain unestablished.

Next bounded phase: bind a complete simulated account snapshot transactionally to the exact price receipts and test interrupted persistence/recovery. Keep account/currency/source-time gaps explicit. Clock remediation requires a separate operational change; these samples alone do not justify stepping the clock of a host with existing scheduled jobs.
