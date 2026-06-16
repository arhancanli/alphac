# Grand Backtest — CORRECTNESS CRITIQUE (vs the real APIs)

Reviewer role: correctness critic. Scope: verify the pinned `grand_matrix.py`
interface in `GRAND_BACKTEST.md` against the SHIPPED APIs
(`analytics/walkforward.py`, `validation/{pbo,dsr,experiments}.py`,
`analytics/metrics.py`, `cli/walkforward_cmds.py`, `regime/hmm.py`,
`signals/service.py`, `features/registry.py`). Flag anything that would crash the
detached run or break the honest-accounting goal.

Verified against HEAD `73fdae4`. `src/alphaforge/analytics/grand_matrix.py` and
`scripts/grand_backtest.py` do NOT yet exist (this is a design review).

---

## What is CORRECT (no change needed)

- **Runner signature + wiring.** `WalkForwardRunner(reader, instruments, universe,
  cost_model, signal_service, settings, *, cost_inputs, registry, daily_btc_reader,
  regime_n_states=3, regime_lag_days=1)` and `.run(start, end, *, train_bars,
  test_bars, allocator, embargo_bars, initial_cash, instrument_ids, rebalance_bars,
  no_trade_band, out_dir, now_ms, alpha_names, experiment_log, dsr_fn, ml, regime)`
  match the spec exactly. The CLI wiring (`LakePaths` → `PITDataReader`,
  `InstrumentStore` ctx-mgr, `UniverseStore`, `FeatureEngine`, `SignalService(...,
  default_registry(), settings.signals, alpha_names=...)`, `TransactionCostModel.
  from_settings`, `_PITDailyBtcReader(reader)` only when regime) is faithfully
  mirrored. `import alphaforge.features.library` before `default_registry()` is
  correct (registers the factor library).
- **Shared `ExperimentLog` threading + idempotency.** `compute_validation` records
  the trial keyed by `variant_trial_config` and the gated runs internally re-run +
  record the blend-only baseline under `base_trial_config`. The integration test
  `tests/integration/test_experiments_honest_trial_count.py` PROVES the exact
  mechanism the matrix relies on: blend=1, +ml=2, +regime=3, +ml+regime=4, and
  re-running identical configs stays 4 (idempotent). Passing `experiment_log=<dedicated
  ledger>` to every `run(...)` is the supported pattern. The dedicated per-run ledger
  + `record` idempotency makes the checkpoint/resume rule sound (record precedes
  `save`, so a crash between them re-runs and re-records idempotently; a crash after
  `save` skips and the ledger line persists). **Sound.**
- **PBO.** `pbo_cscv(perf_matrix: DataFrame|ndarray, *, n_splits=16,
  max_combinations=5000, seed=42) -> PBOResult(pbo, lambdas, is_oos_pairs,
  n_combinations)`. Verified: an 8-column (Blocks A+C) × ~1600-daily-row matrix runs
  clean at `n_splits=16`; a tiny smoke matrix runs at a small even `n_splits`. The
  inner-join-on-shared-daily-grid construction is valid (variants tile identical legs).
  The "≥2 columns, ≥n_splits rows" guard the spec promises matches `pbo_cscv`'s own
  `ValueError`s. **Correct.**
- **DSR.** `dsr_from_returns(daily_returns, n_trials, sr_trials_variance,
  periods_per_year=365) -> DSRReport(psr, dsr, sr_ann, sr_per_period, skew, kurtosis,
  n_obs, expected_max_sr)` and `expected_max_sharpe(n_trials>=2, var)` match. Verified
  the capacity curve CAN deflate a per-capital series against the SHARED context by
  calling `dsr_from_returns(series, cross.n_trials, cross.sr_trials_variance, 365.0)`
  — it reproduces `cross.expected_max_sr` exactly (0.9228 at N=8, V=0.4). `cross_config_dsr`
  reading `log.n_trials()` + `log.trial_sharpe_variance()` + `expected_max_sharpe(max(2,N),
  V)` is correct (`trial_sharpe_variance` returns the documented `DEFAULT_SR_TRIALS_VARIANCE`
  fallback when < 2 finite trials, so `max(2,N)` is the right guard).
- **C_carry factor names resolve.** `carry_fund_21`, `carry_fund_90`, `mr_res_72` are
  all present with `direction=1`; `default_registry().get(<missing>)` raises `KeyError`,
  so the "fail loudly on a typo'd factor" promise holds. There are 16 directional alphas
  (the `alpha_names=None` default).
- **Deployment-verdict conjunction** (`winner is not None` AND `pbo < 0.20`, all on the
  same purged legs) is faithful to `compare_to_baseline` / `clears_dsr_gate` /
  `clears_baseline_gate` as shipped. `select_deflated_winner` correctly treats `A_blend`
  as never eligible (no baseline; `clears_baseline_gate=False` for a blend-only run).

---

## BLOCKING — would crash or break the honest-accounting goal

### B1. Per-config DSR is deflated against a RATCHETING N, not the shared final N — the verdict is order-dependent and anti-conservative for early-ordered configs

`compute_validation` computes each config's `validation.dsr` **at run time**, against
`log.n_trials()` AS IT STOOD WHEN THAT CONFIG RAN. In Pass-1 order the first distinct
config (`A_blend`) is deflated against `max(2, N=1)=2`; the last (`C_carry`) against
`N=8`. `build_matrix_rows` reads `validation.dsr` straight off `walkforward.json`, and
`select_deflated_winner` ranks variants by that same per-config `validation.dsr`. So the
Block-A/C rows are NOT judged against the same `SR*`:

- `expected_max_sharpe(N, V=0.4)`: N=2 → 0.329, N=8 → 0.923 (per-period). The benchmark
  nearly TRIPLES across the run.

This directly contradicts the design's own §2a, which defines `CrossConfigDSR.expected_max_sr`
as "the SHARED `SR*` every config's deflated verdict is judged against — the matrix-level
honest deflation," and the prompt's mandate that "every DISTINCT config logs ONE trial →
N rises → DSR deflates correctly." As written, a gate variant that happens to run early is
judged against a much lower bar than one that runs late — exactly the overfit-hiding the
harness exists to prevent. In the EXPECTED null (per-period SR ≪ 0.33) every variant fails
regardless, so the bug is latent; but a borderline variant could be declared the deflated
winner purely because of run order, producing a DISHONEST PASS. Capacity already re-deflates
against `cross` (§2c), so only the variant rows are inconsistent — an internal contradiction.

**Where:** `grand_matrix.py` `build_matrix_rows` / `select_deflated_winner` / `MatrixRow.dsr`
(§2d) reading run-time `validation.dsr`; `cross_config_dsr` (§2a) defining but not applying
the shared `SR*`.

**Fix:** Deflate EVERY distinct-trial row against the SHARED `(cross.n_trials,
cross.sr_trials_variance)` after Pass-1, exactly as the capacity curve already does. For each
variant recompute `dsr_from_returns(daily_returns(result.equity), cross.n_trials,
cross.sr_trials_variance, 365.0).dsr` (and recompute `clears_dsr_gate` and the must-beat-baseline
predicate from these re-deflated numbers, re-deflating the baseline's stitched equity the same
way). `select_deflated_winner` then ranks on the shared-`SR*` DSR. Keep the run-time `validation.dsr`
only as an audit field if desired, but the verdict + winner MUST use the shared-`SR*` DSR. This is
a pure add (the API supports it — verified) and makes "judged against the SAME `SR*`" literally true.

### B2. `CapacityPoint.sr_ann` (and `MatrixRow.sr_ann`) cannot come from `result.summary` — `PerfSummary` has no `sr_ann`; a literal read is an `AttributeError` crash

The spec says capacity "pulls `result.summary` (sr_ann/max_dd/turnover/final_equity)"
(§2c) and that `psr/dsr/sr_ann` "come straight off `WalkForwardResult.validation`" while
"`max_dd/turnover` from `result.summary`" (§3). `PerfSummary`'s fields are: `... sharpe,
..., max_dd, ..., turnover_ann, ...` — there is **no `sr_ann`** and **no `turnover`**
(it is `turnover_ann`). `result.validation` DOES have `sr_ann`. So:

- `result.summary.sr_ann` → `AttributeError` (crash). `sr_ann` must come from
  `result.validation.sr_ann` (the annualized OOS daily Sharpe) — NOT `summary`.
- `result.summary.turnover` → `AttributeError`. Must be `result.summary.turnover_ann`.

The §2c doc string "pulls `result.summary` (sr_ann/...)" is the trap: an implementer who
follows it literally writes a crashing access. (`select_deflated_winner` says `sr_ann` is
"read straight off the runner" via `validation` — which is the CORRECT source — so the
spec is self-inconsistent on where `sr_ann` lives.)

**Where:** `grand_matrix.py` `capacity_curve` (`CapacityPoint.sr_ann`, `.turnover`) and
`build_matrix_rows` (`MatrixRow.sr_ann`, `.turnover`); §3 prose.

**Fix:** Source `sr_ann` from `result.validation.sr_ann` (guard the `validation is None`
case — a < 2-day OOS span yields `validation=None`). Source `turnover` from
`result.summary.turnover_ann` (and `max_dd`, `final_equity` from `summary`). Note that
`summary.turnover_ann`/`fees_paid` are `nan` unless `fills` carry a `notional` column — the
real engine fills do, so the live run is fine, but the smoke fixture must populate fills or
the capacity-curve `turnover` will be `nan` (acceptable, but assert intentionally).

---

## NON-BLOCKING — must surface / accuracy nits (no crash)

### N1. Distinct trial count is 8, not "~9" — the design over-counts by one

The integration test proves Block A = 4 distinct trials (the 3 gated baselines collapse
onto `A_blend`'s line). Block C = 4 distinct. So `log.n_trials()` = **8**, not 9. The spec's
"N converges to ~9 distinct trials" (§1 trial-accounting + 14-line summary #7) is off by
one: it double-counts the shared baseline as both "A contributes 4 variant trials + 1 shared
baseline (= A_blend)" — but `A_blend`'s own variant trial IS that shared-baseline line (same
`base_trial_config` hash), so it is 4 + 0 + 4 = 8. The harness "reports the HONEST
`log.n_trials()` it observes," so nothing breaks; the example `matrix.json` (`"n_trials": 9`)
and the prose should say 8. Cosmetic but worth fixing so the design's arithmetic is honest.

### N2. The regime gate is INERT for the first ~730 days of OOS — "the real lever" framing overstates the early legs

`run()` reads daily-BTC over `[run_start, end)` = `[2021-01-01, end)`, and each leg's HMM
fits on the expanding slice `ts_open < test_start`. `regime/hmm.MIN_FIT_DAYS = 730`. The
first leg's `test_start ≈ 2022-01-01` has only ~365 daily-BTC rows before it → `build_observations`
raises → documented `IdentityRegime` fallback. The gate cannot activate until
`test_start ≥ run_start + 730d ≈ 2023-01-01`, i.e. the first ~4 of ~17 OOS legs run blend-only.
This is INHERENT to reading daily-BTC over the run window (with `train=365d` the gate can never
have 730 prior days for the first leg). The synthetic fixture's own docstring confirms the
mechanism ("every leg cold-starts to IdentityRegime … the real ≥730-day HMM fit is pinned by
the runner's pipeline test"). No crash — `gate_inactive_frac` already records it — but the
design calls regime "the real lever" (§0, §1, §2d, summary #14) without qualifying that it is
partially inert early. **Fix:** the verdict.md MUST report each regime variant's
`gate_inactive_frac` prominently and state plainly that the early legs are blend-only; consider
documenting that a longer warm-up window (start daily-BTC read at the lake floor 2020-03, or
push `run_start` earlier and drop the under-warmed legs from the regime-vs-blend comparison)
is the only way to make the regime lever fully live across all OOS legs. At minimum, do not
let the verdict claim "regime changed/did not change the result" without disclosing how many
legs the gate was actually active in.

### N3. `max_dd` sign convention — `summary.max_dd` is a NON-NEGATIVE fraction; the schema example shows it negative

`metrics.max_drawdown` / `PerfSummary.max_dd` is a non-negative depth fraction (0.34 = a 34%
drawdown). The `matrix.json` example (§3) and capacity example show `"max_dd": -0.34` /
`-0.31`. Pick one convention and apply it consistently in `write_matrix_json` /
`build_matrix_rows`. Recommend storing the raw `summary.max_dd` (non-negative) and documenting
it, or negating consistently — but don't read `summary.max_dd` expecting a negative number.

### N4. `validation is None` edge must be handled in every reader

`WalkForwardResult.validation` is `None` when the OOS span is < 2 UTC days (real for a
degenerate smoke leg). `build_matrix_rows`, `select_deflated_winner`, `oos_returns_matrix`
(via `daily_returns` returning empty), and `capacity_curve` must all tolerate
`validation is None` / an empty daily-return column without crashing (skip the column /
emit `null` row fields per the `_json_float` convention). The spec mentions "the rare
0-daily-return run" in the checkpoint rule but not in the writers — make it explicit so the
detached run cannot die on one short leg.

### N5. `oos_returns_matrix` inner-join can silently drop a config to < n_splits rows

The spec inner-joins all 8 variant columns and "drops the at-most-one boundary day a variant
might miss." That is fine for the full run (~1600 rows), but if ANY variant has a materially
shorter OOS curve (e.g. a config that hit `dd_flat_halt` and went flat — equity still has
rows, so this is unlikely) the inner join shrinks T for ALL columns. The spec already promises
a `ValueError` when "< n_splits aligned rows survive" — keep that guard and make `matrix_pbo`
surface WHY (which config truncated the join) rather than a bare `pbo_cscv` row-count error,
so a detached failure is diagnosable from `harness.log`.

---

## Smoke-test feasibility (confirmed)

The hermetic smoke path is achievable by reusing the existing synthetic fixtures:
`tests/integration/test_experiments_honest_trial_count.py` already builds a stub
`SignalSource`, a tiny `InstrumentStore`/reader, a `_SyntheticDailyBtc` (`DailyBtcReader`),
and threads `experiment_log=` + `now_ms=` + `instrument_ids=` through `runner.run(...)`.
The smoke must pass `instrument_ids` explicitly (so `_window_ids`/the live lake is never
touched) and a small even `n_splits` to `matrix_pbo` (verified `n_splits=4` on a 40-row,
3-column matrix works). Populate fills `notional` in the fixture if the capacity-curve
`turnover` assertion is to be non-`nan`.
