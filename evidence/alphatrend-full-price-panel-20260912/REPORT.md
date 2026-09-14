# Full raw/synthetic AlphaTrend panel — September 12, 2026

Built all 93,444 inception-aware daily rows across 17 ETFs with distinct raw execution OHLC, raw volume and synthetic signal OHLC. This is a current-vintage research artifact, not a production engine input or historical availability certificate.

## Validation

All 1,358 normalized economic actions apply exactly once after each symbol's anchor. Every symbol has consecutive XNYS sessions. Raw prices and volume match the separately reviewed source v2 exactly. Synthetic prices remain finite, positive and properly ordered.

The independent step bridge matches all four synthetic prices exactly on 2,289 rows: every action date plus every 100th row. Perturbing the current closing price leaves synthetic open/high/low unchanged on every checked row. A separate shares-and-reinvestment book agrees with every post-anchor synthetic close, with maximum relative error 1.133e-14. This book models the signal index convention; it does not make dividend receivables spendable in the execution ledger.

The first available close anchors each symbol's synthetic scale; the anchor OHLC is recorded as raw identity. It is an initialization row, not a pre-close executable forecast. Later bars use only the prior index state and that session's effective actions. No cross-symbol synthetic price-level comparison is validated by this construction.

109 existing accounting, capture, routing, label and producer tests pass. All three new scripts pass Ruff. No performance or IC comparison was run.

## Data-quality findings

Predeclared diagnostic checks flag 16 rows for zero volume, action-adjusted opening gaps over 20%, or intraday ranges over 20%. These are review flags, not a trading filter or proof of errors.

Within-session OHL/close ratios were compared with archived adjusted data, so the same-day vendor adjustment multiplier cancels. Twelve extreme rows have similar archived ratios within 10 bp. Three exceed the descriptive 10 bp threshold:

| Symbol/date | Maximum ratio discrepancy |
| --- | ---: |
| DBA 2007-01-08 | 3,855.05 bp |
| UUP 2007-06-20 | 1,126.63 bp |
| USO 2020-04-09 | 18.52 bp |

UUP 2007-03-15 retains zero volume. No values were repaired, averaged, filled or deleted. Agreement between vendors does not establish tape correctness.

Four bounded raw Polygon daily queries were attempted. The three 2007 requests returned HTTP 403; the USO 2020 request had a connection timeout. Exact HTTP bodies where available and sanitized receipts are retained under polygon_review/. No retry or subscription change was performed.

## Integration status and next work

paired_prices.parquet is the complete separated panel. quality_review.parquet and extreme_cross_source_review.parquet retain the flagged rows and comparisons. Existing TrendInputRoutes deliberately rejects zero volume, so this full panel has not been presented as engine-ready. Resolve the early DBA/UUP source disagreements, establish an explicit zero-volume execution policy without deleting calendar rows, and review the smaller USO discrepancy before full-history routing. Listing/ticker continuity, payable-date settlement and historical observation provenance also remain explicit integration requirements.

A modified strategy will require its own registered identity before performance comparison. Existing corrected AlphaTrend results are unchanged. No new hypothesis was evaluated, no strategy was admitted and no orders were sent. Union remains 238; the Sharpe 2 / 14+ qualified sleeve target remains unmet.
