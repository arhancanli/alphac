# SPINE_REVIEW_equity — EQUITY-D1 / XNYS correctness review (P2 + P1)

**Role:** EQUITY-D1 CORRECTNESS REVIEWER. **HEAD `549aecc`** + the uncommitted spine arc
(working tree). Read-only review; one review doc, no source modified.

**Verdict: CRIT — PASS_WITH_NOTES.** The equity-D1 / XNYS path is correct *as far as the arc
intends it to go*: the calendar seam is threaded through the reader, feature panel, backtest
engine, triple barrier, portfolio annualizers, sizer, and walk-forward, and the corp-actions
read path is live and PIT-correct. Crypto byte-identity holds (the full gate suite passes
unchanged; ruff + mypy --strict clean). The equity *feature-compute* path is deliberately held
behind a fail-closed `FeatureEngine` guard (SPINE_ARC §4), and that is the right call — but the
guard itself is **untested**, and the P1 integration "proof" runs on the fake H1==session grid,
not the real XNYS D1 panel. Those are the gaps to close; none is a crypto regression.

---

## 1. What I verified GREEN (each independently exercised)

### 1.1 Crypto byte-identity (THE hard constraint) — PASS
- Gate integration suite passes **unchanged**: `test_golden_master.py` (final equity
  `round(...,2) == 101_281.97` to the cent; per-fill 1e-9; funding 1e-12;
  `dropped_missing_next_bar == 1`), `test_mu_contract.py`, `test_walkforward_equivalence.py`,
  `test_phase4_deployed_path.py` — 17 passed.
- Unit gates green: `test_triple_barrier.py`, `test_backtest_engine.py`, `test_blend_strategy.py`,
  `test_sizing.py`, `test_feature_engine.py`, `test_pit_reader.py`, `test_calendar.py`,
  `test_signal_service.py`, `test_walkforward.py`, `test_overlay.py`, `test_settings.py`.
- The byte-identity mechanism is sound: every changed spine expression reduces to its prior form
  under `Always24x7Calendar` — `next_bar_open(o,H1)==o+H1.ms`, `floor_bar(t-1,H1)==t-H1.ms`,
  `periods_per_year(H1)==H1.bars_per_year==8760.0`, `expected_bar_opens` delegates to the same
  `core.time` kernel. The new kw-only params all default to the crypto sleeve.
- `ruff check` + `mypy --strict` clean on all 11 changed source files.

### 1.2 Corp-actions READ PATH (P1) — PASS
- `PITDataReader.corporate_actions` (reader.py:181) mirrors `funding()` exactly: ranges on
  `ex_date`, **masks on the stored `available_at`, never `ex_date`** (the leakage-finding-18
  analogue). SELECT column order matches `CORPORATE_ACTIONS_SCHEMA`; `result.cast(schema_for(...))`.
- Reader PIT tests (`test_pit_reader.py::TestCorporateActionsPIT`) are thorough: `available_at`
  boundary (invisible at `avail-1`, visible at `avail`), half-open window on `ex_date`,
  instrument filter, dividend `cash_amount`, schema-exact, empty-interval.
- `FeatureContext.corporate_actions` (context.py:231) serves the `_CA_COLUMNS` projection, cached,
  masked at `as_of=end`; `ex_date`/`available_at` added to `_TS_COLUMNS` so both cast to int64.
- `_adjusted_close_panel` (equity_price.py:258): **fail-closed `ConfigError` when the getter is
  absent**; the only surviving pass-through is an EMPTY actions frame (`C* == C_raw`); the
  availability lag is the explicit `Timeframe.D1.ms` (P18 corner folded in — kills the
  Fri→Mon `grid[1]-grid[0]` 2-session lookahead).

### 1.3 Session-positional feature windows on a REAL XNYS D1 panel — PASS (verified directly)
The engine guard blocks D1 `compute_history`, so I exercised the seam by constructing a
`FeatureContext(asset_class=EQUITY)` directly on a real XNYS-session lake (Thu/Fri/Mon/Tue,
weekend absent):
- `ctx.panel("close", D1)` index == the four XNYS session opens; **weekend slots absent, not
  NaN-padded** (`THU+2*DAY`, `THU+3*DAY` not in index).
- `reversal(panel, window=1)` at the Monday row == `-ln(102/101)` — a Friday→Monday **session**
  hop, NOT a NaN weekend slot and NOT a calendar-day shift. `shift(W)` is W sessions.

### 1.4 Planted-split continuity on a REAL XNYS D1 panel — PASS (verified directly)
On a real XNYS D1 lake with a 2:1 split (ratio 0.5) declared before the window and ex mid-window:
raw closes `[200, 202, 100, 101, 102]` → adjusted `[100, 101, 100, 101, 102]`; the ex-bar return
goes from the raw **-0.70 split artifact** (`ln(100/202)`) to a **continuous -0.01** (`ln(100/101)`).
The split is folded; no -50%/-70% print reaches the factor. This is the role's load-bearing gate
and it holds on the deployed kernel + the real session grid.

### 1.5 Backtest engine session grid (P2) — PASS
- Grid built from `calendar.next_bar_open(ts_open, tf)`; `last_close_of` and the per-bar
  `prev_open = calendar.floor_bar(t-1, tf)` likewise. Crypto reduces to `±tf.ms`.
- Real-XNYS D1 tests (`test_backtest_engine.py`): a Friday-decision order fills at **Monday's
  open** (110.0) hopping Sat/Sun with `dropped_missing_next_bar == 0`; `bars_processed == 4`
  (Fri/Mon/Tue/Wed grid steps, no phantom weekend rows); `config["asset_class"]` echoed.

### 1.6 TripleBarrier session hops (P2) — PASS
- `_scan_one_instrument` walks `calendar.next_bar_open` for entry/path/vertical; crypto reduces to
  `tau + (1+k)·Δ` byte-identically. Real-XNYS D1 tests prove a Friday-entry hold hops the weekend
  to the Tuesday vertical and a Monday-only PT touch resolves on Monday (not a Saturday gap NaN).

### 1.7 Annualizers / periods_per_year from the calendar (P2) — PASS
- `BlendStrategy`: cov grid + `annualize_cov(..., ctx.calendar.periods_per_year(tf))` +
  `_realized_vol_ann(periods_per_year)`; `overlay.vol_target` takes the annualized scalar (doc-only
  edit). `GrinoldSizer.annualization == periods_per_year / h` (default 8760 → crypto identical).
- `WalkForwardRunner`: grid via `self._calendar.expected_bar_opens`; the purge/embargo is measured
  in **grid rows**, so feeding the calendar grid makes "168 bars" == 168 sessions for equity for
  free (no `splits.py` change). `mu_contract` still asserts 8760.

### 1.8 `gaps` XNYS (P18/G8) — PASS
- `reader.gaps(..., asset_class=EQUITY)` reports no weekend gaps; the 24/7 default still reports
  Sat+Sun (`test_pit_reader.py::TestGaps::test_equity_asset_class_skips_weekends`).

---

## 2. CRIT findings (close before lifting the guard / shipping the equity sleeve)

### C1 — The EQUITY/D1 fail-closed guard is UNTESTED [BLOCKER for the arc's own safety contract]
`FeatureEngine._guard_equity_unverified` (engine.py:173) is the single most important safety line
in this arc (SPINE_ARC §4: "makes the partial migration loud, not silent"). There is **no test**
asserting it fires (`grep` for `rejects EQUITY` / `_guard_equity` / `partially-migrated` over
`tests/` returns nothing). I verified by hand that it fires on `compute_history` AND
`compute_asof`, for BOTH the `anchor_tf is D1` and the `asset_class is EQUITY` branches, and that
crypto defaults never trip it — but a future edit could silently delete the guard (or flip the
`is`/`or` logic) and the whole suite stays green while equity compute silently runs on a broken
path. **Fix:** add `tests/unit/test_feature_engine.py::test_rejects_equity_d1_specs` asserting
`pytest.raises(NotImplementedError, match="EQUITY/D1")` on both methods and both trigger branches,
and a companion asserting CRYPTO_PERP/H1 does NOT raise.

### C2 — The P1 integration "proof" runs on the FAKE H1 grid, not the real XNYS D1 panel [HIGH]
`tests/integration/test_corp_actions_read_path.py` lays its synthetic lake on the engine's default
**crypto H1 anchor** (`HOUR` step, "one slot == one session bar", GRID NOTE at :22-29) and drives
`compute_history` through the crypto sleeve — because the EQUITY/D1 engine path is guarded off
(C1's guard). So the integrated read-path proof (reader → context → `_adjusted_close_panel` →
factor) is certified on a contiguous grid that **no real equity lake produces** — this is exactly
the "parity guards the wrong path" / B1 concern the audit raised (LEAKAGE G2, ARCH G1). The split
folding *is* correct (I verified it on a real XNYS D1 panel by hand, §1.4), so this is a
test-fidelity gap, not a wrong number — but the integration test as written would NOT catch a
regression that only manifests on the session-gapped grid (e.g. the C3 panel-tf bug below).
**Fix:** once the guard is lifted (next arc), re-point this test (or add a sibling) at the real
XNYS D1 panel via `FeatureEngine(anchor_tf=D1, asset_class=EQUITY)`. Until then, document in the
test that it certifies the kernel + read wire, NOT the deployed D1 grid.

### C3 — `_adjusted_close_panel` calls `ctx.panel("close")` with the DEFAULT H1 tf → raises on the EQUITY sleeve [HIGH — the concrete blocker behind the guard]
`_adjusted_close_panel` (equity_price.py:278) and the factor bodies (`ctx.panel("quote_volume")`
at :467) call `panel(...)` **without `tf=Timeframe.D1`**, so `panel` uses its default
`tf=Timeframe.H1`. On the EQUITY sleeve the `XNYSCalendar.expected_bar_opens(H1)` raises
`NotImplementedError` ("supports D1 only"). I confirmed this: building an EQUITY-sleeve context and
calling `_adjusted_close_panel` raises `NotImplementedError`, not a usable panel. This is *why* the
§4 guard is load-bearing and correct — the equity feature path genuinely cannot run yet — but it
means the equity factor library is **one more wire short** than "guard-lifted == working." When the
guard is lifted, the panel `tf` (and the `bars`/`panel` defaults across the equity bodies) must be
threaded from the context's anchor TF (e.g. a `ctx.anchor_tf` or pass `tf=D1` explicitly), or the
factors will crash. **Fix (next arc, but flag now):** thread the anchor TF into the equity factor
panel reads; add it to the lift-the-guard checklist in SPINE_ARC §8.

---

## 3. NOTES (non-blocking; correct-as-built or out-of-scope-but-confirmed)

- **`ANCHOR_TIMEFRAME` kept as a re-export** (`engine.py:54 = CRYPTO_PERP_SLEEVE.anchor_tf`) for
  `features/parity.py` and `research/ic_report.py` — both consume it as the crypto-default H1, so
  byte-identical. This is the documented transitional choice (SPINE_ARC §3.1); fine, but the two
  importers should migrate to `sleeve_for(...)` when the equity path is lifted (the symbol is then
  dead).
- **`forward_returns` / `estimate_blend_weights` session hops** are NOT migrated (still `+Δ`
  positional) — correctly out-of-scope (SPINE_ARC §3.6, §8) and covered by the C1 guard. The
  `SignalService` threads `anchor_tf` (crypto-identical) but the equity session-hop of these two is
  the explicit next-arc item.
- **Equity as-of window** (`compute_asof` minimal-window arithmetic) is calendar-ms, not
  session-hopping — correctly out-of-scope and guarded. Confirmed the guard covers `compute_asof`.
- **`tests/golden/` is empty** — the golden master lives in `tests/integration/test_golden_master.py`
  (asserts to the cent). Pre-existing (P18 corner), not introduced here.
- **`StrategyContext.calendar`** is correct (`calendar_for(asset_class)`); the cov-panel grid and
  realized-vol annualizer both source it. Verified crypto identity (8760, 24/7 grid).
- **Equity `CostInputProvider`** (G4): `LakeCostInputs` left H1-gated as designed; an equity cost
  provider is out-of-scope (SPINE_ARC §8). A real equity backtest still needs it — not a regression.

---

## 4. Recommended regression tests to add (close C1, harden C2/C3)

1. **`test_feature_engine.py::test_rejects_equity_d1_specs`** — the C1 guard, both methods, both
   branches (`anchor_tf=D1` and `asset_class=EQUITY`), plus a CRYPTO_PERP/H1 does-not-raise case.
2. **A direct XNYS-D1 panel parity unit** — `FeatureContext(asset_class=EQUITY).panel("close", D1)`
   on a weekend-spanning session lake asserting (i) index == session opens only (no weekend rows),
   (ii) `reversal(panel, 1)` at the post-weekend row == the Fri→Mon session return (the §1.3 probe,
   promoted to a permanent test). This guards the seam independently of the engine guard.
3. **A direct `adjusted_close` continuity unit on a real D1 panel** — promote the §1.4 probe: split
   folded, ex-bar return continuous, pre-declaration row genuinely unadjusted.
4. **(When the guard lifts)** re-point `test_corp_actions_read_path.py` at the real
   `anchor_tf=D1 + XNYSCalendar` path (closes C2) and add the panel-tf threading (closes C3).
