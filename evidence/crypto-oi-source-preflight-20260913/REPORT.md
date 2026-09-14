# OI incremental candidate stopped at full source coverage

Completed2026-09-13. All3334planned archives acquired/reused with verified checksums and no transport failures. Acquisition session39494 and archive audit session87185 both exited0; real coverage runner and independent audit exited0. No active jobs.

The archive content audit found53invalid OI symbol-days out of3226. Independent standard-library CSV/Decimal checks reproduce failures:266missing five-minute timestamps and1364invalid numeric cells across the required OI quantity/value columns. There are no extra or duplicate timestamps among those failed files. Invalid cell counts are not necessarily distinct rows. Valid OI days contain7685adjacent timestamp reversals in original file order, handled by sorting. All3226price days pass; new5m daily open/close endpoints match the retained hourly sources within1e-8.

The frozen common29-day window and D+3availability mapping propagate sparse source failures to many decision dates. Over the full1241frozen evaluation dates:

| Symbol | Eligible decisions | Coverage | Required |
|---|---:|---:|---:|
| BTCUSDT |791|63.7389%|95%|
| ETHUSDT |811|65.3505%|95%|

The independent audit reconstructs every Boolean calendar flag and both totals without using the rolling-window implementation. Minimum training counts pass(290,505,740,936paired source-eligible dates at the four annual cutoffs), but do not override failed evaluation coverage. All4839funding slots and38712hourly prices per symbol had already passed local coverage; this does not fix the OI gaps.

## Decision

STOP this fixed archive-based OI crowding experiment at source qualification. Do not reserve a return/forecast trial, compute labels, fit actual coefficients or run portfolio returns. No interpolation, relaxed288-row completeness, shorter windows, later-start selection, coin expansion, sign/lag/weight rescue or additional identical downloads. Current archives remain retained as research inputs, not point-in-time qualification evidence.

This is an input-coverage failure, not a measured rejection of the economic hypothesis. The earlier eight-day pilot could not establish full-period coverage; the complete audit now changes the next action. Reopening requires materially different verified source data supporting the same frozen coverage/timing requirements, not repeated schema work.

NEXT move to another economically motivated algorithm hypothesis using sufficiently complete existing inputs. Consult prior failed families before selecting it; do not continue OI infrastructure or bulk-acquisition loops. The paired estimator and daily adapter are retained reusable code but do not establish a qualified sleeve. The goal remains>2combined excess Sharpe,<=11%drawdown across frozen normal/stress horizons and>=15qualified distinct sleeves, then product/operational launch.

No portfolio improvement in this phase. Retained combined main normal/stress excess Sharpe0.74241347/0.41886531 is unchanged; measured union336 plus preserved unmeasured failed reservation, zero new qualified sleeves. Previous goal turn was progress; current phase adds a complete independently checked failure and terminates this candidate before a misleading backtest.

Evidence: full-source/coverage/summary.json and day_coverage.json; actual_coverage/result.json, calendar_masks.csv and independent_audit.json; all source receipts/raw archives; frozen EXPERIMENT_SPEC.json in crypto-oi-incremental-design-20260913. No source or failure record was overwritten.
