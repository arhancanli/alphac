# ALPHAC goals — read-only audit and prioritized plan

Audit date: 10 September 2026. Owner: Arhan Canli. Prepared from local operational evidence, read-only scheduler/database inspection, and production HTTP GETs. No strategy, weight, gate, source data, sealed record, scheduler or trading configuration was changed. No research identity was reserved, experiment launched, order submitted, service restarted, message sent or paid data acquired. This document is the audit deliverable, not a promotion or new research authorization.

## Executive conclusion

The paper system is operating and the forward record is growing, but the performance targets are not achieved. The most useful next work is evidence integrity and execution measurement, followed by the already-selected new-family feasibility review. More backtests or extra sleeve names would not resolve the current blockers.

The website design preview is not the newest engine snapshot. Production `/api/v1/status` reported 32 observations through September 10; the local engine maturity artifact at 14:26:53 UTC agrees. Do not use the preview's September 8 artifacts to assess today's research progress.

## Goal scoreboard

| Goal | Verified state | Meaning |
| --- | --- | --- |
| Forward Sharpe 1.50 | 32 daily returns; no reportable forward estimate | The project's frozen contract requires 252 returns for an estimate and 756 plus PSR threshold 0.95 and provenance gates for establishment. Another 220 / 724 observations are needed for those count thresholds alone; passage of time does not guarantee success |
| 14 economically distinct sleeves | Four current sleeves; zero new atlas admissions | Ten additional sleeves must independently qualify. Existing variants, renamed sleeves and incomplete candidates do not count |
| Expected maximum drawdown objective 11% | Current-composition model: 9.318% expected, 16.451% p95 | Research estimates, not established forward risk. Realized paper drawdown to date is 3.871%; that is a different statistic |
| Honest forward record | August 7–September 10; cumulative return −2.65972%; provenance artifact passes | Paper-only normalized composite, not a broker account balance or funded performance |
| Research capacity | 229 identities used / ceiling 400; 171 remaining | First staged review at 320 is 91 identities away; subsequent reviews at 360 and 400, with a 40-identity family tripwire. This is an upper bound, not a work quota |
| Diversification objective | Current-composition research average pairwise correlation about +0.02483, versus −0.03 objective | Retrospective research evidence, not live-forward diversification. The −0.03 objective is not a standalone active admission gate |

Sources: `artifacts/engineering/forward_evidence_maturity.json`, `config/forward_evidence_contract.json`, `config/sleeve_admission_contract.json`, `/Users/arhancanli/meridian/public/glassbox/program_status.json`, and `/Users/arhancanli/meridian/public/glassbox/trial_ledger.json`.

The configuration policy contains historical accounting snapshots of 228 identities and earlier budget numbers. The current generated ledger reports 229; the extra identity is `crypto_carry_portable_v1`, ordinal 229, closed **INCOMPLETE, not admitted**, with no later regrading permitted. Its missing supplemental scenarios were not retroactively invented. See `artifacts/research/crypto_carry_portable_v1_admission_closure.json`.

## Current operations

| Sleeve | Execution basis | Evidence at this audit |
| --- | --- | --- |
| AlphaMax | Dedicated Alpaca paper account | Reconciliation passes; 175 positions, 35 open orders |
| AlphaTrend / managed futures | Dedicated Alpaca paper account | Reconciliation passes; 16 positions, one open order |
| AlphaVintage | Dedicated Alpaca paper account | Reconciliation passes; two positions, zero open orders |
| AlphaForge / crypto carry | Locally simulated paper execution on the sole-writer VPS | Latest mirrored cycle September 10 14:00 UTC is an ordinary hold; September 10 00:00 rebalance records 13 orders, 13 fills, zero rejects |

Broker snapshot: `artifacts/engineering/alpaca_broker_reconciliation.json`, generated September 10 14:25:54 UTC. Open orders are an observation, not proof of a fault. No account identifiers or holdings were copied into this report.

Read-only VPS `systemctl show` confirmed the trade timer active/waiting, its 14:10 run completed at 14:10:44 UTC with exit 0, and the next trigger scheduled for 15:10. The ingestion timer was also active/waiting; its 03:15 run ended at 03:23 with exit 0. An initial SSH attempt using the default identity was denied; the existing key explicitly named by the project sync script succeeded. No authentication settings changed.

GUI-domain launchd inspection confirmed the local export tick running with last exit 0. Paper sleeve jobs and publication were loaded with last exit 0; the health job's last exit was 2 and macro-vintage refresh's last exit was 1. Scheduled one-shot jobs being idle between runs is normal. These are point-in-time checks, not proof of 24/7 availability or the runbook's 99% cycle objective.

The jobs accrue paper observations, ingest sources, export evidence and publish. Their existence does not establish autonomous discovery of new profitable strategies; the research frontier is constrained by explicit data/reviewer gates.

## Findings and priority

### P0 — Reproducible macro-data receipt mismatch

The September 9 nightly health record has three failures and one warning. Its failing published-RTDSM test remains reproducible now using the source-inspected read-only command:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B scripts/seal_alphavintage_rtdsm_portable_fetch.py --validate-published
```

Result: `RuntimeError: Local CPI source's pre-cutoff slice changed: PCPI`.

This validator checks the cutoff-filtered table, not whole-file bytes. Therefore an ordinary append after the receipt's July 15, 2026 cutoff is not sufficient to explain the failure. The receipt still labels itself `PASS_PUBLIC_MACRO_COMPONENT_PORTABLE`; current validation does not support that label. The exact changed rows and cause have not yet been determined. Validation stops on PCPI, so no independent PCPIX-pass claim is made.

Next corrective scope: compare the sealed baseline with the current pre-cutoff slice in an isolated workspace; establish whether this is a source revision, reconstruction change or corruption; preserve both versions and the failed check; then propose a source-bound correction. Do not simply update the receipt hash, relax the test or rewrite old vintages to make the check green. A passing broker reconciliation and forward provenance check do not cover every research reproduction receipt.

### P0 — Macro refresh failed today

`var/log/macrovintage.out` records a September 10 04:23:26 UTC refresh failure: `http.client.RemoteDisconnected: Remote end closed connection without response`. The job explicitly returned 1. The lake metadata still reports a September 9 04:53:05 UTC build.

The current PCPI/PCPIX latest vintage is August 15; monthly vintage age alone is not evidence of stale daily data. The failed refresh and missing acquisition observation are the operational findings. Establish whether failed downloads preserve a complete last-good source set and whether arrival-lag recording remains truthful. No refresh was forced during this audit.

### P1 — Last night's crypto alarm is not today's rebalance state

The September 9 23:32 health snapshot reported the last emitted book as July 30, 42 days earlier. Current read-only SQLite queries show a successful September 10 00:00 rebalance. The same database preserves a September 3 rebalance failure involving an unknown `XUSE:CASH:AALUSD` instrument. Latest hourly holds do not themselves prove successful rebalances; the separate `orders=` cycle record does.

Do not copy the old “42 days” alarm into today's status or erase the historical failure. Verify the next scheduled health report incorporates the new rebalance, and examine the failed instrument-resolution path before describing reliability as fully resolved. This audit neither proved the original defect fixed nor changed execution.

### P1 — Execution-cost evidence is incomplete

The existing cost-realism study identifies a missing decision-price benchmark and fee data for equity sleeves. Direct inspection of the AlphaMax paper database confirms its fills table stores `limit_price`, `fill_price` and submission time, but no decision-reference or fee column. A padded limit is not an independent execution benchmark. A similarly named field elsewhere in the codebase does not prove it is persisted on this running path.

Next design scope: capture clearly distinguished decision and arrival reference prices, quote timestamps/provenance, fills and available fees; leave unavailable values explicitly unknown. Test persistence on the exact broker path, then seek separate approval for prospective runtime instrumentation. Never backfill historical benchmarks with hindsight or change cost assumptions based on incomplete comparisons. Recording fields is not itself proof of realized slippage or improved Sharpe.

The existing execution-gap study is an older limited-overlap diagnostic, not a current portfolio-wide estimate. Before repeating comparisons, bind the exact strategy configuration, common dates and measurement protocol; do not introduce uncounted new return variants.

### P1 — Breadth progress needs an independent reviewer

The selected next family is **active ownership escalation**, based on Schedule 13D control-intent events. The current selection record reports 15.75 years of held source history, passed machine gates and **0 of 48 independent blind labels**. It expressly forbids opening classifier scores, returns, correlations or capacity until the completed source labels and independence attestation pass the governed importer.

I cannot serve as the independent no-AI reviewer or manufacture those labels. Do not recruit or send the packet without owner approval of the reviewer and any cost. The frozen packet already exists under `artifacts/labeling/active_ownership_13d_item4_v3_blind/`.

The initial point gates are precision ≥95%, recall ≥80% and exact ownership agreement ≥90%. Passing them is not admission. The separate confirmatory protocol specifies 640 disjoint filings, 40 per year from 2010–2025, with confidence-bound criteria before admission. That exact technical draft still marks owner approval pending, and acquisition is conditional on the initial review passing. No confirmation documents were acquired by this audit.

The current 20-family reachability screen identifies no family immediately unlocked merely by more parser engineering: 13 require vendor decisions; the others require human evidence, a reachability ceiling, identity redesign, longer history, missing point-in-time history or executable marks. That is a scoped screen result, not a claim that no other strategy can exist.

### P2 — Governance prose and alert delivery need reconciliation

The active v7 admission contract removes the old global average-correlation point gate in favor of candidate and marginal-book tests. However, the forward-evidence contract's diversification prose and parts of `docs/SLEEVE_DISCOVERY_PROGRAM.md` still describe the older non-positive global point gate. Current generated maturity evidence explicitly identifies the active v7 scope. Document and test the precedence; do not silently change scientific thresholds or regrade known results.

The health snapshot also warns that alert email uses a sandbox sender. Configuration presence is not verified delivery. A separately approved test should validate the intended delivery path; no email was sent during this audit.

## Research plan — gated sequence

1. **Integrity correction first.** Diagnose and propose fixes for the PCPI mismatch and refresh failure in an isolated workspace. Exit: source differences explained, originals preserved, relevant tests pass for the right reason, and no unsupported portability claim remains. Production data correction/publication requires separate approval.
2. **Execution observability.** Specify and test prospective benchmark/fee provenance on the real code path. Exit: controlled fixtures reproduce execution measurements, missing data fails honestly, migration/recovery plan reviewed. Deployment and any runtime change require approval.
3. **Independent active-ownership review.** Owner selects an eligible reviewer and approves cost/coordination. Preserve the original packet and no-AI boundary. If the fixed initial gate fails, stop that identity; do not tune on returned labels. If it passes, review the conditional confirmatory design and next preregistration before acquiring its corpus or opening returns.
4. **One prospective identity at a time.** Use the existing full-evidence reservation template to bind the data snapshot, holdout, candidate weight, existing-book snapshot, cost/execution scenarios, capital grid, stress mask and risk-simulation specification before results. The incomplete portable-carry identity demonstrates why naming output classes alone is insufficient.
5. **Evaluate unchanged v7 gates.** Among the existing requirements: ≥756 out-of-sample observations; ≥504 correlation observations; candidate mean correlation ≤0; positive incremental book Sharpe and positive lower 95% bound; positive leave-one-period-out book contributions; expected drawdown ≤11%; required tail-risk comparisons, stress, capacity and execution evidence. DSR must be measured and disclosed; 0.95 is not an individual-sleeve admission gate. Review the complete contract, not this abbreviated list, before any experiment.
6. **Earn forward evidence.** Keep the existing paper epoch observable while research proceeds separately. A live-configuration fingerprint change starts a new evidence epoch under the contract; pre/post-change curves must not be silently pooled. More backtests do not accelerate the forward calendar.
7. **Only afterward: release, distribution and any funded decision.** Finish website/Figma release gates separately, market inspectable records and developer tools, and never present paper or simulated results as funded performance. No funded trading or external investment solicitation is authorized here.

The recent additive attribution identifies crypto as the largest loss contributor (approximately −2.496 percentage points of additive contribution). This is descriptive, not a reason to optimize weights after 32 returns. Additive attribution and compounded cumulative return use different arithmetic and must not be interchanged. The recorded decision is `MONITOR_ONLY_NO_WEIGHT_CHANGE`.

## Scope and evidence limits

- No full test suite was rerun: the nightly failure was inspected and its specific failing read-only validator reproduced. The website's 279 tests do not certify the ALPHAC engine.
- No human reviewer was engaged; no labels, unopened candidate returns or confirmation corpus were read.
- No historical data was reconstructed, no hypothesis was spent and no evidence counter was edited.
- Public sources checked by GET: `https://canlicapital.com/api/v1/status` and `https://canlicapital.com/glassbox/next_sleeve_selection.json`. Native HTTP was used after the browsing lookup failed; the Firecrawl CLI was unavailable and was not installed.
- Source snapshots can advance naturally while the scheduled system runs. Dates above describe the inspected observations, not permanent status guarantees.
- Useful references: `var/health/status.json`; `scripts/health_check.py`; `var/trading_crypto_perp.sqlite` (read-only queries); `artifacts/publication/alphavintage_rtdsm_portable_fetch.json`; `scripts/seal_alphavintage_rtdsm_portable_fetch.py`; `artifacts/analysis/atlas_reachability_screen/result.json`; `artifacts/analysis/next_sleeve_selection.json`; `docs/design/ACTIVE_OWNERSHIP_CONFIRMATORY_CORPUS_PROTOCOL.md`; `docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4_V3.md`; `artifacts/analysis/cost_model_realism/result.json`; `artifacts/engineering/forward_sleeve_contribution.json`.

## Next permission gate

Recommended next phase: isolated macro-data integrity diagnosis and corrective implementation, preserving sealed evidence, with focused regression tests. No trading changes, forced production refresh, service restart, data overwrite, receipt resealing, publication or spending without separate explicit approval. Independent-review coordination is a separate owner decision and can proceed in parallel once approved.

### Approved follow-up, September 10

The isolated diagnosis found **blank-cell expansion, not changed CPI values**: both CPI tables gained 333 missing cells outside the receipt's original observation range, with zero changed existing values and zero removed keys. Archived raw hashes and original normalized hashes were reproduced. An isolated validator correction retains the exact old hashes while rejecting populated extensions and actual historical changes. A candidate-only refresh implementation was also tested; it never promotes data or writes production arrival records. Thirty focused tests passed, including a real-builder archived-workbook integration with synthetic daily inputs and network disabled. Nothing was deployed or resealed. See `/Users/arhancanli/alphac-macro-review.xabapR/REVIEW.md`. The next integration/rollout phase still requires approval.
