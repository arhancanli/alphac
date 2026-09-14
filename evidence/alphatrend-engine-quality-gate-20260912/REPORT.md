# Engine quality gate — September 12, 2026

Added QualityGatedFill through the existing event-driven backtester's fill_model interface. It stores an immutable map of reviewed raw BarView records keyed by exact instrument and bar timestamp. Every queued fill requires a present eligible record and exact OHLC, base volume and quote-volume equality. Missing/disputed records and substituted synthetic prices or changed liquidity fail before ledger application. Eligible records must have positive finite recorded volume. Instrument mismatch and pre-decision bars also fail.

Eight new tests exercise six actual-engine scenarios plus constructor invariants: accepted raw data, disputed data, missing review coverage, price substitution, liquidity substitution and zero volume. The clean engine run matches both fills and equity exactly against the existing ungated reference. These are small deterministic hourly engine fixtures, not ETF historical performance or XNYS end-to-end certification. The full engine/fill/routing regression selection passes 89 tests. Ruff passes for both new files.

An initial test expected a zero-valued rejection counter to exist on the clean run. The engine omits that unused key; the assertion now treats an absent count as zero. A later exact-parity assertion initially used the DataFrame comparator for the equity Series. The failed log and test source are retained; using the Series comparator with exact equality passes. No engine accounting change was required. Existing frozen candidate and engine source were left as found.

## Scope limits

This completes queued-order quality enforcement at the engine interface. It does not integrate the entire AlphaTrend strategy. The engine currently reports these fill refusals through its existing dropped_no_bar_liquidity counter. Forced liquidation and marking paths bypass this fill interface and are not covered; full candidate validation must gate source data before engine entry too. Synthetic/raw input separation, raw holding-label integration, dividend payment-date settlement, lifecycle handling and historical observation provenance remain pending.

Three historical price disagreements remain unresolved. The Firecrawl CLI was unavailable; fallback web searches for the exact DBA/UUP dates yielded no usable corroborating market records. No prices were inferred from search snippets, substituted from another vendor, or discarded. Existing Polygon timeframe denials and vendor clarification draft remain available in prior evidence. No vendor message was sent.

No AlphaTrend performance run, strategy admission or order submission occurred. No strategy hypothesis was added; cumulative union remains 238. Full-history performance testing remains gated by source adjudication and the remaining accounting integration.
