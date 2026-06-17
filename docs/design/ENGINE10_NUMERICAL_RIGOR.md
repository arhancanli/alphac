# ENGINE10 — Numerical Rigor Audit

**Dimension:** Determinism + reproducibility (bit-identical re-runs, fixed seeds),
NaN/inf handling, float stability, the cost/funding/covariance/adjustment/DSR math.

**Scope of "10/10":** a top-shop engine is *bitwise* reproducible — the same inputs +
the same recorded environment reproduce identical artifacts on a different machine and
in a year's time — and has *zero silent numerical degeneracy*: every NaN/inf path either
fails loud or is documented and bounded, every reduction order is fixed, every estimator
floor is scale-aware, and every statistic that consumes a sample size knows exactly how
that sample was formed.

**Verdict for this axis: 8.5/10.** The *math* is excellent — among the best I have audited
in a research-grade engine. The core estimators (EWMA cov, Ledoit-Wolf, nearest-PSD, PSR/DSR,
HMM Baum-Welch) are derivation-correct, fail loud on degeneracy, use log-space / scale-aware
floors, and I *empirically verified* same-machine bit-identical re-runs of the covariance
pipeline, the Clarabel MVO, and the multi-seed HMM fit (see Evidence). What separates it from
10/10 is entirely in the *reproducibility envelope* and the *not-yet-wired equities adjustment*:
the determinism guarantee is **documented but not enforced** (no thread pinning, no env capture,
no library-version provenance), and the equities corporate-action adjustment — the single most
numerically dangerous transform in the new sleeve — is correct-but-dead-code with a latent
availability-lag bug. None of these can corrupt the live crypto book today; all of them are
corners a 10/10 closes before they bite.

---

## Evidence gathered (verified, not asserted)

Same-machine bit-identical re-runs (arm64, this `.venv`):

| Path | Two in-process calls | Two separate processes | With `OMP/OPENBLAS/VECLIB=1` |
|------|----------------------|------------------------|------------------------------|
| `ewma_cov` / `ledoit_wolf_cc` / `nearest_psd` | identical (`np.array_equal`) | — | — |
| `MeanVarianceOptimizer.solve` (Clarabel) | identical | identical SHA-256 | identical SHA-256 |
| `RegimeHMM.fit` (3-state, 8-seed Baum-Welch) | identical means/trans/loglik | — | — |

So on the *current* host the engine **is** bitwise reproducible. The gaps below are about
whether that survives a host/BLAS/library change — which is exactly the bar a 10/10 must meet.

---

## What a 10/10 has on this axis

1. **An enforced determinism envelope, not a documented one.** Thread counts pinned
   (`OMP_NUM_THREADS=1` etc.) so BLAS/OpenMP reduction order can never reorder a floating
   sum; `PYTHONHASHSEED` fixed; a test that asserts a reference artifact hash.
2. **Full environment provenance on every artifact.** Not just `code_git_sha` + `data_sha256`
   but the resolved library versions (numpy/scipy/sklearn/cvxpy/clarabel) and the BLAS vendor,
   so a re-run can be *reproduced*, not merely *described*.
3. **Every sample-size-consuming statistic owns its sample formation.** No silent NaN drops
   that change `n` behind a standard-error term.
4. **No correct-but-dead numerical transform in a shipping path.** Either the adjustment is
   wired or the factors refuse to run on raw prices; never silently run momentum on
   split-contaminated closes.
5. **Scale/availability constants taken from the calendar, never inferred from data spacing.**

---

## Concrete gaps in OUR engine

### G1 — Determinism is documented, not enforced (thread pinning absent) — HIGH
`src/alphaforge/ml/model.py:40-41` literally states reproducibility holds *"for a fixed seed
and the **single-threaded** sklearn build on arm64."* That is a precondition, but **nothing in
the repo enforces it**:
- No `conftest.py` anywhere in the project (only the vendored ones under `.venv`); no
  `OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` / `VECLIB_MAXIMUM_THREADS` / `MKL_NUM_THREADS`
  set in `pyproject.toml`, settings, or any entrypoint (verified: all four read `None` at
  runtime; `threadpoolctl` is not even a dependency).
- `HistGradientBoostingClassifier` (`ml/model.py`) and every `@`/`eigh`/`logpdf` in
  `portfolio/covariance.py`, `portfolio/optimizer.py`, `regime/hmm.py` dispatch to a
  multi-threaded BLAS/OpenMP by default. Multi-threaded reductions are **not order-stable**,
  so the documented "single-threaded build on arm64" assumption is the *only* thing standing
  between the current bitwise-identical result and a non-reproducible one on a different host
  (x86 + MKL, a CI box with more cores, or a future numpy that flips the threshold).

**Risk:** the reproducibility claim is true *by luck of the current host*, not by construction.
A DSR/PBO gate decision, a champion-model promotion, or a "must-beat-baseline" verdict computed
on CI could differ from the one a researcher saw locally — and nothing would flag it.

**Fix:** add a `conftest.py` *and* a process entrypoint shim that sets the four thread env vars
to `1` before numpy import (or call `threadpoolctl.threadpool_limits(1)` in the CLI bootstrap);
add `threadpoolctl` as a dep; add one regression test that pins a reference SHA-256 of the MVO
weights / HMM params / a tiny backtest equity curve and fails if it drifts. This converts the
docstring promise into an enforced invariant.

### G2 — Equities corporate-action adjustment is correct-but-dead-code, and silently runs factors on RAW prices — HIGH
`src/alphaforge/features/library/equity_price.py:253-284` (`_adjusted_close_panel`) feature-detects
`ctx.corporate_actions` and **falls back to the raw (unadjusted) close** when it is absent. It is
absent: `grep` confirms neither `FeatureContext.corporate_actions` (`features/context.py`) nor
`PITDataReader.corporate_actions` (`data/store/reader.py`) exists. So every equity price factor
(`reversal`, `momentum`, the Amihud illiquidity kernel) currently computes
`-ln(C_t / C_{t-W})` on **split-contaminated** closes.

**Risk:** a 2:1 split prints as a -50% momentum/reversal return for the whole lookback window —
a textbook silent numerical degeneracy. The headline correctness gate the `adjusted_close`
docstring itself names ("a 2:1 split must NOT print as a -50% momentum return", lines 52-53) is
**not actually enforced in the live path** — only in the unit test of the pure function. The
adjustment math is derivation-correct and PIT-clean, but it is unreachable.

**Fix:** wire `PITDataReader.corporate_actions(...)` (read the `CORPORATE_ACTIONS` dataset,
already in the schema + ingester) and `FeatureContext.corporate_actions()`; until then, make the
factors **refuse** rather than silently run on raw prices when the universe is equities
(e.g. raise if `market_type == EQUITY and corporate_actions is None`), so a missing read path
fails loud instead of producing contaminated signals.

### G3 — `_adjusted_close_panel` infers the availability lag from data spacing (weekend bug) — MEDIUM (latent; bites when G2 is wired)
`src/alphaforge/features/library/equity_price.py:282`:
```python
tf_ms = int(grid[1] - grid[0]) if len(grid) >= 2 else 86_400_000
```
On a session (NYSE) calendar `grid[1]-grid[0]` can be a **3-day weekend** (Fri→Mon), not one day.
I verified: a grid `[Fri, Mon, Tue, Wed]` yields `tf_ms = 3 days`, overstating the availability
lag by 2 days. Since `adjusted_close` gates each corporate action by `decision >= avail` where
`decision = ts_open + tf_ms`, an inflated `tf_ms` makes splits/dividends knowable *up to two
sessions earlier than they truly are* — a PIT availability error (mild lookahead) on every row.

**Risk:** currently masked because the read path is off (G2), but it is shipped, latent
incorrectness. The constant is knowable exactly (`Timeframe.D1.ms`), which the crypto path uses
directly; this path should too rather than infer it from the (irregular) session spacing.

**Fix:** pass `Timeframe.D1.ms` (or thread the dataset's `Timeframe.ms` through `ctx`) instead of
`grid[1]-grid[0]`. One-line change; remove the fragile inference.

### G4 — DSR/PSR silently drops non-finite returns, changing the `n_obs` that scales the standard error — MEDIUM
`src/alphaforge/validation/dsr.py:251`: `values = values[np.isfinite(values)]`. The dropped count
feeds straight into `sqrt(n_obs - 1)` (`probabilistic_sharpe_ratio:104`). I verified a 400-row
series with 80 NaNs silently becomes `n_obs = 320` with **no log, no warning, no ceiling**.

**Risk:** for genuine non-trading gaps this is benign, but a *malformed* return series (a
mis-joined panel, a bad resample) can be 30% NaN and the DSR will happily report a confident
deflated Sharpe on the surviving 70% — exactly the kind of silent degeneracy a deflation
statistic exists to prevent. A 10/10 deflation gate is suspicious of its own input.

**Fix:** log the drop fraction; raise (or down-weight the verdict) when the NaN fraction exceeds
a small threshold (e.g. >5%), the same loud-failure discipline `nearest_psd` already applies to
a degenerate trace.

### G5 — No library-version / BLAS-vendor provenance on artifacts — MEDIUM
`ml/registry.py:91-92` records `code_git_sha` + `data_sha256` (good, and `data_sha256` is the
content hash of the *materialized matrices*, not a file path — exactly right). But the model card,
the `ExperimentLog` record (`validation/experiments.py`), and the walk-forward leg cards capture
**no resolved library versions and no BLAS identity**. Combined with G1, an artifact can be
*described* (git + data) but not *reproduced* — a numpy/scipy/clarabel point release that changes
a tie-break or a solver tolerance would change the answer with no recorded trace of why.
`uv.lock` exists (good for the *build*), but the lock is not stamped onto the artifact.

**Fix:** stamp `{numpy, scipy, scikit-learn, cvxpy, clarabel}.__version__` + the threadpool
backend (from `threadpoolctl.threadpool_info()`) into the model card and the experiment record.
Cheap, append-only, and it closes the "reproduce it in a year" requirement.

### G6 — C10c two-tier reconcile ladder still deferred (numerical-tolerance corner) — MEDIUM (pre-arm)
Per `project_alphaforge_phase8_prearm_gates.md` C10c, the equity-divergence check is still a single
hard bound rather than the spec's 0.5% WARN → 2% HALT ladder, and C10b leaves SQLite at
`synchronous=NORMAL`. These are execution-correctness gates, but C10c is *numerically* a
tolerance-banding question: a single bound either over-halts on benign float-mark drift or
under-halts on a real divergence. A 10/10 live engine bands its numerical tolerances by severity.

**Fix:** implement the WARN/HALT ladder (already specced); set `synchronous=FULL` / fsync on the
ack path before arming. (Cross-listed with the Execution/Live dimension; flagged here for the
tolerance-band aspect only.)

---

## What is already at 10/10 (so the score is high, not low)

These are genuinely excellent and should be preserved as the bar:

- **EWMA covariance** (`portfolio/covariance.py:51-135`): closed-form `S_T = λ^k S_0 + (1-λ)Σ...`
  computed via a single row-scaled Gram product (no per-bar Python loop, no catastrophic
  cancellation), symmetrized `0.5*(s+s.T)`, drop-and-reinsert young-instrument handling that
  *refuses* (<2 obs) rather than fabricating a variance.
- **`nearest_psd`** (`:221-265`): scale-aware eigenvalue floor `eps_rel * tr/N` (unit-invariant),
  and it **refuses** a non-positive trace rather than laundering a corrupt matrix into a
  silently-singular one — the textbook loud-failure choice.
- **Ledoit-Wolf** (`:138-218`): full π̂/ρ̂/γ̂ derivation, zero-mean convention consistent between
  the shrinkage target and the matrix shrunk, exact `gamma_hat == 0` and `N == 1` edge handling,
  `δ*` clipped to `[0,1]`.
- **PSR/DSR** (`validation/dsr.py`): correct non-Gaussian denominator, per-period vs annualized
  periodicity kept rigorously separate (the load-bearing comment block at the top is exactly
  right), `variance_term <= 0` raises rather than returning `nan`, the `ptp == 0` zero-variance
  guard catches the float residual a bare `std == 0` test would miss.
- **HMM** (`regime/hmm.py`): scaled forward filter + `logsumexp` normalizers (no density
  underflow over thousands of days), `COV_FLOOR` against single-point collapse,
  `allow_singular=False` (loud on degenerate Σ), `np.random.SeedSequence(...).spawn(n_seeds)` for
  per-seed determinism, vol-ascending canonical relabel so state identity is stable across refits,
  forward-only live inference (no smoothing leak). Verified bit-identical.
- **Cost / funding / ledger** (`costs/model.py`, `backtest/ledger.py`): full float64 internally,
  rounding only at report time, the sqrt-impact law **refuses** beyond 5% ADV
  (`CostModelMisuse`) rather than extrapolating, latency charged exactly once (price, not penalty),
  funding event-driven with the correct Binance sign, every cash mutation `_require_finite`-guarded,
  equity always *derived* (never stored).
- **PBO/CSCV** (`validation/pbo.py`): seeded combination sampling with deterministic `sorted(seen)`
  output, `rankdata(method="average")` for ties, `std == 0 → -inf` so a degenerate config can never
  be selected IS-best. **Determinism contract honored.**
- **`ExperimentLog`** (`validation/experiments.py`): idempotent SHA-256 config hash (re-runs don't
  inflate `N`), canonical sorted-key JSON, `math.fsum` for the trial-Sharpe variance,
  loud-failure on a corrupt ledger line. This is the correct way to keep DSR's `N` honest.
- **mu_ann contract tripwire** (`portfolio/optimizer.py:103-155`): catches a ~72x unit bug on the
  *median* (not the tail), with a documented, history-calibrated threshold separating a real bug
  from a crash regime. Genuinely sophisticated.

---

## Does it scale to thousands of equity names? (numerical lens)

Two numerical scaling concerns, both real but not blockers:

- **Ledoit-Wolf θ-terms** build several dense `N×N` intermediates (`x2.T@x2`, `(x*x2).T@x`,
  the `ratio*theta` masks at `covariance.py:196-209`). At N≈20 this is nothing; at N=2000 the
  `T×N` → `N×N` Gram products and the `off`-mask `sum()` are O(N²·T) and materialize multiple
  N×N float64 matrices (≈32 MB each at N=2000) — workable but the constant-correlation single-`r̄`
  shrinkage target is also statistically *weak* for thousands of names (a single average
  correlation across all sectors). A true equities engine shrinks toward a factor model, not one
  scalar correlation. Not a numerical-rigor *defect*, but the estimator choice doesn't scale in
  quality.
- **`nearest_psd` eigendecomposition** (`np.linalg.eigh`) is O(N³); ≈seconds at N=2000 per
  rebalance — fine for a daily equities cadence, but it is the dominant cost and is recomputed every
  solve. A 10/10 caches / does it incrementally.

---

## Severity-ordered fix list

1. **G1 (HIGH)** — pin BLAS/OpenMP threads + `PYTHONHASHSEED`, add `threadpoolctl`, add a
   reference-hash regression test. Converts the reproducibility *claim* into an *invariant*.
2. **G2 (HIGH)** — wire `corporate_actions` into reader+context, or make equity factors refuse on
   missing adjustment. Stops silent split-contaminated signals the moment equity bars land.
3. **G3 (MEDIUM)** — replace `grid[1]-grid[0]` with `Timeframe.D1.ms` in `_adjusted_close_panel`.
4. **G4 (MEDIUM)** — log + bound the DSR/PSR NaN-drop fraction; refuse a heavily-NaN series.
5. **G5 (MEDIUM)** — stamp resolved library versions + BLAS backend onto model cards / experiment
   records.
6. **G6 (MEDIUM, pre-arm)** — implement the C10c WARN/HALT tolerance ladder; `synchronous=FULL`.
