# AlphaForge — Equities Sleeve Foundation (build-ready spec)

Status: ARCHITECT spec, key-gated build. Provider = **Polygon.io** (survivorship-free,
no KYC). The concrete fetch is structured to Polygon's documented REST API but is NOT
wired to the network here — every test uses synthetic/fixture payloads, exactly as
`tests/unit/test_ccxt_source.py` drives `CCXTDataSource` with canned Binance arrays. The
moment a `POLYGON_API_KEY` lands, the same adapter validates live and the equities panel
runs through the identical gauntlet that found crypto-alone a NULL (DSR 0.21, PBO 0.88).

This document pins exact module/class/function names, signatures, windows, the
split/dividend adjustment contract, the survivorship/delisting handling, the PIT mapping,
and the parity/truncation-invariance test plan. It **matches the existing seams** — it
does not fork them. Read alongside: `data/sources/base.py` (the `DataSource` ABC),
`data/schemas.py` (the lake contract), `data/store/reader.py` (the ONE PIT read path),
`data/universe/builder.py` (the PIT survivorship-free universe), `core/calendar.py` +
`core/time.py` (the timeframe/calendar contract), and `features/{spec,registry,context,
cross_section,parity}.py` + `features/library/*` (the factor framework).

Guiding constraint (from the crypto sleeve, do not relitigate): the engine is
multi-asset *by interface*. Equities plug in by (a) adding asset-class enum members, (b)
implementing the `DataSource` ABC for Polygon, (c) registering a real `TradingCalendar`,
(d) widening `calendar_for`, and (e) registering daily-bar factors through the *same*
`@feature` decorator. No engine, reader, writer, schema, optimizer, or backtest changes.

---

## 0. What is genuinely new vs reused

| Concern | Crypto today | Equities (this spec) |
|---|---|---|
| Vendor adapter | `CCXTDataSource(DataSource)` | `PolygonEquitiesSource(DataSource)` — same ABC |
| Settlement leg | funding (`fetch_funding`) | **corporate actions** (splits + dividends) → adjustment factors |
| Calendar | `Always24x7Calendar` | `XNYSCalendar(TradingCalendar)` — sessions filter the grid |
| Native timeframe | 1h (`Timeframe.H1`) | **1d** (`Timeframe.D1`) primary; intraday post-v1 |
| Universe ranking | 30d median daily quote-volume, monthly | top-N by **ADV (dollar)**, monthly — same builder |
| Survivorship | Binance Vision archive + SCD2 | **Polygon delisted-tickers** record + SCD2 |
| Lake schema | `OHLCV_SCHEMA` / `UNIVERSE_SCHEMA` | **unchanged** (+ one new `corporate_actions` dataset) |
| Factor framework | `@feature` PIT fns, winsor→z, parity | **unchanged**; new daily-bar bodies |

Everything in the "unchanged" rows is a hard constraint: any diff to `schemas.py`,
`reader.py`, `cross_section.py`, `engine.py`, `parity.py`, `spec.py`, `registry.py` is a
design smell and must be justified, not assumed.

---

## 1. Equity DataSource — Polygon adapter

### 1.1 Enum + identity additions (the only `core/` edits)

`core/types.py` — extend the two enums (additive; no behavior change for crypto):

```python
class AssetClass(StrEnum):
    CRYPTO_PERP = "crypto_perp"
    CRYPTO_SPOT = "crypto_spot"
    EQUITY = "equity"          # already present

class MarketType(StrEnum):
    PERP = "perp"
    SPOT = "spot"
    CASH = "cash"             # NEW: US cash equities segment
```

Canonical `instrument_id` for equities (round-trips through `SymbolMapper`):

```
"<EXCHANGE>:CASH:<TICKER>"     e.g. "XNAS:CASH:AAPL", "XNYS:CASH:BRKB"
```

- `EXCHANGE` = the listing MIC (`XNAS`, `XNYS`, `ARCX`, `BATS`) — Polygon's
  `primary_exchange`. Using the MIC (not "POLYGON") keeps identity vendor-neutral: a
  second equities vendor later maps to the same id.
- `TICKER` = Polygon ticker, uppercased, dots normalized to a separator-free form.
  **Decision:** dotted/class tickers (`BRK.B`) canonicalize to `BRKB` in the id and
  carry the raw vendor ticker (`BRK.B`) in `Instrument` for the fetch round-trip.

`core/symbols.py` — `Instrument.__post_init__` reconstructs the exchange symbol from
`base+quote`. Equities have no quote currency, so:

- Add `SymbolMapper.equity_instrument_id(mic: str, ticker: str) -> str` and
  `parse_equity_id` helpers, **OR** (preferred, less surface) generalize the existing
  base/quote check: for a `CASH` market the `Instrument` sets `base=<ticker>`,
  `quote="USD"`, and `KNOWN_QUOTES` already contains `"USD"`, so `AAPLUSD` splits to
  `("AAPL", "USD")` and the existing `__post_init__` invariant holds **with zero new
  code** if the canonical symbol is stored as `<TICKER>USD`.
  **Chosen approach:** store the canonical exchange-symbol as `<TICKER>USD`
  (`"XNAS:CASH:AAPLUSD"`), `base=<TICKER>`, `quote="USD"`. This reuses
  `split_exchange_symbol` and the `base+quote` reconstruction check verbatim. The raw
  vendor ticker (`AAPL`, `BRK.B`) is recovered by the source from a `vendor_ticker`
  lookup it owns (mapping built in `list_instruments`), never re-derived from the id.

`Instrument` gets two equity-only conventions, no new fields (the model already fits):

- `market_type=MarketType.CASH`, `asset_class=AssetClass.EQUITY`.
- `funding_interval_hours=None` (already required for non-perp; the `__post_init__`
  branch enforces it).
- `tick_size=0.01` (penny tick; sub-dollar names use 0.0001 — Polygon does not expose a
  per-symbol tick, so this is a documented default, like the crypto fee defaults).
- `lot_size=1.0`, `min_qty=1.0`, `min_notional=0.0`, `can_short=True`,
  `maker_fee_bps`/`taker_fee_bps` = a documented default (e.g. 0.0 commission +
  separate cost model; SEC/TAF handled in `costs/`), `contract_multiplier=1.0`.
- `listed_ts` = Polygon `list_date`; `delisted_ts` = Polygon `delisted_utc`
  (None while active). **This is the survivorship spine** (§1.4).

### 1.2 Module + class skeleton

New file: `src/alphaforge/data/sources/polygon_source.py`

```python
class PolygonEquitiesSource(DataSource):
    name: str  # "polygon.equities"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        rate_budget: RateBudget | None = None,
        client: PolygonClientProtocol | None = None,
        adjustment: Adjustment = Adjustment.SPLIT_ONLY,
    ) -> None: ...
```

- `client` is the seam tests inject (a fake returning canned dict payloads — same
  pattern as the ccxt fake). `api_key=None` + `client=None` raises `ConfigError` (no
  silent unauthenticated calls). Construction does **no** I/O.
- `PolygonClientProtocol` (a `typing.Protocol` in the same module) declares the exact
  REST methods the adapter calls, so the fake is structurally typed and mypy-strict:
  - `get_aggs(ticker, *, multiplier, timespan, from_ms, to_ms, adjusted, limit) -> Mapping`
  - `list_tickers(*, market, active, date, limit, cursor) -> Mapping`
  - `get_ticker_details(ticker, *, date) -> Mapping`
  - `list_splits(*, ticker, execution_date_lte, limit, cursor) -> Mapping`
  - `list_dividends(*, ticker, ex_date_lte, limit, cursor) -> Mapping`
- `rate_budget` metered exactly like `CCXTDataSource._acquire` (Polygon's free tier is
  5 req/min; paid tiers higher — the budget is the throttle).
- Reuse `data/ingest/retry.py` (`transient_retry`, `RateBudget`) unchanged. Transient
  set = Polygon 429 + 5xx + network timeouts; 401/403/`BadTicker`/4xx-other propagate.

### 1.3 The three `DataSource` methods (Polygon endpoint mapping)

**`list_instruments(*, as_of) -> list[Instrument]`** — `GET /v3/reference/tickers`
- Pull BOTH `active=true` AND `active=false` (delisted) sets so the historical universe
  is survivorship-free (§1.4). Paginate via `next_url`/`cursor` until exhausted.
- `market="stocks"`, `type` in the common-equity set (`CS`, `ADRC`; document the
  filter — ETFs/warrants/units excluded in v1, like crypto's USDT-perp-only filter).
- For each ticker, `GET /v3/reference/tickers/{ticker}?date=...` enriches `list_date`
  (→ `listed_ts`), `delisted_utc` (→ `delisted_ts`), `primary_exchange` (→ MIC),
  `composite_figi` (stored for cross-vendor identity later). Build the
  `instrument_id ↔ vendor_ticker` map here.
- Sort by `instrument_id` (matches `DataSource` contract). Stamp `as_of` exactly like
  `CCXTDataSource` (SCD2 versioning + fallback `delisted_ts`).
- **Survivorship warning docstring** mirrors `CCXTDataSource.list_instruments`: the live
  endpoint alone is biased; the delisted set is what makes it whole.

**`fetch_ohlcv(instrument_id, *, tf, since, until, now=None) -> pa.Table`** —
`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`
- `tf=Timeframe.D1` → `multiplier=1, timespan="day"`. (Intraday `H1`/`H4` are post-v1;
  raise `NotImplementedError` for non-D1 in v1 so an accidental intraday equity fetch
  fails loud rather than returning mis-aligned bars.)
- **Adjustment contract (the core equities difference):**
  - Call with `adjusted=false` to get **RAW** OHLCV (as-traded prices/volume). This is
    what we store in the lake's `OHLCV_SCHEMA` — raw is never mutated, exactly like the
    crypto "raw bars as stored" rule (dataDesign.md §0.5).
  - Split/dividend adjustment is **NOT baked into the stored bars.** It is reconstructed
    PIT from the separately-stored `corporate_actions` dataset (§1.5) at *feature* time,
    so a backtest at decision `T` sees only the adjustment factors knowable by `T`. This
    is the equities analogue of funding's `available_at` discipline: applying a split
    factor announced/effective after `T` is the exact same lookahead bug as joining a
    funding rate on `ts_funding`.
  - Rationale for raw-in-lake + PIT-adjust-at-read (vs storing adjusted bars): Polygon's
    `adjusted=true` series is adjusted **to today** — re-running it next year silently
    rewrites history the moment a new split lands. Storing raw + a versioned actions
    table makes the lake immutable and the adjustment reproducible/PIT (the same reason
    the universe table is derived-and-regenerable, not the source of truth).
- Bar timestamp: Polygon agg `t` is the window-**open** epoch-ms (UTC) for daily bars =
  the session date at 00:00 UTC. We label `ts_open` = that value; PIT availability is
  `ts_open + tf.ms` = next-day boundary, which the reader already enforces. (A daily bar
  for session date D is available the instant the session closes; `available_at` =
  `ts_open + 1d` is conservative by < a session and costs nothing at daily frequency —
  documented, same spirit as funding's 5-min lag.)
- Map: `o/h/l/c` → OHLC, `v` → `volume` (shares), `vw*v` or Polygon `vw` → derive
  `quote_volume` = dollar volume (`vw * v` when `vw` present, else `c * v` fallback,
  documented), `n` → `n_trades`. `quality_flags=0`, `ingested_at=now_ms()`.
- **No partial bars, ever:** drop any row with `ts_open + tf.ms > (now or wall clock)`
  — verbatim the `CCXTDataSource` guard. Strictly-increasing `t` check → `SchemaError`
  on non-monotonic payloads.
- `validate_table(table, Dataset.OHLCV)` before return (same as crypto).

**`fetch_funding(...)` is the wrong leg for equities.** The ABC requires three methods.
Options, pick one and document it loudly:
- (Chosen) Keep `fetch_funding` on the ABC; `PolygonEquitiesSource.fetch_funding` raises
  `NotImplementedError("equities have no funding; use fetch_corporate_actions")`. This
  preserves the crypto ABC untouched and is honest — an equity has no funding leg.
- Add a NEW method `fetch_corporate_actions(instrument_id, *, since, until) -> pa.Table`
  (NOT on the ABC; an equities-source-specific method, analogous to how
  `CCXTDataSource` has the private `_funding_intervals_map`). The ingest pipeline
  dispatches on `asset_class` to call the right settlement-leg method. Conforms to the
  new `CORPORATE_ACTIONS_SCHEMA` (§2).
  - Splits: `GET /v3/reference/splits` — `execution_date` (effective/ex-date),
    `split_from`/`split_to` → adjustment ratio `split_to/split_from`.
  - Dividends: `GET /v3/reference/dividends` — `ex_dividend_date`, `cash_amount`,
    `record_date`, `pay_date`, `declaration_date`.
  - **PIT stamping:** each action row carries `available_at` = the date the action was
    *knowable* (split `declaration_date` if present, else `execution_date`; dividend
    `declaration_date` else `ex_dividend_date`) + a publication lag (default 1 day,
    `CA_PUBLICATION_LAG_MS`, mirroring `FUNDING_PUBLICATION_LAG_MS`). The adjustment
    join at read time uses `available_at`, never the ex/effective date — same finding-18
    discipline.

### 1.4 Survivorship — the regression-test discipline (mirrors FTT/LUNA)

The crypto sleeve proves survivorship-freedom with `test_universe_builder.py
::test_mid_month_delisting_closes_at_delisted_ts` (FTT delisted 2022-11-10 still appears
in the historical universe, interval closed at `delisted_ts`). The equities sleeve must
have the byte-for-byte analogue:

- **`PolygonEquitiesSource.list_instruments` MUST return delisted tickers** (the
  `active=false` page). A known pre-period delisting — e.g. **LEHMQ** (Lehman, delisted
  2008) or a recent fixture delisting — must appear in the returned list with
  `delisted_ts` set, so when seeded into the SCD2 store the `UniverseBuilder` ranks it
  while it lived and closes its membership interval at `delisted_ts`.
- Regression test `tests/unit/test_polygon_source.py::test_delisted_ticker_survives`:
  feed the fake client a delisted ticker, assert the built `Instrument` has the right
  `delisted_ts` and that a `UniverseBuilder.rebuild` over a window spanning the delist
  produces a closed interval (`reason="delisted"`) at exactly `delisted_ts` — the same
  assertion shape as the FTT test.

### 1.5 PIT mapping (epoch-ms / ts_open / available_at — unchanged contract)

- All boundary timestamps are integer epoch-ms UTC (`core.time.Ms`). Polygon returns
  ms for aggs and ISO dates for reference data; convert at the edge with
  `parse_utc`/`to_ms` (session dates → 00:00 UTC).
- A decision at session close `T` may use only records with `available_at <= T`:
  - bars: `ts_open + 1d <= T` (reader-enforced, unchanged);
  - corporate actions: stored `available_at <= T` (reader-style filter at the adjustment
    join, §1.5 of corporate-actions handling).
- The adjustment-factor reconstruction at feature time produces, per (instrument, bar),
  a **cumulative split factor** `CF(i, t | as_of)` = product of split ratios with
  `available_at in (decision_ts, ...]` **not yet** applied (i.e. only actions knowable
  by the decision are folded in), and a **total-return** series that reinvests
  dividends. Both are derived in a sanctioned helper (§3.3), never in the lake.

### 1.6 Synthetic-test plan (no network, ever)

`tests/unit/test_polygon_source.py` — fake `PolygonClientProtocol` returning canned dict
payloads, exactly like `test_ccxt_source.py`'s `FakeClient`:

- `test_list_instruments_includes_delisted` — active + inactive pages → both appear,
  sorted by `instrument_id`, lifecycle timestamps correct.
- `test_delisted_ticker_survives` — §1.4 regression.
- `test_fetch_ohlcv_raw_unadjusted` — assert stored bars equal the `adjusted=false`
  payload (raw, not split-adjusted); schema-valid; monotonic; partial-bar dropped via
  injected `now`.
- `test_fetch_ohlcv_rejects_intraday_v1` — `tf=H1` raises `NotImplementedError`.
- `test_fetch_ohlcv_non_monotonic_raises` / `test_until_lt_since_raises`.
- `test_corporate_actions_pit_available_at` — split/dividend rows carry
  `available_at = knowable_date + CA_PUBLICATION_LAG_MS`; schema-valid.
- `test_fetch_funding_not_supported` — raises `NotImplementedError`.
- `test_pagination_stitches` — multi-page cursor walk, deterministic stitch.
- `test_requires_key_or_client` — `ConfigError` when both `api_key` and `client` None.
- Integration `tests/integration/test_polygon_network.py` — skipped unless
  `POLYGON_API_KEY` set (mirrors `test_ccxt_network.py`), the live validation that fires
  when the key lands.

---

## 2. Schemas — one new dataset, everything else unchanged

`data/schemas.py`:

- `OHLCV_SCHEMA` / `UNIVERSE_SCHEMA` — **unchanged**. Equity daily bars use
  `Dataset.OHLCV_1D` (already exists, column-for-column identical). For equities,
  `Dataset.OHLCV_1D` becomes a **natively-ingested** dataset (not resampler-derived).
  Document this: `ohlcv_dataset(D1)` resolves the same dataset whether the bars were
  fetched (equities) or derived from 1h (crypto) — the lake does not care about
  provenance, only the schema. The writer's partial-bar guard already gates
  `OHLCV_DATASETS`, which includes `OHLCV_1D`.
- NEW `Dataset.CORPORATE_ACTIONS = "corporate_actions"` and `CORPORATE_ACTIONS_SCHEMA`:

  | column | type | doc |
  |---|---|---|
  | `instrument_id` | `string` non-null | canonical id |
  | `action_type` | `string` non-null | `"split"` or `"dividend"` |
  | `ex_date` | `ts[ms,UTC]` non-null | ex/effective date (00:00 UTC) |
  | `available_at` | `ts[ms,UTC]` non-null | knowable_date + pub lag; ALL joins use this |
  | `ratio` | `float64` non-null | split: `to/from`; dividend: 1.0 |
  | `cash_amount` | `float64` nullable | dividend cash per share; null for splits |
  | `ingested_at` | `ts[ms,UTC]` non-null | audit only |

  Add to `_SCHEMAS`, `schema_for`, `Dataset` enum, and `__all__`. `validate_table`
  needs no change (it is schema-driven). Add `CORPORATE_ACTIONS` to a new
  `CORPORATE_ACTION_DATASETS` set only if any dataset-family behavior keys off it
  (none in v1 — it is not partial-bar-guarded).

- `lake_relpath` / `LakePaths` — **unchanged**; corporate actions partition by
  `instrument_id=.../year=...` like every other dataset.

`data/store/` — `LakeWriter`, `PITDataReader`, `UniverseStore` need a thin extension:

- `PITDataReader.corporate_actions(instrument_ids, *, start, end, as_of) -> pa.Table` —
  new method, copy-shaped from `reader.funding`: filter `ex_date in [start, end)` AND
  `available_at <= as_of`, sort `(instrument_id, ex_date)`. This is the ONE PIT read
  path for actions; nothing else reads the dataset.

---

## 3. TradingCalendar — NYSE sessions + daily timeframe contract

### 3.1 New calendar class

`core/calendar.py` — add `XNYSCalendar(TradingCalendar)` and widen `calendar_for`:

```python
def calendar_for(asset_class: AssetClass) -> TradingCalendar:
    if asset_class in (AssetClass.CRYPTO_PERP, AssetClass.CRYPTO_SPOT):
        return _ALWAYS_24X7
    if asset_class is AssetClass.EQUITY:
        return _XNYS            # NEW shared instance
    raise NotImplementedError(...)
```

`XNYSCalendar` implements the four abstract methods + inherits `funding_events_in`
(unused for equities — it raises naturally if ever called with bad args; leave as-is):

- Backing data: the `exchange_calendars` package (add to `pyproject.toml` deps;
  `XNYS` calendar) — already named as the intended dependency in `core/calendar.py`'s
  module docstring and `buildabilityCritique.md §52/98`. Wrap it; do not reimplement
  holiday rules. Cache the session schedule (a pandas `DatetimeIndex` of session dates)
  on the instance, lazily, keyed nowhere (the calendar is effectively static for the
  backtest horizon; document the bounded-horizon assumption).
- `is_session(ts)` — True iff the UTC day of `ts` is an XNYS trading session. (v1 works
  at session granularity; intraday open/close-minute precision is post-v1, flagged.)
- `expected_bar_opens(start_ms, end_ms, tf=D1)` — the **session-filtered** grid: every
  session-date 00:00-UTC instant in `[start_ms, end_ms)`. This is the equities analogue
  of the crypto full grid; it is what makes a missing daily bar a real gap (e.g. a
  halted stock) vs a non-session day (weekend/holiday — correctly absent). For `tf`
  other than `D1`, raise `NotImplementedError` in v1.
- `periods_per_year(tf)` — `252.0` for `D1` (the ~252-session year the existing
  docstring promises). This is the single annualization source; Sharpe/vol/covariance
  pick it up via `calendar_for(asset_class).periods_per_year(tf)`, so **no hard-coded
  8760 or 365 leaks into the equity path.** (Crypto keeps 365.)
- `floor_bar(ts, D1)` / `next_bar_open(ts, D1)` — session-aware: `floor_bar` returns the
  00:00-UTC open of the session containing/covering `ts`; `next_bar_open` returns the
  next **session** open (skips weekends/holidays), NOT `ts + 1d`. This is the one place
  the crypto pure-integer kernel does NOT apply — equity bar arithmetic must hop
  sessions. Document loudly: anything doing `ts + tf.ms` for equities is a bug; it must
  call the calendar.

### 3.2 Daily timeframe contract

- `Timeframe.D1` already exists with `ms = 86_400_000`, `pandas_freq = "1D"`,
  `bars_per_year = 365.0`. **The `bars_per_year` property is the 24/7 number and MUST
  NOT be used for equities** — it is correct only for crypto. The equity path uses
  `calendar.periods_per_year(D1) = 252.0`. Add a one-line caveat to `Timeframe.bars_per_year`'s
  docstring pointing at `TradingCalendar.periods_per_year` as the calendared source.
  (No code change to `Timeframe` — the contract was always "calendar owns
  annualization"; this spec just exercises it.)
- `ts_open` for a daily equity bar = session date 00:00 UTC. `available_at = ts_open +
  86_400_000` (next-day boundary; conservative ≥ session close). The reader's existing
  `epoch_ms(ts_open) + tf.ms <= as_of` predicate is correct unchanged.
- **Gap semantics:** `PITDataReader.gaps(..., tf=D1)` already diffs
  `expected_bar_opens` against stored opens. For equities it must consult the **session
  grid**, which means `gaps` (and `FeatureContext.panel`, and every factor's
  complete-grid layout) must use the asset's calendar, not the 24/7
  `core.time.expected_bar_opens`. See §4.0 — this is the single most important
  cross-cutting wiring point.

---

## 4. Price-based equity factor library

### 4.0 The complete-grid wiring point (read first)

Crypto factors call `ctx.panel("close")`, which builds the wide frame on
`core.time.expected_bar_opens(start, end, tf)` — the **24/7** grid. For equities, "row
position == time slot" must mean the **session** grid, or `shift(k)` skips weekends
incorrectly (a 1-session shift would jump ~3 calendar days over a weekend and silently
break truncation/parity). Required change, localized to the engine/context:

- `FeatureContext.panel` builds its grid from `expected_bar_opens`. Parameterize this by
  the context's calendar: `FeatureContext` gains a `calendar: TradingCalendar` (passed
  by the engine from `calendar_for(asset_class)`), and `panel` calls
  `self._calendar.expected_bar_opens(start, end, tf)`. For crypto the calendar is
  `Always24x7Calendar` → identical grid → **zero behavior change, parity unaffected**.
- Consequence: `lookback_bars` for equity factors is counted in **sessions** (= D1
  bars), and `shift(1)` is exactly "previous session". This makes every reused crypto
  formula correct on the session grid with no formula edits — only the grid changes.
- This is the ONE seam edit the factor work depends on. It is calendar-injection, not a
  formula change; `cross_section.py`, `parity.py`, `spec.py`, `registry.py` are
  untouched.

### 4.1 New module + registered factors

New file: `src/alphaforge/features/library/equity_price.py`. Registers through the same
`@feature` decorator; imported by `features/library/__init__.py` (add the import block).
All windows are in **D1 (session) bars**. All bodies run on `ctx.panel(...)` (now
session-gridded), reuse the crypto helpers where structure is identical, and return
`long_series(...)`. `lookback_bars` derived from params at the single factory site
(finding 20). Parity: finite-window specs atol 0; EWMA-family rtol 1e-9.

**Adjusted-price input.** Price factors need split/total-return-adjusted closes, but the
lake stores raw. Provide ONE sanctioned helper (§3.3 below) that the equity factor
bodies call to obtain a **PIT-adjusted close panel** from `ctx`: it reads raw closes
(`ctx.panel("close")`) and the PIT corporate-actions (`ctx`-exposed, see §4.3) and folds
in only actions knowable at each row's decision time. Momentum/reversal over split
boundaries are otherwise garbage (a 2:1 split looks like a -50% return).

| feature name | family | dir | CS? | window (sessions) | lookback_bars | formula |
|---|---|---:|---|---|---|---|
| `eq_mom_252_21` | MOMENTUM | +1 | yes | L=252, skip=21 | `L+1` = 253 | `ln(C*_{t-21}/C*_{t-252})` — **12-1 momentum** |
| `eq_rev_21` | REVERSAL | +1 | yes | W=21 | `21+1` = 22 | short-term reversal: `-ln(C*_t/C*_{t-21})` |
| `eq_lowvol_252` | VOLATILITY | -1 | yes | n=252 | `252+1` = 253 | low-vol anomaly: realized vol of daily log returns (annualized × √252); **direction -1** (low vol → high expected return), CS-ranked |
| `eq_beta_252` | MARKET | 0 | no | Wβ=252 | `252+1` = 253 | rolling market beta vs equal-weight PIT-universe daily return (utility input for BAB) |
| `eq_bab_252` | MARKET | +1 | yes | Wβ=252 | `252+1` = 253 | betting-against-beta: `-zscore_xs(β)` (low beta → +). See §4.2 |
| `eq_vol_252` | VOLATILITY | 0 | no | n=252 | `252+1` = 253 | realized daily vol context (annualized) — risk/cost input, not an alpha |
| `eq_amihud_63` | LIQUIDITY | 0 | no | n=63 | `63+1` = 64 | Amihud illiquidity over 63 sessions (dollar volume), `ln(ILLIQ+eps)` |

Notes on the choices (replication-first, the most-cited price anomalies):

- **12-1 momentum** (`eq_mom_252_21`): the canonical Jegadeesh-Titman / Carhart factor —
  cumulative return from `t-252` to `t-21`, skipping the most recent month to dodge
  short-term reversal. Structurally **identical to crypto `xs_momentum(lookback, skip)`**
  — reuse `momentum.xs_momentum` verbatim on the adjusted-close panel; only L/S change
  (252/21 sessions vs 504/48 hours). `cross_sectional=True`, winsor→z in the PIT
  universe per bar, exactly like `mom_xs_504_48`.
- **Short-term reversal** (`eq_rev_21`): the 1-month reversal anomaly (Jegadeesh 1990).
  Plain (not residualized) for v1 — equity 1-month reversal is robust without the beta
  residualization the crypto `mr_res_*` needs at hour scale; document that residual
  reversal is a post-v1 refinement. `-ln(C*_t/C*_{t-21})` so higher = recent loser =
  expected outperformer, `direction=+1`, CS.
- **Low-volatility anomaly** (`eq_lowvol_252`): realized vol of daily log returns over
  252 sessions, annualized. Reuse the close-to-close vol path; **`direction=-1`** is the
  whole point of the anomaly (low-risk stocks earn higher risk-adjusted returns). CS so
  the winsor→z ranks it cross-sectionally. (`eq_vol_252` is the *same number* exposed as
  a `direction=0` risk context — register both; the alpha is the ranked low-vol, the
  context feeds risk/cost.)
- **Betting-against-beta** (`eq_bab_252`, §4.2): Frazzini-Pedersen. Beta estimated vs the
  equal-weight PIT-universe market (reuse `mean_reversion.rolling_beta` +
  `market_return` machinery — identical structure, daily returns), then the BAB *signal*
  is the cross-sectional rank of **negative** beta. `direction=+1`, CS.
- **Amihud illiquidity** (`eq_amihud_63`): reuse `liquidity.amihud_illiq` verbatim on
  adjusted close + dollar volume, window 63 sessions (~quarter). `direction=0` —
  liquidity is a risk/universe/cost input, the *premium* is unreliable and conflicts with
  tradability, mirroring the crypto liquidity module's stance.

### 4.2 BAB construction (exact)

Reuse, do not reimplement:

1. `returns = log_returns(adj_close_panel)` (daily).
2. `mask = _member_mask(ctx, returns.index, columns)` — the SAME PIT-membership mask
   helper pattern from `mean_reversion._member_mask` (lift it to a shared location or
   import; it is calendar-agnostic — it only calls `ctx.universe_asof`).
3. `mkt = market_return(returns, mask)` — equal-weight PIT-universe daily market return.
4. `beta = rolling_beta(returns, mkt, window=252)` — strictly through `t-1`, the
   existing conservative variant; NaN until 252 valid pairs.
5. `eq_beta_252` body returns `beta` (utility, `direction=0`).
6. `eq_bab_252` body returns `-beta` raw; the CS pipeline (`cross_sectional=True`)
   winsorizes + z-scores it per bar within the PIT universe → the BAB rank. The negation
   makes low-beta → high score; `direction=+1` then means "high score → high expected
   return," consistent with the framework's sign convention. (Frazzini-Pedersen's
   leverage-and-rescale portfolio construction is a *portfolio* concern handled by the
   optimizer/sizing layer, not the factor — the factor is the cross-sectional low-beta
   signal, matching how every other CS factor here is just the ranked exposure.)

### 4.3 Sanctioned PIT adjusted-close helper

`FeatureContext` gains `corporate_actions() -> pd.DataFrame` (copy-shaped from
`.funding()`: reads via the new `PITDataReader.corporate_actions`, pre-filtered to
`available_at <= end`, columns `(instrument_id, ex_date, available_at, action_type,
ratio, cash_amount)`), and a sanctioned join helper analogous to `funding_asof_join`:

`equity_price.adjusted_close(ctx) -> pd.DataFrame` (wide, session grid):
- raw = `ctx.panel("close")`.
- For each (instrument, decision row `t`): cumulative split factor = product of split
  `ratio` for actions with `available_at <= ts_open + tf.ms` AND `ex_date > ts_open`
  (un-applied future-relative splits fold backward into history so a past price is
  expressed in *current-as-of-decision* share terms). Total-return reinvests dividends
  analogously. This is per-row PIT exactly like `funding_asof_join` — a split knowable
  only after `t` must not touch the price at `t`.
- The helper is the ONE place equity adjustment happens; every equity price factor calls
  it, so the adjustment convention cannot drift between factors (the same single-site
  discipline as `lookback_bars` derivation and the shared `adv_quote_30d`/`sigma_daily`).
- **Lookback honesty:** the adjustment reaches back only through the context window;
  specs must declare `lookback_bars` covering their formula window (the split/dividend
  recency horizon is bounded by the same window), so `verify_truncation` stays green.

### 4.4 Cross-section + masking — unchanged

`CSPipeline(steps=("winsorize","zscore"))` applies verbatim; the universe mask comes
from `UniverseStore.membership_asof` (equity universe, §5). No change to
`cross_section.py`. Equity CS factors are winsor→z within the PIT membership per bar,
truncation-invariant, batch/asof parity — identical contract to crypto.

### 4.5 Parity / truncation tests (the discipline gate)

`tests/unit/test_factors_equity_price.py` — for EVERY registered equity factor, the same
two harnesses every crypto factor test calls:

- `verify_truncation(engine, spec, ids, ts_samples, history_start=<early>)` — full
  history vs exactly `lookback_bars` **sessions** must match (atol 0 for the finite-window
  factors here; all listed equity factors are finite-window — no EWMA — so atol 0 across
  the board).
- `verify_parity(engine, specs, ids, ts_samples)` — batch `compute_history` vs live
  `compute_asof` agree.
- Synthetic daily-bar fixtures on a session grid (build via the `XNYSCalendar`), with a
  planted split mid-window to assert the adjusted-close helper neutralizes it (a 2:1
  split must NOT register as a -50% momentum print) and that the split is invisible
  before its `available_at` (PIT).
- A low-vol-direction test: assert `eq_lowvol_252.direction == -1` and that the CS-ranked
  output gives lower-vol names higher scores.
- A BAB sign test: a synthetic low-beta name outranks a high-beta name in `eq_bab_252`.

---

## 5. UniverseBuilder — equity universe (top-N by ADV, monthly, survivorship-aware)

`UniverseBuilder` is **reused as-is** — it is already a pure function of (reader,
instrument record, config) and already survivorship-free by construction (ranks delisted
names while they lived, closes intervals at `delisted_ts`). The equity wiring:

- **Ranking signal:** the builder's `_median_daily_quote_volume` reads `Timeframe.H1`
  bars and sums per UTC day. For equities the native bar is **D1**, and `quote_volume`
  IS already dollar volume per day. The builder must rank on **ADV (dollar)** = trailing
  `rank_window_days`-session median of daily dollar volume. Minimal, surgical change:
  parameterize the builder's read timeframe (it currently hard-codes `Timeframe.H1` in
  `_median_daily_quote_volume`). Add a `tf: Timeframe = Timeframe.H1` constructor arg (or
  derive from a passed `asset_class`); for equities pass `D1`, and the per-UTC-day
  summing becomes a no-op (one bar per session) — the median-of-daily-dollar-volume
  reading is exactly ADV. This is a ≤10-line change, fully covered by the existing
  builder tests plus a new equity test.
- **`min_listing_age_ms` / `min_days`:** keep the eligibility gate; for equities,
  `min_days` counts sessions with volume in the window (30 sessions default is sensible;
  document). `min_listing_age_ms` = 30 days keeps brand-new IPOs out until they have
  stable ADV, mirroring the crypto "no week-old listing" rule.
- **Rebalance:** monthly (the builder's only supported cadence; `UniverseCfg.rebalance`
  already validated). `effective_from` = the 1st-of-month 00:00 UTC instant. CONTRACT:
  on a non-session 1st (holiday/weekend), the membership is *in force* from that instant
  and the first *tradable* decision is the next session — the backtest already only
  decides on session bars (the engine/loop iterate the session grid), so membership is
  live before the first session decision, exactly as the crypto ordering contract
  (finding 21) requires. Document this explicitly in the equity wiring.
- **top-N:** `UniverseCfg.entry_rank/exit_rank` (16/26 defaults) give a top-~20 with
  hysteresis. For equities a broader N (e.g. top-500/600 with a hysteresis band) is the
  research target; set via config — **no builder change**, just `UniverseCfg` values per
  asset class. (If breadth needs N in the hundreds, confirm the band still
  `entry_rank < exit_rank`; the config validator enforces it.)
- **Survivorship regression** lives in §1.4 (the delisted ticker must produce a closed
  interval at `delisted_ts`).

`tests/unit/test_universe_builder_equity.py` — feed the builder a small SCD2 equity
record (including one delisted name) and synthetic D1 dollar-volume bars; assert top-N by
ADV, hysteresis, and the delisted-name interval closes at `delisted_ts` (the equity FTT
test).

---

## 6. Exact file manifest (pin every path)

NEW files (under `src/alphaforge/` unless noted):

- `data/sources/polygon_source.py` — `PolygonEquitiesSource(DataSource)`,
  `PolygonClientProtocol`, `Adjustment` enum, `CA_PUBLICATION_LAG_MS`,
  `fetch_corporate_actions`.
- `features/library/equity_price.py` — `eq_mom_252_21`, `eq_rev_21`, `eq_lowvol_252`,
  `eq_beta_252`, `eq_bab_252`, `eq_vol_252`, `eq_amihud_63`, plus the `adjusted_close`
  helper and any shared `_member_mask` import.
- `tests/unit/test_polygon_source.py` — §1.6 fake-client tests.
- `tests/unit/test_factors_equity_price.py` — §4.5 parity/truncation/PIT tests.
- `tests/unit/test_universe_builder_equity.py` — §5 equity universe test.
- `tests/integration/test_polygon_network.py` — key-gated live validation (skipped
  without `POLYGON_API_KEY`).

EDITED files (surgical, additive — no crypto behavior change):

- `core/types.py` — `MarketType.CASH` member.
- `core/calendar.py` — `XNYSCalendar`, `_XNYS` singleton, `calendar_for(EQUITY)` branch,
  `__all__`.
- `core/symbols.py` — equity-id docstring note (chosen approach reuses existing logic;
  add only if a helper is needed for dotted-ticker canonicalization).
- `core/time.py` — one-line docstring caveat on `Timeframe.bars_per_year` (no code).
- `data/schemas.py` — `Dataset.CORPORATE_ACTIONS`, `CORPORATE_ACTIONS_SCHEMA`,
  `_SCHEMAS`/`schema_for`/`__all__` additions.
- `data/store/reader.py` — `PITDataReader.corporate_actions(...)` (copy-shaped from
  `funding`).
- `data/universe/builder.py` — parameterize the ranking timeframe (`tf` arg; D1 for
  equities); ≤10 lines.
- `features/context.py` — inject `calendar: TradingCalendar`; `panel` uses
  `self._calendar.expected_bar_opens` (no-op for crypto); add `.corporate_actions()`
  reader passthrough + sanctioned adjusted-close join helper hook.
- `features/engine.py` — pass `calendar_for(asset_class)` into the `FeatureContext` it
  constructs (the engine already knows the requested instruments' asset class via the
  SCD2 store, or takes it as a param).
- `features/library/__init__.py` — import the new `equity_price` factors.
- `pyproject.toml` — add `exchange-calendars` (and Polygon SDK or `httpx` — adapter can
  call REST directly behind the Protocol, so a heavy SDK is optional; prefer `httpx`
  behind `PolygonClientProtocol` to keep the dep surface small and the fake trivial).

UNCHANGED (do NOT edit — verify the diff touches none of these): `data/schemas.py`'s
`OHLCV_SCHEMA`/`UNIVERSE_SCHEMA` column sets, `data/store/writer.py`, `data/store/lake.py`,
`features/spec.py`, `features/registry.py`, `features/cross_section.py`,
`features/parity.py`, `backtest/*`, `portfolio/*`, `validation/*`.

---

## 7. Build order (dependency-correct, each step independently testable)

1. **Enums + identity** (`core/types.py`, `core/symbols.py` note) — `MarketType.CASH`,
   equity id round-trips. Tiny; unblocks everything.
2. **Schema + reader** (`data/schemas.py`, `reader.corporate_actions`) — the new dataset
   + PIT read path. Test with hand-built Arrow fixtures.
3. **Calendar** (`core/calendar.py` + `exchange-calendars` dep) — `XNYSCalendar`,
   `calendar_for(EQUITY)`, 252 annualization, session grid. Test session membership +
   `expected_bar_opens` against known 2020-2024 NYSE holidays.
4. **Context calendar injection** (`features/context.py`, `features/engine.py`) — the
   §4.0 grid wiring. Re-run the FULL existing crypto parity suite → must stay green
   (proves the injection is a no-op for `Always24x7Calendar`).
5. **Polygon source** (`data/sources/polygon_source.py`) — adapter + fake-client tests,
   including the §1.4 survivorship regression. No network.
6. **Equity universe** (`builder.py` tf-param + equity test) — top-N ADV + delisting.
7. **Equity factors** (`features/library/equity_price.py` + tests) — adjusted-close
   helper first, then the seven factors, each with `verify_truncation`/`verify_parity`.
8. **Integration (key-gated)** — `test_polygon_network.py`; flips from skipped to live
   when `POLYGON_API_KEY` lands. The real fetch validates the synthetic contracts.

Every step is ruff + mypy --strict clean, matches neighbour docstring density, and
touches only the files in §6. When this lands, an equities daily panel ingests through
the same `DataSource → LakeWriter → PITDataReader → UniverseBuilder → FeatureEngine`
pipeline and runs the same DSR/PBO/CPCV gauntlet — the breadth bet the crypto NULL
pointed us toward.
