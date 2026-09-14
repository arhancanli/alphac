# Paired-input research runner — September 12, 2026

Connected isolated synthetic feature history, raw holding-return labels, paired-price allocation and the payable-date engine in TrendRunnerBundle. A controlled six-instrument XNYS fixture now runs the real feature engine, fixed 63/126/252 trend service, allocator and quality-gated fills together. This is diagnostic wiring, not an AlphaTrend performance trial.

Signal and execution lakes are separate. The signal lake carries synthetic OHLC and no corporate-action table, preventing adjustment reapplication; the raw lake carries raw OHLC and economic actions. Both preserve raw volume. Quote volume is an explicit raw-close-times-raw-volume proxy, not an observed trade-notional feed. Membership starts at each symbol's first supplied bar; this is an explicit diagnostic construction, not historical universe evidence.

The allocator needed an additional separation: covariance now uses synthetic close returns with no missing-value forward-fill, while existing share quantities are valued using raw closes. The opt-in PairedPriceBlendStrategy forks the rebalance method and keeps the original unchanged. Tests intercept allocator inputs on nonflat books and verify raw-price position weights exactly. Full fixture fills remain near raw opens even though synthetic price levels are scaled by different factors for each instrument.

The bundle binds input content, payment schedule, settings and computed signals. Mismatched settings and substituted signal frames fail. Staged parquet content is verified before component construction. Disputed prices block the whole feature history before writes, missing payment schedules fail, and this bundle explicitly refuses prospective mode because historical price-receipt timing is not verified. No existing data lake is modified.

47 targeted tests pass, including five bundle tests plus existing allocator, raw-label, payable engine/ledger and quality-gate tests. Ruff passes for all three new source/test files. Initial integration failures were imports used only for typing and an incorrect dataset enum; these were corrected before the passing end-to-end run.

## Real history and remaining gates

historical_preflight.json preserves the pre-acquisition inventory: 93,444 rows, three disputed prices, one zero-volume bar, 1,348 dividends and only 25 saved recent payment-date matches. The actual runner refuses these data before computing real signals or returns.

A subsequent bounded Polygon reference acquisition recovered 1,111 dividend records, with 1,101 unique symbol/ex-date matches containing a pay date. See ../alphatrend-full-dividend-reference-20260912/coverage.json. There remain 247 Sharadar events without a unique pay-date match, including four multiple-record groups. The latter share payment dates but their economic components have not been approved for merging. Two unique matches differ in cash amount by more than one cent. Historical first-publication timing remains unproven.

The components are connected for controlled diagnostics. Historical price/action adjudication, full payment coverage, lifecycle evidence, actual-clock/prospective proof and registration of the combined changed methodology remain necessary before the real comparison. Runtime mutation during an active read is not prevented by a filesystem lock; packet verification is performed at component construction. Future production hardening must preserve immutable runtime inputs.

No real AlphaTrend signals/IC/portfolio returns were computed. Fabricated fixture outputs are not sleeve results. The strategy hypothesis union remains 238; no candidate admission or paper/live activation occurred.
