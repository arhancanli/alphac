# Phase 12F — Determinism Review

**Reviewer role:** DETERMINISM REVIEWER (Phase 12 — ML meta-gate + HMM regime gate
wired into the full-pipeline walk-forward).
**Base:** HEAD `7039a1a` + uncommitted working tree.
**Date:** 2026-06-16.

## Verdict: PASS

Two independent `WalkForwardRunner.run(ml=True, regime=True)` invocations over the
SAME tiny synthetic lake produce a **byte-identical** stitched OOS equity curve, an
**identical** `ValidationReport` (variant + nested blend-only baseline), and
**identical** per-leg risk counters. Both gates fire for real (a genuine seeded
`RegimeHMM` Baum-Welch fit and a genuine seeded `HistGBMMetaModel` fit) on the run, so
determinism is asserted against the heavyweight stochastic seams, not stubs. `ruff` and
`mypy --strict` are clean on every changed file.

## What was verified

### 1. Byte-identical equity across two identical gated runs

New test: `tests/integration/test_walkforward_gated_determinism.py` (7 tests, ~30s
module wall-time — well inside the 90s budget; the two genuine HMM fits on ~720-740
daily rows are the only heavyweight steps, and the synthetic lake is built once,
module-scoped, with the two runs reusing it).

- `test_stitched_equity_is_byte_identical` — `Series.equals` (dtype + index + every
  value, no tolerance) PLUS a belt-and-braces `np.array_equal` on the raw float64
  values and the int64 ts index. A single divergent ULP would fail.
- `test_final_equity_matches_exactly` — final marked OOS equity compared by
  `float.hex()` (bit-exact).
- `test_validation_report_is_identical` — `variant == "ml+regime"`,
  `gate_inactive_frac`, `clears_baseline_gate`, `sr_ann.hex()`, and the full
  `to_json_obj()` (including the nested blend-only baseline block) all identical.
- `test_baseline_block_is_present_and_identical` — the gated variant carries the
  blend-only baseline (D5) and its `sr_ann.hex()` is run-invariant.
- `test_leg_count_and_spans_match` / `test_per_leg_risk_counters_match` — leg layout
  `(train_start, test_start, test_end)` and the per-leg risk-counter deltas
  (rebalances / fallbacks / holds / halts) match exactly.
- `test_two_gated_runs_produce_a_nonflat_curve` — anti-vacuity guard: the curve
  genuinely trades (`fills > 0`) and moves (`std > 0`), so the equality is asserted
  against a curve that exercised the full gated pipeline rather than two flat lines.

The two runs write to **separate** `out_dir`s and **separate** experiment ledgers, so
neither perturbs the other; run B executes after run A in the same process and is still
bit-identical, which also rules out leaked global `np.random` state between runs.

### 2. Why determinism holds (seed audit)

Every random draw in the gated path is seeded with a fixed constant:

- **HMM** (`regime/hmm.py`): `RANDOM_STATE: Final[int] = 42`; the multi-seed
  Baum-Welch restart loop derives per-seed RNGs from
  `np.random.SeedSequence(self._random_state).spawn(self._n_seeds)` — no global RNG, no
  wall-clock. The winning fit is selected by best data log-likelihood (a deterministic
  argmax over the seeded restarts). States are pre-sorted by ascending vol, so the
  gross-multiplier mapping is label-stable.
- **HistGBM** (`ml/model.py`): the classifier is constructed with `random_state = 42`
  (default), threaded into the serialized params.
- **Fixture**: the daily-BTC series (`default_rng(7)`) and hourly closes
  (`default_rng(101 + k)`) are the only data randomness, identical run-to-run.
- **Gate broadcast** (`signals/gating.py::apply_regime_gate`): the daily→hourly join is
  a single backward `pandas.merge_asof` on a `np.unique`-sorted ts grid followed by a
  `np.searchsorted` scatter — both order-deterministic; no dict-iteration or unstable
  sort feeds a value.

### 3. OFF == identity, byte-for-byte (D7) — still holds

`tests/integration/test_walkforward_equivalence.py` (the OFF-path equivalence pin) is
GREEN alongside the gated suite. The gated code path is dead when `ml=regime=False`
(`gated = ml or regime`), so the determinism of the gated path does not regress the
shipped blend-only determinism.

### 4. Static checks

- `ruff check` — **All checks passed** on all 6 changed/new source files
  (`analytics/walkforward.py`, `cli/research_cmds.py`, `cli/walkforward_cmds.py`,
  `signals/__init__.py`, `signals/features_serve.py`, `signals/gating.py`) plus all 8
  Phase-12 test files and the new determinism test.
- `mypy --strict` — **Success: no issues found in 7 source files** (the 6 changed
  source files + the new determinism test).

### 5. Full Phase-12 suite

All Phase-12 tests pass together (79 tests across the 9 Phase-12 test modules + the
OFF-path equivalence test): the runtime-verification full pipeline
(`test_walkforward_full_pipeline.py`), the D7 identity
(`test_gates_default_off_identity.py`), the D1 scale-never-flip
(`test_meta_gate_scales_never_flips.py`), the D2 no-same-day-leak
(`test_regime_gate_no_same_day_leak.py`), the D5/D6 honest-trial-count
(`test_experiments_honest_trial_count.py`), the CLI flags
(`test_cli_gated_flags.py`), the unit gating + feature-serve-parity tests, and this new
determinism module.

## Reproduce

```bash
export PATH="$HOME/.local/bin:$PATH" && cd /Users/arhancanli/alphaforge
uv run pytest tests/integration/test_walkforward_gated_determinism.py -q
uv run ruff check src/alphaforge/signals/gating.py src/alphaforge/analytics/walkforward.py \
  src/alphaforge/signals/features_serve.py src/alphaforge/cli/walkforward_cmds.py \
  src/alphaforge/cli/research_cmds.py src/alphaforge/signals/__init__.py \
  tests/integration/test_walkforward_gated_determinism.py
uv run mypy --strict src/alphaforge/signals/gating.py src/alphaforge/analytics/walkforward.py \
  src/alphaforge/signals/features_serve.py src/alphaforge/cli/walkforward_cmds.py \
  src/alphaforge/cli/research_cmds.py src/alphaforge/signals/__init__.py \
  tests/integration/test_walkforward_gated_determinism.py
```

## Notes / non-blocking observations

- **Ledger separation is the caller's job.** Determinism of the `ValidationReport`'s
  DSR/PSR fields depends on a fresh-per-run `ExperimentLog`; this is correct by design
  (the ledger is the cross-trial selection-bias accumulator, intentionally stateful
  across configs). The determinism test isolates each run on its own ledger, mirroring
  how a CI re-run or a fresh experiment would behave. With a SHARED ledger, the second
  run of the same config is idempotent on the config hash (`N` unchanged), so the DSR
  inputs would still match — but the test does not rely on that, and shouldn't.
- **The determinism test uses `_stub_dsr`** so the verdict's bit-equality is asserted
  on the curve-derived `sr_ann` (real) rather than re-deriving scipy's DSR twice; the
  real `dsr_from_returns` is itself a pure function of the (identical) returns, so this
  narrows the determinism surface to the parts Phase 12 actually introduced without
  weakening the guarantee.
