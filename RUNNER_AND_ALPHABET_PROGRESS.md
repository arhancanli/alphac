# AlphaTrend runner and Alphabet collection

September 12 TREASURY CALENDAR RESOLUTION checkpoint: Treasury confirms the Christmas Eve 2018 two-year auction closed at 11:30 ET. The 16:00 reversal remains conflicted. BrokerTec confirms the 2023 Good Friday settlement exception for Actives/RV Curves; historical notice portal requires login. All 15 boundaries on 12 dates remain venue-unverified. Exact archive inquiry drafted, unsent; no prices, purchases or new trials, union 240. [Resolution evidence](evidence/treasury-calendar-resolution-20260912/REPORT.md).

September 12 TREASURY CALENDAR checkpoint: 610 phase boundaries checked against extracted SIFMA schedules; 15 recommendation conflicts on 12 dates, including the 2018 Christmas Eve reversal. Five source date contradictions retained. Fedwire-open is insufficient for market settlement; added separate market-calendar and explicit-lag checks. 37 tests pass. Complete venue calendars, amendments and instrument settlement rules remain unverified; no dates shifted, no returns/purchases, union 240. [Audit and settlement addendum](evidence/treasury-calendar-20260912/REPORT.md).

September 12 TREASURY SOURCE COVERAGE checkpoint: GovPX documents bill/off-the-run/WI coverage before 2013, but top-of-book is indicative and firm/voice coverage remains unverified. EOD delivery follows snapshot time. Staged precise metadata-only inquiry for 514 preliminary CUSIPs and 1,830 entry/exit leg requests. Local CRSP filename is SEC fundamentals schema. No entitlement or executable-quote coverage verified; no prices/purchases/messages, union 240. Next independent work: historical trading/settlement calendar. [Coverage report](evidence/treasury-source-coverage-20260912/REPORT.md).

September 12 TREASURY TRADE SPEC checkpoint: phase-held proposal specifies benchmark selection, fixed CUSIPs/quantities per phase, settlement-aware aggregation and exact dirty-price/modified-duration hedge equations. Staged 305 phases, 915 leg slots and 514 preliminary CUSIPs. 26 tests pass. Cash bill/off-the-run/WI coverage, benchmark vintages, calendars, financing, capital and lot sizing remain required. Coverage inquiry drafted, not sent; no prices/returns/purchases, union 240. [Specification and report](evidence/treasury-trade-spec-20260912/REPORT.md).

September 12 TREASURY REFERENCE MAP checkpoint: recovered inflation classification from 4,903 free official metadata rows; 156 events match prior dates. All 3,039 event-session rows have issued reference candidates, with 9,117 assignments independently checked. Nine two-year auctions reopen older 5y/7y issues. 636 post rows precede first issuance; another 37 precede reopening-tranche settlement. Ten current tests pass. Tradable on-the-run/WI transitions, rolls, settlement and duration weights remain unresolved. No returns or paid data, union 240. [Report](evidence/treasury-security-map-20260912/REPORT.md).

September 12 NATIVE REFINING checkpoint: assembled 11,109 spread definitions across three dates. No exact single-instrument 3:2:1 recipe in downloaded parents. Two native cracks match 2020/2025 exposure, but coverage fails at 83/600 and 64/600 versus 90% required. Legacy 2015 sides conflict; vendor issue is consistent, reproduction and unsent draft saved. 50 tests pass; 4,800 timestamps and 147 accepted snapshots independently verified. No returns/purchases, union 240. Refinery route parked; next independent track is Treasury tradable-security/hedge mapping. [Report](evidence/refining-native-spreads-20260912/REPORT.md).

September 12 REFINING SYNCHRONIZATION checkpoint: full delivery-month matching and fixed-grid quote audit complete. Coverage fails on all three windows: 0/600 (2015), 5/600 (2020), 27/600 (2025), against 90% required per date. All selected 2015 records carry bad receive-time flags. Corrected sparse-field/integer export; 33 tests pass and 10,800 timestamp values plus all 32 accepted indications independently verified. No new returns or purchases, union 240. Next: inspect exchange spread-leg feasibility using existing files. [Audit report](evidence/refining-synchronization-20260912-v3/REPORT.md).

September 12 SLEEVE FRONTIER checkpoint: refinery-margin feasibility added; three-date CL/RB/HO sample acquired at estimated $0.1695 (billing unverified), 935,435 quotes/26,398 definitions. Outright filter retains 253,724 rows, 251,376 valid two-sided. Nine units tests pass. Treasury audit finds 64 overlapping sessions; tradable security/hedge identities remain required. No new strategy returns, union 240. [Frontier report](evidence/sleeve-frontier-20260912/REPORT.md).


September 12 RETROSPECTIVE COMPARISON checkpoint: registered baseline 2877bd5fcfbf7967 and candidate 45c8d387e6e0b6c5, union now 240. Candidate FAILS fixed comparison: Sharpe 0.158 vs 0.197, CAGR 0.558% vs 0.615%, drawdown 13.67% vs 11.30%, turnover 4.684 vs 4.330. Both positive but all four comparative criteria fail. Saved metrics/source bindings verified; no admission or activation. [Full result](artifacts/analysis/alphatrend_retrospective_comparison_20260912/REPORT.md).


September 12 RETROSPECTIVE EXECUTION checkpoint: explicit vintage-bound action/payment path implemented; default knowledge gates retained. Fixed Decimal payment binding. Staged 62,798 rows with 834 actions and 830 payments, re-anchored signal OHLC; raw fields unchanged. Historical engine preflight and 47 tests pass. No strategy returns or registration, union 238. [Report](evidence/alphatrend-retrospective-execution-20260912/REPORT.md).


September 12 LATER WINDOW checkpoint: data-only audit finds 62,798 rows across 17 ETFs from 2012, complete XNYS coverage and 830 dividend payment references, with no flagged prices or missing payment dates. All 834 actions are late-observed; retrospective execution integration and registration remain pending. Vendor drafts prepared, not sent. 21 regression tests pass; no new returns, union 238. [Window report](evidence/alphatrend-later-window-20260912/REPORT.md).


September 12 REVIEWED PANEL checkpoint: corrected USO 2020-04-09 open from 5.41 to 5.40 using raw SIP plus archived price agreement. Rebuilt all 93,444 rows with 1,355 reviewed actions; 2,286 bridge checks pass. Two price and four payment-date disputes remain; source/SIP volume difference retained. 23 tests pass; full-history gate still refuses, no strategy trial, union 238. [Reviewed panel report](evidence/alphatrend-reviewed-panel-20260912/REPORT.md).

September 12 EFA EVENT checkpoint: excluded one extra source dividend using audited fiscal totals and explicit three-for-one split basis; original archived and inference recorded. Four payment events remain unresolved, with 1,345 retained dividends. Retained cash precision difference is preserved. Seven EFA/QQQ checks pass. No panel rebuild or real strategy trial, union 238. [EFA event report](evidence/alphatrend-efa-event-review-20260912/REPORT.md).

September 12 QQQ EVENT checkpoint: two extra dividend events excluded from a separate research snapshot using exact issuer-history agreement and audited fiscal-year totals. Originals archived; decision explicitly marked as inference. Five unresolved dividend events remain, with 1,346 retained dividends. Three negative tests and offline replay pass. No price-panel rebuild or real strategy trial, union 238. [QQQ event report](evidence/alphatrend-qqq-event-review-20260912/REPORT.md).

September 12 ISSUER PAYMENT checkpoint: recovered 19 dates from the previous 23 gaps using Invesco histories and two filing adjudications. Cross-source review quarantined three previously matched FXE dates: seven unresolved events remain (four unmatched, three conflicting). 22 tests pass; no panel rebuild or real strategy trial, union 238. [Issuer payment report](evidence/alphatrend-payment-source-review-20260912/REPORT.md).

September 12 DIVIDEND RECOVERY checkpoint: recovered 16 more dates (23 gaps remain), quarantined one invalid issuer SPY payable date, and applied three issuer/Polygon cash revisions in a separate snapshot. The other 1,355 action rows are unchanged. 19 tests pass. Historical panel not rebuilt, no strategy trial, union 238. [Recovery report](evidence/alphatrend-dividend-recovery-20260912/REPORT.md).

September 12 DIVIDEND ADJUDICATION checkpoint: six issuer histories and QQQQ reference recover 208 payment dates; gaps reduced from 247 to 39. Four duplicate groups explained by combined distributions. Two cash discrepancies exceed one cent/share; smaller precision differences retained. Six extraction tests pass. No historical payment schedule approval or strategy trial; union 238. [Adjudication report](evidence/alphatrend-dividend-adjudication-20260912/REPORT.md).

September 12 RUNNER BUNDLE checkpoint: controlled end-to-end synthetic features → raw labels → paired-price allocator → payable engine succeeds. Raw exposure marks, settings/signals binding and staged-file checks verified; 47 tests pass. Real history blocked before computation. Seventeen Polygon reference requests recovered 1,111 records and 1,101 unique payment-date matches; 247 unmatched/ambiguous events and cash/source discrepancies remain. No actual strategy trial, union 238. [Runner report](evidence/alphatrend-runner-bundle-20260912/REPORT.md); [Payment reference report](evidence/alphatrend-full-dividend-reference-20260912/REPORT.md).

September 12 PAYABLE ENGINE checkpoint: opt-in daily-equity loop now processes ex-date entitlement, fills, payment boundaries and financing chronologically. Eight XNYS-calendar tests include weekend settlement, shorts, ex-date purchases and terminal receivables; 135 tests pass. Legacy no-action/no-financing fills/equity match exactly, original engine unchanged. Full AlphaTrend runner binding and historical data gates remain pending; no performance trial, union 238. [Payable engine report](evidence/alphatrend-payable-engine-20260912/REPORT.md).

September 12 PAYABLE LEDGER checkpoint: real Ledger subclass separates dividend entitlement from settled cash and includes signed pending amounts in equity. Exact payment boundaries and split financing intervals are required. Ten new tests; 56 combined tests pass. Recent Polygon packet has 25/25 pay dates, but full historical coverage and publication timing remain absent. Engine-loop integration pending; no performance trial, union 238. [Payable ledger report](evidence/alphatrend-payable-ledger-20260912/REPORT.md).

September 12 RAW LABEL SERVICE checkpoint: opt-in trend service now uses a separately bound raw holding-label provider instead of feature opens. All 119 preserved labels replay exactly; fabricated tests verify release timing, late-record rejection, label separation and full/prefix parity. 51 targeted tests pass. Full runner/settlement integration and three price disputes remain pending; no performance trial, union 238. [Raw label service report](evidence/alphatrend-raw-label-service-20260912/REPORT.md).

September 12 ENGINE QUALITY GATE checkpoint: queued-order fill adapter now enforces exact reviewed raw bars and eligibility inside EventDrivenBacktester. Six engine scenarios verify accepted and refused fills; clean fills/equity match reference exactly. 89 tests pass. Full AlphaTrend integration and three historical price disputes remain unresolved; no performance trial, union 238. [Engine gate report](evidence/alphatrend-engine-quality-gate-20260912/REPORT.md).

September 12 QUALITY ROUTING checkpoint: v2 retains all 93,444 calendar rows and exact raw prices/volume; four rows are execution-ineligible. Zero-volume label endpoints fail without date shifting; unresolved prices block full feature history. 78,439 clean-symbol feature rows route exactly. 70 targeted tests pass. USO retry returned HTTP 403; three source disputes remain unresolved, engine integration pending, union 238. [Quality routing report](evidence/alphatrend-quality-routing-20260912/REPORT.md).

September 12 FULL PRICE PANEL checkpoint: built 93,444 separate raw/synthetic rows across 17 ETFs; all 1,358 actions apply once. 2,289 step-bridge checks match exactly; independent shares-book error is at most 1.133e-14. 109 tests pass. Sixteen bars reviewed, with three cross-source disagreements and one zero-volume bar unresolved; Polygon 2007 probes denied and 2020 probe timed out. Engine integration remains pending. No performance trial, union 238. [Full panel report](evidence/alphatrend-full-price-panel-20260912/REPORT.md).

September 12 ACTION UNITS checkpoint: normalized 1,358 economic events, including 19 dividends requiring conversion to ex-date raw-share units. Ten splits agree with price factors within 0.969 bp; 25 recent Polygon dividend matches differ by at most $0.000004/share. 109 tests pass. Payment dates, historical publication provenance and full engine integration remain unresolved; no strategy trial, union 238. [Action validation report](evidence/alphatrend-action-validation-20260912/REPORT.md).

September 12 SHARADAR DIRECT ACQUISITION checkpoint: new credential verified with January 2004 SPY rows. Acquired 93,444 fund-price rows and 1,370 action records for all 17 ETFs, 2003–September 11, 2026 (inception-aware). No expected session gaps. Raw imputation follows vendor formulas; 12 floating-boundary repairs recorded in a separate v2 parquet and one zero-volume UUP bar retained. Historical publication provenance, action semantics and engine integration still require validation. No new strategy trial; union 238. [Acquisition report](evidence/alphatrend-sharadar-direct-20260912/REPORT.md).

September 12 SFP CONTROLS / DIVIDEND SETTLEMENT checkpoint: controls show Nasdaq API and ZF/SEP samples work but target ETF price queries remain empty; product entitlement is not proven. Recovered 1,414 ETF ACTIONS archive records (1,384 dividends, 11 splits plus lifecycle records), not yet normalized. Added isolated settled-cash/receivable simulation; 93 chain tests and 10 existing contract tests pass after regenerating a missing local capability artifact. No engine integration, strategy trial or new hypothesis; union 238. [Settlement report](evidence/alphatrend-dividend-settlement-20260912/REPORT.md); [Access and archive report](evidence/alphatrend-sfp-controls-20260912/REPORT.md).

September 12 INPUT ROUTING / HISTORY INVENTORY checkpoint: explicit feature, execution and label routes implemented; all 238 captured bars route exactly, with labels reading raw opens. 85 tests pass. Four-root inventory finds recent 17-ETF data and the 2021–2026 Polygon snapshot, but does not establish the full raw/action prefix for the fixed anchor. TICKERS metadata identifies all 17 ETFs as SFP; three SFP probes returned schemas but no rows, so usable access is unresolved. Engine integration and registration remain pending; no return trial or new hypothesis, union 238. [Routing report](evidence/alphatrend-input-routes-20260912/REPORT.md).

September 12 HOLDING LABEL checkpoint: explicit raw-open shares/dividend-receivable labels match an independent holdings book for all 119 fixed 21-session labels (17 ETFs; max numerical error 2.22e-16). Synthetic-index ratios differ for 28 labels, up to 0.409 bp, and are not substituted. Fixed-release v2 rejects late action records even on later replay. 78 tests pass. Candidate specification prepared as an unregistered draft; full historical inputs and input separation remain prerequisites. No strategy return trial; union 238. [Label report](evidence/alphatrend-holding-labels-20260912_completed/REPORT.md).

September 12 OHLC BRIDGE checkpoint: synthetic open/high/low/close mapping completed for all 238 continuation bars. Closes exactly match the prior bridge; 476 perturbation checks show the mapped open does not depend on the same-session closing price. 62 tests pass. Still current-vintage diagnostics; no Yahoo equivalence, forward-label validation or producer activation. No new hypothesis; union 238. [OHLC report](evidence/alphatrend-ohlc-bridge-20260912/REPORT.md).

September 12 ACTION BRIDGE checkpoint: 34 Polygon reference GETs succeeded with 25 records. A versioned forward close-index bridge produced 238 isolated diagnostic continuation rows. Treasury adjusted-level differences remain 0.165/0.605/0.208 bp (IEF/SHY/TLT); exact Yahoo parity is false. 54 tests pass. Historical publication timing, OHLC/open-label mapping, clock and producer binding remain unresolved. No new return trial or activation; union 238. [Bridge report](evidence/alphatrend-price-bridge-20260912/REPORT.md).

September 12 HISTORY / ADJUSTMENT checkpoint: acquired all 238 missing raw SIP bars (17 ETFs × 14 sessions, August 24–September 11), with complete timestamp and OHLCV checks. An expanded IEF/SHY/TLT overlap shows adjusted-vs-raw daily-return differences up to 34.28/30.62/40.25 bp. Direct appending remains blocked; an action-aware, versioned price bridge and point-in-time provenance are required. 39 tests pass; no new strategy trial or activation, union 238. [Continuity report](evidence/alphatrend-history-bridge-20260912/REPORT.md).

September 12 INPUT CAPTURE / RANK TRACE checkpoint: AlphaMax first allocation reconstructs all 202 replay order quantities exactly; CVS rank 173 versus TEAM 172 straddles the short cutoff with a 0.118624 bp annual-forecast gap. Historical root cause remains unproven. AlphaTrend raw SIP adapter captured all 17 bars; 32 tests passed. Clock, history continuity, adjustment parity and producer binding remain blocked; no activation or new return trial, union 238. [Rank trace](evidence/alphamax-initial-allocation-20260912/REPORT.md); [Daily capture](evidence/alphatrend-daily-capture-20260912T055801Z/REPORT.md).

September 12 PRODUCER / DURABLE REPLAY checkpoint: corrected journal 59901461092dd7a6 and state-recovering producer implemented; two fixed historical sessions match archived forecasts exactly and recover exact targets in a separate process. 18 targeted tests passed. The first null-forecast/cutoff harness failure is preserved; corrected producer fails on insufficient forecasts. Frozen-history adapter only, no live activation. AlphaMax known-identity replay retained all 113 outputs and matches the prior failed replay hash exactly; initial 202 decision prices/IDs match but 20 quantities differ, including TEAM short replaced by CVS. Precise upstream forecast/covariance/input cause remains unresolved. One reproduction run, no new hypotheses; union 238. [Producer](evidence/alphatrend-producer-20260912_completed/REPORT.md) / [durable replay](artifacts/analysis/alphamax_durable_replay_20260912/REPORT.md).

September 12 OBSERVATION / REFERENCE RECOVERY checkpoint: fresh GET-only checks return valid September 11 SIP daily bars for all 17 ETFs and 17 asset identities. Latest SIP quotes 403; clock sample fails bounds; FXE/FXY/USO are HTB and not shortable (14/17 shortable). Daily capture access is established, but corrected journal binding, producer/history/state parity and operational readiness remain incomplete. AlphaMax now has 113 recovered reference files: all 12 legs / 729 equity rows stitch exactly to the preserved root, with boundaries and cash continuity verified. Original fresh-input replay mismatch remains unresolved; replay outputs were discarded and no hash match found in bounded search. No new return trial, orders, epoch activation or deployment; union 238. [Readiness and recovery report](evidence/alphatrend-observation-readiness-20260912/REPORT.md).

September 12 COST STRESS / OVERLAP checkpoint: corrected continuous candidate passes fixed 2x-cost criteria. Session Sharpe 0.506 vs baseline 0.015; CAGR 2.37% vs -0.03%; drawdown 11.85% vs 15.02%. Ledger and report both use 252-session metrics. Identities 11b181067d8da228 / e7c03d85c7f196b9, union 238. Base-cost candidate correlation: AlphaMax 0.330 over 728 matched intervals; AlphaVintage -0.004 over 5,163 (-0.049 on the common 728-interval window). Max replay provenance unresolved; Vintage remains KILLED; no qualified portfolio claim. Next: prospective input/clock/borrow readiness, Max provenance repair and complementary sleeve feasibility. No orders, deployment, purchases or admission. [Stress and overlap report](artifacts/analysis/alphatrend_causal_stress_20260912/REPORT.md).

September 12 CAUSAL / CONTINUOUS comparison: corrected exit-session IC release and uninterrupted portfolio implemented in an isolated research path. 86 tests passed; both variants pass 12 timing boundaries and 252 allocation contexts. Registered corrected baseline 2ab27017e93d15a4 and candidate 59901461092dd7a6 (union 236). Candidate session Sharpe 0.596 vs 0.144, CAGR 2.81% vs 0.53%, maximum drawdown 11.03% vs 12.41%, turnover 4.16 vs 5.20. Final audit also corrected legacy 365-day annualization to 252 sessions; original ledger rows are preserved with a bound metric correction. All frozen criteria pass; retain for validation only. Legacy candidate remains on hold and old stress evidence is not transferable. Next: separately preregister corrected doubled-cost validation, then overlap and operational readiness. No deployment/orders/admission. [Corrected comparison](artifacts/analysis/alphatrend_causal_continuous_20260912/REPORT.md).

September 12 RECORDER / RESEARCH HOLD checkpoint: isolated append-only recorder implemented, 252 archived captures / 504 events, exact persisted-context recovery. Forward equivalence FAILED: all six tested IC-update dates use weights inconsistent with completed-session-only prices; 26/252 allocation contexts differ across the research leg-reset boundary. Candidate ec7ec19175ac10a9 is on research hold. Earlier 0.677 and stressed 0.542 Sharpe results are preserved simulations, not forward-valid evidence. Correct label availability and continuous allocation semantics, test parity, then register corrected comparisons before returns. No paper epoch, orders, deployment or new return trial; union remains 234. [Recorder and parity report](evidence/alphatrend-observation-recorder-20260912_completed/REPORT.md).

September 12 forward-readiness checkpoint: local production SignalService lacks the retained directional variant. mf_tick refreshes historical prices and reruns WF; live_cycle reads the latest simulated position weights. That path has no evidenced immutable candidate decision epoch. Local ETF data reach September 10; saved WF end is August 25. Existing account credential files are present; no keys or remote broker state were inspected. Prior correlations describe the old AlphaTrend construction, not the new candidate. Next implementation: isolated append-only observation recorder and equity-calendar as-of parity, then bounded feed/clock/borrow checks. No new returns, orders or admission; union remains 234. [Readiness and sleeve map](evidence/alphatrend-forward-readiness-20260912/REPORT.md).

September 12 validation checkpoint: the retained directional candidate passed the single preregistered full-engine 2x-cost scenario. Stressed Sharpe 0.542 versus baseline 0.150; CAGR 2.07% versus 0.45%; maximum drawdown 10.50% versus 12.35%; turnover 8.60 versus 9.68. Both new cost identities remain counted (union 234). Corrected exchange-session exposure analysis gives incremental raw-return intercept 0.59% annually with descriptive interval -0.75% to 1.94%; positive independent alpha is not established. The candidate also underperformed in 2013-2019. Retain frozen for independent/prospective validation and portfolio overlap assessment, not promotion. [Completed validation](artifacts/analysis/alphatrend_directional_validation_20260912/REPORT.md).

September 12 directional-blend checkpoint: hypothesis ec7ec19175ac10a9 (ordinal 232) passes all four frozen development criteria. Sharpe 0.327 -> 0.677; CAGR 1.11% -> 2.63%; maximum drawdown 10.24% -> 9.63%; annual turnover 9.69 -> 8.61. Baseline signal and timestamped equity reproduce exactly. Gross exposure stays about 94.77%, but net exposure rises from 15.86% to 39.01%. Retain for further testing only; no admission or deployment. The full union remains counted at 232. Next: freeze validation of exposure attribution, cost robustness and independent/prospective evidence before measuring further variants. [Completed directional comparison](artifacts/analysis/alphatrend_directional_20260912_attempt2/REPORT.md).

September 12 forecast-audit checkpoint: exact archived forecast reconstruction and 593 sealed files verified. On 247 sampled dates, mean cross-sectional Rank IC is 0.0222 for the standardized blend and 0.0362 for expected returns; both descriptive 95% intervals include zero. Cross-sectional centering changes the pre-centering trend sign in 17.15% of complete audited observations. The next justified experiment is a separately registered direction-preserving blend with existing settings fixed. No new portfolio trial or promotion occurred; strategy selection union remains 231. [Full forecast audit](artifacts/analysis/alphatrend_forecast_audit_20260912/REPORT.md).

September 12 checkpoint: the cash-retention variant is also rejected under the unchanged scenario. Sharpe 0.218 versus baseline 0.327; CAGR 0.10% versus 1.11%; maximum drawdown 1.86% versus 10.24%. Mean marked gross exposure was only 0.89%. [Completed comparison](artifacts/analysis/alphatrend_cash_retention_20260912/REPORT.md). Both trials remain counted; neither was deployed.

September 11 checkpoint: the registered development comparison is now complete. The cost-filter candidate is **rejected under the frozen scenario**: Sharpe 0.327 → 0.213 and maximum drawdown 10.24% → 35.14%, despite lower turnover. [Completed report](artifacts/analysis/alphatrend_cost_development_20260911_attempt2/REPORT.md). Earlier pending-status notes below are retained as history. Untouched validation and admission are still not established.

The optional cost filter now runs through `WalkForwardRunner` and the existing
`mf_gauntlet.py` command via `--trend-cost-policy`. `--trial-reservation` passes
through to canonical registration. Its full dated, side-specific cost policy and
hash enter trial identity, saved run configuration and the input snapshot. The
snapshot retains both original and filtered expected returns. Default runs keep
their existing behavior. No production profile or deployed job was changed.

A pre-return correction replaces the draft's 10-session holding assumption with
the signal configuration's 21-session horizon, annualized on 252 sessions.
The rebalance cadence can remain 10 sessions. This follows the existing Grinold
expected-return convention; it does not assert that positions exit after exactly
21 sessions. The cost gate also preserves the baseline units check and tail clipping.

The fixed modeled cost components total 12 basis points per round trip: twice
1 bp commission + 3 bp half-spread + 2 bp latency. That is **not the complete
cost**: impact needs trade size, lagged volume and volatility; short borrow and
financing also need explicit treatment. The legacy 50 bp annual borrow assumption
is not dated security-level lending evidence. The configured IC of 0.02 remains
a model assumption; this work does not establish its empirical calibration.

The [readiness record](evidence/trend-cost-runner-20260911/readiness.json) binds
those findings to source files. A complete candidate cost policy and a verified
untouched evaluation interval remain missing. No new market-return trial was run,
no Sharpe improvement is claimed, and the full historical experiment union must
carry forward when the new trial is reserved. A comparison on already-inspected
data must be labelled a development comparison rather than untouched validation.

## Alphabet

The bounded collector saved five observation packets, with sample hashes verified:

| Explicit credential/feed context | Quote response | Result |
| --- | --- | --- |
| General paper / SIP | 403 | Stopped after first denied request |
| General paper / IEX | 200 in all three rounds | No pair passed the age/skew diagnostic |
| Equity paper / SIP | 403 | Stopped after first denied request |

Both symbols continued to report easy-to-borrow status. IEX quote diagnostics
included ages around 1.8 seconds, pair skew of 4.9 seconds, and negative apparent
ages of roughly 0.3–0.4 seconds. Negative ages are unresolved timing evidence;
this collector does not calibrate the host clock. None of these samples is
execution clearance. Quote-age rules are diagnostics, not proof that a quiet
standing quote is invalid.

[Alpaca documents](https://docs.alpaca.markets/us/reference/stocklatestquotes-1)
SIP as covering US exchanges and IEX as a single-exchange feed. The collector
explicitly requests a feed and never falls back silently. Separate IEX observations
were collected only after preserving the SIP denial. Asset requests are sequential;
this is not an atomic quote/borrow snapshot or a synchronized trade decision.

No orders, locates, paid data purchases, account changes or background schedulers
were made. This was bounded collection, not continuous monitoring. Additional
Databento credits do not establish Alpaca SIP access. The next Alphabet data step
is to resolve consolidated quote entitlement or select another licensed feed,
and establish clock calibration before collecting decision-quality observations.

## Verification

75 focused runner, cost-policy, optimizer, snapshot and golden-master tests pass.
One optional real-lake funding test is skipped because its lake is absent in this
checkout. Changed Python files pass Ruff. Synthetic results validate the wiring
and accounting behavior; they do not establish improved market performance.
