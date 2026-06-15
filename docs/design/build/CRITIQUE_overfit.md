# CRITIQUE — Overfit / Multiple-Testing review of Phases 9, 11, 12

Role: adversarial overfit / multiple-testing critic.
Reviewed: `docs/design/build/09_labeling.md`, `09_ml.md`, `11_regime.md`,
`12_integration.md` against the shipped validation arsenal
(`validation/dsr.py`, `pbo.py`, `experiments.py`, `analytics/walkforward.py`)
and `leakageCritique.md`.

## Context that frames every finding

The Phase-10 gauntlet judged **crypto-perps-ALONE as NO bounded edge**: PSR ≈ 0.73,
DSR ≈ 0.35–0.44 against a 0.95 gate, PBO ≈ 0.62 (a coin-flip that the in-sample
winner is out-of-sample below median). Bolting an ML meta-model and an HMM regime
gate onto a base with **no demonstrated edge** is the textbook setup for
*manufacturing a prettier overfit*: a flexible learner will find structure in the
noise of a thin base, and a four-way gate cross (`blend / ml / regime / ml+regime`)
is itself a small selection search. The build specs are leakage-rigorous
(cost-honest labels, purged ES, filtered-not-smoothed gate, no same-day leak — all
genuinely correct). **The gap is not leakage. The gap is that nothing in the plan
forces the new layers to PROVE they beat the raw blend before they can be turned on,
and the trial-count `N` that DSR depends on does not honestly absorb the extra
search the ML/regime layers introduce.** The defaults-off flag is a convenience,
not a gate.

Verdict: **PROCEED_WITH_FIXES**. The numbered items below are must-fix before any
gated artifact is allowed to influence a deployment decision.

---

## MUST-FIX (numbered)

### 1. There is NO enforced "must-beat-baseline on a purged WF net of costs" gate. The plan ships a flag, not a gate. (BLOCKING)

`12_integration.md` §(e) item 2 computes the gated `ValidationReport` *and* the
blend-only `baseline` and attaches both to `walkforward.json` so "the operator sees
the gate's marginal lift". That is **reporting, not gating**. There is no predicate
anywhere — not in `walkforward.py`, not in `cli/research_cmds.py::evaluate`
(`eligible = dsr_ok [and pbo_ok]`, L280), not in the spec — that says:

> a gated variant is LIVE-ELIGIBLE only if `variant.dsr >= max(_DSR_GATE, baseline.dsr)`
> AND its OOS net-of-cost Sharpe strictly exceeds the blend-only OOS net-of-cost Sharpe
> on the SAME purged walk-forward.

Because the base failed the gauntlet, the *only* honest reason to add ML/regime is
a demonstrated marginal lift over the base on truly OOS, cost-netted data. Without
a hard predicate, a gated variant that is merely *less bad than the broken base* —
or that wins by luck on one variant of the 4-way cross — can be shipped.

**Fix:** add a `clears_baseline_gate` boolean to `ValidationReport`, computed in
`compute_validation` / the `run` tail, defined as
`variant.dsr >= _DSR_GATE AND variant.sr_ann > baseline.sr_ann AND
variant.dsr > baseline.dsr` on the identical leg set, both net of fees + half-spread
+ funding. Make `evaluate`'s `eligible` require it. Encode the doctrine in the specs
as **"the ML and regime layers SHIP DISABLED and stay disabled until they clear
`clears_baseline_gate` on a purged walk-forward net of costs"** — a tested gate, not
a sentence in a docstring. Add an integration test asserting a gated variant that
ties or loses to baseline is reported `NOT live-eligible`.

### 2. DSR `N` does not absorb the selection pressure the ML/regime layers actually add. (BLOCKING)

`12_integration.md` §(e) item 1 claims honest `N` because `blend / --ml / --regime /
--ml --regime` hash to four distinct `trial_config`s → four ledger lines. This is
true but **dangerously incomplete**:

- It adds *at most 3* trials. The ML layer's real search surface is far larger:
  `DEFAULT_PARAMS` (max_depth, learning_rate, min_samples_leaf, l2, max_bins),
  `P_MIN`, `SIZE_STEP`, the `EARLY_STOP_DAYS`/`ISOTONIC_DAYS` split, the feature set
  (§3 enumerates ~30 columns — every include/exclude is a choice), and the weekly
  promotion gate thresholds (`+0.002` logloss, `0.8×` rank_ic). The regime layer adds
  `K∈{2,3}`, `GATE_WEIGHTS`, `lag_days`, `MIN_FIT_DAYS`, `N_SEEDS`. **None of these
  reach the ledger.** If any are ever tuned by looking at the gated WF curve, that
  is selection pressure DSR cannot see → DSR is overstated exactly when the new
  layers most need deflating.
- `09_ml.md` §2 says each weekly promotion decision "is a trial; `retrain.py` appends
  its config hash to the `ExperimentLog`". 52 promotion decisions/year compound this.
  Good that it logs — but the spec must pin **what config is hashed** so that retuning
  a threshold creates a new trial (otherwise the ratchet hides in idempotent re-logs).

**Fix:** (a) the `trial_config` for an ML/regime run must include the *model
hyperparameters and feature-set hash and gate constants actually used*, not just the
two booleans — so a tuned variant is a distinct trial. (b) Document a hard rule:
**any knob touched while looking at a gated WF result is a logged trial.** (c) State
the expected-N inflation explicitly: adding ML+regime should *raise* `N` and
therefore *raise* `SR*` (`dsr.expected_max_sharpe`), making the gate harder — that is
the point; a plan where DSR gets *easier* after adding two flexible layers is
self-refuting.

### 3. Finding 10 (the vectorized prescreen / PBO sweep matrix) is STILL unwired — `N` is structurally undercounted at its largest source, and the gauntlet's PBO 0.62 has no automated re-test on the gated curves. (BLOCKING)

`ExperimentLog.record` is called from exactly two places: `compute_validation` (one
record per full WF run) and `cli/research_cmds.py`. There is **no sweep/prescreen
logger** anywhere in `src/alphaforge` (grep confirms: no `sweep`/`prescreen` variant
logging). leakageCritique finding 10's fix has two halves and **neither is done**:

1. "log every vectorized variant's config hash into experiments.log too" — not wired.
   So today's `N` already counts only WF runs (a handful), not the thousands of
   factor/threshold variants screened upstream. The DSR ≈ 0.35–0.44 gauntlet number
   was therefore computed against an *already-too-small* `N`; the true DSR is even
   lower. Adding ML/regime — more flexible learners on the same thin base — makes the
   undercount worse, not better.
2. "feed the sweep-stage return matrix to PBO, not just the CPCV finalists." The
   gated specs never feed PBO at all. `pbo_cscv` only runs when an operator hand-supplies
   `--config-matrix` to `af research evaluate`. The gauntlet's **PBO 0.62 failure** —
   the single most damning overfit signal — has no automated counterpart for the gated
   variants. We will add ML+regime and never CSCV-test whether the gated winner is OOS
   below median.

**Fix:** (a) build the `T×N` per-period return matrix from the WF legs of all
evaluated variants (at minimum the 4-way gate cross + each feature/param variant
swept) and run `pbo_cscv` automatically inside the gated-run validation block; gate
on `PBO < 0.20` for the *gated* curve, not just the operator-optional path. (b) Wire
the upstream factor sweep to append config hashes to the SAME ledger (or implement
the Bailey–LdP effective-N clustering) so `N` reflects the full funnel. Until (a)+(b),
**stamp every gated `walkforward.json` "N undercounted; PBO not run on gated variants —
DSR is an upper bound."**

### 4. `DEFAULT_SR_TRIALS_VARIANCE = 1.0` fallback neuters the deflation precisely in the low-trial regime the new layers live in.

`experiments.py` returns `V[SR] = 1.0` whenever `< 2` finite per-period Sharpes exist,
and `walkforward.py` feeds `max(2, n_trials)` to the maths. With only a few WF trials
on the ledger (the realistic state), `expected_max_sharpe` is computed with `V[SR]=1.0`
— a *unit-variance* cross-trial spread that is almost certainly far larger than the
true spread of these highly-correlated variants, so `SR*` is inflated in a way that is
**not data-driven**. This cuts both directions but is not honest either way: the
deflation is a placeholder, and the gated/ungated comparison in §(e) compares two DSRs
both built on that placeholder.

**Fix:** when a gated run reports DSR, require `n_trials >= _MIN_DSR_TRIALS_REAL`
(e.g. ≥ 8 genuinely distinct trials) before the `clears_dsr_gate`/`clears_baseline_gate`
verdict is allowed to read `True`; below that, force the verdict to a third state
`provisional` (never `LIVE-ELIGIBLE`). Surface `sr_trials_variance` source
(`measured` vs `DEFAULT_SR_TRIALS_VARIANCE`) on the report so an operator cannot mistake
a 1.0-placeholder deflation for a measured one.

### 5. The Phase-9 promotion gate judges ML-challenger-vs-ML-champion — NOT gated-pipeline-vs-blend-only. A model can be "promoted" while the gated book still loses to the raw blend.

`09_ml.md` §1.4 `judge_promotion` promotes on `logloss_new <= logloss_champ + 0.002`
and `rank_ic_new >= 0.8·rank_ic_champ`. These are **label-space / model-quality**
metrics — exactly the train/serve-at-the-policy-level skew leakageCritique finding 12
warns about ("a model that looks great on barrier labels can be neutral-to-negative
under the MVO policy"). The deployment gate per finding 12 must be the *full-pipeline
C-engine walk-forward PnL*, not logloss/rank-IC on barrier labels. Nothing in the
promotion gate references the blend-only baseline PnL.

**Fix:** `judge_promotion` must require, in addition to the label-space metrics, that
the gated pipeline (Phase-12 `compute_research_gated` over the OOS window) produces a
net-of-cost OOS Sharpe **≥ the blend-only baseline over the same window**. A model that
improves logloss but does not improve gated portfolio PnL over the raw blend is NOT
promoted. Tie this to the §(e) baseline machinery so there is ONE definition of "beats
the blend."

### 6. Nothing bounds the meta-model's minimum effective sample / label balance — it can confidently fit noise on a thin base.

`09_ml.md` `min_samples_leaf=200` and `l2=5.0` are sensible regularization, but there
is no floor on (a) the number of *effective* (uniqueness-weighted, cluster-deflated)
training events, nor (b) meta-label balance. leakageCritique finding 23 (cross-sectional
event redundancy: ~40 simultaneous regime-correlated events per bar inflate effective N)
is unaddressed in the ML spec — `weights.py` computes *within-symbol* uniqueness only and
the spec explicitly defers cross-symbol commonality to "CV purging," which finding 23
says purging does NOT fix for *in-training* statistics. So the GBM's "200-sample leaf"
may be 200 near-duplicate events = a handful of independent observations. On a base with
no bounded edge, a confidently-calibrated `p` on a near-singular sample is exactly the
noise-fit failure mode.

**Fix:** (a) add a minimum-effective-N guard to `HistGBMMetaModel.fit` /
`weekly_retrain`: refuse to fit (or force `IdentityMeta`) when
`sum(sample_weight) / max(concurrency)` (a crude effective-sample proxy) or the count of
*timestamp-clustered* events is below a floor. (b) Multiply sample weights by `1/√(n_t)`
(finding 23's fix) or report cluster-bootstrapped (by timestamp) error bars on the
gated OOS Sharpe so the §(e) lift is shown with a CI, not a point estimate — a lift
inside its own bootstrap CI is not a lift.

### 7. The 4-way gate cross is a selection search; the plan picks the best variant but does not deflate for having chosen among four.

`12_integration.md` reports `blend / ml / regime / ml+regime` and an operator will
naturally deploy the best of the four. Choosing the max of four correlated DSRs is
itself multiple testing — and §(e) counts them as four ledger trials for the *global*
`N`, which is correct for the global deflation, but does not protect the *selection of
the winner among the four* from the standard "best-of-k" optimism (the same effect PBO
measures).

**Fix:** make the gated PBO (item 3a) include all four variants as columns so CSCV
directly measures whether the IS-best gate variant is OOS below median. Require the
deployed variant to be the IS-best *and* OOS-above-median under CSCV; otherwise default
to the simpler model (blend, then regime, then ml, then ml+regime — Occam tiebreak,
documented).

### 8. Cost-honest labels (09_labeling) are necessary but the spec must state they are NOT sufficient against thin-base overfit — and one cost is optimistically omitted.

The triple-barrier cost-honesty (fees + half-spread + expected funding) is correct and
materially better than gross labels. Two caveats the plan should record so no one reads
"cost-honest" as "overfit-proof":

- **Impact is deliberately excluded** (`09_labeling.md` §1.6: "impact... is excluded
  here"). That is defensible at label time (size unknown) but it means the label is
  *optimistic* on exactly the rank-30–40 alts where impact bites (leakageCritique
  findings 8/11). On a thin base, an optimistically-labeled positive is the noise the
  meta-model will happily fit. State that the gated WF (which DOES apply impact via the
  truth engine fills) is the binding economic check, and that label-space win-rate must
  never be cited as edge.
- **`f_hat` = last-known funding rate over a 72-bar (3-day) hold** is a flat-rate
  expectation across up to ~9–18 settlements; in a regime flip the realized funding
  diverges. This is correctly PIT (no fix needed) but adds *label noise* the learner can
  overfit to. Note it as a known label-noise source feeding item 6's effective-N concern.

**Fix:** add a one-paragraph "cost-honesty bounds, not eliminates, overfit risk" note to
`09_labeling.md` and `09_ml.md`; make the binding gate the gated WF net-of-cost PnL
(items 1, 5), with label metrics explicitly demoted to development diagnostics
(finding 12).

---

## What the plan already gets right (so the fixes are targeted, not a rewrite)

- Leakage discipline is genuinely strong: cost-honest net labels, vertical-exit at
  next open, gap-aware stops, purged ES disjoint from isotonic disjoint from promotion
  (finding 9), filtered-not-smoothed gate with the `d−1` lag + dual guards (finding 13),
  gate-never-flips and OFF==identity equivalence tests (rule 3/R3). None of these need
  fixing; they are the reason this is PROCEED_WITH_FIXES not BLOCK.
- The seam discipline (Protocols, IdentityMeta/IdentityRegime, OFF byte-identical) is
  exactly right and makes "ship disabled" mechanically cheap — the missing piece is the
  *gate that keeps it disabled until proven* (item 1).
- Adding the gate flags to `trial_config` is the correct *direction* for honest N; it is
  just insufficient in magnitude (items 2, 3).

## Bottom line

The build will not leak. The risk is that it will produce a *cleanly-computed,
non-leaking, and still-overfit* number on a base the gauntlet already flagged as edgeless
— and that the plan, as written, lets an operator deploy that number because the only
guardrails are a default-off flag and a side-by-side report. Convert the report into a
hard gate (item 1), make the deflation honest about the new search (items 2–4), tie ML
promotion to gated PnL not logloss (item 5), and CSCV-test the gated variants (item 3a).
Then the ML/regime layers either earn their place by beating the blend on purged,
cost-netted OOS data — or they stay disabled, which on the current evidence is the
correct outcome.
