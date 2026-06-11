Environment verified before writing this assessment: arm64, macOS 26.5, system Python 3.9.6, `~/alphaforge` absent, **no Homebrew, no libomp, no uv installed**. That last fact matters more than the designs assume — see Findings 2.x.

---

# Findings

## 1. Overengineering — cut or defer from v1

The three designs together describe roughly 12–18 person-months of work. The data layer (A) and execution layer (C) are appropriately sized; the alpha/ML layer (B) is where most of the deferral should happen. Specific calls:

**CUT from v1 (build later, or never):**

1. **The entire ML stack of Design B** — triple-barrier labeling, meta-labeling LightGBM, sample-uniqueness weights, isotonic calibration, MDA/SHAP importance, weekly champion/challenger retrain. Design B itself admits the *side* comes from the rule-based alpha blend and ML only "gates and scales" it. So v1 trades the blend directly: `signal = Ã` with a dead zone, no `p_meta`. This removes `labeling/`, `ml/`, shap, numba, and the libomp dependency from the critical path while keeping the contract (`SignalService` → μ vector) identical. The ML becomes a multiplicative gate added later without touching portfolio/execution.
2. **HMM regime model (B §8).** It exists to produce a gross multiplier (1.0/0.7/0.3). Design C's vol-target overlay + DD ladder + VaR de-gross already implement three overlapping de-risking mechanisms. A fourth, requiring hmmlearn, a hand-written forward filter, and state-matching across refits, is not worth it in v1. Defer; this also deletes the hmmlearn dependency entirely.
3. **Vectorized backtester (C §5) and its parity test.** Its purpose is fast sweeps over thousands of ML variants — which v1 doesn't have. Maintaining two engines doubles the silent-divergence surface (C's own failure mode #3). Build only the event-driven truth engine; add the vectorized screen when sweeps actually become slow.
4. **`FeatureCache` (A §7.3).** At ~60 MB of total lake data, full factor recomputation over 5 years takes seconds-to-minutes. A content-addressed cache with code-hash invalidation and GC is the classic source of "stale artifact" bugs the design elsewhere fights hard against. Keep `FeatureSpec.key` (needed for manifests/reproducibility); drop the cache layer until recompute time measurably hurts.
5. **VWAPParticipationFill** (C §4.2). `NextOpenFill` matches live timing; sizes are pre-trade-capped at 1% ADV. Defer.
6. **Telegram inbound command poller** (`/halt`, `/flatten`, `/kill`, `/ack`). Outbound alerts + the `touch ~/alphaforge/KILL` file sentinel over SSH cover the real need with ~10% of the code and zero inbound attack surface. Keep `/status` at most; defer the rest.
7. **CPCV + PBO + DSR as deployment *gates*.** Keep `pbo.py`/`dsr.py` as small pure functions (they're each ~100 lines and good hygiene), but they only bind once there is a model-selection process — i.e., with the ML phase. Purged walk-forward alone is the v1 evaluation. Also see Finding 6.2: DSR ≥ 0.95 as a hard gate is unrealistic.
8. **Spot market ingestion.** v1 trades USDT-M perps only (shorting required by the optimizer). The only stated spot consumer is BTC spot for regime features — and regime is deferred; even if kept, BTC perp closes are an adequate proxy. Cutting spot halves the ingestion/test surface. Keep `MarketType.SPOT` in the type system; don't ingest it.
9. **Extended kline columns `n_trades`, `taker_buy_volume`.** Keep `quote_volume` (load-bearing: ADV, Amihud, universe). The other two are "useful later" — fetch them later. This may let v1 use plain ccxt `fetch_ohlcv` plus one raw call for quote volume, or just the raw endpoint — but trim the schema promise.
10. **Ridge-stacking blend behind a flag (B §9.1), per-regime blend weights (B §8), sleeve attribution (C §10.2)** — all explicitly research/v2 in their own designs; strike from v1 scope so they don't leak into interfaces.

**KEEP despite looking heavy (these are the institutional rigor):** PIT reader as the single read path; SCD2 instruments; universe builder with hysteresis and delisting history (suggest `N_in = 20` not 40 for v1 — C's own soak plan starts at 5 symbols); quality checks (the 3-condition bad-print detector is flag-only and cheap); resampler; truncation-invariance and parity tests; the cycle-status crash-recovery ladder; deterministic client order IDs; kill switch; golden-master backtest test.

**Simplify:** MVO is kept, but build C's `RankEqualVolFallback` (rank + inverse-vol + clip) *first* as the primary allocator and ship a full paper-trading phase on it. The MVO then arrives as a drop-in with its fallback already battle-tested. At G_max=1.0, w_max=0.15, turnover cap 0.10, the constrained MVO and the rank/inverse-vol portfolio will produce similar books anyway — the upgrade is real but not blocking.

## 2. Dependency risk on Apple Silicon

Ground truth on this machine: **no brew, no libomp, no uv.** Bootstrap order matters: uv installs via its standalone installer (no brew needed); brew is only required if/when lightgbm lands.

| Package | Risk | Verdict / safe alternative |
|---|---|---|
| **ta-lib** | High (C lib via brew + wrapper version skew) | Already avoided by both designs — confirm: never install. Factor math in-house. |
| **lightgbm** | Medium-high *on this machine*: pip wheel exists for macOS arm64 but dylinks OpenMP → `import lightgbm` fails without `brew install libomp`, and brew isn't installed. | Deferred with the ML phase anyway. When it lands: install brew + libomp, pin both; or use **sklearn `HistGradientBoostingClassifier`** (ships self-contained wheels, ~equivalent for shallow boosted trees on tabular alphas) as the no-brew fallback. |
| **hmmlearn** | Medium: small, sporadically maintained project; wheel availability has lagged new Python versions before; compiled extension. | Deferred with regime phase. If/when added: pin `hmmlearn==0.3.x`, and note that since B already hand-writes the forward filter, writing the ~150-line Baum–Welch yourself removes the dependency entirely — a legitimate option. |
| **cvxpy + ECOS** | **Do not depend on ECOS** — effectively unmaintained, source builds on new Pythons. The full `cvxpy` package drags in ECOS/SCS/OSQP. | Use **`cvxpy-base` + `clarabel`** (pure Rust, native arm64 wheels) with **`osqp`** as fallback — exactly Design C's solver choice; just make the *packaging* choice explicit (`cvxpy-base`, not `cvxpy`). |
| **numba** | Medium: llvmlite pin chains; numba lags numpy majors. Design A pins numpy ≥ 2.0, Design B pins numpy ≥ 1.26 — with numba in the env this conflict becomes real (numpy 2.x needs numba ≥ 0.60). | Cut from v1 (it only served the deferred triple-barrier loop). When labeling lands, try vectorized numpy first; the event count (~40 sym × 8.7k bars/yr × 72-bar scan) is tractable. |
| **shap** | Pulls numba transitively — same pin problem. | Deferred with ML phase. |
| pyarrow, duckdb, pandas, numpy, scipy, sklearn, ccxt, pydantic, structlog, typer, tenacity, httpx, matplotlib (Agg), marimo, hypothesis, freezegun | Low — all ship native arm64 wheels. | Fine. Unify numpy pin at ≥ 2.0 now (no numba in v1 to block it). |

Other dependency-adjacent: unify Parquet compression (A says zstd, B says snappy) → **zstd** everywhere. One `uv.lock` for the whole repo — B and C casually assume "they share the venv"; make that explicit, it's one project.

One non-library risk worth a line: **Binance API geo-availability.** Public klines endpoints are broadly reachable, but the paper loop's live ticker fetches from binance.com can be geo-blocked depending on operating region/IP. Verify from the actual operating location early (Phase 2 backfill will reveal it); the `DataSource`/`Broker` abstractions make Bybit/OKX via ccxt a low-cost fallback.

## 3. Cross-design coherence

The designs were clearly written against the same mandate but **do not agree on the most basic conventions.** Reconciliation needed before any code:

1. **Three timestamp conventions.** A: integer epoch **milliseconds**, bars labeled by **open** time. B: `datetime64[ns, UTC]`, `ts` = bar **start**. C: integer epoch **seconds**, timestamps refer to bar **close**. This is the #1 must-fix. Ruling: A wins (epoch-ms ints at API boundaries, `ts_open` storage label, `available_at = ts_open + Δ`, decision time = bar close). C's engine and SQLite schemas convert to ms (`ts_ms` columns already exist in C's `fills` — extend consistently); B's pandas layer derives decision-time indices via A's single sanctioned relabel helper.
2. **Two Instrument classes.** A: `instrument_id "BINANCE:PERP:BTCUSDT"`, `tick_size/lot_size/min_notional`, fee bps, SCD2 validity. C: ccxt-style `symbol`, `price_step/qty_step/min_qty/min_notional`, `can_short`. Unify into **one** `core/instruments.py`: A's identity scheme + SCD2 + C's trading fields (`can_short`, `min_qty`), one name per concept (`tick_size`, `lot_size` — drop `price_step/qty_step`). C's `Instrument` factory reads from A's `InstrumentStore` at `as_of`.
3. **Two calendars.** A's `TradingCalendar` (expected_bar_opens, is_session) and C's `BarCalendar` (periods_per_year, floor, next_close, funding_ts_in) are the same object. Merge; B's hardcoded 8760s become `calendar.periods_per_year`.
4. **Two factor abstractions.** A: `FeatureSpec`/`FeatureContext`/`FeatureEngine` with PIT-windowed context. B: `Factor` protocol over a raw panel + `FactorMeta`/`FactorRegistry`. Ruling: A's machinery is the registry/engine (its parity + truncation tests are the crown jewels); B's `FactorMeta` fields (`family`, `direction`, `cross_sectional`) merge into `FeatureSpec`; B's factor bodies become A-style registered functions in `features/library/`; B's `cross_section.py` slots in unchanged as post-processing. Drop B's parallel registry.
5. **Universe contract mismatch.** A exposes `universe_members(as_of)` intervals; B expects an `in_universe` bool column on the panel. Reconcile in A's `DatasetBuilder`/reader: it materializes the flag. Document that CS ops take the mask (B's safeguard #4) and the mask comes from A's intervals — one source.
6. **Funding PIT join mismatch.** A: `available_at = ts_funding + 5 min`, merge_asof on `available_at`. B: as-of join on settlement `ts` with 8h tolerance. A's is strictly more correct; B's carry factor must join on `available_at`. One join helper in `features/context.py`, not two implementations.
7. **Fees defined in two places.** A's instruments table carries `maker_fee_bps/taker_fee_bps`; C's `costs/fees.py` has `FeeSchedule` presets (values agree: 2/5 perp, 10/10 spot). Ruling: `costs/` is the consumer of record and the single import (C's own rule: "never reimplemented"); the instruments table may *store* observed fees, but `TransactionCostModel` is constructed from `FeeSchedule`, and nothing else reads fee fields.
8. **Dual scheduler bug.** A's `LiveUpdater` wakes at bar close + 30s grace to ingest; C's `LiveLoop` wakes at bar close + **20s** and at stage 1 "confirms bar present." The trading loop would routinely fire before the data writer finishes. Ruling: **one timer.** `LiveLoop` owns the schedule; its stage 1 *invokes* the incremental updater (or blocks until the ingest watermark covers `cycle_ts`, with a timeout → staleness gate). `af data update --follow` survives as a data-only mode, never run concurrently with the loop.
9. **Missing contract: ADV and σ_daily series.** C's cost model and pre-trade checks need per-instrument 30d-median ADV and EWMA σ_daily "from the data layer," but in A those exist only inside the universe builder. Expose both as registered features in `features/library/` (they're factors like any other) — one computation feeding universe, costs, and risk.
10. **Horizon inconsistency.** B's alpha horizon h = 72 bars; C amortizes costs at `h_hold = 48` bars (A ≈ 182). These should be the same config constant (A ≈ 8760/72 ≈ 122). C already asserts the purge gap ≥ label horizon via shared config — do the same for the amortization horizon.
11. **Naming drift at the seam:** C's `LiveLoop` depends on a `SignalPipeline`; B calls it `SignalService.on_bar_close`. Unify as `signals/service.py::SignalService` (B's name). B writes predictions to Parquet, C writes `target_weights` to SQLite — keep both (predictions = research artifact, target_weights = ops state) but stamp both with `cycle_ts` and the blend config hash so they reconcile.
12. **Layout/state divergence:** A uses `src/` layout (correct — keep); B and C use flat packages. A puts ops state in `var/ops.sqlite`, C in `~/alphaforge/state/alphaforge.db`, artifacts in `~/alphaforge/artifacts/`. Unify: `var/ops.sqlite` (ingest/quality/heartbeat) + `var/trading.sqlite` (C's full schema) + `artifacts/`. Two DBs is right (different write cadences, different owners), two *naming conventions* is not. Cosmetic but telling: B's §4.2 contains a Cyrillic-typo path (`features/факт…`) — the designs were not cross-read; assume more drift than what's listed here.
13. **Async boundary.** C is async (Broker ABC, httpx, `asyncio.to_thread` for SQLite); A and B are sync. Fine — but confine `async` to `execution/` and `live/`; do not async-ify ingestion or features. The loop calls sync compute directly (it has a full hour of budget).

## 4. Operational reality: 24/7 paper on a sleeping laptop

Honest version, which none of the designs quite states:

- **A MacBook with the lid closed does not run your loop, full stop.** `caffeinate -i` prevents *idle* sleep while on AC with the lid open; it does not survive lid-close (clamshell mode requires external display + power). Any design language implying continuous 24/7 operation on this laptop is overpromise.
- **The architecture already tolerates this — say so and design for it.** Watermark-based idempotent backfill means data gaps self-heal on wake; `cycle_ts`-keyed cycles mean missed bars are *skipped*, not corrupted. v1 laptop story: a **launchd LaunchAgent** (`KeepAlive=true`, `RunAtLoad=true`, `ProcessType=Background`) with a `caffeinate -i`-wrapped process; accept missed cycles while asleep; make missed-cycle accounting a first-class metric in `af status` and the daily tearsheet ("38/24 expected cycles run" must be visible, not silent).
- **One concrete bug to design around:** on macOS, `time.monotonic()`/asyncio timers historically do not advance during system sleep — `await asyncio.sleep(3600)` spanning a lid-close oversleeps by the nap duration. The loop must sleep in short ticks (30–60s) and re-check **wall clock** against the next `cycle_ts` deadline, recomputing after every wake. Cheap to build, miserable to debug if missed.
- **The real deployment story is a small VPS, sooner than "later."** Everything here is files + SQLite + one process; a Hetzner CAX (arm64, ~€4/mo) runs identical wheels to the MacBook. Plan it as an explicit phase (Phase 8 below): laptop = development + research; VPS = the soak. Trying to make macOS power management institutional-grade is a worse use of time than `rsync && systemd`.
- **Crash recovery:** C's design (status ladder + deterministic client order IDs + reconciler) is genuinely good — keep verbatim. Add the missing piece: **backups.** The Parquet lake is re-derivable from the exchange; `var/trading.sqlite` (fills, equity curve, risk events) and `data/predictions/` are **not**. Nightly `sqlite3 .backup` + copy off-box (or litestream to free-tier object storage) from day one of paper trading. Also keep C's note: `~/alphaforge` must not live in an iCloud-synced folder (home root is safe by default; Desktop/Documents are not).
- **Disk growth: a non-issue, except logs.** Lake ≈ 100–200 MB for 5y × 40 symbols; predictions/equity rows are trivial; total < 2 GB/yr. The only unbounded growth is structlog JSONL (per-cycle, per-symbol lines) — set 30-day retention/rotation in Phase 1 config, and note the feature cache (if it had survived) would have been the other unbounded directory; cutting it also cut the GC problem.
- **Clock discipline:** macOS NTP is fine; on the VPS enable chrony. The 30s ingest grace assumes < ~5s skew — assert clock sanity (exchange `fetchTime` vs local) once per cycle, alert on > 2s.

## 5. Unified package layout

`src/` layout (A), one uv project, one lockfile. B's modules slot under A's skeleton; C's modules join as siblings. Items marked `[deferred]` exist in the tree design but are not built in v1 phases.

```
~/alphaforge/
├── pyproject.toml                  # uv; python>=3.12; [project.scripts] af = alphaforge.cli.main:app
├── uv.lock
├── configs/                        # base.yaml, paper.yaml
├── data/                           # gitignored: lake/, features/, quality/, predictions/
├── var/                            # ops.sqlite, trading.sqlite, log/ (30d rotation), KILL sentinel
├── artifacts/                      # backtests/{run_id}/, models/ [deferred]
├── notebooks/                      # marimo .py
├── tests/                          # unit/ property/ golden/ integration/
└── src/alphaforge/
    ├── config/settings.py          # ALL pydantic-settings: paths, data, quality, universe,
    │                               #   costs, portfolio, risk, live (A's loader, C's models folded in)
    ├── core/
    │   ├── time.py                 # Timeframe, UTC guards, epoch-MS everywhere (A wins; C's seconds dropped)
    │   ├── types.py                # shared enums + OrderRequest/Fill/Position/AccountState (C, re-based on ms)
    │   ├── instruments.py          # THE Instrument: A identity+SCD2 ∪ C trading fields; InstrumentStore
    │   ├── symbols.py              # ccxt ↔ exchange ↔ instrument_id
    │   ├── calendar.py             # TradingCalendar ABC: A's expected_bar_opens ∪ C's periods_per_year,
    │   │                           #   floor/next_close/funding_ts_in; Always24x7Calendar
    │   ├── errors.py / logging.py  # structlog config
    ├── data/                       # Design A verbatim (perp-only ingestion in v1)
    │   ├── schemas.py / sources/ / ingest/ / store/ / quality/ / universe/
    ├── features/
    │   ├── spec.py                 # FeatureSpec ∪ FactorMeta (family, direction, cross_sectional merged in)
    │   ├── registry.py / context.py / engine.py / parity.py     # A machinery (cache.py [deferred])
    │   ├── cross_section.py        # B: winsorize_mad, cs_zscore, cs_rank, neutralize, CSPipeline
    │   └── library/                # B's factor bodies as A-registered features:
    │       ├── vol.py momentum.py mean_reversion.py carry.py liquidity.py
    │       └── market.py           # ADV30, sigma_daily — shared by universe/costs/risk (Finding 3.9)
    ├── validation/                 # B: splits.py (purged WF; CPCV [deferred]), metrics.py (IC/NW),
    │                               #   pbo.py dsr.py [report-only in v1]
    ├── signals/                    # B: blending.py (EWMA Rank-IC), sizing.py (Grinold μ), service.py
    │                               #   SignalService = THE contract with live/loop
    ├── labeling/                   # B [deferred — ML phase]
    ├── ml/                         # B [deferred — ML phase]
    ├── regime/                     # B [deferred]
    ├── costs/                      # C: fees.py, model.py — single TransactionCostModel, sole fee authority
    ├── backtest/                   # C: ledger.py, fills.py (NextOpenFill; VWAP [deferred]),
    │                               #   engine.py, result.py (vectorized.py [deferred])
    ├── portfolio/                  # C: covariance.py, optimizer.py (rank/inv-vol first, MVO second),
    │                               #   overlay.py, discretize.py
    ├── risk/                       # C: limits.py, pretrade.py, monitors.py, killswitch.py
    ├── execution/                  # C: broker.py, paper.py, order_manager.py, reconcile.py,
    │                               #   ccxt_broker.py (NotArmed stub)
    ├── live/                       # C: store.py (trading.sqlite), loop.py (OWNS the hourly timer,
    │                               #   invokes data updater — Finding 3.8), recovery.py, alerts.py (outbound)
    ├── analytics/                  # C: metrics.py, tearsheet.py, walkforward.py (attribution.py [deferred])
    ├── research/session.py         # A
    └── cli/main.py                 # typer `af`: data/quality/universe/features/backtest/paper/status/arm
```

## 6. Realistic expectations — where the designs overpromise

1. **"atol=0 parity" between batch and as-of feature paths (A §7.5) is unachievable for EWMA-family features.** Span-based EWMA has infinite memory; a live computation truncated to `lookback_bars` cannot be bit-identical to a full-history pass. This collides with the finite-`lookback_bars` contract that B's `ewma_vol(span=168)`, EWMA-IC blending, and C's EWMA covariance all depend on. Fix the *spec*, not the test: define every EWMA feature with an explicit warmup convention (e.g., lookback = 10× span, documented truncation error < 1e-12) and set parity tolerance accordingly. Parity stays exact (atol=0) for finite-window features only.
2. **"DSR ≥ 0.95 deployment gate" will block deployment forever** at this data length and trial count — or, worse, be quietly waived, which trains the operator to ignore gates. With 1–2 years of OOS and an honestly-measured N of dozens of configs, almost nothing clears 0.95. Treat DSR/PBO as mandatory *reports* in v1, with the gate threshold a documented judgment call.
3. **The μ pipeline's precision is illusory.** `μ = IC_target · σ√h · F̃ · G` stacks three fudge factors (assumed IC = 0.02, regime gate, vol-target scale) before a λ=7 MVO whose λ was itself derived from "believed gross Sharpe ≈ 1.0." Realistic net-of-cost expectation for a free-data, 1h-bar, top-20 crypto cross-sectional system paying ~15–20 bps round trips: **Sharpe 0.5–1.0 in good regimes, with multi-month flat/down stretches** — not the implied 1.0+ gross. This is fine — but the vol-targeting overlay and constraints, not the MVO objective, will dominate realized sizing. Say so, and don't burn weeks tuning λ.
4. **"kill -9 mid-backfill, rerun → byte-identical lake" (A Phase-4 gate) is false as written:** re-fetched rows get new `ingested_at` wall-clock values, so files differ. The gate should be "logically identical excluding `ingested_at`" — trivial fix, but a gate that can't pass as specified erodes trust in all gates.
5. **Meta-labeling's value at this scale is unproven.** ~120 independent 72-bar cross-sections/year × ≤40 names is thin training data for even a depth-4 LightGBM. B's own framing (ML "only learns when alphas work") is the right hedge — the build plan should demand the rule-based blend show positive purged-WF IC *before* any ML is added, otherwise the ML phase is optimizing noise.
6. **24/7 laptop operation** — covered in Finding 4; the designs' launchd/caffeinate notes understate the lid-close reality.
7. **Quality-check thresholds (k=8σ, 0.25 volume fraction, 0.8 downtime fraction) are presented with false precision.** A's own build order has the right instinct ("tune nothing until you've seen real findings") — treat every default as a placeholder pending the Phase 3 review of real Binance history.

## 7. Phased build plan — empty repo → live paper trading

Eight phases. Each is a coherent shippable unit with an explicit verification gate; nothing in a later phase is needed to verify an earlier one.

**Phase 1 — Repo + core kernel.**
Bootstrap uv (standalone installer — no brew needed), `src/` skeleton, CI (ruff, mypy --strict, pytest). Build `core/` complete: `time.py` (epoch-ms, Timeframe, bar arithmetic), unified `instruments.py` + `symbols.py`, merged `calendar.py`, `types.py`, `errors.py`, `logging.py`, `config/settings.py` (all sections, including costs/portfolio/risk so later phases never touch config plumbing), `data/schemas.py`.
*Verify:* hypothesis property tests for bar arithmetic (`floor/next_close/expected_bar_opens` round-trips); SCD2 instrument round-trip test; the `datetime.now()`-grep test; `uv run af --help` works; CI green.

**Phase 2 — Lake + ingestion.**
`LakePaths`, `LakeWriter` (atomic replace, dedupe, partial-bar drop guard), `PITDataReader`, `CheckpointStore`, `CCXTDataSource` (perp only), `BackfillJob`, `af instruments refresh`, `af data backfill`.
*Verify:* PIT boundary unit test (bar invisible at `close − 1 ms`, visible at `close`); backfill 10 perps × 3y of 1h + funding; `kill -9` mid-run, rerun, **logically identical lake excluding `ingested_at`**; spot-check 3 random bars and 3 funding rows against the Binance UI. (This phase also empirically confirms API reachability from the operating region.)

**Phase 3 — Data integrity: quality, resample, universe.**
Quality checks + `ValidationReport` + `af quality run`; `Resampler` (4h/1d); `UniverseBuilder` + history rebuild (`N_in=20`).
*Verify:* hypothesis tests of resample aggregation identities; quality run over the real backfill with a written half-page review of findings (downtime windows, bad prints) and any threshold adjustments; universe history contains ≥1 known-delisted symbol; `af universe rebuild` is deterministic across reruns.

**Phase 4 — Factor layer + first evidence of alpha.**
`features/` machinery (spec/registry/context/engine/parity — no cache), `cross_section.py`, library: vol estimators, momentum ×3, TS-mom ×3, residual reversal, carry ×2, liquidity, plus ADV30/σ_daily as registered features. `validation/metrics.py` (RankIC, Newey–West) and execution-aware forward returns (the one piece of `labeling/` v1 needs).
*Verify:* truncation-invariance test for every registered factor (CI); batch-vs-asof parity (atol=0 finite-window, documented tolerance + warmup for EWMA family); funding-sign regression (May-2021 episode → CARRY > 0); **deliverable: a RankIC report per factor over full history with NW t-stats — the go/no-go evidence the system has anything to trade.**

**Phase 5 — Truth backtester.**
`costs/` (fees + cost model, hand-computed fixtures), `Ledger` (funding-sign and flip property tests), `NextOpenFill`, `EventDrivenBacktester`, `BacktestResult`, `analytics/metrics.py` + `tearsheet.py`.
*Verify:* golden-master 3-asset scripted run asserted **to the cent** (fills, fees, funding, equity); `qty>0, f>0 ⇒ payment<0` and long+short ⇒ net-zero-funding hypothesis tests; signal-on-final-bar produces zero fills (`LookaheadError` regression); hand-reproduced funding for a real historical BTC perp position matches Binance's published rates.

**Phase 6 — Portfolio + risk, then strategy backtest.**
Covariance (EWMA + Ledoit–Wolf + PSD repair), **rank/inverse-vol allocator as primary**, vol-target overlay, `discretize.py`, `RiskLimits`/`PreTradeChecker`/monitors/`KillSwitch`; then MVO via `cvxpy-base` + Clarabel as the upgrade with the proven fallback behind it. `signals/blending.py` + `sizing.py` (IC-weighted blend, h=72 amortization aligned per Finding 3.10). `walkforward.py` (purged WF only).
*Verify:* LW vs brute-force on small matrices; optimizer sanity (no costs/constraints ⇒ `w ≈ (1/λ)Σ⁻¹μ`; refuses to trade on the `_ann/_bar` mismatch asserts); DD-ladder state-machine test with hysteresis; **deliverable: full purged walk-forward backtest of the blend, 2020→now, net of costs, with tearsheet — the decision artifact for proceeding to paper.**

**Phase 7 — Paper trading loop.**
`live/store.py` (trading.sqlite), `PaperBroker`, `OrderManager` (tested vs `FlakyBroker` double), `Reconciler`, `recovery.py`, outbound Telegram alerts + file-sentinel kill switch, `LiveLoop` owning the single timer and invoking the incremental updater (Finding 3.8), wall-clock-deadline sleep ticks (Finding 4), `SignalService` wired in. `af status` with missed-cycle accounting.
*Verify:* subprocess SIGKILL at every cycle stage → clean recovery, no double orders (deterministic client IDs); **14-day soak on 5 symbols on the laptop**, accepting sleep gaps, with daily tearsheets; end-of-soak reconciliation: replay the soak window through the Phase-5 engine and compare signals and costs to paper fills within stated tolerance.

**Phase 8 — Deployment + ops hardening.**
VPS migration (Hetzner CAX-class arm64 recommended; launchd KeepAlive is the laptop fallback), systemd unit, nightly `sqlite3 .backup` + off-box copy of `var/` and `data/predictions/`, log rotation, clock-sanity check per cycle, widen universe to 20, 30-day soak.
*Verify:* ≥ 99% of expected cycles executed over 30 days; backup **restore drill** (rebuild ledger on a clean machine from backups alone); modeled-vs-realized slippage report reviewed; missed-cycle and reconciliation alerts demonstrated end-to-end.

**Post-v1 backlog (explicitly out of scope above):** labeling + LightGBM meta-model (brew + libomp or sklearn HGB; requires Phase 6 blend showing positive purged-WF IC first), CPCV/PBO/DSR as gates, HMM regime gate, vectorized engine + parity, feature cache, VWAP fills, Telegram inbound commands, spot ingestion, sleeve attribution, equities calendar.

### Critical Files for Implementation
- /Users/arhancanli/alphaforge/src/alphaforge/core/time.py — the unified timestamp/bar-arithmetic contract all three designs must share (Finding 3.1)
- /Users/arhancanli/alphaforge/src/alphaforge/core/instruments.py — the merged Instrument model resolving A/C field conflicts (Finding 3.2)
- /Users/arhancanli/alphaforge/src/alphaforge/data/store/reader.py — PITDataReader, the single PIT enforcement point everything reads through
- /Users/arhancanli/alphaforge/src/alphaforge/signals/service.py — SignalService, the alpha→portfolio seam where Designs B and C meet (Finding 3.11)
- /Users/arhancanli/alphaforge/src/alphaforge/live/loop.py — LiveLoop, owner of the single scheduler and the cycle/recovery ladder (Findings 3.8, 4)
