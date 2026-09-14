# Native refinery-spread feasibility

September 12, 2026. The native-spread route has matching signed exposure in the 2020 and 2025 samples, but still fails the fixed quote-coverage requirement. The 2015 route is blocked by leg-side metadata. No return backtest, sleeve admission, orders or additional data purchase occurred. Hypothesis union remains 240.

The audit assembled 3,361, 3,850 and 3,898 complete spread definitions on the three dates. It preserves every leg record, rejects incomplete latest snapshots and never infers missing sides from names. No single listed instrument in these downloaded parents matches the exact selected -3 CL, +2 RB, +1 HO contract vector in either direction. This is a sample inventory finding, not an exchange-wide assertion.

Two matching 1:1 instruments exist for June 2020 and September 2025. Buying two RB–CL spreads and one HO–CL spread gives the recipe exactly. This remains two separate instruments/orders, with residual execution risk between them. Current CME documentation describes 1:1 crack mechanics and notes that some implied eligible quotes are not disseminated. Our displayed-book test therefore cannot measure all exchange liquidity. [CME mechanics](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457092911/Implied+Intercommodity+Ratio+Spreads).

| Sample | Selected native spreads | Qualifying grid points | Coverage | Decision |
|---|---|---:|---:|---|
| 2015-01-15 | Signed pair identities fail | Not evaluated | Unavailable | Metadata blocked |
| 2020-04-20 | CL:C1 RB-CL M0; CL:C1 HO-CL M0 | 83 / 600 | 13.83% | Fail |
| 2025-07-15 | CL:C1 RB-CL U5; CL:C1 HO-CL U5 | 64 / 600 | 10.67% | Fail |

The fixed criteria retain the prior one-second grid, maximum one-second event/receive age, maximum 250 ms cross-instrument skew, completed updates, acceptable flags, finite noncrossed tick-aligned prices and two-way displayed size sufficient for two gasoline spreads and one heating-oil spread. Coverage must reach 90% on each date. No thresholds were adjusted after observing native quote results. Metadata examples were inspected before the new protocol was frozen; this is a feasibility extension, not an untouched holdout.

Insufficient gasoline-spread size accounts for 412 of 600 first failures in 2020; gasoline-spread age accounts for 322 in 2025. The previously tested outright route had only 5 and 27 qualifying points on those dates. Better quote coverage does not demonstrate better returns or total execution costs. No dollar-cost conversion is asserted: spread multipliers, fees, historical rounding, margin, first-notice, trading status and sequential execution remain unresolved. Supplemental checks verify USD currency, activation before the sample and expiry beyond ten days for all four selected spread instruments.

## Legacy anomaly and source review

Both selected 2015 crack definitions assign A to both legs. Databento defines leg_side as the side taken when buying the spread, so the recorded exposure does not match the intended recipe. [Schema](https://databento.com/docs/schemas-and-data-formats/instrument-definitions).

The vendor tracker lists a legacy MDP2 multi-leg defect as a fix in progress. Indexed vendor issue text describes always-A leg_side, reversed ordering and negative-price parsing concerns. This is consistent with our observation; the cause and correction status of our exact file are not independently confirmed by the vendor. The direct rendered issue URL exposes the tracker listing rather than the detailed description. [Issue listing](https://issues.databento.com/roadmap/cme-globex-mdp2-multi-leg-data-quality-issues), [indexed vendor tracker description](https://issues.databento.com/b/6vrl98vl/feature-ideas/xeureobi-trades-missing-for-outright-single-stock-options-on-2026-04-282930).

`vendor_reproduction.json` records exact local examples and source hash. `VENDOR_DRAFT.md` is prepared but not sent. Original records remain unchanged; no symbol-based repair is authorized by the evidence.

## Validation and next work

50 focused tests pass, including 17 new cases covering spread assembly and native quote filters. Ruff passes all new code and tests. Independent verification checks 4,800 exact nullable timestamps against raw records, all 147 accepted snapshots, four instrument lifecycles and frozen source bindings. Full grid JSON retains integer nanoseconds. `route_metadata_valid` means signed pair matching only, not order readiness.

Park the current refinery execution route pending corrected legacy metadata and a justified model of sequential orders or nondisseminated implied liquidity. Do not buy more of the same sample or relax filters merely to obtain a pass. The next independent research task is the Treasury-auction track: resolve historically tradable on-the-run security and hedge identities, including overlapping exposure, before examining returns. Sharpe 2 and 14+ qualified sleeves remain objectives, not achieved results.
