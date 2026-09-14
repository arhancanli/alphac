# Corrected AlphaTrend producer interface

Use `CausalTrendJournal` with corrected candidate 59901461092dd7a6, an exact configuration binding and a fresh epoch. `CausalTrendProducer` accepts three bound adapters: immutable input verification, causal signal computation and a fresh stateful allocator factory. Each input includes its session label, source binding and allocation context. Call `produce` with actual receive-time and clock evidence for a prospective epoch.

The initial state is explicitly `{"completed": 0, "last_session": null}`. The producer reconstructs internal allocation state by replaying committed signals and contexts and checking exact target equality. Failed/missed work never advances committed state. Interrupted captures must be resolved through the journal's explicit abandonment operation; never recompute the same session. A missing session after an accepted decision requires an explicitly bound new epoch. This conservative policy still needs operational evaluation before use.

The included adapter in `scripts/check_causal_trend_producer.py` is a historical diagnostic, not a live connector. Its fixed source directory, synthetic clock and empty-book contexts must not be relabeled prospective. `scripts/recover_causal_trend_producer.py` verifies saved target recovery in a separate process. All output directories are exclusive and refuse overwrites.

Do not activate the producer solely because replay tests pass. A live adapter, full causal history, verified context, appropriate source/receipt evidence and the host clock gate remain required. Current quote and borrow constraints apply separately to execution. No broker order capability is included.

Daily acquisition adapter (September 12): `validation/trend_daily_capture.py` and `scripts/capture_trend_daily_inputs.py` now preserve and validate raw SIP receipts. This is an acquisition stage; history/adjustment/clock gates still prevent producer activation. See [capture evidence](evidence/alphatrend-daily-capture-20260912T055801Z/REPORT.md).

Historical acquisition update: all 14 missing sessions were acquired separately. The old panel is total-return adjusted and SIP bars are raw; the expanded overlap demonstrates time-varying adjustment ratios. Producer integration awaits a versioned action-aware bridge. [Audit](evidence/alphatrend-history-bridge-20260912/REPORT.md).

The isolated forward-close bridge now handles splits/dividends with receipt gates. Its current-vintage diagnostic is not an adapter for the frozen candidate: Yahoo parity and the open-label convention are unresolved. [Details](evidence/alphatrend-price-bridge-20260912/REPORT.md).

The additive OHLC wealth-coordinate bridge passes current-close-independence checks. It requires forward-label validation and a separately registered candidate before strategy-return testing; it is not connected to the frozen producer. [Report](evidence/alphatrend-ohlc-bridge-20260912/REPORT.md).

Use explicit raw-open holding labels for the proposed wealth-price variant, not synthetic-open ratios. The v2 label guard rejects records observed after the fixed exit-close release. This convention is not integrated or registered. [Specification and checks](evidence/alphatrend-holding-labels-20260912_completed/REPORT.md).

A diagnostic input boundary now separates synthetic features, raw execution and raw-open labels. It is not yet wired into the shared-reader engine path. Full raw/action historical coverage remains unestablished. [Report](evidence/alphatrend-input-routes-20260912/REPORT.md).

An isolated dividend settlement component distinguishes accrued value from settled cash. It remains outside the frozen engine and requires actual payment date coverage plus broker reconciliation for paper use. [Details](evidence/alphatrend-dividend-settlement-20260912/REPORT.md).

Direct Sharadar access now supplies the full requested ETF price prefix and action records. The missing-history access gate is resolved; this does not activate the producer or establish historical publication timing. [Audit](evidence/alphatrend-sharadar-direct-20260912/REPORT.md).


September 12 ACTION UNITS checkpoint: normalized 1,358 economic events, including 19 dividends requiring conversion to ex-date raw-share units. Ten splits agree with price factors within 0.969 bp; 25 recent Polygon dividend matches differ by at most $0.000004/share. 109 tests pass. Payment dates, historical publication provenance and full engine integration remain unresolved; no strategy trial, union 238. [Action validation report](evidence/alphatrend-action-validation-20260912/REPORT.md).


September 12 FULL PRICE PANEL checkpoint: built 93,444 separate raw/synthetic rows across 17 ETFs; all 1,358 actions apply once. 2,289 step-bridge checks match exactly; independent shares-book error is at most 1.133e-14. 109 tests pass. Sixteen bars reviewed, with three cross-source disagreements and one zero-volume bar unresolved; Polygon 2007 probes denied and 2020 probe timed out. Engine integration remains pending. No performance trial, union 238. [Full panel report](evidence/alphatrend-full-price-panel-20260912/REPORT.md).


September 12 QUALITY ROUTING checkpoint: v2 retains all 93,444 calendar rows and exact raw prices/volume; four rows are execution-ineligible. Zero-volume label endpoints fail without date shifting; unresolved prices block full feature history. 78,439 clean-symbol feature rows route exactly. 70 targeted tests pass. USO retry returned HTTP 403; three source disputes remain unresolved, engine integration pending, union 238. [Quality routing report](evidence/alphatrend-quality-routing-20260912/REPORT.md).


September 12 ENGINE QUALITY GATE checkpoint: queued-order fill adapter now enforces exact reviewed raw bars and eligibility inside EventDrivenBacktester. Six engine scenarios verify accepted and refused fills; clean fills/equity match reference exactly. 89 tests pass. Full AlphaTrend integration and three historical price disputes remain unresolved; no performance trial, union 238. [Engine gate report](evidence/alphatrend-engine-quality-gate-20260912/REPORT.md).


September 12 RAW LABEL SERVICE checkpoint: opt-in trend service now uses a separately bound raw holding-label provider instead of feature opens. All 119 preserved labels replay exactly; fabricated tests verify release timing, late-record rejection, label separation and full/prefix parity. 51 targeted tests pass. Full runner/settlement integration and three price disputes remain pending; no performance trial, union 238. [Raw label service report](evidence/alphatrend-raw-label-service-20260912/REPORT.md).


September 12 PAYABLE LEDGER checkpoint: real Ledger subclass separates dividend entitlement from settled cash and includes signed pending amounts in equity. Exact payment boundaries and split financing intervals are required. Ten new tests; 56 combined tests pass. Recent Polygon packet has 25/25 pay dates, but full historical coverage and publication timing remain absent. Engine-loop integration pending; no performance trial, union 238. [Payable ledger report](evidence/alphatrend-payable-ledger-20260912/REPORT.md).


September 12 PAYABLE ENGINE checkpoint: opt-in daily-equity loop now processes ex-date entitlement, fills, payment boundaries and financing chronologically. Eight XNYS-calendar tests include weekend settlement, shorts, ex-date purchases and terminal receivables; 135 tests pass. Legacy no-action/no-financing fills/equity match exactly, original engine unchanged. Full AlphaTrend runner binding and historical data gates remain pending; no performance trial, union 238. [Payable engine report](evidence/alphatrend-payable-engine-20260912/REPORT.md).


September 12 RUNNER BUNDLE checkpoint: controlled end-to-end synthetic features → raw labels → paired-price allocator → payable engine succeeds. Raw exposure marks, settings/signals binding and staged-file checks verified; 47 tests pass. Real history blocked before computation. Seventeen Polygon reference requests recovered 1,111 records and 1,101 unique payment-date matches; 247 unmatched/ambiguous events and cash/source discrepancies remain. No actual strategy trial, union 238. [Runner report](evidence/alphatrend-runner-bundle-20260912/REPORT.md); [Payment reference report](evidence/alphatrend-full-dividend-reference-20260912/REPORT.md).


September 12 DIVIDEND ADJUDICATION checkpoint: six issuer histories and QQQQ reference recover 208 payment dates; gaps reduced from 247 to 39. Four duplicate groups explained by combined distributions. Two cash discrepancies exceed one cent/share; smaller precision differences retained. Six extraction tests pass. No historical payment schedule approval or strategy trial; union 238. [Adjudication report](evidence/alphatrend-dividend-adjudication-20260912/REPORT.md).



September 12 DIVIDEND RECOVERY checkpoint: recovered 16 more dates (23 gaps remain), quarantined one invalid issuer SPY payable date, and applied three issuer/Polygon cash revisions in a separate snapshot. The other 1,355 action rows are unchanged. 19 tests pass. Historical panel not rebuilt, no strategy trial, union 238. [Recovery report](evidence/alphatrend-dividend-recovery-20260912/REPORT.md).



September 12 ISSUER PAYMENT checkpoint: recovered 19 dates from the previous 23 gaps using Invesco histories and two filing adjudications. Cross-source review quarantined three previously matched FXE dates: seven unresolved events remain (four unmatched, three conflicting). 22 tests pass; no panel rebuild or real strategy trial, union 238. [Issuer payment report](evidence/alphatrend-payment-source-review-20260912/REPORT.md).



September 12 QQQ EVENT checkpoint: two extra dividend events excluded from a separate research snapshot using exact issuer-history agreement and audited fiscal-year totals. Originals archived; decision explicitly marked as inference. Five unresolved dividend events remain, with 1,346 retained dividends. Three negative tests and offline replay pass. No price-panel rebuild or real strategy trial, union 238. [QQQ event report](evidence/alphatrend-qqq-event-review-20260912/REPORT.md).



September 12 EFA EVENT checkpoint: excluded one extra source dividend using audited fiscal totals and explicit three-for-one split basis; original archived and inference recorded. Four payment events remain unresolved, with 1,345 retained dividends. Retained cash precision difference is preserved. Seven EFA/QQQ checks pass. No panel rebuild or real strategy trial, union 238. [EFA event report](evidence/alphatrend-efa-event-review-20260912/REPORT.md).



September 12 REVIEWED PANEL checkpoint: corrected USO 2020-04-09 open from 5.41 to 5.40 using raw SIP plus archived price agreement. Rebuilt all 93,444 rows with 1,355 reviewed actions; 2,286 bridge checks pass. Two price and four payment-date disputes remain; source/SIP volume difference retained. 23 tests pass; full-history gate still refuses, no strategy trial, union 238. [Reviewed panel report](evidence/alphatrend-reviewed-panel-20260912/REPORT.md).


September 12 LATER WINDOW checkpoint: data-only audit finds 62,798 rows across 17 ETFs from 2012, complete XNYS coverage and 830 dividend payment references, with no flagged prices or missing payment dates. All 834 actions are late-observed; retrospective execution integration and registration remain pending. Vendor drafts prepared, not sent. 21 regression tests pass; no new returns, union 238. [Window report](evidence/alphatrend-later-window-20260912/REPORT.md).


September 12 RETROSPECTIVE EXECUTION checkpoint: explicit vintage-bound action/payment path implemented; default knowledge gates retained. Fixed Decimal payment binding. Staged 62,798 rows with 834 actions and 830 payments, re-anchored signal OHLC; raw fields unchanged. Historical engine preflight and 47 tests pass. No strategy returns or registration, union 238. [Report](evidence/alphatrend-retrospective-execution-20260912/REPORT.md).


September 12 RETROSPECTIVE COMPARISON checkpoint: registered baseline 2877bd5fcfbf7967 and candidate 45c8d387e6e0b6c5, union now 240. Candidate FAILS fixed comparison: Sharpe 0.158 vs 0.197, CAGR 0.558% vs 0.615%, drawdown 13.67% vs 11.30%, turnover 4.684 vs 4.330. Both positive but all four comparative criteria fail. Saved metrics/source bindings verified; no admission or activation. [Full result](artifacts/analysis/alphatrend_retrospective_comparison_20260912/REPORT.md).

