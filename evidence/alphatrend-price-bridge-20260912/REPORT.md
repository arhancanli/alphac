# AlphaTrend action-aware close bridge

Implemented `forward_close_reinvestment_v1` as an isolated, deterministic signal
close-index continuation. It advances exactly one XNYS session at a time:

`index_next = index_previous * (new_shares_per_old * raw_close_next + cash_per_old_share) / raw_close_previous`

This models reinvestment at the ex-session close for a signal index, not actual
payment-date cash availability. Execution prices, dividend accounting, volume,
open/high/low values and the frozen strategy are not changed. A simultaneous
split and dividend is rejected because the vendor share basis is unresolved.
The old generic dividend adjustment path was not reused: its source explicitly
notes unresolved availability/parity behavior.

The new bridge checks finite positive prices, consecutive sessions, decision
windows, complete effective-date coverage, snapshot receipt timing and digest,
action identity, symbol, range and duplicate events. An empty action list is
accepted only with an explicitly complete coverage snapshot. The caller must
supply verified provider evidence; hashes and completeness assertions alone do
not establish independent truth. Future effective actions do not affect today's
index. Late receipts fail in PROSPECTIVE mode; the explicit current-vintage
DIAGNOSTIC mode does not claim historical availability.

34 bounded Polygon GETs succeeded, producing 25 reference records across the 17
ETFs for May 1–September 11. Raw bytes and receipts are retained separately.
Declaration dates have not been substituted for first-observed timestamps.
The diagnostic binds both split and dividend response receipts, verifies their
hashes, HTTP/JSON status, query scope, pagination absence and supported currency
and action types before feeding the bridge.

All 238 missing symbol/session closes were extended from the frozen August 21
anchor into a separate diagnostic parquet. No lake splice or signal computation
occurred. The Treasury overlap test anchors at May 1 and compares 77 subsequent
sessions with the frozen Yahoo-adjusted history:

| ETF | Maximum absolute adjusted-level difference |
| --- | ---: |
| IEF | 0.164788 bp |
| SHY | 0.605136 bp |
| TLT | 0.207699 bp |

These are price-level differences after anchoring, not portfolio performance or
the daily-return differences reported in the earlier raw-price audit. Exact Yahoo
parity is false for all three. Close agreement does not establish unchanged
forecasts, weights, or historical point-in-time validity.

Validation: 54 tests passed across bridge, history/daily capture, producer and
journal. New bridge cases cover cash distributions, forward/reverse splits, late
receipts, invalid/incomplete snapshots, repeated sessions, duplicate actions,
ambiguous share basis, future actions and pre-close decisions. Ruff and diff
whitespace checks pass. Source and response bindings verified at closure.

Remaining before producer integration: reconcile the precise adjustment
convention and residual provider differences; define the open/OHLC mapping needed
by causal forward labels; establish full-prefix provenance and clock evidence;
bind the adapter and actual account context. If this economic index replaces the
old Yahoo convention, register that changed candidate before strategy returns.
No new hypothesis or return measurement; union remains 238. No paper activation.
