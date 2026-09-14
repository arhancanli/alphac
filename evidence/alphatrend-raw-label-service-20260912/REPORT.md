# Raw-label trend signal integration — September 12, 2026

Added an opt-in RawLabelTrendSignalService that gets holding-return labels from RawHoldingLabelProvider instead of computing forward returns from feature-frame open_px. The frozen causal service is unchanged. The new service retains the fixed calendar anchor, fixed IC decision grid, existing shrinkage and exit-session release convention. Its trial binding includes the raw input digest, action snapshots, observation mode and label convention.

The provider uses exact raw opens, split-adjusted share quantities and dividend receivables without reinvestment. It deep-copies the price route and freezes mapping/snapshot references. Labels remain unavailable before exit close; prospective snapshots first observed after fixed release cannot backfill earlier IC observations. Missing inception endpoints stay NaN on the original grid, while printed zero-volume or disputed endpoints fail. Unknown instruments and malformed decision/cutoff timestamps fail. Current-vintage diagnostics remain explicitly labeled.

## Verification

All 119 existing 21-session holding labels replay exactly through the provider using the preserved recent SIP/Polygon packet. This is the same accounting sample, not another performance experiment. Placeholder signal columns in that replay only satisfy route validation; they are not used for forecasts or labeling.

Six new integration tests use fabricated data, testing dividend labels and maturity, feature-open separation, exact full/prefix parity, expected dividend-driven IC weights, late-record rejection, inception/dispute behavior and input isolation. Forecast arrays are held fixed during feature-open perturbation; no claim is made that a strategy is insensitive to changed features. An initial test expected a weight above 0.9; the existing shrinkage produces exactly 8/9, 1/18, 1/18 in that fixture, and the test now checks those values. No shrinkage setting was changed.

51 targeted tests pass across the new service/provider, retained causal service, labels, routing, dividend settlement and quality-gate engine scenarios. Ruff passes for all four new files. The executed replay runner was preserved before a nonsemantic line-wrap fix; both sources are hash-bound.

## Remaining work

This connects raw labels to the signal service's weight calculation. Full synthetic feature ingestion, producer/backtest runner wiring, dividend payment-date cash integration and historical data provenance are not complete. Three historical price disputes remain unresolved. The new provider does not create a point-in-time historical record from current-vintage data.

Dividend receivables are included in economic labels, not credited as spendable execution cash. The separate settlement component still needs engine integration with real payment dates. No actual AlphaTrend forecasts/IC or strategy performance comparison was run in this phase. No candidate was registered or admitted, no orders were sent, and the hypothesis union remains 238. Sharpe 2 and 14+ qualified sleeves remain unmet.
