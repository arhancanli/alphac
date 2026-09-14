# Live source capability phase — September 13, 2026

All four previously verified paper-account bindings matched fresh account responses. The bounded read-only run retained **31 endpoint responses**, including 16 account-identity reads. Each account completed the requested activity pagination and had identical account/position response bodies before and after the scan. This is evidence of accessible sources and observed agreement, not simultaneous valuation or settlement completeness.

The fixed activity window was September 11, 20:31:55 UTC through September 12, 20:31:55 UTC, selected from the local clock at invocation. The folder uses the September 13 Dubai session date. The local clock remains uncalibrated: the fresh SNTP check failed the existing 50 ms offset / 100 ms uncertainty policy. No time adjustment occurred, and this receipt does not identify which threshold failed or provide a numerical offset.

| Configuration | Responses | Activity records | Identity match | Pagination exhausted |
|---|---:|---:|---|---|
| Dedicated spot | 7 | 0 | Yes | Yes |
| Existing default paper | 8 | 3 | Yes | Yes |
| Existing equity paper | 8 | 3 | Yes | Yes |
| Existing vintage paper | 8 | 3 | Yes | Yes |

These are four configurations with distinct retained bindings, not proof of a complete four-sleeve partition map. In particular, the dedicated spot account is not the legacy simulated crypto-perpetual ledger. Three other historical/configured accounts remain unverified. A current identity match does not authenticate historical NAV rows or prove ownership, funding separation, source-cut timing or complete delayed flow coverage.

Parsed account/position/activity responses are retained in owner-only files under `~/.local/share/alphaforge/portfolio-source-capability-20260913/`; only sanitized capability summaries and hashes are in this research packet. Credential values, authentication headers and raw account bodies were not printed or copied into the report. Read-only GET requests used the existing fixed paper origin; no orders, history replacements, service changes or new epochs occurred.

Source review found additional crypto evidence gaps: quote money is documented as USDT, completion currently reuses the initial cycle time, and the `order_book_mid` label can conceal one-sided or empty-book fallback behavior. The [instrumentation specification](CRYPTO_RECEIPT_SPEC.md) defines prospective receipt, currency, mark-provenance and persistence requirements. It has not been installed in production.

One research correction accompanies this audit: the legacy acquisition adapter now calls its residual `accounting_residual_quote`, adds a missing currency/USD-conversion gate and emits schema v2. The prior v1 packet's `accounting_residual_usd` name and report's dollar notation were unsupported; their numerical residual was in quote units. Those archived files remain unchanged, and this is the correction record. No historical returns were recalculated or relabeled.

Validation: 115 focused collector, acquisition, valuation, paper-reader and activity tests passed; Ruff passed for the runner and changed adapter/tests. Four private packet file hashes and content hashes, all 31 receipt counts, identity assertions and activity-page counts are independently verified in `verification.json`. Source snapshots and a file manifest accompany this report. Live source access succeeded; operational timing and synchronized valuation remain blocked.

Phase complete. Combined Sharpe >2, maximum drawdown ≤11%, and 15+ qualified sleeves remain unestablished; no new strategy trial or admission occurred. Next proposed bounded phase: implement and test the crypto receipt schema and exact mark-provenance changes in the isolated research checkout, while separately diagnosing the clock failure read-only. Do not relax the clock or valuation gates merely to obtain a pass.
