# GB_CRITIQUE — Anti-overfit review of the Grand Backtest harness

Role: adversarial anti-overfit / multiple-testing critic.
Reviewed: `docs/design/build/GRAND_BACKTEST.md` against the SHIPPED validation
arsenal it leans on — `analytics/walkforward.py` (`compute_validation`,
`compare_to_baseline`, the `run(...)` trial-recording tail, `_gate_trial_config`),
`validation/experiments.py` (`ExperimentLog`, idempotent `record`, `n_trials`,
`trial_sharpe_variance`), `validation/dsr.py` (`expected_max_sharpe`,
`dsr_from_returns`), `validation/pbo.py` (`pbo_cscv` CSCV), `analytics/metrics.py`
(`PerfSummary`, `daily_returns`, `turnover`), and `cli/walkforward_cmds.py` (the
wiring template). HEAD `73fdae4`.

## Verdict: PASS_WITH_NOTES

The matrix is a genuinely HONEST robustness study in its STRUCTURE: it is bounded
(8 distinct trials + 4 zero-cost capacity runs + the reference blend, ~16 runs, not
a grid), every search dimension is one-knob-at-a-time off a single reference, the
deployment verdict is the correct conjunction (must-beat-baseline AND dsr≥0.95 AND
pbo<0.20 on the same purged legs), and it commits to reporting the full matrix and
stating the expected null plainly. The mechanics that prevent N-inflation are real
and verified against the shipped code:

- **`initial_cash` is excluded from the trial hash.** `walkforward.py:847-857`
  builds `base_trial_config` WITHOUT `initial_cash` (it lives only in the engine
  `config` echo, L823). So Block B's capacity sweep genuinely shares a hash and
  adds 0 to N. ✓
- **The three gated baselines collapse to one ledger line.** Each gated run records
  its blend-only baseline keyed by `base_trial_config` (L884), and
  `_gate_trial_config` returns `{}` when both gates are off (L1055-1068), so
  `A_blend`'s variant hash == every gated baseline's hash. `record`'s idempotency
  (`experiments.py:231-234`) collapses them. ✓
- **The must-beat-baseline gate is the SAME predicate the prior CRITIQUE_overfit #1
  forced into the engine** (`compare_to_baseline`, L502-525: strict `dsr≥0.95 AND
  dsr>baseline.dsr AND sr_ann>baseline.sr_ann`). The harness REUSES it rather than
  reinventing a weaker one. ✓
- **PBO is computed over the VARIANT set, not the capacity duplicates.**
  `oos_returns_matrix`'s contract excludes Block B (which would be N identical
  columns biasing the CSCV rank). `pbo_cscv` needs ≥2 columns and ≥`n_splits` rows;
  the variant set (8 cols) and ~1500 daily OOS rows clear both. ✓
- **A dedicated per-run ledger** isolates N from the polluted global
  `var/experiments.jsonl`. ✓

None of the structural levers manufacture an edge. The notes below are two real
defects (one of which flatters a non-edge and must be fixed before the verdict is
trusted) and several clarity fixes.

---

## BLOCKING — must fix before the verdict can be believed

### GB1. The winner and the per-config DSR gate are judged against a PARTIAL, RUN-ORDER-DEPENDENT N — not the shared final SR* the design itself computes. (the overfit-flattering bug)

This is the core anti-overfit failure and it is subtle because the design looks
honest. `compute_validation` (`walkforward.py:468-499`) **records the trial FIRST,
then reads `N = log.n_trials()` and computes the DSR against the N-SO-FAR** (L478,
L487-498). Because the harness stitches every config onto ONE growing ledger and
runs them sequentially, the `validation.dsr` / `validation.clears_dsr_gate` written
into each `walkforward.json` is deflated against a DIFFERENT, monotonically smaller
benchmark depending on WHEN the config ran:

- `A_blend` runs first → recorded as the 1st (and only finite) trial →
  `trial_sharpe_variance()` returns the `DEFAULT_SR_TRIALS_VARIANCE = 1.0`
  placeholder (`experiments.py:274-275`) → `expected_max_sharpe(2, 1.0) ≈ 0.52`
  (per-period) → its DSR collapses to ≈ 0.
- The gated variants (`A_ml`, `A_regime`, `A_ml_regime`) run next, while N is still
  4-6 → they are deflated against a SMALLER SR* than the final matrix N.
- `C_carry` (last in Pass 1) sees the full N.

`expected_max_sharpe` is monotonically increasing in N, and `DSR = PSR(SR*)` is
DECREASING in SR*. So **the early-run configs get a HIGHER (flattering) DSR than
they would at the final honest N.** Quantified with a realistic per-period
`V[SR] ≈ 1e-4` and a candidate "winner" at `sr_pp ≈ 0.04` over ~1500 daily obs:

| N (at judge time) | SR* (per-period) | DSR of the same curve |
| --- | --- | --- |
| 4  | 0.0107 | **0.871** |
| 6  | 0.0133 | 0.850 |
| 9  | 0.0155 | **0.828** |

A ~4-6 DSR-point swing is enough to flip a marginal variant across the 0.95 gate, or
to reorder which Block-A variant is "highest DSR." The bug is doubly
overfit-flattering for the must-beat-baseline test: `A_blend`'s baseline DSR is
recorded at N=1 with the 1.0 placeholder (≈ 0), so `variant.dsr > baseline.dsr`
compares a variant DSR computed at N≈4-6 against a baseline DSR computed at N=1 —
**two DSRs against different SR\* benchmarks, apples to oranges** — and the tiny
placeholder baseline makes the gate trivially easy to clear on the DSR leg.

The cruel irony: the design ALREADY BUILDS THE CORRECT FIX. `cross_config_dsr(log)`
(§2a) reads the FINAL N / V[SR] / SR* off the ledger after all distinct trials are
recorded, and its docstring calls this "the SHARED `SR*` every config's deflated
verdict is judged against — the matrix-level honest deflation." But nothing actually
judges against it: `select_deflated_winner` (§2d) reads `validation.dsr` /
`validation.clears_dsr_gate` "straight off the runner" (L331), `build_matrix_rows`
fills `MatrixRow.dsr` "straight off `WalkForwardResult.validation`" (schema note
L480-482), and `write_verdict` reports `cross.expected_max_sr` but selects the
winner on the per-config partial-N DSR. The shared SR* is computed and printed but
never enforced.

**Fix.** Re-deflate EVERY config against the shared final `cross` context before any
gate decision. Concretely: `select_deflated_winner`, `build_matrix_rows`, and the
baseline comparison must recompute each curve's DSR (and `clears_dsr_gate`, and the
`variant.dsr > baseline.dsr` leg of `compare_to_baseline`) from that config's OOS
daily returns via `dsr_from_returns(rets, n_trials=max(2, cross.n_trials),
var_sr=cross.sr_trials_variance, ...)` — i.e. ALL configs judged against the SAME
final N and the SAME V[SR]. The raw per-config `walkforward.json` value may still be
SAVED (it is the runner's honest record of what it saw at the time), but the verdict
and the winner MUST use the re-deflated, run-order-invariant DSR. Add a unit test on
synthetic fixtures: run two configs in BOTH orders and assert the deflated winner and
each config's `clears_dsr_gate` are IDENTICAL regardless of run order. Without this,
the headline "deflated verdict" is run-order-dependent and tilts toward passing a
non-edge — the exact failure mode this study exists to rule out.

---

## NOTES — fix for correctness/clarity, not edge-manufacturing

### GB2. The trial-count arithmetic is wrong and self-contradictory (says "13" and "~9"; the true honest N is 8).

§1 "Trial accounting" headlines "**Distinct trials logged on the shared ledger:
13**" then concludes "**N converges to ~9 distinct trials**." Both are wrong, and
they contradict each other. Walking the actual hashes:

- Block A distinct hashes = {`A_blend`, `A_ml`, `A_regime`, `A_ml_regime`} = **4**.
  The 3 gated baselines collapse onto `A_blend`'s hash (GB1 verified) and add
  nothing — `A_blend` is ALREADY one of the four.
- Block C runs are blend-only (`gated=False`), so they spawn NO baseline; distinct
  hashes = {`C_rebal24`, `C_band10`, `C_mvo`, `C_carry`} = **4**.
- Block B = **0** (shared hash).
- **Honest `log.n_trials()` = 8.**

The phrase "A contributes 4 variant trials + **1 shared baseline trial (= A_blend)**"
double-counts `A_blend` (it is both a variant trial AND the shared baseline — one
ledger line, not two). This is not overfit-flattering — if anything it overstates N,
which over-deflates (conservative). But it is a wrong claim in the document's
central honest-accounting section, and a builder who codes `assert n_trials == 9`
(or 13) will trip on the real value 8. Correct the narrative to "8 distinct trials"
and the matrix.json example (`"n_trials": 9`) to match what the ledger will actually
report. The principle is right; the count is not.

### GB3. The example `sr_trials_variance: 0.43` in the matrix.json schema is implausible for a PER-PERIOD V[SR] and will mislead readers calibrating the gate.

`trial_sharpe_variance()` returns the sample variance of **per-period (daily)**
Sharpes (`experiments.py:260-278`), which for daily Sharpes of order 0.01-0.05 is
~1e-4, not 0.43. A V[SR]=0.43 would imply per-period Sharpes spread by ~0.66/day
(annualized SR spread > 12), which is nonsense. The schema's paired
`expected_max_sr: 0.71` is the per-period SR* and is equally implausible (per-period
SR* should be ~0.01-0.02). These are illustrative placeholders, but they bake a
unit confusion into the pinned schema that will mislead whoever reads the verdict.
Replace the example values with realistic per-period magnitudes (e.g.
`sr_trials_variance: 0.0001`, `expected_max_sr: 0.015`) and annotate that BOTH are
PER-PERIOD, never annualized — the same convention `dsr.py` is at pains to enforce.

### GB4. `MatrixRow`/`CapacityPoint` field name `turnover` must map to `PerfSummary.turnover_ann`.

`analytics.metrics.PerfSummary` exposes the annualized one-way turnover as
`turnover_ann` (metrics.py:402), and `max_dd`/`final_equity` as named. The design's
`MatrixRow.turnover` and `CapacityPoint.turnover` are fine as output field names but
the implementer must read `result.summary.turnover_ann` (not `.turnover`, which does
not exist). A build-time detail, not a design flaw — flagged so the smoke test
asserts the mapping rather than silently writing `nan`.

### GB5. PBO over a heterogeneous variant family is defensible but should be stated.

`matrix_pbo` ranks Blocks A+C together (8 configs spanning gate variants AND
rebalance/band/allocator/alpha-subset knobs). CSCV is agnostic to what the columns
represent — it is exactly a config sweep — so this is legitimate. But the "config
family" mixes two different search axes (gates vs portfolio knobs), so a low PBO
means "the IS-best of THIS mixed family generalizes," which is a slightly weaker
statement than "the IS-best GATE generalizes." Not a flaw; the verdict should just
name what the PBO is over so it is not over-read. With ~1500 daily OOS rows the
default `n_splits=16` is well-supported (C(16,8)=12870 < the 5000 cap → seeded
sampling kicks in deterministically; ample rows). ✓ on mechanics.

---

## Things I checked and found GENUINELY honest (no action)

- Bounded matrix size (~16 runs / 8 distinct trials), one-knob-at-a-time off a
  single reference R — not a hundreds-deep grid that would ratchet N to crush every
  Sharpe by construction.
- `select_deflated_winner` returns `None` as the expected honest null; `A_blend` is
  correctly never eligible (no baseline). Winner judged by DSR, ties by sr_ann —
  raw Sharpe is reported but never decisive.
- The deployment verdict is the correct AND-conjunction on the SAME purged legs net
  of costs; it is explicitly "do not weaken."
- Checkpoint/resume + `record` idempotency dovetail correctly: a re-run of a
  half-finished config does NOT double-count N (idempotent on hash).
- Dedicated per-run ledger isolates N from prior CLI runs (reproducible N).
- The honest frame (Phase-10 null) is carried into the verdict; the design commits
  to stating a null plainly and showing the full gate table + capacity curve.

Once GB1 is fixed (re-deflate all configs against the shared final SR* before any
gate/winner decision) and GB2-GB3 are corrected for honesty, this is a top-tier,
genuinely deflated robustness study rather than a search that could flatter a
non-edge.
