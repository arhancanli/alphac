# Phase 12F — LEAKAGE REVIEW (adversarial)

Reviewer role: LEAKAGE REVIEWER. Scope: verify no lookahead in the Phase-12 gated
walk-forward — no `ts_open >= test_start` enters any HMM or meta fit (D3/D4); the
regime lag is applied EXACTLY once (D2); train/serve feature parity holds (D4/#15);
OFF == identity byte-for-byte (D7). HEAD `7039a1a` + uncommitted working tree.

Verdict: **PASS_WITH_NOTES** — no lookahead found on any path. One non-leak hygiene
note (a duplicated `assemble_meta_features` definition).

---

## What was verified (and how)

### D2 — regime lag applied EXACTLY once (no double-shift)

- The lag lives ONLY in the frozen seam `regime.hmm.RegimeHMM.gross_multiplier_series`
  (`raw.shift(lag_days)`, line 649). `lag_days < 1` is rejected (rejects same-day
  `lag_days=0`). The value at day `D` is `raw[D-1]` (filtered posterior through
  `D-1` close).
- `signals.gating.apply_regime_gate` broadcasts that already-lagged daily `G` to the
  hourly panel with ONE backward `pd.merge_asof` on the day-`D` `ts_open`
  (`allow_exact_matches=True`), then a `searchsorted` map back to panel rows. **No
  second `shift`** — confirmed by `grep '\.shift\|shift('` over `gating.py`,
  `features_serve.py`, `walkforward.py` (zero hits). The key is the gate's own
  day-`D` `ts_open`, NOT `available_at`.
- `tests/integration/test_regime_gate_no_same_day_leak.py` proves it adversarially:
  poisoning day-`d` (and EVERY later) BTC observation to NaN leaves day-`d`'s hourly
  `mu_ann` BIT-IDENTICAL to the clean run, while a control asserts day `d+1` DOES
  change (so the pipeline is not inertly ignoring its input). A vacuity tripwire
  asserts `nanstd(G) > 1e-6`. `gate[D] == raw[D-1]` is pinned directly
  (`assert_array_equal(g_vals[1:], raw_vals[:-1])`).

### D3 — HMM fit on the expanding `ts_open < test_start` window only

- `WalkForwardRunner._build_leg_regime` (walkforward.py L1112) slices
  `daily_btc.iloc[daily_ts < test_start]` BEFORE `build_observations`, so no day-`D`
  observation with `ts_open >= test_start` can enter the Baum-Welch fit. Sub-
  `MIN_FIT_DAYS` (730) slices and any degenerate slice fall back to `IdentityRegime`
  (G ≡ 1) rather than raising; an empty pre-window is short-circuited.
- The daily-BTC series is read ONCE over `[global_start, end)` and only ever sliced
  DOWN per leg (`_read_daily_btc`, L1090). The production reader `_PITDailyBtcReader`
  PIT-clamps at `as_of=end`; verified that `build_observations` consumes ONLY OHLC
  (open/high/low/close), never `quality_flags`, so the `as_of`-dependent flag mask
  cannot perturb the observations. A daily bar that closed before `test_start` returns
  bit-identical OHLC at `as_of=end` and `as_of=test_start` (OHLCV rows are not revised
  in this lake; the only `as_of` effect is close-visibility + flag masking).
- `test_walkforward_full_pipeline.py::TestNoTestSpanLeak` spies the REAL `RegimeHMM.fit`
  and asserts every captured `obs.index` max `ts_open < test_start` of its leg, with a
  non-vacuity guard requiring at least one genuine HMM fit (the late legs cross
  MIN_FIT_DAYS; the early legs cold-start). `gate_inactive_frac` strictly between 0 and
  1 confirms BOTH paths fire in one run.

### D4 — meta-model fit on the purged train window; train/serve parity

- `_train_leg_meta` (L1184) selects events strictly `train_start <= ts < test_start`,
  then `build_fit_windows(asof=test_start, horizon_bars=h)` gives
  `fit_end = test_start - h·Δ`. Verified in the frozen seam `ml.model.HistGBMMetaModel.fit`
  (L354-373) that train/ES/iso masks are carved by `decision_ts` vs
  `es_start/iso_start/fit_end`, and the train block is purged of rows whose label `t1`
  overlaps the ES block. Rows with `fit_end < ts < test_start` fall into NONE of the
  three masks and are silently dropped — **no `ts_open >= test_start` decision bar, and
  no label resolution reaching `>= test_start`, enters the fit.** The labeler reads
  bars over `[train_start, test_start)` with `as_of=test_start`; events whose forward
  barrier bars are not in-window get `t1=NaN` and are dropped (conservative).
- TRAIN/SERVE PARITY (#15): BOTH the per-leg trainer (L1243) and the serve gate
  (`_assemble_leg_features`, L572-578) build X through the SAME function
  `signals.features_serve.assemble_meta_features` with the same call shape
  `(signal_frame, {}, _GATE_FEATURE_NAMES)`. The v1 feature surface is the processed,
  direction-signed `alpha_blend` itself (already a column of the ungated blend frame
  the serve path also reads), so train and serve assemble byte-identical X.
- `test_walkforward_full_pipeline.py::TestNoTestSpanLeak` spies the REAL
  `HistGBMMetaModel.fit` and asserts every captured `X.index` max `ts_open < test_start`.
  `test_feature_serve_parity.py` + `test_meta_gate_scales_never_flips.py` pin the
  parity surface.

### D1 — meta gate scales magnitude, never flips; no re-z-score

- `grep cs_zscore|zscore|standardi` over `gating.py`/`walkforward.py`: only docstrings
  (the bug they avoid), no call. The gate multiplies by `|size| ∈ [0,1]` (sign-safe:
  `bet_size_from_prob` is magnitude-only, `IdentityMeta.bet_size` carries `sign==side`).
- `gate_signal_frame` folds `|size|` and `G` into `mu_ann` by linearity
  (`mu_ann · |size| · G`); since both factors are `>= 0`, `sign(mu_ann_gated) ==
  sign(mu_ann)` or 0. `test_meta_gate_scales_never_flips.py` drives the runner's exact
  `gate_signal_frame` call over a REAL mixed-sign cross-section with a NON-constant
  `|size|` and asserts zero sign flips on finite rows, exact ungated reproduction at
  `|size|=1`, and the `|mu_ann| < 3.0` contract still holds.

### D7 — OFF == identity, byte-for-byte

- The gated block is dead on the OFF path (`gated = ml or regime`); `daily_btc` read
  only when `regime`. `test_gates_default_off_identity.py` and the pre-existing
  `test_walkforward_equivalence.py` + `test_mu_contract.py` are GREEN — the OFF equity
  + validation + config hash are unchanged.

### D5/D6 — honest trial count + must-beat-baseline

- `_gate_trial_config` hashes the ACTUAL gate params (feature-set sha, window days,
  n_states, gate weights, lag days) only when a gate is on; absent when off (byte-
  identical config hash). `compare_to_baseline` uses STRICT inequalities (a tie loses).
  `test_experiments_honest_trial_count.py` pins 4 distinct hashes + a 5th for a tuned
  param + the baseline/clears-baseline round-trip. CLI `evaluate` requires
  `clears_baseline_gate` for gated runs.

---

## Runtime verification

`runner.run(ml=True, regime=True)` runs end-to-end on a synthetic tmp lake with a
REAL HMM fit and REAL per-leg HistGBM fits. No runtime bug found; no edit to
`walkforward.py` was needed. mypy --strict + ruff clean on all changed source files.

Tests run (all green): `test_gating.py`, `test_feature_serve_parity.py`,
`test_gates_default_off_identity.py`, `test_meta_gate_scales_never_flips.py`,
`test_regime_gate_no_same_day_leak.py`, `test_walkforward_full_pipeline.py`,
`test_experiments_honest_trial_count.py`, `test_cli_gated_flags.py` (66 tests), plus
the D7 regression `test_walkforward_equivalence.py` + `test_mu_contract.py`.

---

## Notes (non-leak)

1. **Duplicated `assemble_meta_features`.** The function is defined TWICE — in
   `signals/features_serve.py` (the one production train AND serve both use) and in
   `signals/gating.py` (imported only by `tests/unit/test_gating.py`). This is NOT a
   leak (both production paths route through the single `features_serve` copy, so the
   train/serve surface is byte-identical), but it is a maintenance hazard: a future
   edit to one "single surface" definition could silently diverge from the other while
   tests stay green. Recommend deleting the `gating.py` copy and re-pointing
   `test_gating.py` at `features_serve.assemble_meta_features` (or having `gating.py`
   re-export it), so "THE single train/serve surface" is literally one function.
