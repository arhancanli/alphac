# Phase 12F — OVERFIT-GATE REVIEW (D5 must-beat-baseline + D6 honest trial count)

Reviewer role: **OVERFIT-GATE REVIEWER**. Scope: verify the two anti-overfit
decisions are REAL ENFORCED predicates, not cosmetic flags.

- **D5** — `clears_baseline_gate` refuses a gated variant that ties OR loses the
  blend-only baseline, and `af research evaluate` reports it NOT live-eligible.
- **D6** — `trial_config` hashes the ACTUAL gate parameters, so a tuned gated
  variant is a DISTINCT DSR trial (`N` rises → `SR*` rises → the gate hardens).

Verdict: **PASS_WITH_NOTES**. Both predicates are correctly implemented and
enforced end-to-end. One latent (non-reachable-from-runner) hardening note on the
CLI eligibility branch; one observability suggestion. No blocking issues.

HEAD `7039a1a` + uncommitted working tree. `mypy --strict` + `ruff` clean on the
three reviewed source files; 59 Phase-12 tests green
(`test_experiments_honest_trial_count` 11/11, `test_cli_gated_flags` included).

---

## D5 — the must-beat-baseline gate is a HARD predicate (verified)

`compare_to_baseline` (`analytics/walkforward.py:502`) is the predicate:

```python
variant.clears_dsr_gate                 # dsr >= 0.95
AND isfinite(variant.dsr) AND isfinite(baseline.dsr)  AND variant.dsr    > baseline.dsr
AND isfinite(variant.sr_ann) AND isfinite(baseline.sr_ann) AND variant.sr_ann > baseline.sr_ann
```

Runtime-probed truth table (all as designed):

| variant DSR / SR_ann | vs baseline 0.96 / 1.0 | `clears_baseline_gate` |
|---|---|---|
| 0.97 / 1.1 | strictly beats both | **True** |
| 0.955 / 1.1 | own DSR clears 0.95 but **< baseline** | **False** |
| 0.97 / 0.9 | loses on Sharpe | **False** |
| 0.96 / 1.1 | ties DSR | **False** |
| 0.94 / 1.1 (clears_dsr=False) | own DSR below gate | **False** |
| NaN / 1.1 | degenerate variant | **False** |
| 0.97 / 1.1 vs NaN baseline | degenerate baseline | **False** |

The headline overfit refusal — a variant whose **own** DSR clears 0.95 but does
not beat the baseline (0.955 vs 0.96) — is correctly refused. Strict `>` means a
TIE loses (a variant that does not earn the extra trial it costs is rejected),
exactly D5. Non-finite operands compare `False` (a degenerate curve never beats
the baseline) — a guard the spec did not strictly require but which is correct.

**Enforcement is real, not advisory.** Two enforcement points:

1. **Runner tail** (`run`, L869-895): a gated run (`gated = ml or regime`)
   *always* recomputes the blend-only baseline by re-running the legs with
   `ml=False, regime=False` over the IDENTICAL splitter/grid/legs
   (`_run_leg_set(..., ml=False, regime=False, daily_btc=None)`), records it as its
   own distinct ledger trial under the gate-keyless `base_trial_config`, attaches
   it as `validation.baseline`, and sets
   `clears_baseline_gate = baseline is not None and compare_to_baseline(variant, baseline)`.
   The baseline is measured on the same purged legs — apples to apples (D5's
   "identical purged legs net of fees + half-spread + funding").

2. **CLI `evaluate`** (`research_cmds.py:309-337`): `eligible = base_eligible AND
   baseline_ok`, where `baseline_ok` is False for a gated variant whose
   `clears_baseline_gate` is False. Runtime-probed: a gated variant with
   `clears_baseline_gate=False` whose equity-derived DSR clears 0.95 is reported
   `NOT live-eligible (does not beat blend baseline)` — the DSR-clearing path
   does NOT bypass the baseline gate. `test_cli_gated_flags.py::
   test_gated_run_that_loses_baseline_is_not_live_eligible` pins this through the
   real typer command.

The integration tests cover: the canonical tie (a `_FixedDSR` stub giving variant
and baseline identical DSR/SR), the pure-predicate strict-inequality table, the
`to_json_obj` round-trip of the losing report, and the CLI refusal. The
LOSING-while-own-DSR-clears case is covered at the predicate level
(`compare_to_baseline(_vr(0.955, ...), _vr(0.96, ...))`) and at the CLI level
(forced `clears_baseline_gate=False`).

## D6 — the trial hash counts ACTUAL gate params (verified)

`_gate_trial_config` (`walkforward.py:1043`) emits, ONLY when the respective gate
is on:

- `ml` on → `ml=True`, `ml_feature_set_sha` (sha256 of sorted `_GATE_FEATURE_NAMES`,
  16 hex), `ml_window_days` (365).
- `regime` on → `regime=True`, `regime_n_states`, `regime_gate_weights`
  (`GATE_WEIGHTS[n_states]`), `regime_lag_days`.

With both off the helper returns `{}` (verified directly), so the blend-only
`trial_config` is byte-identical to today's HEAD ledger (D7 on the ledger).

Runtime-probed hashes for {blend, ml, regime(n=3), regime(n=2), ml+regime} are
all 5 distinct, and the gate-keyless baseline hash never collides with any gated
hash. So:

- blend / --ml / --regime / --ml --regime are 4 distinct trials; each gated run
  also re-records the blend-only baseline under the SAME gate-keyless
  `base_trial_config`, which is idempotent (not a 5th trial). `n_trials()`
  walks 1 → 2 → 3 → 4. Pinned by
  `test_four_combinations_are_four_distinct_trials` and `test_rerun_is_idempotent`.
- Tuning `regime_n_states` 3→2 is a 5th distinct hash. Confirmed that this moves
  BOTH `regime_n_states` AND `regime_gate_weights` ((1.0,0.7,0.3) → (1.0,0.3)),
  so the variant is doubly-distinguished. Pinned by
  `test_tuning_regime_n_states_makes_a_fifth_hash`.
- A different ml feature set → different `ml_feature_set_sha` → different hash.
  Pinned by `test_tuning_ml_feature_set_makes_a_distinct_hash`.

`N` rising tightens the DSR benchmark `SR*` (`experiments.py` +
`compute_validation` feed `n_trials` / `trial_sharpe_variance` into
`dsr_from_returns`), which is the entire point: a tuned variant pays for the
search it represents. Idempotency is preserved (`ExperimentLog.record` is keyed
on the config hash).

The variant trial is recorded BEFORE the baseline (the variant
`compute_validation` runs at L866, the baseline at L883), so a LOSING gated
variant still costs its own trial — it cannot tie/lose the baseline AND escape
the `N` increment. Good: you cannot fish for a variant for free.

---

## Notes (non-blocking)

### N1 — `evaluate` skips the baseline gate when `baseline` is null but `variant != "blend"` (latent; not runner-reachable)

`research_cmds.py:312-314`: `is_gated_variant = validation is not None and
baseline is not None`. If a `walkforward.json` carries `variant: "ml"` with
`baseline: null` and `clears_baseline_gate: false`, then `is_gated_variant` is
False, `baseline_ok` is True, and a DSR-clearing run is reported LIVE-ELIGIBLE —
the baseline gate is silently skipped.

**This is NOT reachable from the runner.** The variant and baseline
`ValidationReport`s are computed over the IDENTICAL OOS test windows (same
splitter, grid, legs; only the per-leg signal frame differs ⇒ identical bar-close
timestamps ⇒ identical UTC-day count). `compute_validation` returns `None` iff
`< 2` daily returns; so variant-non-None ⟹ baseline-non-None, and the gated
branch only runs when variant is non-None. Verified empirically. The edge is
reachable only via a hand-built or externally-mutated artifact, or a future
refactor that lets the two spans diverge.

Suggested defensive hardening (cheap, future-proofs the seam): key
`is_gated_variant` on `variant != "blend"` rather than on `baseline is not None`,
and treat a gated-variant-with-missing-baseline as NOT live-eligible (fail
closed). One-liner in `evaluate`. Not blocking.

### N2 — observability: `gate_inactive_frac` is reported but not gated on

`gate_inactive_frac` correctly surfaces the cold-start IdentityRegime fallback
fraction (D3/leakage #19). It is reported in `walkforward.json` and the summary
line but is not part of `clears_baseline_gate`. This is by design (the binding
gate is must-beat-baseline), and a regime variant that is 100% identity-fallback
simply ties the baseline on the regime contribution and loses on the extra trial
it cost — so the overfit gate already refuses a vacuous regime variant. No action
needed; flagging only that an operator should read `gate_inactive_frac` when
interpreting a `regime`/`ml+regime` verdict (the CLI summary prints it).

---

## Evidence

- `compare_to_baseline` truth table: 7/7 as designed (runtime probe).
- D6 hash distinctness: 5/5 distinct; gate-keyless baseline never collides.
- `GATE_WEIGHTS` keyed by `n_states` ({2,3}); n_states change moves weights too.
- `evaluate` eligibility logic: gated-losing → NOT live-eligible (baseline ground);
  gated-winning → LIVE-ELIGIBLE; blend-only → judged on DSR alone.
- `mypy --strict` + `ruff`: clean on `walkforward.py`, `research_cmds.py`,
  `walkforward_cmds.py`.
- Tests: `test_experiments_honest_trial_count.py` 11/11; full Phase-12 suite 59/59.
