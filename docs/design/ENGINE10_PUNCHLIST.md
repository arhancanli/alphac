# ENGINE10 PUNCHLIST — what separates AlphaForge from a true 10/10

**Audit lead synthesis.** HEAD `dfdf515`. Read-only audit; claims spot-verified against
source (file:line). Consolidates 7 dimension audits (Correctness-Leakage, Numerical-Rigor,
Validation-Rigor, Scale-Performance, Risk-Ops-Safety, Test-Coverage, Architecture-Seams).

---

## 1. Honest overall score: **8.0 / 10**

Per-dimension (auditor scores, all independently spot-checked and confirmed):

| Dimension | Now | One-line verdict |
|---|---|---|
| Correctness-Leakage | 8.5 | Crypto path is a true 10 by construction+regression; the entire gap is the unwired equities sleeve, and it is leakage-bearing. |
| Numerical-Rigor | 8.5 | Math is best-in-class; gap is the reproducibility envelope (no thread pinning / reference hash) + dead equity adjustment. |
| Validation-Rigor | 8.5 | Anti-overfit *math* is top-shelf; deflation does not see the whole search (V[SR] semantics, honest N), CPCV is dead-wired. |
| Test-Coverage | 8.5 | 2030 tests + golden master + parity harness, but coverage is unmeasured, estimators have no property tests, equity E2E untestable. |
| Risk-Ops-Safety | 8.0 | Mechanisms are institutional-grade but several are **built-but-unwired**; **no liveness signal** is the single biggest fail-safe gap. |
| Architecture-Seams | 7.5 | Seams are *designed* asset-class-agnostic but the **spine bypasses its own calendar seam**; adding equities today forks the engine. |
| Scale-Performance | 6.5 | Weakest axis. Kernels scale; two 20-name architectural choices go linear with huge Python-object constants at 1000s of names. |

**Composite = 8.0**, not the headline 8.5, because Scale (6.5) and Architecture-Seams (7.5)
are weighted by the stated equities ambition, and because the largest cluster of gaps
(corporate-actions read-path, calendar-blind spine, anchor-TF pin) is the *same root defect*
surfacing in 5 of 7 dimensions — a structural hole, not seven cosmetic ones.

**The honest framing:** the **crypto-perp product at N≈20 is genuinely 9–9.5/10** and nothing
in this punch-list threatens it. The score is dragged to 8.0 by (a) the equities sleeve being
wired from both ends with the middle missing, and (b) real-money / liveness gaps that are
deferred but open. AlphaForge is one focused engineering arc (the equities spine) plus the
Phase-8 pre-arm gates plus a liveness layer away from being a defensible 9.5; the last
half-point is calendar time under live capital that no amount of code can buy today.

---

## 2. Ranked gap-to-10 punch-list (highest impact first, deduped across dimensions)

Severity: **blocker** (wrong numbers / unsafe with real capital) · **high** · **medium** · **polish**.
Effort: **S** ≈ ≤1 day · **M** ≈ 2–5 days · **L** ≈ 1–3 weeks · **XL** ≈ multi-week arc.

---

### P1 — Equities corporate-actions READ-PATH is absent: every equity price factor silently runs on RAW unadjusted close
**Severity: blocker · Effort: M · Cited by 5/7 dimensions (Leakage G1, Numerical G2, Scale H3, Test G1, Architecture G2)**

- **Confirmed.** `src/alphaforge/features/library/equity_price.py:270` — `_adjusted_close_panel`
  does `ca_getter = getattr(ctx, "corporate_actions", None); if ca_getter is None: return raw`.
  There is **no** `corporate_actions` method on `data/store/reader.py` (PITDataReader) **or**
  `features/context.py` (FeatureContext) — grep returns nothing. The write side is fully built
  (schema, `polygon_source.py`, `data_cmds.py` ingester), so the data exists but is unreachable.
- **Risk:** a 2:1 split prints as a -50% return into momentum/reversal/beta/vol inputs. The
  fallback is *documented as intentional* (equity_price.py:265-268), so nothing alarms. Latent
  today (no equity bars ingested) but goes live silently the instant equity research runs.
- **Fix:** Add `PITDataReader.corporate_actions(ids, start, end, *, as_of)` masking on stored
  `available_at` (never `ex_date`) — mirror the funding PIT pattern — and
  `FeatureContext.corporate_actions()` serving the `_CA_COLUMNS` projection. The factor side
  already feature-detects and consumes it, so **no factor change** once the method exists.
  Then **replace the silent raw fallback with a fail-closed raise** when an EQUITY/D1 context
  is asked for an adjusted panel with no CA surface. Add an integration regression: plant a
  split → `compute_history` → assert no -50% return at the ex bar and split-invisibility before
  `available_at`.

---

### P2 — Feature/backtest/label/portfolio spine is hard-locked to the 24/7 H1 grid; equity D1 session windows are silently wrong
**Severity: blocker · Effort: L · Cited by 4/7 (Leakage G2, Architecture G1/G3/G5/G6, Numerical G3, Test G1)**

- **Confirmed.** `features/engine.py:45` — `ANCHOR_TIMEFRAME: Final[Timeframe] = Timeframe.H1`,
  a hard module constant. `features/context.py:231` reindexes the panel to the bare 24/7
  `expected_bar_opens`. `backtest/engine.py` is "1h-only" (`self._tf=Timeframe.H1`, `BARS_PER_DAY=24`).
  `labeling/triple_barrier.py` does `delta=tf.ms` positional hops. `portfolio/strategy.py:527,564`
  builds the cov panel + realized-vol annualizer on the 24/7 grid with `sqrt(365)`.
  `analytics/walkforward.py:743` builds the WF grid calendar-blind. **`XNYSCalendar`
  (`core/calendar.py`) is wired into nothing** in the spine — the *one* place it is correctly
  used is `triple_barrier.py:534` via `calendar_for(inst.asset_class)`, proving the seam exists
  and the spine bypasses it.
- **Risk:** equity D1 `shift(252)` windows span calendar days not sessions; weekends become
  NaN/sentinels; a "72-bar embargo" becomes 72 calendar days straddling weekends; realized vol
  is annualized with the wrong periods-per-year. Equity factor tests (`test_factors_equity_price.py:89-98`)
  **admit they fake a session grid no real lake produces** — green tests certify bodies, not the
  deployed path.
- **Fix:** Thread `asset_class` / `TradingCalendar` through `FeatureEngine` → `FeatureContext.panel`
  (grid = `calendar_for(asset_class).expected_bar_opens`), the backtest engine, TripleBarrier
  (session hops not fixed ms), the cov panel + annualizer (pass `calendar.periods_per_year(tf)`
  into the already-correctly-parameterized `annualize_cov`), and the WF grid + purge/embargo
  (in sessions). Replace `ANCHOR_TIMEFRAME` module constant with a per-sleeve anchor TF from
  config; take `periods_per_year` from the calendar in the Grinold sizer / IC machinery instead
  of `timeframe.bars_per_year`. **Until done, `compute_history` must reject D1/EQUITY specs**
  rather than silently use the 24/7 grid. Run `verify_parity` / `verify_truncation` on the XNYS
  D1 path. Add a parity test that an equity D1 panel has only session rows (no weekend NaNs).

> P1 + P2 are the **same root cause** (the spine is mono-sleeve and calendar-blind) and should
> be one engineering arc. They are why three other dimensions independently score the equities
> sleeve as "wired from both ends with the middle missing."

---

### P3 — Phase-8 pre-arm real-money gates C3/C5/C7/C10 all still open against HEAD (must clear before live capital)
**Severity: blocker (for live capital) · Effort: M–L · Cited by Risk-Ops (C3/C5/C7/C10a-c), Numerical (C10c), Test (no xfail guard)**

All verified open at HEAD:
- **C3** — `execution/reconcile.py:473` marks broker equity via `account()` at `fills[-1].ts`
  but the book at `floor_bar(now)`; on a live moving book these differ → spurious halts or
  masked divergence. Protocol `BrokerView` lacks `account_at()`. **Fix:** add
  `account_at(as_of)` (PaperBroker already has it at `paper.py:520`) and reconcile at one shared
  `as_of`. *(This is the one pre-arm gate with a leakage flavor — information-set mismatch across two instants.)*
- **C5** — `live/loop.py:786` `_replay_recorded_fills` rebuilds from the store only; a real venue
  fill landing in the submit→persist window is undiscoverable on boot (CCXTBroker reads raise
  `NotArmed`). **Fix:** wire `fetch_order(client_order_id)` into `recover_on_boot` for non-paper brokers.
- **C7** — `live/loop.py:807` `_sync_book_snapshot_after_recovery` writes broker truth INTO the
  book row at `floor_bar(now)`, then reconcile compares book to that derived row — a tautology,
  keyed at the wrong timestamp. **Fix:** reconcile against broker truth BEFORE adopting it; key
  the snapshot at the interrupted `cycle_ts`.
- **C10a** — `execution/paper.py:480` `_book_fill` precedes `acks[coid]=ack` at `paper.py:488`
  (confirmed: book-then-ack). Crash between → booked fill with no idempotency key replays as a
  fresh order (double-fill). **Fix:** record the dedup ack first / atomically with the position mutation.
- **C10b** — `live/store.py:306` `PRAGMA synchronous=NORMAL` — not power-loss durable. **Fix:**
  `synchronous=FULL` (or fsync between `record_intent` and `submit`) on the irreplaceable
  `trading.sqlite`; the re-derivable Parquet lake can stay NORMAL.
- **C10c** — `execution/reconcile.py:224` single hard bound `equity_rel=5e-3`; execDesign §8.4
  specs a 0.5% WARN → 2% HALT ladder. **Fix:** implement the two-tier ladder, routing WARN
  through the alerter so a 0.6% mark wobble warns instead of halting the 24/7 loop.
- **Test gap:** none of these have an executable xfail/skip spec; reconcile tests always use a
  fixed `as_of=T0`, never the moving-book hazard. **Add** `tests/integration/test_prearm_gates.py`
  with one xfail per gate so arming flips them green.

---

### P4 — No liveness signal: a dead loop is indistinguishable from a healthy idle one
**Severity: blocker (for unattended live) · Effort: M · Cited by Risk-Ops**

- **Confirmed.** `live/alerts.py` `send_tearsheet` has **zero live loop callers** (grep shows
  only the alerter implementations + a self-call). No heartbeat command anywhere; execDesign §9
  specs an 8h heartbeat + a 00:05-UTC tearsheet job. `loop.py:644` only keeps the *internal*
  tick alive when halted — there is no external emission.
- **Risk:** if the loop OOM-kills or the box reboots, nothing alerts the operator. The single
  biggest fail-safe gap: a dark system looks identical to a healthy one.
- **Fix:** emit an 8h heartbeat alert from the loop + an **external watchdog** that alerts on
  heartbeat *absence* (the in-process loop cannot alert on its own death). Wire the 00:05-UTC
  tearsheet job (`send_tearsheet` already exists). Add CRIT re-send-until-ack (§9.4) keyed off a
  halt-ack sentinel file (mirror the kill-switch file-ack pattern).

---

### P5 — Built-but-unwired risk controls: VaR/CVaR, clock-sanity, monthly universe refresh are all dark in the production loop
**Severity: high · Effort: S–M · Cited by Risk-Ops**

- **Confirmed.** `historical_var_cvar` / `VarReport` (`risk/monitors.py:55`) are only re-exported
  in `risk/__init__.py` — **no gate consumes them**; `RiskCfg.var_confidence/var_window_days`
  feed `RiskLimits` which never uses them. `clock_sanity` and `universe_refresher` are supported
  by `LiveLoop` (`loop.py:522/958, 528/1014`) but `cli/paper_cmds.py _build_loop` passes
  **neither** (grep confirms absent) → `clock_skew_alerts` is permanently 0 and the live universe
  freezes over a soak (can hold a name that dropped out of the liquid set).
- **Fix:** (a) consume `historical_var_cvar` over the live equity curve each cycle to gate gross /
  alert when CVaR exceeds a configured fraction; surface it in `af paper status` + the tearsheet.
  (b) Construct `ClockSanity(CCXTExchangeTimeSource(...))` in `_build_loop` and pass to LiveLoop.
  (c) Wire a `UniverseRefresher` over `UniverseBuilder.rebuild` for monthly live rebalance.

---

### P6 — Scale architecture: backtester materializes the whole universe as nested dicts of per-bar Python objects
**Severity: high (for equities scale) · Effort: L · Cited by Scale H1, plus G9 (per-bar loop), G5/G6/G7 (cov/LW/MVO)**

- **Confirmed.** `backtest/engine.py:1023` `_load_bars` builds `dict[str, dict[Ms, BarView]]`
  via `to_pylist()` over every column and a `BarView` object per bar. Measured ~752 MB / ~12 s
  *just to build* at 2000 names × 10y daily, before any compute. The per-bar event loop then runs
  O(N) Python inner loops (mark/funding) and appends a dict per position per bar.
- **Risk:** none at N=20; goes linear with huge Python-object constants at 1000s of names.
- **Fix:** replace with a columnar store (Arrow table / per-column NumPy arrays indexed by
  `(id_code, ts_open)` via `searchsorted`); read `close[row]` from contiguous arrays; build a
  `BarView` lazily only for touched orders. Vectorize the mark; accumulate `position_records` as
  preallocated columnar arrays. (~752 MB → ~80 MB.) Stacked secondary scale walls in the same arc:
  incremental EWMA covariance + Ledoit-Wolf every K rebalances (G5); stream LW intermediates to
  avoid 6 dense N×N matrices (G6); factor-model / two-stage MVO fallback (G7).

---

### P7 — Lake reader does O(N) iterdir() + an inlined SQL path-literal per read, repeated every rebalance
**Severity: high (for equities scale) · Effort: M · Cited by Scale H2, Architecture (partitioning)**

- **Confirmed.** `data/store/reader.py:242` `_files`, `:54-61` `_sql_file_list`, `:133`
  `read_parquet([...])`; `data/store/lake.py:101` `years_for` does an `iterdir` per instrument.
  The product strategy re-reads the full trailing T×N panel this way at every rebalance
  (`strategy.py:438-463`). At equity scale: ~2000 dir-listings + a multi-MB SQL string per read ×
  ~2500 rebalances.
- **Fix:** glob/manifest read path using `LakePaths.glob` with
  `read_parquet('<glob>', hive_partitioning=true)` so DuckDB prunes by partition from row-group
  stats — one query, zero per-instrument iterdir. Cache `years_for` per `(dataset, instrument)`.
  For the equity sleeve, partition by date-panel files (the day-aggs ingester already produces
  day panels). Benchmark `PITDataReader.ohlcv` on a 1000-name read before any equity scale-up.

---

### P8 — No coverage measurement and no mutation testing in CI — assertion strength of ~2500 tests is unaudited
**Severity: high · Effort: S (cov) + M (mutation) · Cited by Test G2**

- **Confirmed.** `pyproject.toml:83` `addopts = "-q --strict-markers -m 'not network'"` (no `--cov`);
  `.github/workflows/ci.yml:86` runs bare `uv run pytest`; no mutmut/cosmic-ray config anywhere.
- **Fix:** add `pytest-cov` with `--cov=alphaforge --cov-branch` and a ratcheting
  `--cov-fail-under` floor; add a mutmut/cosmic-ray job over `costs/`, the optimizer + covariance,
  `backtest/ledger.py`, and `validation/`, triaging survivors into new assertions.

---

### P9 — The numerically critical estimators have ZERO property tests (covariance + entire validation arsenal)
**Severity: high · Effort: M · Cited by Test G3**

- **Confirmed pattern.** `test_covariance.py`, `test_dsr.py`, `test_pbo.py`, `test_cpcv.py`,
  `test_validation_metrics.py`, `test_costs.py` are example-based only (no `@given`). The
  optimizer already shows the idiom (`test_optimizer.py:455`).
- **Fix:** add `@given` property tests — covariance PSD + symmetric + shrinkage∈[0,1] and
  shrinks-to-target; DSR/PSR∈[0,1] and monotone in n_trials/Sharpe; PBO∈[0,1] with PBO≈0.5 on
  i.i.d.-noise PnL; cost impact monotone in notional ≥0.

---

### P10 — Anti-overfit deflation does not see the whole search (V[SR] semantics + honest N)
**Severity: high · Effort: M · Cited by Validation G1+G2, and CPCV-dead G4/G3**

- **Confirmed pattern.** `validation/experiments.py:260-278` computes `V[SR]` as the variance of
  the ~8 *config-trial* Sharpes, but `alphaDesign.md:657` + `cpcv.py:12` mandate **CPCV-path**
  Sharpe variance — code and doc disagree (G1). Honest N counts only the final ~8-config grid
  (only `.record()` sites are `walkforward.py:468` + `retrain.py:545`); the entire upstream funnel
  (25-factor library, IC screening, blend-weight selection, horizon=72, universe choice) logs
  **zero** trials, so DSR deflates against N≈8 when the true funnel is hundreds (G2). CPCV is
  correct + 19-tested but **dead** — its `n_backtest_paths` is consumed by no gate (G4).
- **Scaling note:** G2 *worsens* on a thousands-name equity sleeve (wider upstream search, same final grid).
- **Fix:** wire CPCV into the selected-family evaluation (resolves G1+G4 together): backtest each
  CPCV path, feed path-Sharpe variance to DSR. Add `.record()` (nan-Sharpe placeholder) at the
  upstream decision points, OR expose a documented research-budget knob seeding N with an honest
  lower bound. If config-trial variance is the deliberate choice, amend the design doc + cpcv
  docstring and demote CPCV to a labeled research-only diagnostic. **Today doc and code disagree —
  pick one.**

---

### P11 — CV/WF embargo (168 bars) is ~12–20× shorter than the dominant slow-feature lookback (720–3240 bars)
**Severity: medium (high latent) · Effort: S · Cited by Leakage G3, Validation G3, Numerical (lookback)**

- **Confirmed.** `validation/splits.py:101` + `cpcv.py` default `embargo_bars=168`;
  `walkforward.py` + `scripts/grand_backtest.py` use 168; yet `retrain.py:93` itself sets
  `DEFAULT_EMBARGO_BARS=720` with the comment "must be >= the dominant slow-feature lookback
  (~720), not the splitter's 168 default". `momentum_slow.py:61` reaches lookback 3240;
  `carry_dynamics.py:255` reaches 2025.
- **Risk:** safe *today* only because `PurgedWalkForward` is forward-chaining (embargo vacuous);
  becomes a real leak the moment train-after-test appears (CPCV V[SR] per P10, cross-validated
  blend weights), inflating CV IC/Sharpe feeding PBO and the DSR baseline gate.
- **Fix:** derive WF/grand-backtest embargo from the max lookback of the ACTIVE factor set
  (≥720, up to ~2025–3240), as `retrain.py` already does. Pin a test asserting
  `embargo_bars >= max_active_lookback`. Run an embargo-sensitivity sweep (E ∈ {168, 720, 2160, 3240})
  to bound the inflation.

---

### P12 — Determinism documented, not enforced — no BLAS/OpenMP thread pinning, no PYTHONHASHSEED, no reference-hash test
**Severity: high · Effort: S · Cited by Numerical G1**

- **Confirmed.** No `conftest.py` anywhere; `pyproject.toml` sets no thread env and `threadpoolctl`
  is not a dep; `ml/model.py:40-41` only documents a single-threaded-arm64 caveat.
- **Fix:** add `conftest.py` + a CLI bootstrap setting `OMP/OPENBLAS/VECLIB/MKL_NUM_THREADS=1`
  before numpy import (or `threadpoolctl.threadpool_limits(1)`); add the `threadpoolctl` dep; add
  a regression pinning SHA-256 of MVO weights / HMM params / a tiny backtest curve that fails on
  drift. (Same-machine bit-identical re-runs were empirically verified by the Numerical auditor,
  so this hardens an already-good state.)

---

### P13 — risk_events audit table specced but never created; per-asset 2.5σ stop + 24-bar embargo absent
**Severity: high · Effort: M · Cited by Risk-Ops**

- **Confirmed.** Grep for `risk_events` over `src/` returns nothing; `TradingStore._CREATE_SQL`
  creates 7 tables, none named `risk_events`. execDesign §9.1 specs it; §7 line 543 specs the
  per-asset 2.5×σ_daily adverse-move stop + 24-bar re-entry embargo, which has no implementation
  and no config field (only a cost comment at `strategy.py:106`).
- **Risk:** pre-trade rejects are ephemeral WARN alerts only — no durable queryable risk ledger
  for a 30-day post-mortem. A single name blowing up is caught only indirectly by the position cap
  + aggregate drawdown ladder.
- **Fix:** add the `risk_events` table; write a row on every pre-trade reject, ladder transition,
  reconcile breach, per-asset stop, and clock-skew event. Implement the per-asset stop + embargo,
  **or** formally retract it from the spec.

---

### P14 — No equity-short borrow/locate cost anywhere; Instrument lacks the field
**Severity: high (blocks equity shorts) · Effort: M · Cited by Architecture**

- **Confirmed.** Grep `borrow|locate|short_fee|htb` over `src/` finds nothing in cost models;
  `core/instruments.py` has `can_short: bool` but no `borrow_fee_bps`/HTB/locate.
- **Fix:** add `borrow_fee_bps` (+ optional HTB/locate flag) to `Instrument` and a daily borrow
  accrual in the cost model for short equity positions, mirroring the perp event-funding leg.
  **Required before any equity short capital.**

---

### P15 — No scale benchmark anywhere; largest test universe is 8 names — every scale gap is unguarded in CI
**Severity: high · Effort: M · Cited by Scale H4**

- **Confirmed.** No `tracemalloc`/RSS/throughput assertion at >100 names in `tests/`.
- **Fix:** add a nightly/marked-slow perf+memory regression: run the full pipeline at the largest
  intended universe (2000 names × 5y daily synthetic lake) and assert wall-time + tracemalloc peak
  under explicit budgets, so a regression fails CI. (Gates P6/P7 from silently regressing.)

---

### P16 — Crypto + equity survivorship: PIT universe architecture is correct, end-to-end proof against the REAL seed path is unconfirmed
**Severity: medium · Effort: S–M · Cited by Leakage G4+G5**

- **Confirmed pattern.** `data/universe/builder.py` + `store.py` handle delisted names PIT; the
  Vision historical dump exists. But no regression proves a *specific known* delisted perp (e.g.
  FTTUSDT) appears in 2021 membership built from the **real** seed path, only synthetic fixtures.
  Equity lifecycle (`listed_ts/delisted_ts`) for delisted tickers is not yet populated into the
  instrument store (same trap, equity flavor).
- **Fix:** add the crypto regression against real seed data; seed equity lifecycle for delisted
  tickers and add the equity analogue regression. Until proven, **stamp crypto backtest reports as
  potentially survivorship-biased before the first archive date**.

---

### P17 — Walk-forward and grand-matrix run fully sequential despite being embarrassingly parallel
**Severity: medium · Effort: M · Cited by Scale G8**

- **Confirmed.** No `ProcessPool`/`joblib`/`multiprocessing` in `analytics/`; serial leg/config loops.
- **Fix:** parallelize across configs (fully independent) with a `ProcessPoolExecutor`; keep legs
  ordered within a config. Turns the grand backtest from serial-hours to cores-parallel.

---

### P18 — Smaller corners (medium/polish, deduped)
**Effort: S each**

- **DSR/PSR silently drop non-finite returns, changing n_obs** (`validation/dsr.py:251` → `:104`):
  log the NaN-drop fraction and raise/down-weight above ~5%. *(Numerical G4)*
- **Availability lag inferred as `grid[1]-grid[0]`** (`equity_price.py:282`): a Fri→Mon first gap
  gives a 2-session lookahead. Use `Timeframe.D1.ms`. *(Numerical G3 — latent until P1 wires the path.)*
- **`PITDataReader.gaps` uses the 24/7 kernel** (`reader.py:227`): reports every weekend as a gap
  for equity D1. Route through `calendar_for(asset_class)`. *(Architecture G8)*
- **Artifacts lack library/BLAS-vendor provenance** (`ml/registry.py:91`, `validation/experiments.py`):
  stamp numpy/scipy/sklearn/cvxpy/clarabel versions + threadpool backend onto model card + experiment record. *(Numerical G5)*
- **Kill switch not re-checked immediately before `_om.place`** (`risk/killswitch.py` docstring vs
  `loop.py:1167`): benign at 1h paper cadence, real for a longer decide→submit path. *(Risk-Ops)*
- **CRIT alerts fire once, no re-send-until-ack** (`live/alerts.py:137`): add a 15-min re-send
  timer keyed off a halt-ack sentinel. *(Risk-Ops — folded into P4.)*
- **Config is mono-sleeve, no AssetClass field / sleeve registry** (`config/settings.py:74`):
  introduce an AssetClass-keyed sleeve registry; re-express bar-count tuning constants as durations.
  *(Architecture — the config-layer half of P2.)*
- **`calendar_for` keyed on AssetClass not MIC** (`core/calendar.py:287`): forces all equities onto
  XNYS; re-key on listing venue. *(Architecture)*
- **Equities ingest watermark does not advance on an empty session** (`data/ingest/equities.py:301`):
  advance on empty-but-processed. *(Architecture polish)*
- **Capacity sweep varies only `initial_cash`** (`grand_matrix.py:177`): conflates impact-decay with
  order-clipping/config-drop; record fraction-filled + fraction-cap-bound per point. *(Validation G6)*
- **Small-N statistical honesty** (`dsr.py:108` at N=8, 8-column PBO): compute SR* via Monte-Carlo at
  true N or surface a small-N caveat / bootstrap CI. *(Validation G5)*
- **Split-then-dividend interaction unguarded** (`equity_price.py:238`): add
  `test_adjusted_close_split_then_dividend` (no code change). *(Leakage G6)*
- **tests/golden/ is empty**: snapshot a full-pipeline numeric master for the grand-backtest harness.
  *(Test G6)*
- **ml/importance.py (MDA + clustering) executed but never asserted**: add `test_ml_importance.py`. *(Test G5)*
- **Deployed-path parity proven only for finite-window crypto specs**: extend to EWMA-family + equity. *(Test G7)*
- **C10c WARN/HALT ladder + `synchronous=FULL`** — folded into P3 (C10b/c).

---

## 3. What reaching a true 10 requires

### A. Closeable now by engineering (the path from 8.0 → ~9.3)
These are bounded, code-only, and verifiable in CI. None need calendar time.

1. **The equities spine arc (P1 + P2 + P7 + P14 + config registry).** Wire the corporate-actions
   read-path, make the feature/backtest/label/portfolio/WF spine calendar-aware off a per-sleeve
   anchor TF, build the equity cost-input + borrow surfaces, and introduce the AssetClass sleeve
   registry. This is the single highest-leverage arc: it closes the largest cluster of blockers
   and is the precondition for the equities sleeve being *trustworthy at all*. Until it lands,
   `compute_history` should fail-closed on EQUITY/D1 specs.
2. **The Phase-8 pre-arm gates (P3) + liveness layer (P4).** C3/C5/C7/C10a-c + heartbeat/watchdog
   + tearsheet job + CRIT re-send. These gate real capital and unattended operation; all are
   precisely specified and bounded.
3. **Wire the dark risk controls (P5) and the risk_events ledger + per-asset stop (P13).**
4. **The scale arc (P6 + P15 + P17), if equities at 1000s of names is truly the target.** Columnar
   bar store, glob/manifest reads, incremental covariance, parallel grand-backtest, and a perf/RSS
   regression test. If the real target stays ~20 crypto perps, P6/P7/P15/P17 are deferrable and the
   honest score for *that* product is already ~9.5.
5. **Validation honesty (P10 + P11) and reproducibility (P12).** Reconcile V[SR]/CPCV with the
   design doc, count the honest funnel in N, derive embargo from the active lookback, pin BLAS
   threads + a reference hash.
6. **Test hardening (P8 + P9 + P16 + P18 corners).** Coverage + mutation in CI, property tests on
   the estimators, real-seed survivorship regressions, executable xfail gate guards.

### B. What only live battle-testing over calendar time can buy (the last ~0.7)
No amount of code closes these; a 10/10 is *earned*, not built.

- **A live track record under real fills, real funding, real venue outages.** The truth backtester
  is cost-honest, but slippage/impact/borrow-availability assumptions are only validated by money
  on the line over months. The capacity curve (P18) is a model until it is a measurement.
- **A clean Phase-8 soak + reconciliation history:** weeks of the 24/7 loop surviving reboots,
  clock skew, partial fills, and reconcile breaches *in production*, with the risk_events ledger
  full of real (benign) events that prove the controls fire correctly — not just in tests.
- **Out-of-sample decay measured forward.** DSR/PBO bound *in-sample* overfit; only forward live
  PnL relative to the deflated expectation tells you the alpha was real. A top systematic shop's
  10/10 is precisely the institutional muscle of having watched many strategies decay and knowing
  which survive — an organizational asset, not a repository property.

**Bottom line:** AlphaForge is an honest, well-instrumented **8.0** with a genuinely 9.5-grade
crypto core. The deferrals are documented and deliberate, not hidden — but they are documented,
not yet *executable red tests*, and several safety controls are built but unwired. Engineering can
move it to a defensible ~9.3 in a few focused arcs (equities spine first, then pre-arm + liveness).
The final climb to a true 10 is the part code cannot write: live capital, surviving time.
