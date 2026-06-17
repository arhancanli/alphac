# ENGINE10 — Scale-Performance Audit

**Dimension:** Does the engine actually SCALE from ~20 crypto perps to THOUSANDS of equity names?
**Scope:** feature engine, cross-section, covariance/optimizer, walk-forward compute, memory, lake read paths.
**Verdict:** **6.5 / 10.** Every numeric kernel is correct and the *math* scales gracefully (O(N²)/O(N³) but small constants — measured below). The wall is **not** the algorithms; it is two pervasive architectural choices made for a 20-name universe that turn linear at thousands of names with large Python-object constants: (a) the backtester materializes the entire universe as nested dicts of per-bar Python `BarView` objects, and (b) the lake reader does one filesystem `iterdir()` + one inlined-SQL-path-literal *per instrument, per read*, and the product strategy re-reads the full trailing panel that way at every rebalance. A 2000-name, 10-year daily backtest would not crash — it would be memory-heavy (multi-GB) and re-do O(N) filesystem work on every one of ~2500 rebalances. A true 10/10 shop runs the whole panel in columnar arrays end-to-end, reads through a manifest/predicate-pushdown query (not per-instrument `iterdir`), and never instantiates a Python object per bar.

All timings below are measured on this machine (`uv run python`, single core), not asserted.

---

## 1. What a 10/10 engine has on this axis

- **Columnar end-to-end.** Bars, features, signals, marks all live as contiguous NumPy/Arrow arrays (T×N), never as `dict[str, dict[ts, object]]`. No per-bar Python object is ever instantiated; the event loop is vectorized or operates on integer-indexed array views.
- **Manifest-driven reads with predicate pushdown.** The lake is queried by partition manifest / a single hive-partition scan with row-group statistics doing the pruning — never one `os.scandir` per instrument per read. Reads cost O(rows returned), not O(universe size × reads).
- **Incremental / cached estimators.** Trailing covariance and trailing panels are maintained incrementally across rebalances; they are not recomputed from a freshly re-read T×N window every step.
- **A capacity model for the optimizer.** Either a factor-model covariance (low-rank: Σ = BFBᵀ + D, so the QP is O(N·K) not O(N²) dense) or a documented universe-sharding/two-stage selection so the dense MVO never sees thousands of names at once.
- **Parallel walk-forward.** Independent CPCV/walk-forward legs run across cores/processes; the harness fans out.
- **Benchmarked at target scale.** A perf test asserts wall-time and peak-RSS at the *largest intended* universe (thousands of names), in CI or a nightly, so a regression that doubles memory is caught.

AlphaForge has none of the first four, no walk-forward parallelism, and no scale benchmark. Its kernels are clean and its correctness is excellent — the gap is purely the scale-engineering corners.

---

## 2. Concrete gaps (file:line + measured risk)

### G1 — Backtester materializes the whole universe as nested dicts of Python `BarView` objects — **HIGH**
`src/alphaforge/backtest/engine.py:1023` `_load_bars` builds `dict[str, dict[Ms, BarView]]` by iterating `to_pylist()` of every column (`:1035-1051`) and instantiating one `BarView` per bar. Measured (dataclass with `slots`, identical shape):

| universe | bars | build time | resident dict-of-BarView |
|---|---|---|---|
| crypto 20×5y-1h (current) | 876k | 2.1 s | 159 MB |
| equity 2000×5y-1d | 2.52M | 5.8 s | 376 MB |
| equity 2000×10y-1d | 5.04M | 11.9 s | **752 MB** |

This is *before any computation* — just building the dict. `to_pylist()` itself (`engine.py:1035-1040`) materializes every column as a Python list first, doubling transient memory. The whole frame is held resident for the entire run (`bars` is captured by the loop and the inner `_execute`/`_force_flat` closures). For a 2000-name 10y run this is ~0.75 GB of nested dicts plus the transient lists, the ledger, `position_records`, `order_records`, and the `LakeCostInputs` panels — easily multi-GB. **Risk:** the engine that is "built for ~20 perps" runs at ~160 MB; at 2000 equity names it is 5–10× that just for bars, and the per-object Python overhead (not the data) dominates. This is the single biggest scale wall.

### G2 — Lake reader does O(N) filesystem work + an O(N) inlined SQL path literal on *every* read — **HIGH**
`src/alphaforge/data/store/reader.py:242` `_files` loops over instruments calling `partition_paths` → `years_for` (`lake.py:101-120`), which does one `instrument_dir.iterdir()` syscall **per instrument**. The resulting file list is rendered into a literal SQL string by `_sql_file_list` (`reader.py:54-61`) and inlined into `read_parquet([...])` (`reader.py:133`). At 2000 names × ~10 years that is **2000 directory listings + a ~1.9 MB SQL string literal per read**. Because `StrategyContext.bars` (`engine.py:206`) and `BlendStrategy._close_panel` (`strategy.py:518-542`) call `ctx.bars(...)` at **every rebalance** (`strategy.py:423`, `strategy.py:526`), this O(N) enumeration repeats ~2500 times for a daily-rebalance 10y run. **Risk:** read cost scales with universe size × number of rebalances, not with rows actually returned; the `iterdir` storm and multi-MB query strings dominate at thousands of names. A 10/10 reads via a single hive-partitioned scan (`lake.glob` already exists at `lake.py:72` with `hive_partitioning=true`) or a cached partition manifest, with DuckDB doing row-group pruning.

### G3 — Product strategy re-reads + re-estimates the full T×N covariance from scratch every rebalance — **MEDIUM**
`src/alphaforge/portfolio/strategy.py:438-463`: each rebalance re-reads the trailing `cov_window_bars+1` panel via `ctx.bars` (G2), then runs `ewma_cov` → `ledoit_wolf_cc` → `nearest_psd` → `annualize_cov` fresh. The module docstring (`strategy.py:56-62`) explicitly notes "an incremental EWMA cache is a measured-need optimization, not a v1 requirement (… ~720×20 floats — microseconds)" — a 20-name assumption stated in the code. Measured covariance pipeline cost (T=720):

| N | ewma_cov | ledoit_wolf | nearest_psd (eigh) | total/rebalance |
|---|---|---|---|---|
| 20 | 0.000 s | 0.000 s | 0.002 s | 0.003 s |
| 1000 | 0.009 s | 0.024 s | 0.053 s | 0.087 s |
| 2000 | 0.037 s | 0.116 s | 0.376 s | **0.529 s** |

At 2000 names, 0.53 s/rebalance × ~2500 daily rebalances ≈ **22 min just on covariance**, on top of re-reading the panel each time (G2). The eigh in `nearest_psd` (`covariance.py:262`) is O(N³) and dominates. **Risk:** the docstring's "microseconds" reasoning no longer holds; nothing is cached across rebalances.

### G4 — Ledoit-Wolf builds 6+ dense N×N intermediates → peak ~411 MB at N=2000 — **MEDIUM**
`src/alphaforge/portfolio/covariance.py:195-212`: `q = (x2.T @ x2)`, `c = (x.T @ x)`, `b = ((x*x2).T @ x)`, `pi_mat`, `theta_ii`, `theta_jj`, `ratio` are each N×N float64. Measured peak for one `ledoit_wolf_cc` call at N=2000: **411 MB** (one N×N = 32 MB; ~13 live simultaneously). **Risk:** at N≈3000 this single call peaks >900 MB; combined with G1's resident bar dict the process can OOM on a commodity box. The math is correct and intentionally vectorized — the gap is that no one bounded the *intermediate* footprint for a large cross-section.

### G5 — Dense MVO QP scales O(N²) in build and worse in solve; no factor-model / sharding fallback — **MEDIUM**
`src/alphaforge/portfolio/optimizer.py:462-499`: `quad_form(w, psd_wrap(cov_psd))` over a dense N×N Σ with `norm1`, `abs`, turnover and box constraints. Measured (Clarabel, includes the OSQP-fallback budget):

| N | MVO solve |
|---|---|
| 100 | 0.007 s |
| 600 | 0.16 s |
| 1000 | 0.42 s |
| 1500 | 0.97 s |
| 2000 | **1.84 s** |

The optimizer's own docstring (`optimizer.py:6-12`) frames the MVO-vs-rank choice for "~20 crypto perps" and notes "At G_max=1.0, w_max=0.15 … the constrained MVO and this book are similar anyway." At 2000 names × ~2500 rebalances, 1.84 s/solve ≈ **77 min** of solve time, and a dense N×N PSD wrap is held per solve. **Risk:** there is no factor-structured covariance path (Σ = BFBᵀ + D) that would make the QP O(N·K), and no universe-cap before the optimizer. A 10/10 either factor-models Σ or two-stages (rank-select top-M, optimize M). The `RankEqualVolFallback` primary (`optimizer.py:254`) *does* scale (it is O(N log N) argsort), so v1's chosen primary is safe — but the advertised MVO upgrade is the scale liability.

### G6 — Walk-forward / grand-matrix is fully sequential; no leg or config parallelism — **MEDIUM**
`src/alphaforge/analytics/walkforward.py:670-1023`: the leg loop runs each `EventDrivenBacktester.run` in-process, one after another (`:1009-1021`), reusing one strategy across legs (`load_leg`). `grand_matrix.py` runs each config's full walk-forward serially. There is no `ProcessPoolExecutor`/`joblib`/`multiprocessing` anywhere (`grep` confirms none). CPCV produces C(N,k) splits (default 45) and the grand matrix runs ~dozens of configs — each an independent full backtest. **Risk:** legs and configs are embarrassingly parallel but run on one core; total grand-backtest wall time = Σ(per-config sequential time), which at equity scale (G1+G3+G5 stacked) becomes hours-to-days. The math is leg-independent (continuous OOS equity is handled by `load_leg` state-carry), so coarse-grained parallelism is safe and absent.

### G7 — Per-bar event loop has O(N) Python inner loops over the full universe every bar — **MEDIUM**
`src/alphaforge/backtest/engine.py:649-704`: step (1) funding loops over all instruments (`:649`), step (2) mark loops over all instruments and rebuilds `{iid: last_close[iid] for iid in ledger.positions()}` (`:662-669`), and `position_records.append(...)` runs per open position per bar (`:693-704`). Measured step-2 inner loop alone at N=2000 × grid=2520 = **5.04M Python iterations in 0.94 s**; `position_records` for a fully-held universe would be 5.04M dict rows (~1.26 GB of Python dicts) materialized before `_build_result` turns them into a DataFrame. **Risk:** the event loop's constant factors are pure-Python and scale with N×grid; combined with G1 the per-bar overhead is the second memory/throughput multiplier. A 10/10 marks the whole book as one vectorized array op and accumulates positions columnar.

### G8 — Universe builder ranks via a per-row Python loop building `dict[str, dict[int, float]]` — **MEDIUM (equities-specific)**
`src/alphaforge/data/universe/builder.py:295-328` `_median_daily_quote_volume`: `to_pylist()` of five columns then a `zip` Python loop over **every (instrument, bar) row** building nested dicts, per monthly rebalance. For equities the read is D1 (one bar/session/name), so a 30-day window × 2000 names ≈ 60k rows/rebalance — tolerable per call, but it is invoked at every monthly instant over the rebuild horizon (`builder.py:185-208`) and `_rank` re-sorts all eligible names each time. At thousands of names over 10+ years (120+ rebalances) the Python-loop constant compounds. **Risk:** modest now (D1 keeps row counts down) but it is the same "materialize to Python then loop" anti-pattern as G1/G7; a vectorized Arrow `group_by().aggregate()` would be ~100× faster and the natural equities scale-up will surface it.

### G9 — Equities read-path is INCOMPLETE: adjusted-close feature-detect returns RAW prices; no `CORPORATE_ACTIONS` reader; no D1 bars yet — **HIGH (correctness-at-scale blocker for the equities sleeve)**
`src/alphaforge/features/library/equity_price.py:253-272` `_adjusted_close_panel` does `getattr(ctx, "corporate_actions", None)` and, when absent, **returns the raw close panel unadjusted**. Confirmed: `FeatureContext` and `PITDataReader` have **no** `corporate_actions` method, and the reader has **no** `CORPORATE_ACTIONS` query path (grep confirms both). The schema and ingester exist (`CORPORATE_ACTIONS` in `writer.py:60`, `EquitiesFlatFilesJob`), and the universe builder accepts `rank_tf=D1`, but the equity *bars* are "pending a data-plan upgrade" (HEAD commit). **Risk:** the equities sleeve cannot actually run end-to-end today — and when it does, every equity price factor will silently compute on split/dividend-unadjusted prices until the context/reader edit lands. This is a scale-readiness gap (the thousands-name path is not wired through), not a perf wall, but it is load-bearing for the dimension's premise. This must be closed before any equities scale claim is credible.

### G10 — No scale benchmark anywhere; largest test universe is 8 names — **HIGH**
`grep` of `tests/` shows the largest instrument universes are ~8 names (`test_universe`), and the "300/700/200" loop counts are *timestamps*, not instruments. There is no perf/memory assertion at >100 names, let alone thousands. **Risk:** every gap above is unguarded — a change that doubles per-bar memory or makes the reader quadratic ships green. A 10/10 has a nightly that runs the largest intended universe and fails on wall-time/RSS regression. Without it, "does it scale to thousands?" is currently **unknown to CI** and answered only by this audit's ad-hoc measurements.

---

## 3. Severity summary

| # | Gap | Severity |
|---|---|---|
| G1 | Backtester nested-dict of Python `BarView` objects (~0.75 GB @ 2000×10y) | HIGH |
| G2 | Reader O(N) `iterdir` + inlined SQL path literal per read, repeated per rebalance | HIGH |
| G9 | Equities read-path incomplete: raw (unadjusted) prices, no CA reader, no D1 bars | HIGH |
| G10 | No scale benchmark; largest test universe is 8 names | HIGH |
| G3 | Covariance re-read + re-estimated from scratch every rebalance (~0.5 s @ N=2000) | MEDIUM |
| G4 | Ledoit-Wolf 6+ dense N×N intermediates → ~411 MB peak @ N=2000 | MEDIUM |
| G5 | Dense MVO QP O(N²) build, ~1.8 s @ N=2000; no factor-model/shard fallback | MEDIUM |
| G6 | Walk-forward / grand-matrix fully sequential; no leg/config parallelism | MEDIUM |
| G7 | Per-bar O(N) Python inner loops + position_records growth | MEDIUM |
| G8 | Universe builder per-row Python loop building nested dicts | MEDIUM |

No blockers for the *crypto* product (everything is comfortable at N≈20). The HIGHs are all "scales to thousands" gaps: two are memory/throughput walls (G1, G2), one is an incomplete read-path (G9), one is the absence of any guard (G10).

---

## 4. Concrete fixes

- **G1:** Replace `_load_bars`' `dict[str, dict[Ms, BarView]]` with a columnar store: keep the Arrow table (or per-column NumPy arrays) and index it by `(instrument_id_code, ts_open)` via a precomputed `dict[(int,int)->row]` or sorted-array `searchsorted`. The event loop then reads `close[row]` from a contiguous array instead of instantiating `BarView`. Eliminates the per-object overhead (the 752 MB → ~80 MB of actual data) and the `to_pylist()` transient. Keep `BarView` only as the fill-model view, constructed lazily per touched order.
- **G2:** Add a `reader.ohlcv_glob(...)` path that uses the existing `LakePaths.glob` (`lake.py:72`) with `read_parquet('<glob>', hive_partitioning=true)` and lets DuckDB prune by `instrument_id`/`year`/`ts_open` from row-group stats and the hive partition columns — one query, zero per-instrument `iterdir`, no multi-MB inlined string. Cache `years_for` results per `(dataset, instrument)` so repeated `ctx.bars` calls in one run don't re-scan directories. Fall back to the explicit list only for tiny universes if measured faster.
- **G3:** Maintain an incremental trailing-return ring buffer + incremental EWMA covariance updated each bar (the closed-form recursion in `ewma_cov` already supports it); re-run Ledoit-Wolf only every K rebalances (intensity drifts slowly — the docstring already argues this). Avoids the full re-read (depends on G2) and the O(N³) eigh every step.
- **G4:** Stream the Ledoit-Wolf intermediates: compute `pi_hat`, `rho_hat`, `gamma_hat` without holding all 6 N×N matrices simultaneously (accumulate scalar sums; reuse buffers / use `np.einsum` with `optimize=True` to avoid materializing `q`/`b`). Targets <100 MB peak at N=2000.
- **G5:** Add a factor-model covariance option (Σ = BFBᵀ + D from the regime/PCA factors already in `regime_features.py`) so `quad_form` becomes a low-rank quadratic the solver handles in O(N·K); and/or a documented two-stage allocator: rank-select top-M by mu_ann, optimize the M-name sub-problem. Keep `RankEqualVolFallback` as the safe O(N log N) primary (it already is).
- **G6:** Wrap the walk-forward leg loop and the grand-matrix config loop in a `ProcessPoolExecutor` (legs are independent except for the `load_leg` equity carry, which can be threaded through deterministically by running legs in order but parallelizing across *configs*, which are fully independent). Bound workers by config; this alone turns the grand backtest from serial-hours to cores-parallel.
- **G7:** Vectorize step (2): mark the whole book in one array op over the positions array; accumulate `position_records` as columnar arrays (preallocated, row-pointer) instead of a list of dicts, and only snapshot held names (the code already iterates `state.positions`, but the dict-per-row is the cost). Depends on G1's columnar store.
- **G8:** Replace the `to_pylist` + Python `zip` loop with Arrow `table.group_by(["instrument_id", day_bucket]).aggregate([("quote_volume","sum")])` then a vectorized per-instrument median; drops the per-rebalance ranking from O(rows) Python to native.
- **G9:** Land the deferred context/reader edit: add `PITDataReader.corporate_actions(...)` (CA dataset, PIT on `available_at`) and `FeatureContext.corporate_actions`, so `_adjusted_close_panel` stops returning raw prices; complete the D1 bar ingest read-path. Until then, fail-loud (raise) if equity price factors are requested without a CA surface, rather than silently returning unadjusted prices (a silent-correctness trap at scale).
- **G10:** Add a perf/memory regression test (nightly or marked-slow): run the full pipeline at the largest intended universe (e.g. 2000 names × 5y daily synthetic lake), assert wall-time and `tracemalloc` peak under explicit budgets. This is what converts "scales?" from an audit guess into a CI guarantee.
