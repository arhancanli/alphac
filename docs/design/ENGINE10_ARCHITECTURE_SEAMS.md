# ENGINE10 — Architecture-Seams Audit

**Dimension:** Architecture-Seams — multi-asset generality, seam cleanliness, config
discipline, one-of-everything-integrity-critical, documentation.
**Verdict:** 7.5 / 10. The *design intent* of asset-class agnosticism is genuinely
present (the `Instrument` model, the `TradingCalendar` abstraction with `calendar_for`,
the `DataSource` ABC, the SCD2 store, the generic seeder, the `tf`-parameterized
backtest engine, the `periods_per_year` annualization plumbing). But the equities sleeve
is **wired from both ends with the middle wires missing**, and — more seriously — the
*engine spine* (the feature panel, the signal service, the portfolio strategy, the
walk-forward harness) is hard-pinned to the 24/7 / 1h crypto grid in several
integrity-critical seams. Today, adding the equities sleeve **does** require forking the
engine: a separate D1 pipeline cannot be driven through `FeatureEngine`/`SignalService`
as written, and equity factors silently run on a calendar-blind grid and on
**unadjusted** prices. A 10/10 adds a sleeve by registering a calendar + a source + a
cost provider and changing no engine code.

Audited at HEAD `dfdf515`. Read-only; no source modified.

---

## 1. What a 10/10 engine has on this axis

1. **One calendar seam, consulted everywhere a time-grid or annualization is built.**
   No module ever calls a bare 24/7 grid kernel or hard-codes `8760`/`365`/`252`; every
   grid comes from `calendar_for(asset_class).expected_bar_opens(...)` and every
   annualization from `calendar.periods_per_year(tf)`. A new session calendar (XNAS, LSE,
   TSE) is registered once and the whole stack — features, covariance, Sharpe,
   walk-forward purge/embargo — follows.
2. **An asset-class-parameterized anchor.** The feature/signal/sizing layer is not nailed
   to one timeframe; the "anchor timeframe" and the bars-per-year are per-sleeve, threaded
   from config, not a module-level `Final` constant.
3. **A complete, symmetric read path.** Anything that can be *ingested* can be *read PIT*
   and *served to features* through the same generic surface. No dataset is writable but
   unreadable.
4. **One cost model that spans the asset classes it claims to support** — perp funding,
   equity borrow/locate fees for shorts, commissions, all behind one interface; the
   instrument record carries the fields each class needs.
5. **A wiring factory / sleeve registry** so "run crypto at H1 and equities at D1" is a
   config + registry concern, not a code edit. One config object can describe N sleeves.
6. **Storage and read paths that scale to the breadth roadmap** (thousands of names):
   columnar batch reads, not one-file-per-instrument SQL literals.
7. **Documentation that states the seam contracts and — crucially — the *current* wiring
   gaps** so an operator never mistakes "the kernel exists" for "the path is live."

---

## 2. Concrete gaps in OUR engine

### G1 — The feature panel (THE sanctioned window-math surface) is calendar-blind. `BLOCKER` for equities
`FeatureContext.panel()` builds its reference grid with the bare 24/7 kernel:
`grid = expected_bar_opens(self._start, self._end, tf)`
(`src/alphaforge/features/context.py:231`; same in `compute_history`,
`src/alphaforge/features/engine.py:97`). `FeatureContext.__init__`
(`context.py:106-129`) takes **no `asset_class` and no calendar**. For an equity D1 read
this grid includes every weekend/holiday slot as a NaN row, so `adj_close.shift(252)` in
the equity factors (`features/library/equity_price.py:302`, `reversal`/`xs_momentum`/
`realized_vol`/`beta`) shifts across ~365 *calendar-day* slots, not 252 *sessions*. The
factor docstrings explicitly claim "computed positionally on the complete grid (`shift` is
an exact time op)" and "252 sessions" (`equity_price.py:296,310-318`) — that contract is
**false** on the 24/7 grid. Every rolling-window equity factor computes the wrong window.
This is the single most important seam break: the layer that promises "row position ==
time slot" is built on the wrong notion of "time slot" for equities.

**Why it's a blocker, not polish:** it is silent and wrong, not loud and missing. A
12-1 momentum (`eq_mom_252_21`) would mix in weekend NaNs and span the wrong horizon; the
values look plausible and pass schema checks.

### G2 — Equity factors run on UNADJUSTED prices: the corporate-actions read wire is missing. `BLOCKER` for equities
The corporate-actions seam is built from both ends but the middle is absent:
- **Ingest end exists:** `CORPORATE_ACTIONS_SCHEMA` (`data/schemas.py:300`), writer key
  (`data/store/writer.py:60`), `PolygonEquitiesSource.fetch_corporate_actions`
  (`data/sources/polygon_source.py:590`), CLI `_ingest_corporate_actions`
  (`cli/data_cmds.py:483-526`).
- **Adjustment kernel exists and is tested:** `adjusted_close(...)`
  (`features/library/equity_price.py:143-250`) — a correct per-row PIT total-return
  reconstruction.
- **The read wire is MISSING:** there is **no `corporate_actions` read method on
  `PITDataReader`** and **no `corporate_actions()` method on `FeatureContext`** (verified:
  zero hits for `corporate_actions` in `reader.py`/`context.py`). `_adjusted_close_panel`
  feature-detects `getattr(ctx, "corporate_actions", None)`
  (`equity_price.py:270-273`) — which is always `None` — and falls through to the **raw**
  close panel.

Consequence: every equity price factor today consumes split- and dividend-**unadjusted**
prices. A 2:1 split prints as a −50% one-day return; a 4:1 as −75%. This poisons momentum,
reversal, vol, and beta. The code comment calls this a "forward-compatible feature-detect"
(`equity_price.py:263-267`), i.e. it is a *known* deferred wire — but until the
`reader.corporate_actions → ctx.corporate_actions` path lands, the equity factor library
is non-functional on real splits.

### G3 — The anchor timeframe is a hard-pinned module constant; the signal/sizing spine is H1-only. `BLOCKER` for equities
`ANCHOR_TIMEFRAME: Final[Timeframe] = Timeframe.H1` (`features/engine.py:45`).
`FeatureEngine.compute_history`/`compute_asof` pin `tf = ANCHOR_TIMEFRAME`
(`engine.py:87,126`) and take **no `asset_class`**. The entire `SignalService` pins to it:
the Grinold sizer (`signals/service.py:165`), the decision-bar floor
(`service.py:214`), forward returns (`service.py:247`), the IC grid step
(`service.py:254`), the blend-weight estimator (`service.py:261`). The μ contract is
written `mu_ann = mu_h · (8760/h)` (`signals/__init__.py:9`, `signals/sizing.py:11,86`)
with `bars_per_year` taken from `self.timeframe.bars_per_year` (`sizing.py:87`) — which is
365 for D1, **not** the equity 252. So even a separate D1-configured run cannot drive the
feature→signal→sizing chain without code changes: the anchor, the annualizer, and the IC
horizon are all crypto-1h. This is the structural reason the engine **must be forked** to
add the equities sleeve as it stands.

### G4 — Cost-honest backtester warmup is hard-pinned to 24/7/1h; no equity cost provider exists. `HIGH`
The backtest engine is the *most* generalized component — it takes `tf`
(`backtest/engine.py:529`), validates `tf`-alignment (`engine.py:588`), and accepts an
injectable `cost_inputs` provider (`engine.py:531`) with an explicit guard that the
default is 1h-only (`engine.py:547-551`). Good seam. **But:** the default
`LakeCostInputs` warmup hard-codes `Timeframe.H1` (`engine.py:401`), `BARS_PER_DAY = 24`
(`engine.py:387`), `WARMUP_MS = 33 days`, and the bare 24/7 grid
`expected_bar_opens(read_start, end, self._tf)` (`engine.py:404`). No equity
`CostInputProvider` exists anywhere in the tree (verified). So a real equity backtest
needs a not-yet-built provider, and the only built one leaks the 24/7 grid.

### G5 — Portfolio strategy covariance panel + realized-vol annualizer are 24/7-hardcoded. `HIGH`
`BlendStrategy._close_panel` builds the covariance input grid with the bare kernel
`expected_bar_opens(ctx.ts - window·ctx.tf.ms, ctx.ts, ctx.tf)`
(`portfolio/strategy.py:527`) — for equity D1 this is again a calendar-day grid with
weekend NaNs feeding EWMA+Ledoit-Wolf covariance. `_realized_vol_ann` annualizes with
`np.sqrt(tf.bars_per_year)` (`strategy.py:564`) = √365 for D1, not the equity √252; same
in the overlay (`portfolio/overlay.py:15,53`). The covariance *annualizer* in
`covariance.annualize_cov` is correctly parameterized (`portfolio/covariance.py:268`), but
its caller passes `tf.bars_per_year` (`strategy.py:463`) rather than
`calendar.periods_per_year(tf)`, re-introducing the 24/7 number.

### G6 — Walk-forward CV harness grid + purge/embargo are calendar-blind. `HIGH`
`WalkForwardRunner` builds its grid with `expected_bar_opens(start, end, tf)`
(`analytics/walkforward.py:743`) and `PurgedWalkForward` measures train/test/embargo in
`tf`-bar counts. On equities the embargo/purge gap straddles weekend NaN slots, so a
"72-bar" purge is not 72 sessions. The validation arsenal (Deflated/Probabilistic Sharpe,
PBO, CPCV) is `periods_per_year`-parameterized at the metric (`validation/dsr.py:232`,
`analytics/metrics.py`) — good — but the *splitter geometry* is bar-count, calendar-blind.

### G7 — `PITDataReader.gaps` uses the 24/7 kernel, not the asset calendar. `MEDIUM`
`reader.py:227` (`gaps`) calls `expected_bar_opens(start, end, tf)` directly. For an
equity D1 series this reports every weekend/holiday as a "gap," so the gap/backfill tool
is unusable for equities exactly as the docstring on `core/calendar.py:177-196`
(`XNYSCalendar` "THE BAR/AVAILABILITY BOUNDARY") warns against: "Anything doing
`ts + tf.ms` to find the next equity bar is a bug." The reader is that anything. Note this
is *inconsistent* with the labeling layer, which **does** consult the calendar correctly
(`labeling/triple_barrier.py:534` uses `calendar_for(inst.asset_class)`). The engine has a
clean calendar seam in one place and bypasses it in the spine.

### G8 — No equity-short cost (borrow / locate) anywhere; `Instrument` lacks the field. `HIGH` (before any equity short capital)
`Instrument` carries `can_short: bool` but **no `borrow_fee_bps` / hard-to-borrow / locate
fields** (`core/instruments.py:50-81`); a grep for `borrow|short_fee|locate|htb` across
`src/` finds nothing. Equity shorts pay a daily borrow rate (often the dominant cost for
small/illiquid names) and require locates. The "cost-honest" claim — true for perp funding
(modeled as event funding) — does not yet extend to the equity short leg. A long/short
equity sleeve would systematically overstate short-side returns. This is the equity
analogue of the perp-funding integrity work and must exist before any equity short
exposure.

### G9 — Config is mono-sleeve; no `AssetClass` / multi-sleeve concept. `MEDIUM`
`AppConfig` has a single `DataCfg` (`config/settings.py:74`) with one `exchange`
(default `binanceusdm`) and one `timeframe` (default `H1`), and the tuning constants are
expressed in 1h bars (`QualityCfg.ewma_span_bars = 168 = 7 days` of 1h bars
`settings.py:165`; `SignalsCfg.horizon_bars = 72` `settings.py:181`; the quality
`outlier_k` doc is "crypto 1h returns" `settings.py:149`). There is no `asset_class`
field and no way to describe "a crypto sleeve at H1 AND an equity sleeve at D1" in one
config — you would maintain two configs and two pipelines. There is no wiring factory /
sleeve registry; the CLI assembles the chain ad hoc per command. A 10/10 has a sleeve
registry keyed on `AssetClass` that yields `(calendar, anchor_tf, source, cost_provider,
factor set)`.

### G10 — Per-instrument lake partitioning + one-`read_parquet`-literal reads won't scale to thousands of names. `MEDIUM`
The reader assembles a Python list of one Parquet leaf per `(instrument, year)` and
inlines it into a single `read_parquet([...])` SQL literal
(`reader.py:54-61, 124-133, 242-260`) with a `list_contains(?::VARCHAR[], instrument_id)`
predicate. For ~20 perps × a few years this is tens of files. For the breadth roadmap
(thousands of equity names × 20 years) this becomes a `read_parquet` literal with
tens-of-thousands of paths per query, plus a per-instrument lake directory explosion
(`LakePaths.partition_paths`). The PIT/DuckDB design is sound; the *physical layout and
fan-out* are tuned for the 20-name crypto case and have not been validated for breadth.
A 10/10 either partitions by `(asset_class, date)` panel files (the equity day-aggs are
already panel files — see `EquitiesFlatFilesJob`) or batch-globs, not name-by-name.

### G11 — Calendar registry is asset-class-keyed, not exchange-keyed. `MEDIUM`
`calendar_for(asset_class)` (`core/calendar.py:287`) maps **all** `EQUITY` to the single
`XNYSCalendar`. The breadth roadmap (cross-listings, XNAS vs XNYS half-days, LSE/TSE) needs
a calendar per *listing venue* (the MIC is already in the instrument id via
`equity_instrument_id(mic, ticker)`, `core/symbols.py:118`). The seam is one level too
coarse: it should key on the venue/MIC, falling back to an asset-class default. Today every
US equity is forced onto NYSE sessions, which is wrong for Nasdaq-specific half-day
schedules and for any non-US listing.

### G12 — Equities ingest watermark does not advance on a legitimately-empty session. `POLISH`
`EquitiesFlatFilesJob._process_day` only calls `checkpoints.set(...)` when `tickers > 0`
(`data/ingest/equities.py:301-303`). A session that parses to zero rows never advances the
day watermark, so it is re-listed and re-fetched on every subsequent run (cost/noise, not
corruption). Minor, but it breaks the "resume = skip everything ≤ watermark" invariant the
module docstring promises.

### G13 — Documentation does not flag the live wiring gaps. `MEDIUM` (documentation axis)
The design docs (`EQUITIES_SLEEVE.md`, `EQUITIES_CRITIQUE.md`, `EQUITIES_INGEST.md`) and the
in-code docstrings describe the *intended* seams beautifully and even pre-document the
deferred CA wire (`equity_price.py:263-267`). But there is no single "equities sleeve
readiness / what is NOT yet wired" status doc, so the gap between "kernel exists + tests
pass" and "an equity backtest is correct end-to-end" (G1, G2, G3) is invisible to an
operator reading the green test suite. The 24/7-grid leaks (G1/G5/G6/G7) are *contradicted*
by the calendar module's own docstring warnings — a 10/10's docs and code agree.

---

## 3. The concrete fixes

- **G1/G7 (calendar-aware grid seam):** Give `FeatureContext` and `PITDataReader.gaps` an
  `asset_class` (or a `TradingCalendar`) and replace every bare
  `expected_bar_opens(...)` in the read/feature/strategy/walk-forward spine with
  `calendar_for(asset_class).expected_bar_opens(...)`. The `XNYSCalendar` already
  implements this correctly; it is a threading job, not new logic. Add a parity test that
  an equity D1 panel has exactly session rows (no weekend NaNs).
- **G2 (CA read wire):** Add `PITDataReader.corporate_actions(ids, start, end, as_of)`
  joining on the stored `available_at` (the `FUNDING` PIT pattern), and a
  `FeatureContext.corporate_actions()` that serves it in `_CA_COLUMNS` shape. The factor
  side already consumes it via feature-detect — no factor change needed once the method
  exists. This is the highest-leverage single fix: it turns the entire equity factor
  library from wrong to correct.
- **G3 (anchor):** Replace the module-level `ANCHOR_TIMEFRAME` with a per-engine /
  per-sleeve anchor timeframe threaded from config, and take `bars_per_year` /
  `periods_per_year` from `calendar_for(asset_class)` in the sizer and IC machinery
  instead of `timeframe.bars_per_year`.
- **G4:** Build an equity `CostInputProvider` (ADV + daily sigma from D1 bars, calendar
  grid) and parameterize `LakeCostInputs`' `BARS_PER_DAY`/`WARMUP`/grid off the calendar.
- **G5/G6:** In `BlendStrategy` and `WalkForwardRunner`, source the grid and the
  annualizer from the calendar (pass `calendar.periods_per_year(tf)` into `annualize_cov`
  and `_realized_vol_ann`; build the cov/CV grids via the calendar). Express purge/embargo
  in sessions for equities.
- **G8:** Add `borrow_fee_bps` (and an optional HTB/locate flag) to `Instrument` and a
  daily borrow accrual in the cost model for short equity positions, mirroring the perp
  event-funding leg.
- **G9:** Introduce an `AssetClass`-keyed sleeve registry that yields
  `(calendar, anchor_tf, source, cost_provider, factor set)`; let `AppConfig` hold a list
  of sleeves. Re-express bar-count tuning constants as durations so they are calendar-
  portable.
- **G10:** Validate the lake layout at breadth: partition the equity sleeve by
  `(date)` panel files (the ingester already produces day panels) or batch-glob, and
  benchmark `PITDataReader.ohlcv` for a 1000-name read before any equity scale-up.
- **G11:** Re-key `calendar_for` on the listing venue/MIC with an asset-class default.
- **G12:** Advance the day watermark on an empty-but-processed session.
- **G13:** Add an `EQUITIES_READINESS.md` (or a section in the sleeve doc) enumerating the
  *live wiring* state vs the *kernel/test* state, explicitly listing G1/G2/G3 as the gates
  before any equity backtest is trustworthy.

---

## 4. What is genuinely 10/10 already (so the fixes don't regress it)

- **`Instrument` / `core/types`** — frozen, slotted, kw-only, SCD2-versioned, unit-
  documented; `AssetClass`/`MarketType` taxonomy and `contract_multiplier`/
  `funding_interval_hours` invariants are clean multi-asset foundations
  (`core/instruments.py`, `core/types.py`).
- **Symbol identity seam** — the equity collision-free id (`equity_instrument_id` /
  `parse_equity_id` with the synthetic-quote, fixed-length strip, and the loud rejection
  of routing an equity id through `to_ccxt`) is exactly the right kind of seam discipline
  (`core/symbols.py:117-198`).
- **`TradingCalendar` ABC + `calendar_for`** — the abstraction is correct; the *problem is
  that the spine bypasses it*, not the abstraction itself (`core/calendar.py`).
- **`DataSource` ABC + generic `InstrumentSeeder`** — the survivorship merge correctly
  no-ops for a survivorship-free equity source (`data/ingest/seed.py`); the source
  interface is genuinely asset-agnostic (`data/sources/base.py`).
- **`UniverseBuilder`** — properly parameterized (`rank_tf=D1` ADV pass-through), PIT,
  survivorship-free, deterministic (`data/universe/builder.py`).
- **Backtest engine cost-input *seam*** — injectable `CostInputProvider` + `tf` parameter
  is the right shape (`backtest/engine.py:326-360,531`); only the default provider and the
  upstream strategy are pinned.
- **Annualization is parameterized at the metric layer** (`periods_per_year` in
  `analytics/metrics.py`, `validation/dsr.py`, `portfolio/covariance.py`); the leak is
  only at the *callers* that pass `tf.bars_per_year` instead of the calendar value.

The engine is one disciplined refactor — thread `asset_class`/calendar through the
feature→signal→portfolio→walk-forward spine, finish the CA read wire, add the equity cost
provider and borrow leg — away from being able to add a sleeve without a fork. The seams
are designed; several are simply not yet *used* by the spine.
