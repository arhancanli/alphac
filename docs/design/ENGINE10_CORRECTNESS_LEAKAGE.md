# ENGINE10 — Correctness / Leakage Audit

Read-only audit at HEAD ~`dfdf515`. Dimension: residual lookahead / PIT / survivorship /
train-test contamination across ALL paths (crypto + the new equities sleeve).

Verdict score: **8.5 / 10** for this axis. The crypto path is essentially a 10/10 by
construction — the earlier `leakageCritique.md` findings (1–29) are, with one structural
exception, closed in code with regression coverage. The gap to a true 10/10 is concentrated
entirely in the **equities sleeve**, where a correct adjustment kernel exists but its
read-path is unwired, so the equity factors silently run on RAW, unadjusted, wrong-calendar
prices — a leakage class that is *latent* today (no equity bars ingested yet) but will be
live and silent the moment equity research runs.

A 10/10 on this axis means: **zero leakage provable by construction + a regression test on
every path.** Crypto meets that bar. Equities does not yet — the proofs and tests exist only
for the pure adjustment function, not the integrated path, and the path that would run is
provably wrong (wrong calendar) and provably unadjusted (silent fallback).

---

## What a 10/10 engine has on this axis

1. A single PIT read gate with explicit `as_of`, no `now` default, identical in backtest and
   live — and it owns availability for EVERY dataset including corporate actions.
2. Every information surface (prices, funding, quality flags, **splits/dividends**, regime
   posteriors, universe membership) carries its own `available_at` and is masked by it; no
   downstream consumer can join on the event date (`ts_funding`, `ex_date`) instead of the
   knowable date.
3. One feature framework on one calendar; positional window math (`shift(W)`) means exactly
   "W sessions" on every asset class, enforced by an asof/batch parity test **on the deployed
   path for that asset class**.
4. Survivorship-free universe seeded from a historical listing/delisting record, with a
   regression test asserting a known pre-go-live delisting appears in historical membership.
5. CV/WF embargo ≥ the dominant feature decorrelation length, or an embargo-sensitivity study
   that bounds the inflation; DSR trial-count N covers the entire selection funnel.
6. Cost-and-funding-honest, gap-aware labels; the deployment gate is the full-pipeline
   walk-forward, not label-space metrics.

The crypto sleeve hits 1, 2 (crypto surfaces), 3 (crypto), 6 cleanly. Equities breaks 1, 2,
3. Items 4/5 are partial on both. Details below, each verified against the code.

---

## GAPS (file:line, mechanism, severity, fix)

### G1 — Equity corp-actions adjustment is UNREACHABLE: factors silently run on raw, unadjusted prices. **[BLOCKER for equities; latent today]**

The adjustment kernel `adjusted_close()` is correct and unit-tested (PIT cross-row, planted
split). But the integration point feature-detects a method that **does not exist**:

- `src/alphaforge/features/library/equity_price.py:270` — `_adjusted_close_panel`:
  `ca_getter = getattr(ctx, "corporate_actions", None); if ca_getter is None: return raw`.
- `src/alphaforge/features/context.py` — `FeatureContext` has **no** `corporate_actions`
  method (verified: grep returns nothing).
- `src/alphaforge/data/store/reader.py` — `PITDataReader` has **no** `corporate_actions`
  method (verified). The write-side is fully built: `CORPORATE_ACTIONS_SCHEMA`
  (`schemas.py:300`), the Polygon fetch with correct `available_at = declaration_date + lag`
  (`polygon_source.py:644`), the CLI ingester (`data_cmds.py:483`), and the lake writer all
  exist. Only the READ side is missing.

Mechanism / risk: every equity price factor (`eq_mom_252_21`, `eq_rev_21`, `eq_lowvol_252`,
`eq_beta_252`, `eq_bab_252`, `eq_amihud_63`) calls `_adjusted_close_panel`, which today returns
RAW close. A 2:1 split prints as a -50% one-day return → a spurious reversal/momentum/vol
spike. This is not a benign approximation: it injects fabricated returns into the alpha,
risk, and beta inputs. It is the equities analogue of leakage finding 5, except worse — the
fallback is *documented as intentional* ("BUILD-ORDER GAP", lines 54–66) so it will not trip
any alarm. The module's own docstring concedes the integrated path is untested:
"`_adjusted_close_panel` feature-detects … and falls back to the raw close panel."

Why it is latent, not yet active: no equity bars are in any lake (the flat-files ingester is
"pending a data-plan upgrade"). So the silent fallback harms nothing *today*. But the instant
equity bars land and someone runs `compute_history` on equity ids, they get raw-price factors
with zero warning — the worst kind of leakage, because the code reads as "done."

Fix: build the read-path (one builder's job, explicitly deferred): add
`PITDataReader.corporate_actions(instrument_ids, *, as_of)` masking on stored `available_at`
(never `ex_date`), add `FeatureContext.corporate_actions()` that serves the `_CA_COLUMNS`
projection, and **replace the silent fallback with a fail-closed error** when an equity
(D1) context is asked for an adjusted panel but no corp-actions surface is wired. Add an
integration regression: a planted split in a real synthetic lake → `compute_history` →
assert no -50% return at the ex bar and assert pre-declaration bars are unadjusted.

### G2 — The feature engine, backtester, and labeler are hard-locked to the 24/7 H1 grid; equity D1 session-positional windows are silently wrong. **[BLOCKER for equities]**

`XNYSCalendar` exists and is correct (`core/calendar.py:177`, `periods_per_year(D1)=252`,
session-hopping `next_bar_open`/`expected_bar_opens`). It is wired into **nothing** on the
feature/backtest/label path (verified: grep `XNYS|nyse|calendar` over `features/engine.py`,
`features/context.py`, `features/parity.py` returns nothing):

- `src/alphaforge/features/engine.py:45` — `ANCHOR_TIMEFRAME = Timeframe.H1`, hard-coded; no
  calendar parameter on `FeatureEngine.__init__` (`engine.py:52`). `compute_history` builds
  its grid via the module-level 24/7 `expected_bar_opens(start, end, tf)` (`engine.py:97`).
- `src/alphaforge/features/context.py:231` — `panel()` reindexes to the 24/7
  `expected_bar_opens` grid. For D1 this includes Saturdays, Sundays, and holidays as NaN
  rows. `shift(252)` therefore reaches back 252 *calendar* days ≈ 180 sessions, not 252
  sessions; `mom_252_21` becomes a window of the wrong length.
- `src/alphaforge/backtest/engine.py:380,404,612` — engine docstring states "1h-only"; it
  builds the union grid from `ts_open + self._tf.ms` on the 24/7 step. A D1 run expects a bar
  every calendar day; weekend/holiday slots have no bar and are dropped as
  `dropped_missing_next_bar` (`engine.py:776`) — so a D1 backtest cannot fill correctly.
- `src/alphaforge/labeling/triple_barrier.py:285,329` — `_scan_one_instrument` walks
  `bar_ts = tau + (1+k)·delta` with `delta = cfg.timeframe.ms`. For D1 the weekend timestamps
  have no `pos_of` entry → `gapped=True` → NaN sentinel. Every event spanning a weekend
  (i.e. essentially all of them) becomes an unlabeled sentinel.

Verified at the source of truth — the equity factor test itself
(`tests/unit/test_factors_equity_price.py:89–98`): "the engine anchors on the crypto H1
grid … each grid slot is one session bar in these tests." The tests fabricate a contiguous
session grid (HOUR step = one session) that **no real equity lake will ever produce**, so
green tests here certify the bodies but NOT the deployed path (this is leakage finding 3's
"parity guards the wrong path" recurring for equities — the parity/truncation invariants are
proven on a grid that cannot exist).

Mechanism / risk: not a classic future-peek, but a correctness-of-information-set failure
that produces systematically wrong features and uninterpretable labels on equities, and a
research/live grid mismatch (whatever ad-hoc session grid research uses will differ from the
24/7 grid the engine actually builds). It is leakage-class because the window no longer
matches its `lookback_bars` *time* guarantee, which is the foundation the whole
parity/truncation safety net rests on.

Fix: thread an `anchor_tf` + `TradingCalendar` through `FeatureEngine` → `FeatureContext.panel`
(grid = `calendar.expected_bar_opens`) and through the backtest engine and `TripleBarrier`
(`delta`/grid hops = calendar sessions, not fixed ms). Run `verify_parity`/`verify_truncation`
on the XNYS D1 path. Until then, the equity sleeve must be flagged NOT-READY for any compute,
and `compute_history` should reject D1 specs rather than silently use the 24/7 grid.

### G3 — CPCV / walk-forward embargo (168 bars) is ~20× shorter than the slowest feature's decorrelation length (3240 bars). **[HIGH]**

- `src/alphaforge/validation/splits.py:33,134` and `validation/cpcv.py:40` — default
  `embargo_bars = 168` (7d), justified as "> 2× the 72-bar max label horizon."
- `src/alphaforge/features/library/momentum_slow.py:61` — `mom_res_2160_168` has
  `lookback_bars = 720 + max(15·168, 2160) = 3240` bars (~135 days).

Mechanism: the embargo and purge are sized for the *label horizon* (72), which correctly
prevents the label interval from straddling the test boundary. But a train sample 169 bars
after a test block computes its 90-day residual momentum and 720-bar beta almost entirely
from prices INSIDE the test block. That train/test feature dependence is not removed by
`t1`-purging (which only handles label overlap). The CPCV/WF IC and Sharpe distributions —
the inputs to PBO and to the must-beat-baseline DSR gate — are inflated for the slow factors.
This is the one design-critique finding (14) that is NOT structurally closed; the code
implements exactly the 168 default the critique flagged.

Fix: either (a) run and report an embargo-sensitivity sweep (E ∈ {168, 720, 2160, 3240}) so
the inflation is bounded and disclosed, or (b) set the embargo per-run to the dominant feature
decorrelation length when slow factors are present, or (c) restrict CPCV inference to
fast-feature models and lean on the strictly forward-chaining WF (where post-test→train
contamination cannot occur) for slow-feature configs.

### G4 — Crypto survivorship: lake seeding from a "historical archive" is asserted but the seed source is not verifiably a delisting-complete record. **[MEDIUM — verify, likely partial]**

`leakageCritique.md` finding 1 (the survivorship hole) is the most consequential historical
finding. The universe layer now genuinely supports delisted names PIT
(`data/universe/builder.py:186` closes membership at `delisted_ts`; `_close_delisted`
at `:261`; store intervals for delisted instruments are ordinary rows, `store.py:22,130`), and
the builder docstring claims seeding "from the historical archive (finding 1)". That is the
right architecture. What I could NOT verify in this read-only pass is that the *seeder* is
actually fed an archive containing pre-go-live delistings (FTTUSDT, LUNA, etc.) rather than a
live `list_instruments()`. The Vision source exists (`data/sources/vision.py`) which is the
correct historical dump, but the end-to-end "known pre-2026 delisting appears in 2021
membership" regression test the critique demanded is the proof that closes this — confirm it
exists and runs against real seed data, not a synthetic fixture.

Fix: add/confirm the explicit regression asserting a specific known delisted perp appears in
historical universe membership built from the real seed path; until proven, stamp crypto
backtest reports "universe may be survivorship-biased before <first-archive-date>."

### G5 — Equity universe survivorship depends on an equity lifecycle/SCD2 feed that is not yet populated. **[MEDIUM — latent, same shape as G4 for equities]**

`builder.py:121` filters eligibility on `delisted_ts null or > T` and reads `listed_ts`/
`delisted_ts` from the instrument store, which is PIT-correct logic. But for equities this
requires an SCD2 record for delisted tickers (the flat-files day file contains delisted names'
bars, but lifecycle dates come from `get_ticker_details`/reference data, not the bar file).
Until the equity instrument store is seeded with delisted-ticker lifecycle facts, an equity
universe built today would be survivorship-biased exactly like the original crypto hole — the
day-aggs bars are survivorship-free, but the *eligibility filter* needs the delist dates to
exclude already-dead names at past `T` and to include names that were alive then but are dead
now. This is latent (no equity universe built yet) but is the same trap as G4 and must be
proven before any equity backtest.

Fix: seed equity lifecycle (`listed_ts`/`delisted_ts`) for delisted tickers into the
instrument store; add the equity analogue of the G4 regression (a known delisted ticker, e.g.
a 2021 bankruptcy, appears in 2020 membership and is absent from 2026 membership).

### G6 — `adjusted_close` dividend anchor uses the RAW ex-open price across multiple actions; correct for back-adjustment but worth a regression. **[POLISH]**

`equity_price.py:238` anchors the dividend total-return factor on `raw_values[ex_pos, j]`
(the RAW close at the ex bar). Each action's factor is computed independently against raw
prices and multiplied (`factor[applies,j] *= div_factor`). For a sequence split-then-dividend,
the dividend's `cash/price` ratio is taken against the *raw* (unsplit) price, which is the
correct convention only if the cash amount is also in raw per-share terms (Polygon reports
`cash_amount` per as-traded share, so this is consistent). It is correct, but it is a corner
where a sign/scale slip would be silent. There is a unit test for a planted split; add one for
split-and-dividend-in-the-same-window to lock the interaction.

Fix: add a `test_adjusted_close_split_then_dividend` asserting the composed factor matches a
hand-computed expectation; no code change expected.

### G7 — Phase-8 pre-arm gates C3/C5/C7/C10 are reconciliation/durability, not data-leakage — but C3's marks are a real-vs-research divergence surface. **[MEDIUM — out of dimension except C3]**

Per `project_alphaforge_phase8_prearm_gates.md`, C3/C5/C7/C10 are execution/reconciliation
correctness (mark-time, fill discovery, reconcile-before-adopt, ack durability), unreachable
in v1 (broker is a NotArmed stub). They are blockers for live capital but mostly outside the
leakage dimension. The one with a leakage flavor is **C3**: reconcile marks broker equity at
`fills[-1].ts` but the book at `floor_bar(now)`; on a live moving book these timestamps differ,
so the equity comparison mixes information from two instants. That is an information-set
inconsistency (the same class as a one-bar join skew) and should be closed with a shared
`account_at(as_of)` timestamp before arming. Confirm C3 is on the pre-arm checklist (it is).

---

## What is genuinely 10/10 (verified, not assumed)

- **PIT reader** (`reader.py`): explicit `as_of`, no `now` default; OHLCV visible iff
  `ts_open + Δ <= as_of`; **per-bit quality-flag availability masking** with fail-closed
  undeclared bits (finding 5 closed, `reader.py:64`); funding masked on stored `available_at`
  never `ts_funding` (finding 18 closed, `reader.py:152`). In-memory DuckDB query-only; `.tmp`
  files structurally invisible.
- **Funding cost honesty** (findings 6/3): interval-aware annualization `8760/interval_hours`
  from SCD2 (`features/library/carry.py:8,87`); backtest applies funding by iterating the
  **stored events table**, not a clock (`backtest/engine.py:14,620`, `ledger.py:46,246`); the
  clock helper is COUNT-only and refuses non-divisors of 24 (`calendar.py:75`).
- **Triple-barrier labels** (findings 11/24/17): cost-honest net return via the shared
  `TransactionCostModel`, gap-aware stop fills (worse of {barrier, open}), PT fills AT the
  limit, vertical exit at next open never `C_{t+H}`, funding counted on
  `[entry, t1)` half-open, `f̂` from last-published rate (`triple_barrier.py:22-73,350-393`).
- **HMM regime gate** (finding 13): FILTERED posteriors only (no smoothing reaches `G`),
  explicit `available_at`, `lag_days=1` so day-D uses through day-(D-1) close
  (`regime/hmm.py:17,124,597,626`).
- **Single feature framework** (finding 3): `SignalService` consumes the one `FeatureEngine`
  (`signals/service.py:50,219,234`) — no parallel buffer/pipeline; parity is the deployed
  contract for crypto.
- **One purged splitter** (finding 16): `PurgedWalkForward` shared by CV and the WF analytics
  (`analytics/walkforward.py:98`), `purge_bars = settings.signals.horizon_bars` asserted from
  one constant; uniform-grid assertion guards bar-count semantics (`splits.py:182`).
- **Next-open fills** with a `LookaheadError` tripwire when `next_bar.ts_open <
  order.decision_ts` (`backtest/fills.py:156`) — same-bar fill is structurally impossible
  (finding 4 closed for the truth engine).
- **Must-beat-baseline gate** well-formed: `dsr>=0.95 AND dsr>baseline.dsr AND
  sr_ann>baseline.sr_ann`, strict, on identical purged legs (`walkforward.py:502`).

---

## The corner that separates 9 from 10

The crypto engine is a 10/10 on leakage. The equities sleeve ships a **correct adjustment
function and a correct calendar that are wired into nothing**, behind a *documented silent
fallback* — so the system reads as complete while the deployed equity path would (a) use raw
unadjusted prices and (b) use the wrong (24/7) calendar grid, with green tests that run on a
synthetic grid no real lake produces. A 10/10 does not allow a leakage-bearing path to exist
behind a `getattr(...) is None` fallback; it fails closed and proves the integrated path with
a regression. Close G1 + G2 (wire the read-path and the calendar, replace the fallback with a
fail-closed error, add integrated regressions), bound G3's embargo, and prove G4/G5
survivorship end-to-end — then the equities path reaches the crypto path's bar and the engine
is a 10/10 on this axis.
