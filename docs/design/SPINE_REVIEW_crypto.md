# SPINE_REVIEW_crypto — CRYPTO BYTE-IDENTITY REVIEW (P2 + P1 spine arc)

**Role:** CRYPTO BYTE-IDENTITY REVIEWER. **Verdict: PASS (no crypto drift).**
**HEAD:** `549aecc` (working tree: the P2 calendar-aware spine + P1 corp-actions read-path arc).
**Gate:** the existing crypto regression suite must pass UNCHANGED. It does — twice, end to end.

The arc is an **OFF == identity refactor** on the crypto path, as designed (SPINE_ARC §5). Every
crypto number is unchanged. I found **zero crypto numeric drift** and **no blocking issues**.

---

## 1. The gate ran and is UNCHANGED

| Suite | Result |
|---|---|
| `test_golden_master.py` + `test_mu_contract.py` + `test_walkforward_equivalence.py` (the core gate) | **13 passed** (224.9s) |
| `test_phase4_deployed_path.py` + `test_triple_barrier.py` + `test_backtest_engine.py` + `test_blend_strategy.py` + `test_sizing.py` + `test_feature_engine.py` + `test_pit_reader.py` + `test_calendar.py` | **216 passed** (7.3s) |
| `test_feature_parity.py` + `test_feature_serve_parity.py` + `test_signal_service.py` + `test_gates_default_off_identity.py` + `test_walkforward_gated_determinism.py` + `test_factor_invariants.py` + `test_data_integrity_end_to_end.py` + `test_regime_gate_no_same_day_leak.py` | **179 passed** (99.9s) |
| `test_corp_actions_read_path.py` (new P1) + `test_sleeve.py` (new) + `test_settings.py` | passed |
| **FULL non-network suite** (`uv run pytest -q`) | **2736 collected, exit 0, zero F/E/x/s** (ran twice) |
| `ruff check src/` (+ new files) | All checks passed |
| `mypy --strict src/` | Success: no issues found in 133 source files |

- The golden master (`test_golden_master.py`) asserts the full-pipeline CRYPTO_PERP equity curve
  **to the cent** plus per-fill price/fee/realized to 1e-9, funding to 1e-12, and the
  `dropped_missing_next_bar == 1` counter. It passes unchanged — the primary byte-identity gate
  for the engine grid/next-bar (§3.3) and the annualizers (§3.5).
- `test_mu_contract.py` asserts `annualize_cov(..., 8760.0)` and `mu_ann = mu_h·8760/h` on
  CRYPTO_PERP — passes unchanged (gate for §3.5/§3.6).
- The deployed-path parity/truncation harness (`test_phase4_deployed_path.py`) passes unchanged
  (gate for the feature engine + context panel + as-of/batch parity).

## 2. Why it is byte-identical — verified at the source

The refactor routes every bare spine call through `calendar_for(asset_class)`, defaulting to
`AssetClass.CRYPTO_PERP` → the shared `Always24x7Calendar`. That calendar is **not a
re-implementation** — each method literally forwards to the same primitive the spine called before
(`core/calendar.py:117-131`, confirmed):

| Spine expression (before) | After the arc | Crypto reduction (verified) |
|---|---|---|
| `expected_bar_opens(s,e,H1)` | `Always24x7.expected_bar_opens` | → same `core_time.expected_bar_opens` |
| `tf.bars_per_year` (8760) | `Always24x7.periods_per_year(H1)` | → returns `tf.bars_per_year` = 8760.0 |
| `ts_open + tf.ms` (grid step) | `Always24x7.next_bar_open(ts_open,H1)` | → `core_time.next_bar_open` = `ts_open + H1.ms` |
| `t - tf.ms` (prior open) | `Always24x7.floor_bar(t-1,H1)` | → `core_time.floor_bar(t-1,H1)` = `t - H1.ms` |
| `tau + (1+k)·Δ` (TB walk) | iterated `Always24x7.next_bar_open` | each hop `+H1.ms` ⇒ same arithmetic |
| `mu_h · 8760/h` | `mu_h · periods_per_year/h`, ppy=8760 | identical |

Every new parameter is kw-only with a crypto default (`anchor_tf=H1`, `asset_class=CRYPTO_PERP`,
`calendar=None → calendar_for(CRYPTO_PERP)`, `periods_per_year=Timeframe.H1.bars_per_year`), so an
un-migrated caller is byte-identical and the migration is mechanical. No new float op is introduced:
the annualizers receive the *same* `8760.0` constant, just sourced via a method that returns it.

Spot-checks confirming no crypto behavior change:
- **`backtest/engine.py`**: grid `= {next_bar_open(o,tf)}` and `prev_open = floor_bar(t-1,tf)` used
  in all three lookups (funding `:715`, mark `:724`, order-build `:1006`). For 24/7 these equal the
  old `o + tf.ms` / `t - tf.ms` exactly. The new `config["asset_class"]` echo key is additive (no
  test asserts dict-equality of the echo).
- **`labeling/triple_barrier.py`**: `path_opens[k]` for 24/7 = `tau + (1+k)·Δ`; vertical
  `path_opens[horizon]` = `tau + (1+horizon)·Δ`. `delta = cfg.timeframe.ms` is preserved in
  `apply_triple_barrier` for `_grid_sigma` (positional EWMA, calendar-agnostic) and the funding
  `decision_ts = event_ts + delta` (pure-integer availability) — both correct to keep.
- **`portfolio/strategy.py`**: `periods_per_year = ctx.calendar.periods_per_year(tf)` = 8760.0 for
  crypto; `_realized_vol_ann(periods_per_year)` → `sqrt(8760)` as before.
- **`signals/sizing.py` / `service.py`**: `annualization = periods_per_year/h` = `8760/72`;
  default sleeve `CRYPTO_PERP_SLEEVE` resolves H1 + 8760.0.
- **`analytics/walkforward.py`**: `sleeve_for(settings.data.asset_class)` defaults CRYPTO_PERP → H1
  + 24/7 grid; the 24/7 grid feeds the bar-count splitter unchanged (`test_walkforward_equivalence`
  is green).
- **`data/store/reader.py`**: `corporate_actions()` mirrors `funding()` exactly, masking on stored
  `available_at` (never `ex_date`); `gaps()` defaults CRYPTO_PERP → 24/7 grid. Crypto never reads
  corp-actions; if it did, perps have none ⇒ empty frame.
- **`features/library/equity_price.py`**: the fail-closed raise only fires when the getter is
  *absent* — unreachable now that `FeatureContext` always exposes `corporate_actions()`. The empty
  frame ⇒ `return raw` branch is the crypto/no-action path (byte-identical). Equity factors are
  never instantiated on the crypto path regardless.
- **The `_guard_equity_unverified()` fail-closed guard** rejects EQUITY/D1 specs; CRYPTO_PERP/H1
  never trips it. This makes the partial equity migration loud, not silent — exactly per SPINE_ARC §4.

## 3. Residual bare constants — grepped, triaged, NONE are crypto drift

`grep` over `src/` for `expected_bar_opens` / `ANCHOR_TIMEFRAME` / `bars_per_year` / `sqrt(8760)` /
`sqrt(365)` / `8760` / `365` leaves the following sites. **Every one is either H1-correct for
crypto or on a fail-closed equity path — none changes a crypto number.** Logged as follow-ups, not
blockers:

1. `backtest/engine.py:428` `LakeCostInputs` bare `expected_bar_opens(...,H1)` — **intentionally
   left H1-gated** (SPINE_ARC §3.3/§8; the ctor rejects non-H1, equity injects a future provider).
   Crypto-identical.
2. `portfolio/optimizer.py:97,411` `_PERIODS_PER_YEAR = Timeframe.H1.bars_per_year`, used for the
   `holding_bars` annualization — module constant, NOT threaded through the calendar this arc. H1 is
   correct for crypto; wrong for equities, but the equity compute path is fail-closed. **Follow-up:
   thread `periods_per_year` into the optimizer's holding-period annualizer when the equity guard is
   lifted.**
3. `data/quality/checks.py:232,463` bare `expected_bar_opens(...)` — the quality-check layer is not
   in this arc's scope and is calendar-blind for equities (reports weekends as gaps, the same class
   as the now-fixed `reader.gaps`). Crypto-identical (24/7). **Follow-up: route through
   `calendar_for(asset_class)` in the equity arc** (sibling of audit G7/P18).
4. `features/parity.py:122` `tf = ANCHOR_TIMEFRAME` and `research/ic_report.py:428` `delta =
   ANCHOR_TIMEFRAME.ms` — use the re-exported `ANCHOR_TIMEFRAME` (= `CRYPTO_PERP_SLEEVE.anchor_tf` =
   H1). For a crypto engine `ANCHOR_TIMEFRAME == engine._anchor_tf == H1`, so the parity harness is
   self-consistent and byte-identical (the deployed-path parity test is green). The parity harness
   cannot run on equity anyway (the engine guard raises). **Follow-up: resolve the anchor from the
   engine's sleeve in `parity.py`/`ic_report.py` when the equity path opens.**
5. `features/library/vol.py:60` `BARS_PER_YEAR_H1` (`sqrt(8760)` annualizers), `research/ic_report.py:91`
   `BARS_PER_YEAR = 8760.0`, `analytics/metrics.py:70,73` `DAYS/HOURS_PER_YEAR` — crypto factor
   bodies / research / metric-layer named constants; the metric layer is already
   `periods_per_year`-parameterized at call sites (audit-confirmed) and equity vol deliberately keeps
   the 8760/365 bases out (`equity_price.py:124`). Crypto-correct, not in scope.

None of (1)-(5) is reachable by a crypto numeric path in a way that differs from HEAD. The crypto
spine's grid/annualization is fully routed through the calendar; the residuals are equity-future or
crypto-correct H1 constants.

## 4. Tests — additive, crypto assertions intact

`git diff --numstat tests/`: the changes are overwhelmingly **additive** (new equity D1 session-grid
tests in `test_backtest_engine.py` +109/-3, `test_triple_barrier.py` +118/-0, `test_pit_reader.py`
+136/-0 for the corp-actions read, `test_settings.py` +9/-0). The only removals:
- `test_backtest_engine.py` -3: a `Timeframe` import hoisted to the top (cosmetic).
- `test_factors_equity_price.py` +19/-10: the **equity** feature-detect test updated from
  "raw pass-through when no CA surface" to "**fail-closed raise** when no CA getter" — the P1
  contract change. Equity-only; no crypto assertion touched.

No crypto golden/parity/contract assertion was weakened, relaxed, or deleted.

## 5. Verdict

**PASS — no crypto byte-identity regression.** The OFF==identity refactor holds: the full crypto
regression gate (golden master to-the-cent, mu contract, walk-forward equivalence, deployed-path
parity/truncation, triple-barrier, the full 2736-test non-network suite) passes UNCHANGED, ruff and
mypy --strict are clean, and the byte-identity is structural (the 24/7 calendar forwards to the same
`core.time` kernel / `tf.bars_per_year` the spine used before). The fail-closed engine guard and the
fail-closed adjusted-panel raise keep the partial equity migration loud. The residual bare constants
are all H1-correct for crypto or on a fail-closed equity path; logged as equity-arc follow-ups, none
is a crypto drift.
