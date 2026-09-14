# AlphaTrend exposure and forecast-quality diagnostic — September 13, 2026

Saved-path diagnostic only. Both existing baseline/candidate paths remain unchanged and the directional candidate remains rejected. No new signals, strategy returns or return identities were produced; union244.

## Findings

The configured TrendVolTarget allocator takes sign(mu) and inverse volatility; mu magnitude, previous weights and cost inputs do not determine its unconstrained target. The downstream strategy still has volatility scaling, per-name caps, drawdown controls and order filters. Therefore ignoring magnitude inside this allocator does not mean execution ignores every constraint.

| Measurement | Baseline | Rejected directional candidate |
|---|---:|---:|
| Mean gross exposure | 97.02% | 97.14% |
| Mean net exposure | 10.35% | 30.03% |
| Mean short exposure | 43.34% | 33.56% |
| Max marked gross exposure | 103.48% | 105.02% |
| Position/latest-forecast sign mismatch | 6.99% | 6.83% |

Across all 2,940 equity dates and 17 instruments, SHY averaged about32.92% absolute capital weight in each arm. The directional candidate increased average net exposure from10.35% to30.03%, while gross stayed near97%. This helps explain why changing normalization changed economic direction much more than capital allocation. It does not show that higher or lower net exposure would perform better prospectively.

For orders recorded as filled,96.89% of baseline decision-price notional and96.42% of candidate notional had |mu_ann| below1%. Median absolute mu on these orders was0.521%/0.529% annualized. Other fixed descriptive cutoffs and quantiles are retained in result.json. Forecast magnitude is not a calibrated expectation; these bins do not authorize a trading threshold. Decision-price notional is not actual execution-price turnover or a cost estimate.

Roughly7% of nonzero position rows disagreed with the latest available forecast sign in both arms. Positions are snapshots before the new decision, and may reflect older targets, rebalance cadence and execution filters. This is not evidence that the allocator inverted its input or that every disagreement is an error. Order side is a position change and was not equated with forecast direction.

## Verification

All earlier attribution hashes verify. Forecasts join by exact instrument and calendar-resolved prior session, with zero missing forecasts for filled orders. An independent sorted-timestamp search confirms every order uses the latest strictly prior signal row. All saved position weights exactly equal quantity times mark divided by same-date equity; aggregate gross equals net plus twice short exposure. Unique-key checks pass. Ruff passes. See verification.json, result.json, protocol.json and per-instrument/order tables.

Source-derived diagnostics include all instruments and the full retained interval. The protocol was saved before aggregate measurements. Files remain private. No claim of point-in-time historical source availability, executable capacity, independent alpha, sleeve qualification or portfolio goal attainment follows.

## Next experiment direction

Investigate a single causal direction-confirmation rule at scheduled rebalances, preserving the original baseline and complete instrument set. The economic question is whether requiring persistence before reversing an existing position reduces small-signal reversal costs without losing useful trend response. This is distinct from deleting weak instruments, replacing weights by inverse volatility again, or applying a magnitude threshold as if forecasts were calibrated. Delay can also harm crash response and must be measured.

Before any candidate returns: specify exact state transitions, warmup, zero/missing forecasts, shortability overrides, confirmation timing, identical costs and a mandatory cost stress; register all changed decision paths. Compare complete curves, reversal/turnover counts, drawdown and combined-portfolio contribution. No confirmation variant has been implemented or measured in this checkpoint.
