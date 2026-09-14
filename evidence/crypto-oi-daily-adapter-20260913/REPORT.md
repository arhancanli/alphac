# Daily OI feature adapter completed — 2026-09-13

Implemented scripts/crypto_oi_daily_features.py against the previously frozen incremental-forecast specification. No historical labels, forecasts or returns were computed. Full-period acquisition has not started.

The adapter validates exact 288-point five-minute source-day grids, symbols, finite positive OI/close values, duplicate/missing timestamps, funding rows against a caller-supplied independent settlement schedule, and event-completion availability. It sorts observations before selecting daily endpoints. Source-day inputs become usable no earlier than D+3 midnight, 48 hours after day end; actual later source availability makes that decision ineligible rather than changing the frozen lag.

Feature construction preserves every UTC calendar anchor and requires complete common daily records across the 29-day input window. Daily records require complete price, OI and funding source days; missing source days invalidate affected windows without interpolation or calendar compression. The fixed seven-/28-day momentum and seven-day OI changes use calendar endpoints. Funding is settlement-weighted over21 days, not an average of daily averages. OI contraction produces zero for the added crowding feature, as specified.

Labels are a separate explicit operation. They retain NaN for missing endpoint bars or labels not yet available; the seven-day endpoint hourly bar must have completed and any later receipt time also applies. These are price-only predictive targets, not executable portfolio returns. Real label computation remains forbidden before canonical registration.

## Verification

30 tests pass in the retained run:17 adapter tests plus13 previously frozen estimator tests. Coverage includes unordered source rows, incomplete grids/funding, duplicate/wrong-symbol/nonfinite/naive inputs, premature source availability, exact lag/calendar formulas, gap invalidation and recovery, prefix invariance under truncation and changed future values, settlement-weighted funding, OI contraction, label maturity/missing/delayed endpoints, and a two-symbol synthetic adapter-to-annual-model run. The integration uses only synthetic sources and verifies shared training counts and the frozen purge cutoff. Session36764 exited0.

The existing BTC/ETH cadence audit was inspected: each has5149 retained eight-hour gaps with zero mismatches,3744 within the main evaluation. This is evidence of observed regularity, not independent proof of the historical expected schedule. The adapter deliberately requires a separately supplied schedule rather than deriving completeness expectations from the very rows being checked. prior_funding_cadence.json preserves the bounded lookup. Production data and prior cadence/funding experiments were not changed or rerun.

## Next action

Prepare one full-range source acquisition manifest for the fixed2022-01-01–2026-06-01 BTC/ETH design. Reuse the completed pilots and already frozen prices/funding where exact grids and hashes support reuse; avoid unnecessary downloads. Bind an explicit modeled eight-hour funding schedule independently of observed-row membership, preserving the historical-metadata limitation. Report missing days and qualified feature coverage without computing targets. Do not assume the observed cadence alone establishes point-in-time schedule provenance.

Use a resumable bounded acquisition with per-file terminal outcomes and no repeated sample sweeps; inspect any live process handle before restarting. After coverage passes, freeze input/code bindings and reserve both diagnostic identities before historical labels/forecasts. Run the one fixed matched screen and stop on failure without sign/window/lag rescue. If it passes, a separately preregistered cost-aware full-portfolio test is still required. No test or metadata audit here counts as a new sleeve.

Main combined reference remains0.74241347 normal/0.41886531 stressed excess Sharpe. Measured trial union336 plus the preserved failed unmeasured reservation; no new returns or qualified sleeves. Prior goal turn was progress (design and estimator); this turn completes the daily adapter and synthetic integration. Goal active; no live jobs.
