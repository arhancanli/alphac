# Incremental OI forecast design and model implementation

Phase completed 2026-09-13: fixed hypothesis and a tested matched forecast estimator; no full-archive acquisition, historical labels, scores, portfolio returns, or qualification.

The hypothesis is that growth in outstanding positions strengthens funding-associated reversal, conditional on funding and price momentum. This is an interpretation to test, not proof that OI measures signed speculative demand. The candidate adds exactly one feature: negative funding sign times positive seven-day base-quantity OI log growth. The control includes funding mean, seven- and 28-day momentum and an ETH indicator. This belongs to the existing crypto crowding family; all previous funding failures remain part of the research history.

EXPERIMENT_SPEC.json freezes BTC/ETH, a 48-hour lag after source-day end, expanding annual training, seven-day labels, a further seven-day purge, training-only standardization, ridge penalty1 and a nonnegative candidate coefficient. It also fixes coverage, paired forecast-loss, yearly and block-bootstrap screen gates before obtaining the full source history. These retrospective dates have already been examined in other research; chronological fitting alone does not create an untouched holdout. Two-coin forecast quality cannot establish 15 sleeves or full-portfolio Sharpe.

scripts/crypto_oi_incremental_model.py implements the matched constrained ridge estimator for prebuilt feature rows. Thirteen synthetic tests pass: future label/feature exclusion, strict purge, identical matched rows, negative-effect boundary solution equal to the control, positive interior solution against an independent augmented least-squares solve, order invariance, timezone/availability/label maturity checks, missing paired rows, duplicates, invalid values, short history, symbol indicators and exclusion of pre2022 data. Tests do not verify a daily source reader or economic edge.

## Next required implementation

1. Build the daily feature adapter with exact UTC calendar windows, sorted complete288-row days, no missing-day interpolation, source-day-end+48h modeled availability, actual funding settlement coverage and seven-day price-label maturity. Test time truncation, gaps, early label access and endpoint handling on synthetic data. The label convention is the 00:00 one-hour bar open at the decision and its counterpart seven days later; availability is after the end bar closes. This is a forecast diagnostic, not an assumption of executable same-open fills.
2. Acquire the full fixed source range once under a bounded, resumable manifest with explicit missing-file accounting, reusing pilot files. No additional sample-date or timestamp-shift sweeps. Verify all source/feature coverage before looking at predictive losses. Unexpected gaps must be retained; do not select a favorable shorter window.
3. Bind code, inputs and evaluation plan, then reserve both canonical matched identities before computing actual labels/forecasts. Fit once per frozen year. Measure and independently reconstruct the paired loss gates. Failed screen stops this fixed hypothesis without sign/window/lag/coin rescue.
4. Only a passing diagnostic permits a separately frozen execution and full combined comparison using actual funding and normal/stress costs. No diagnostic target or forecast Sharpe substitutes for portfolio performance. The 2022 independent evaluation limitation remains explicit because2022 trains this model.

## Evidence correction

Inspection found the preceding volume-check closure accidentally included its own SHA256 while its output file was still empty. Original closure is preserved. prior_closure_binding_audit.json independently checks every non-self entry and records that the self-entry is invalid. The source archives and measured discrepancy flags remain verifiable. This phase closure excludes itself from its binding list.

Current BIL portfolio reference remains unchanged: main normal/stress excess Sharpe0.74241347/0.41886531. Measured union336 plus preserved unmeasured failed reservation; no newly qualified sleeves. Previous goal turn was progress; this turn adds a frozen controlled algorithm experiment and working tested estimator. Goal remains active; no running job.
