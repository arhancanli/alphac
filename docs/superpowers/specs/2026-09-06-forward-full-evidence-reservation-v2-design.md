# Forward full-evidence reservation v2: design spec

**Author:** Claude (session), for owner review. **Status:** proposal only, nothing implemented.

**One-minute summary.** The program needs an honest forward Sharpe of 1.5 across up to 14
sleeves, which needs at least 10 new sleeve admissions under contract v7
(`config/sleeve_admission_contract.json`). Zero are admitted. The only prospective trial run so
far, `crypto_carry_portable_v1` (ordinal 229), sealed FINAL INCOMPLETE and can never be
regraded, because nine evidence inputs (stress, execution, capacity, book, weight, mask,
drawdown spec) were not frozen before the primary result ran, and the trial policy treats any
attempt to add them now as a new identity. This spec proposes: (a) a precise, hash-enforced
definition of a "diagnostic" that reuses the sealed primary path and does not spend a new
identity, versus a return-path change that does; (b) closing the seriality guard's real gap,
where a packet marked "complete" unblocks the next reservation even when its decision is
INCOMPLETE, by requiring ADMIT, KILL, or a signed waiver; (c) a pre-acceptance satisfiability
audit proving every frozen scenario can actually fail; (d) exact sourcing for the nine fields a
`crypto_carry_portable_v2` reservation (ordinal 230) must freeze. It also lays out the full data
flow, the owner-gated checkpoints, and a TDD-ordered test list with a mutation for every new
guard. Nothing here spends a hypothesis identity or touches code.

## 1. Problem and goal

The governing objective, read from `config/sleeve_admission_contract.json`
(`objective.honest_forward_sharpe_target`), is an honest forward Sharpe of 1.5, with an
in-sample support band of 2.25 to 3.0 (`implied_in_sample_target`) implied by this book's own
measured 1.5x to 2.0x backtest-to-forward haircut. Reaching it needs "up to 14" sleeves and "at
least ten new admissions" (`objective.minimum_new_sleeves` = 10, `target_total_sleeves` = 14);
fourteen is not a quota, the book stays smaller if fewer clear the gate. Zero new sleeves are
admitted. `docs/design/ALPHAC_MASTER_PLAN.md` (reconciled 2026-09-06) states the durable union
ledger holds 229 hypothesis identities: 228 retired legacy identities plus the one prospective
identity, `crypto_carry_portable_v1`, which has executed once and closed
`INCOMPLETE / NOT ADMITTED`. The published `program_status.json` lives in the site repository
(`~/meridian/public/glassbox/program_status.json`), not here; the numbers above come from the
contract and the master plan.

`crypto_carry_portable_v1`'s closure
(`artifacts/research/crypto_carry_portable_v1_admission_closure.json`) records
`decision.admitted: false`, `disposition: "INCOMPLETE"`, `final_for_admission: true`,
`identity_may_be_regraded_later: false`. Its `governance_finding.required_but_unfrozen_fields`
lists nine fields never hash-bound before the primary result:
`stress_scenario_manifest`, `stressed_cost_grid`, `stressed_execution_grid`,
`capacity_capital_points`, `capacity_fill_model`, `existing_book_snapshot`,
`candidate_book_weight`, `diversification_stress_mask`,
`book_drawdown_simulation_specification`. Two trial-policy files exist:
`config/trial_accounting.json`, which governs (`research_status: ACTIVE_STAGED_PROSPECTIVE_BUDGET`,
`prospective_v7_review.status: IN_FORCE`), and `config/trial_accounting_v7_proposed.json`, whose
own `research_status` and `prospective_v7_review.status` both read `PROPOSED_NOT_IN_FORCE`. The
proposed file is the historical draft that `config/admission_v7_promotion.json`
(`source_bindings.trial_policy_proposal`) already promoted into the active one; it is a
superseded audit-trail copy, not a second live policy. Neither file defines a diagnostic or
supplemental evidence class; `trial_accounting.json`'s only identity exemption is
`window_only_keys: ["start", "end"]`.

## 2. What v2 changes

**(a) Diagnostic evidence class.** A diagnostic scenario computes cost, execution, or capacity
outcomes on top of the exact decisions already sealed in the primary path (same instrument
weights, same entry and exit times); it cannot alter which decisions were made and cannot become
the deployed return series. Anything that changes the decision path (signal, rebalance clock,
universe, weighting) remains a new `hypothesis_identity` under `trial_accounting.json`'s existing
definition. Enforcement: extend `validate_reservation` in
`src/alphaforge/validation/trial_reservation.py` with a check, parallel to
`_validate_governance_epoch`, that every diagnostic scenario in the reservation carries a
pre-frozen `assumptions_sha256`/`result_sha256` pair (the same canonical-hash pattern
`_matches_canonical_sha256` already enforces in `src/alphaforge/validation/sleeve_admission.py`)
and that no diagnostic scenario may be added, removed, or reordered after `reserved_at`.

**(b) Seriality guard.** `_validate_forward_epoch_serial_completion`
(`src/alphaforge/validation/trial_reservation.py:284`) unblocks the next reservation once a prior
packet has `complete: true` and `missing_sections: []`. The sealed
`artifacts/research/trial_packets/da5f5f47f99f9bd2.json` shows exactly this: `"complete": true`
with `disposition: "INCOMPLETE_NOT_ADMITTED"` and
`next_forward_identity_blocked_by_this_packet: false`. Packet completion records evidence
accounting, not a gate outcome, per the closure's own
`governance_finding.seriality_interaction`. V2 requires the guard to also check, for every prior
forward identity, that its sealed closure disposition is `ADMIT` or `KILL`, or that a waiver
record exists. Waiver file shape (new, e.g.
`artifacts/research/seriality_waivers/<hypothesis_key>.json`): `schema`,
`waived_hypothesis_key`, `waived_packet_content_hash` (must equal the exact sealed packet's
`content_hash`, so any re-seal invalidates the waiver), `reason` (free text, minimum length
enforced, same convention as the NOT_APPLICABLE-reason checks in `sleeve_admission.py:618`),
`authorized_by` ("Arhan Canli, owner, <date>"), and a `content_hash` computed the same way
`_observed_content_hash` computes it elsewhere in this file.

**(c) Satisfiability audit.** Before a reservation is accepted, every frozen stress, capacity,
and execution scenario must be provably able to FAIL. Construction: for each scenario, build a
synthetic decision-and-cost path at the extreme of that scenario's own frozen assumption range
(for cost/execution: maximum stated slippage, latency, or rejection rate against a synthetic
high-turnover blotter; for capacity: a synthetic fill ratio set below
`capacity_minimum_stressed_fill_ratio` at the frozen capital point). Pass/fail criterion: running
the scenario's own evaluator against that synthetic path must register the FAIL branch for that
dimension in isolation, with every other dimension held at a trivially passing value. A scenario
that cannot be made to fail within its own frozen bounds fails the audit before acceptance. The
receipt (new, e.g. `artifacts/audit/crypto_carry_portable_v2_satisfiability.json`) lists each
scenario id, its synthetic-path descriptor, and `can_fail: true`, and its hash is bound into the
reservation, following the drift-detection pattern already used by
`scripts/audit_forward_full_evidence_reservation_v2_template.py`.

**(d) The nine frozen fields, sourced (never typed):**

1. `stress_scenario_manifest`, `stressed_cost_grid`, `stressed_execution_grid`: authored per
   `execution_dimensions` in `config/sleeve_admission_contract.json`, scoped to the crypto perp
   venue as the v2 draft requires ("does not supply universal stress multipliers",
   `docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md:86`); hash-bound via
   `execution_evidence_policy.scenario_manifest_required_fields`.
2. `capacity_capital_points`, `capacity_fill_model`: derived from the measured crypto capacity
   sweep in `scripts/capacity_export.py` (sr_ann 0.4009 at $100k, 0.0424 at $1M, -0.3720 at $10M,
   the "capacity cliff"), must include the governing $500,000 point
   (`thresholds.capacity_usd_min`) and at least one point at or above the measured cliff.
3. `existing_book_snapshot`: the four constituent equity curves named in
   `docs/design/CURRENT_BOOK_DRAWDOWN_STUDY_PROTOCOL.md`'s "Frozen inputs" plus the 10% BTC/SPY
   overlay, on the common calendar-day window.
4. `candidate_book_weight`: predeclared per contract
   `diversification_evidence_policy.candidate_weight`; authored by the owner before reservation,
   never fit to a result.
5. `diversification_stress_mask`: predeclared per the same policy block; sourced from a dated
   crisis-window definition consistent with the `crisis_conditional_dependence` and
   `tail_co_loss` items in `required_robustness`.
6. `book_drawdown_simulation_specification`: the frozen estimators in
   `docs/design/CURRENT_BOOK_DRAWDOWN_STUDY_PROTOCOL.md` (bootstrap and correlation-regime
   models, seeds 20260823/20260824), extended to the book-plus-candidate composition rather than
   reused verbatim, since that protocol measures the current four-sleeve book only.

## 3. Data flow

Reservation (`artifacts/research/preregistrations/crypto_carry_portable_v2/return_identity_reservation.json`,
new) validated by `scripts/validate_forward_trial_reservation.py` calling the extended
`validate_reservation` -> runner (`scripts/run_crypto_carry_portable_v2.py`, new, mirroring
`scripts/run_crypto_carry_portable_v1.py`'s `AF_*` env rejection at line 103) writes
`artifacts/prospective/crypto_carry_portable_v2/input_snapshot/manifest.json` -> book-evidence
builder (new script) reads the frozen snapshot, weight, and mask and calls
`alphaforge.validation.diversification.diversification_report` plus the drawdown spec ->
`evaluate_sleeve_evidence` (`src/alphaforge/validation/sleeve_admission.py`, unchanged) -> seal
result (`scripts/seal_crypto_carry_portable_v2_result.py`, new, mirroring
`scripts/seal_crypto_carry_portable_v1_result.py`) -> seal closure
(`scripts/seal_crypto_carry_portable_v2_admission_closure.py`, new) -> packet
(`scripts/build_identity_trial_packets.py`, existing) -> manifest
(`scripts/build_trial_packet_manifest.py`, existing) -> `research_export.py` (existing) -> site.
Each new file-mediated edge (result read by closure, closure read by packet, manifest read by
`research_export.py`) must be added to `tests/unit/test_publish_pipeline_order.py`'s `EDGES`
tuple, the same mechanism that caught the AlphaVintage stale-state bug documented at the top of
that file.

## 4. Owner-gated points

A new promotion record, `config/forward_full_evidence_reservation_v2_promotion.json`, mirrors
`config/admission_v7_promotion.json`: owner, `authorized_by`, `promoted_at`, source bindings to
the template, the diagnostic-class definition, and the satisfiability-audit receipt. Only Arhan
Canli signs it, per every existing promotion in this repository. Budget: `config/trial_accounting.json`
reports `hypothesis_identity_budget: 400`; the master plan states 229 identities spent and
roughly 171 headroom (68.35% planning probability of at least ten admissions, explicitly not a
forecast). Reserving ordinal 230 spends one more. The process must stop and wait: after this spec
is reviewed; after the diagnostic-class and seriality-guard changes are drafted but before they
are wired into the in-force validator; before running the promotion script; before spending
identity 230; and before sealing any ADMIT, which changes the live weight schedule per
`docs/SLEEVE_DISCOVERY_PROGRAM.md`'s admission sequence step 7.

## 5. Tests, TDD order, mutations

1. `tests/unit/test_trial_accounting_diagnostic_class.py` (new): pins the diagnostic definition
   before any code reads it. Mutation: change one diagnostic's bound decision path so it no
   longer matches the primary path; assert it is now classified a new identity.
2. `tests/unit/test_validate_forward_trial_reservation.py`: extend
   `test_reservation_blocks_second_forward_identity_until_prior_packet_is_complete` so today's
   exact `crypto_carry_portable_v1` state (complete packet, INCOMPLETE disposition, no waiver)
   still blocks ordinal 230. Mutation: replay that exact packet with no waiver; assert rejection.
3. `tests/unit/test_seriality_waiver.py` (new). Mutation: point `waived_packet_content_hash` at a
   stale hash; assert rejection.
4. `tests/unit/test_satisfiability_audit.py` (new). Mutation: set a stress multiplier to 1.0 or a
   capacity point at $600k (below the ~$10M measured cliff); assert the audit refuses acceptance
   because the scenario cannot fail. This is decorative-pass risk 1, made concrete.
5. `tests/unit/test_crypto_carry_portable_v2_run.py` (new, mirrors
   `test_crypto_carry_portable_v1_run.py`'s pinned status mutation).
6. `tests/unit/test_crypto_carry_portable_v2_admission_closure.py` (new, mirrors
   `test_crypto_carry_portable_v1_admission_closure.py`), extended to prove ADMIT and KILL are
   both reachable outcomes, not just INCOMPLETE.
7. `tests/unit/test_publish_pipeline_order.py`: add the v2 edges.
8. `tests/unit/test_mutation_coverage.py` (existing) must keep passing. Note: neither
   `test_crypto_carry_portable_v1_admission_closure.py` nor
   `test_forward_full_evidence_reservation_v2_template.py` currently contains any of the four
   substrings `discover_guards` matches on (`artifacts/`, `meridian`, `config/sleeve`,
   `glassbox`), so neither is currently required to carry a mutation in
   `scripts/mutation_ledger.py`. Every new v2 guard test will reference such a path for real
   assertions anyway; register its mutation explicitly rather than relying on the substring rule.
   Decorative-pass risk 2 is the seriality guard itself: it is the literal defect this spec fixes.

## 6. Out of scope and open questions

Out of scope: regrading `crypto_carry_portable_v1` (closure forbids it); changing any threshold
in `config/sleeve_admission_contract.json`; the full atomic multi-identity batch reservation
described in `docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md`'s "Batch accounting and
seriality" section; the overlay covariance-halflife unit defect; any change to
`config/sleeve_discovery.json`'s other candidates.

Open questions:
1. What exact disposition vocabulary does a sealed v2 closure use, ADMIT/KILL as in the
   template's `decision.possible_dispositions`, and does it match the closure schema's existing
   `disposition` field? Answered when a second closure exists.
2. Can any crypto capacity point above $500,000 both qualify and sit meaningfully below the
   measured ~$10M cliff? Answered by a fresh curve in `scripts/capacity_export.py`'s pattern.
3. What exact crisis window defines `diversification_stress_mask` for crypto carry? Answered by
   a new authored mask file, not yet written.
4. Does spending the 230th identity on an already-once-run family change the 6.5% historical hit
   rate `config/trial_accounting.json`'s `budget_review` assumes? Answered by the next owner
   budget review.
5. Should the satisfiability audit be a one-time reservation check or a standing regression that
   reruns as contract thresholds change? Answered by extending
   `scripts/audit_forward_full_evidence_reservation_v2_template.py`'s drift-detection pattern.

## 7. Size estimate

Diagnostic-class definition and validator support: 2-3 sessions. Seriality guard rewrite plus
waiver schema: 1-2 sessions. Satisfiability audit tool: 2-3 sessions. Authoring the nine frozen
fields as real data: 2-4 sessions. Promotion record and script: under 1 session, plus an
unscheduled owner-approval wait. Runner, book-evidence builder, seal scripts, and pipeline-order
wiring: 3-4 sessions. Mutation-ledger registration and full mutation run: 1 session. Total: roughly
12-18 sessions, each stage gated by the checkpoints in section 4.
