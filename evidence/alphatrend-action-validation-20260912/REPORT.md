# AlphaTrend corporate-action unit validation — September 12, 2026

Validated the newly acquired Sharadar history before connecting it to raw-price accounting. This phase computes action and price consistency diagnostics, not strategy returns or IC.

## Results

- Normalized 1,358 economic events: 1,348 dividends and 10 splits. Preserved 12 listing/ticker lifecycle records separately.
- Converted 19 dividends from the vendor's split-adjusted units to cash per share on the ex-date. Source records remain unchanged.
- All action dates have both an acquired price and a preceding-session price. Maximum split-ratio discrepancy against closeunadj/close adjustment factors is 0.969 basis points; this is descriptive agreement, not independent proof of every source event.
- Matched 25 retained Polygon dividends by symbol/ex-date. Largest absolute cash difference is $0.000004 per share.
- 109 tests pass: 99 capture, bridge, label, routing, settlement, normalization and producer tests plus 10 existing corporate-action contract tests. Ruff passes for the three new source/test/script files.

## Accounting rules established

The [Sharadar action dictionary](https://sharadar.com/docs/descriptions) defines dividend amounts on a split-adjusted basis and split ratios as new shares per old share. For this complete current vintage, multiply a dividend by the product of later effective splits for the same symbol to recover its ex-date share basis. Forward and reverse splits, symbol isolation and ambiguous same-day actions have explicit tests. Duplicate or same-day split/dividend records fail rather than guessing an ordering.

A signal index may reinvest economic dividends at the ex-date close under the previously specified convention. Raw holding labels instead retain the dividend receivable. Spendable cash must wait for a known payment date; ex-date entitlement is insufficient. Split shares and cost basis must change together before ex-date execution.

## Remaining integration requirements

ACTIONS does not supply payment dates or historical first-publication timestamps. The normalizer records actual acquisition time; it does not fabricate historical availability. This dataset supports current-vintage historical diagnostics, not a point-in-time certification.

The normalization is not yet connected to the backtest engine. Next, build and verify the complete separated raw execution and synthetic signal panel, preserving the flagged zero-volume UUP bar. Resolve listing/ticker continuity explicitly. Wire raw holding labels and payable-date cash accounting only after their required inputs and policies are available. Register any changed strategy construction before comparing its performance.

The malformed vendor action-description CSV response was preserved; the successful JSON response supplies the dictionary evidence. Source hashes in protocol.json were reverified after testing. No new strategy hypothesis, paper activation or live order occurred. The cumulative strategy hypothesis count remains 238; Sharpe 2 and 14+ qualified sleeves are not achieved.
