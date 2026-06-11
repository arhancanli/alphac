Confirmed greenfield: `~/alphaforge` does not exist, machine is arm64 (Apple Silicon), system Python is 3.9.6 so the toolchain must pin its own 3.12 (uv handles this). The full design follows.

---

# AlphaForge — Data & Research Infrastructure Design (v1)

Scope: ingestion, storage, point-in-time correctness, data quality, universe management, instrument model, feature store, config/secrets/logging, research environment. Crypto (Binance spot + USDT-M perps via ccxt) first; asset-agnostic interfaces so equities plug in later.

---

## 0. Global Conventions (the data contract — everything else depends on this)

These conventions are load-bearing. They must be enforced in code, not documentation.

1. **All timestamps are UTC, stored as Arrow `timestamp[ms]` with UTC timezone** (pandas `datetime64[ms, UTC]`). Naive datetimes are a programming error; a `require_utc()` guard raises on them. Internally, integer epoch-milliseconds (`int`) are used at API boundaries (`since_ms`, `as_of_ms`) to remove all timezone ambiguity from function signatures.
2. **Bars are labeled by OPEN time** (`ts_open`), matching what ccxt/Binance return. A bar covering `[ts_open, ts_open + Δ)` is **available at** `ts_open + Δ` (its close). This is the single most common source of lookahead bias; the PIT reader enforces it mechanically (Section 3).
3. **Decision timestamp convention:** a signal computed "at bar close T" may use any record with `available_at <= T`. Execution happens at the open of the next bar (price `open` of the bar whose `ts_open = T`). The data layer guarantees the first half; the backtest/execution layers consume it.
4. **Every persisted analytical dataset carries an explicit or derivable `available_at`.** OHLCV: derived (`ts_open + Δ`). Funding: explicit column. Universe membership and instrument metadata: interval-versioned (`effective_from`/`effective_to`, `valid_from`/`valid_to`).
5. **Raw data is never mutated in place and never silently "fixed."** Bad prints are *flagged* (`quality_flag` bitmask), never altered. Gaps are never synthetically filled in the lake; fill policy is an explicit, declared parameter at the feature layer.
6. **Analytical data lives in Parquet (immutable, atomically replaced files); mutable operational state lives in SQLite (WAL mode); DuckDB is a query engine only, never a storage owner.** This avoids DuckDB's single-writer lock conflicting between the 24/7 live loop and concurrent research sessions.

---

## 1. Repository & Package Layout

```
~/alphaforge/
├── pyproject.toml                  # uv-managed; python = ">=3.12"
├── uv.lock
├── .env.example                    # documented env vars; real .env gitignored
├── .gitignore                      # data/, var/, .env
├── configs/
│   ├── base.yaml                   # default settings (checked in)
│   └── live.yaml                   # overrides for the 24/7 loop
├── data/                           # the lake (gitignored)
│   ├── lake/                       # Parquet datasets (Section 2)
│   ├── features/                   # feature cache (Section 7)
│   └── quality/reports/            # validation artifacts (Section 4)
├── var/
│   ├── ops.sqlite                  # checkpoints, run log, quality summaries, heartbeat
│   └── log/                        # structlog JSON files
├── notebooks/                      # marimo .py notebooks (Section 9)
├── tests/
│   ├── unit/ ...
│   ├── property/                   # hypothesis tests (resampler, PIT)
│   └── golden/                     # frozen fixture parquet + expected outputs
└── src/alphaforge/
    ├── __init__.py
    ├── config/
    │   ├── __init__.py
    │   └── settings.py             # pydantic-settings models + load_settings()
    ├── core/
    │   ├── __init__.py
    │   ├── time.py                 # Timeframe enum, UTC guards, bar arithmetic
    │   ├── types.py                # shared enums, NewTypes (Ms = int), Dataset enum
    │   ├── instruments.py          # Instrument model, AssetClass, InstrumentStore (SCD2)
    │   ├── symbols.py              # SymbolMapper: ccxt ↔ exchange ↔ instrument_id
    │   ├── calendar.py             # TradingCalendar ABC + Always24x7Calendar
    │   ├── errors.py               # AlphaForgeError hierarchy
    │   └── logging.py              # structlog configuration
    ├── data/
    │   ├── __init__.py
    │   ├── schemas.py              # pyarrow schemas, schema_version constants
    │   ├── sources/
    │   │   ├── __init__.py
    │   │   ├── base.py             # DataSource ABC
    │   │   └── ccxt_source.py      # CCXTDataSource (Binance spot + USDT-M perp)
    │   ├── ingest/
    │   │   ├── __init__.py
    │   │   ├── backfill.py         # BackfillJob (also serves as incremental updater)
    │   │   ├── updater.py          # LiveUpdater: hourly follow-loop scheduling
    │   │   ├── checkpoints.py      # CheckpointStore (SQLite watermarks)
    │   │   └── retry.py            # tenacity policies, RateBudget
    │   ├── store/
    │   │   ├── __init__.py
    │   │   ├── lake.py             # LakePaths: partition path construction, glob patterns
    │   │   ├── writer.py           # LakeWriter: merge-dedupe-sort-atomic-replace
    │   │   ├── reader.py           # PITDataReader (DuckDB over Parquet)
    │   │   └── resample.py         # Resampler: 1h → 4h/1d
    │   ├── quality/
    │   │   ├── __init__.py
    │   │   ├── checks.py           # Check protocol + concrete checks
    │   │   └── report.py           # ValidationReport build/persist/render
    │   └── universe/
    │       ├── __init__.py
    │       ├── builder.py          # UniverseBuilder (ranking, hysteresis)
    │       └── store.py            # membership intervals + snapshots persistence
    ├── features/
    │   ├── __init__.py
    │   ├── spec.py                 # FeatureSpec, FeatureSetSpec
    │   ├── registry.py             # FeatureRegistry + @feature decorator
    │   ├── context.py              # FeatureContext (PIT-windowed data access)
    │   ├── engine.py               # FeatureEngine: batch + incremental paths
    │   ├── cache.py                # FeatureCache: content-addressed parquet cache
    │   ├── parity.py               # train/serve parity verification
    │   └── library/
    │       ├── __init__.py
    │       ├── returns.py          # example features: log returns, momentum
    │       ├── volatility.py       # realized vol, ATR
    │       └── funding.py          # funding-rate features (PIT-lagged)
    ├── research/
    │   ├── __init__.py
    │   └── session.py              # ResearchSession: one-line wiring for notebooks
    └── cli/
        ├── __init__.py
        └── main.py                 # typer app: `af` entrypoint
```

`pyproject.toml` registers the CLI: `[project.scripts] af = "alphaforge.cli.main:app"`. Layout is `src/` style (prevents accidental import of uninstalled package — a known source of "tests pass locally, prod uses stale code").

---

## 2. Storage: Parquet lake + DuckDB query engine

### 2.1 Decision and rationale

**Chosen: Hive-partitioned Parquet files on local disk, queried via DuckDB; SQLite (WAL) for operational state.**

Data volume check (justifies "small data" choices): 100 symbols × 5 years × 8,760 1h bars/yr ≈ 4.4M rows × ~80 bytes ≈ 350 MB uncompressed, ~60 MB as zstd Parquet. Funding: 100 × 5 × 1,095 ≈ 0.5M rows. This is trivially small; the constraint is **correctness and concurrency**, not throughput.

| Alternative | Verdict | Why |
|---|---|---|
| Parquet + DuckDB | **chosen** | Zero server ops; columnar scans; filter pushdown on hive partitions; readable from pandas/polars/duckdb/any future language; immutable files + atomic `os.replace` give crash-safe, lock-free concurrent reads while the live loop writes |
| Native DuckDB tables | rejected for storage | single-writer database lock: the 24/7 updater and an open research notebook would fight over the file. Fine as ephemeral engine. |
| TimescaleDB / ClickHouse | rejected | server processes to babysit on a solo laptop; massive overkill at this volume; complicates "cloud later" lift-and-shift less than plain files do |
| SQLite for bars | rejected | row-oriented; fine at this size but no columnar pushdown, painful schema evolution, awkward from polars/duckdb. Kept for ops state where its concurrency (WAL) is the right tool |
| Feather/Arrow IPC | rejected | weaker compression, weaker long-term-format guarantees than Parquet |

### 2.2 Partitioning scheme

Hive-style key=value directories so DuckDB pushes filters into the file listing:

```
data/lake/ohlcv/exchange=binance/market=perp/timeframe=1h/symbol=BTCUSDT/year=2024/data.parquet
data/lake/ohlcv/exchange=binance/market=spot/timeframe=1h/symbol=BTCUSDT/year=2024/data.parquet
data/lake/funding/exchange=binance/symbol=BTCUSDT/year=2024/data.parquet
data/lake/instruments/snapshot.parquet                  # small SCD2 table, single file
data/lake/universe/membership/universe=perp_top40/data.parquet
data/lake/universe/snapshots/universe=perp_top40/year=2024/data.parquet
```

- **One file per leaf partition** (`data.parquet`), rewritten whole on update. At ≤ 8,784 rows per (symbol, year, 1h) leaf this costs milliseconds and buys atomicity: write `data.parquet.tmp-<uuid>` then `os.replace()` (atomic on APFS). Readers never see a torn file.
- Partition by `year` not `month/day`: keeps file count low (~500 files for 100 symbols × 5y), and DuckDB row-group pruning handles intra-year time filters.
- Within each file rows are **sorted by `ts_open`, unique on `ts_open`** (writer enforces).
- Parquet options: compression `zstd` level 3, dictionary encoding on, row group size default. Write with `pyarrow.parquet.write_table`.

### 2.3 Persisted schemas (exact)

All schemas carry `schema_version: int` in Parquet key-value metadata (`b"alphaforge.schema_version"`), starting at `1`. `alphaforge/data/schemas.py` is the single source of truth (pyarrow `Schema` objects); the writer validates every table against it before writing.

**`ohlcv`** (partition cols `exchange: str`, `market: str` ∈ {spot, perp}, `timeframe: str`, `symbol: str` (exchange symbol), `year: int` are encoded in the path; columns below are in-file):

| column | arrow dtype | notes |
|---|---|---|
| `ts_open` | `timestamp[ms, tz=UTC]` | bar open; primary key within partition |
| `open` | `float64` | |
| `high` | `float64` | |
| `low` | `float64` | |
| `close` | `float64` | |
| `volume` | `float64` | base-asset units |
| `quote_volume` | `float64` (nullable) | exact quote-asset volume from raw klines (Binance field index 7); null for sources lacking it |
| `n_trades` | `int64` (nullable) | trade count (Binance klines index 8) |
| `taker_buy_volume` | `float64` (nullable) | base units (klines index 9); useful flow feature later |
| `quality_flag` | `int32` | bitmask, 0 = clean (Section 4.3) |
| `ingested_at` | `timestamp[ms, tz=UTC]` | wall clock at write; audit only, never used in features |
| `source` | `string` | e.g. `ccxt.binanceusdm` |

`available_at` is **not stored** for OHLCV; it is always derived as `ts_open + Δ_timeframe` by the reader (storing it would invite drift).

**`funding`** (partitions `exchange`, `symbol`, `year`):

| column | arrow dtype | notes |
|---|---|---|
| `ts_funding` | `timestamp[ms, tz=UTC]` | settlement time (00:00/08:00/16:00 UTC on Binance) |
| `funding_rate` | `float64` | per-interval decimal rate (e.g. 0.0001 = 1 bp per 8h) |
| `mark_price` | `float64` (nullable) | if the source provides it |
| `available_at` | `timestamp[ms, tz=UTC]` | `ts_funding + δ_funding` (Section 3.2) |
| `ingested_at` | `timestamp[ms, tz=UTC]` | |
| `source` | `string` | |

**`instruments`** (SCD2; single small file, fully rewritten by `af instruments refresh`):

| column | arrow dtype | notes |
|---|---|---|
| `instrument_id` | `string` | canonical: `"BINANCE:PERP:BTCUSDT"`, `"BINANCE:SPOT:BTCUSDT"`, later `"NASDAQ:EQ:AAPL"` |
| `exchange` | `string` | `binance` |
| `asset_class` | `string` | `crypto_perp` \| `crypto_spot` \| `equity` |
| `symbol_exchange` | `string` | `BTCUSDT` |
| `symbol_ccxt` | `string` | `BTC/USDT:USDT` (perp) / `BTC/USDT` (spot) |
| `base`, `quote` | `string` | `BTC`, `USDT` |
| `tick_size` | `float64` | min price increment |
| `lot_size` | `float64` | min amount step |
| `min_notional` | `float64` | exchange min order value (quote units) |
| `contract_multiplier` | `float64` | 1.0 for linear perps and spot; field exists so options/index futures fit later |
| `maker_fee_bps`, `taker_fee_bps` | `float64` | defaults: perp 2.0/5.0 bps, spot 10.0/10.0 bps (Binance VIP0, no BNB discount — conservative) |
| `funding_interval_hours` | `int32` (nullable) | 8 for Binance perps; null for spot/equity |
| `listing_ts` | `timestamp[ms, tz=UTC]` (nullable) | first available 1h bar (probed at backfill, see 5.4) |
| `delisting_ts` | `timestamp[ms, tz=UTC]` (nullable) | set when instrument disappears from exchange info while bars exist |
| `status` | `string` | `active` \| `delisted` |
| `valid_from`, `valid_to` | `timestamp[ms, tz=UTC]` (`valid_to` nullable) | SCD2: a new row is appended when tick size/fees/etc. change; current row has `valid_to = null` |
| `ingested_at` | `timestamp[ms, tz=UTC]` | |

**`universe/membership`** (PIT intervals — the table backtests join against):

| column | arrow dtype | notes |
|---|---|---|
| `universe` | `string` | `perp_top40` |
| `instrument_id` | `string` | |
| `effective_from` | `timestamp[ms, tz=UTC]` | first decision timestamp at which membership holds |
| `effective_to` | `timestamp[ms, tz=UTC]` (nullable) | exclusive end; null = currently a member |
| `rank_at_entry` | `int32` | |
| `adv_usd_at_entry` | `float64` | |

**`universe/snapshots`** (full audit of every rebalance, including non-members):

| column | arrow dtype |
|---|---|
| `universe` | `string` |
| `rebalance_ts` | `timestamp[ms, tz=UTC]` |
| `instrument_id` | `string` |
| `rank` | `int32` |
| `adv_usd_30d` | `float64` |
| `eligible` | `bool` |
| `member_after` | `bool` |
| `action` | `string` ∈ {`enter`, `stay`, `exit`, `out`} |
| `reason` | `string` (nullable) — e.g. `min_history`, `stablecoin_excluded` |

**SQLite `var/ops.sqlite`** (WAL mode, `busy_timeout=5000`):

```sql
CREATE TABLE ingest_watermarks (
  source TEXT NOT NULL, dataset TEXT NOT NULL,        -- 'ohlcv' | 'funding'
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL,      -- timeframe='' for funding
  watermark_ms INTEGER NOT NULL,   -- available_at of last finalized record persisted
  rows_total INTEGER NOT NULL DEFAULT 0,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY (source, dataset, symbol, timeframe)
);
CREATE TABLE run_log (
  run_id TEXT PRIMARY KEY, kind TEXT, started_ms INTEGER, finished_ms INTEGER,
  status TEXT, detail_json TEXT
);
CREATE TABLE quality_findings (
  run_id TEXT, dataset TEXT, symbol TEXT, timeframe TEXT,
  check_name TEXT, severity TEXT, n_findings INTEGER, detail_json TEXT
);
CREATE TABLE heartbeat (component TEXT PRIMARY KEY, last_beat_ms INTEGER, detail TEXT);
```

### 2.4 Key classes

```python
# alphaforge/data/store/lake.py
class LakePaths:
    """Pure path arithmetic for the Parquet lake; no I/O. Single source of truth
    for partition layout and glob patterns consumed by writer and reader."""
    def __init__(self, root: Path) -> None: ...
    def ohlcv_leaf(self, exchange: str, market: str, timeframe: Timeframe,
                   symbol: str, year: int) -> Path: ...
    def ohlcv_glob(self, exchange: str | None = None, market: str | None = None,
                   timeframe: Timeframe | None = None) -> str: ...
    def funding_leaf(self, exchange: str, symbol: str, year: int) -> Path: ...
    # ... analogous for instruments / universe

# alphaforge/data/store/writer.py
class LakeWriter:
    """Idempotent upsert into one leaf partition: read-existing → concat → 
    dedupe on key (keep latest ingested_at) → sort → validate schema → atomic replace."""
    def __init__(self, paths: LakePaths) -> None: ...
    def upsert_ohlcv(self, table: pa.Table, *, exchange: str, market: str,
                     timeframe: Timeframe, symbol: str) -> UpsertStats: ...
    def upsert_funding(self, table: pa.Table, *, exchange: str, symbol: str) -> UpsertStats: ...
    def replace_instruments(self, table: pa.Table) -> None: ...
    def replace_universe_membership(self, universe: str, table: pa.Table) -> None: ...

@dataclass(frozen=True)
class UpsertStats:
    rows_in: int; rows_new: int; rows_replaced: int; rows_total_after: int
```

`upsert_ohlcv` splits the incoming table by `year(ts_open)` and processes each leaf independently. Dedupe key: `ts_open`; conflict resolution: keep the row with max `ingested_at` (a re-fetch of a finalized bar may correct an earlier partial read).

---

## 3. Point-in-Time Correctness

### 3.1 The single enforcement point: `PITDataReader`

**Rule: no code above the storage layer reads Parquet directly.** Research, features, backtest, and live trading all go through `PITDataReader`, which requires an explicit `as_of_ms` and applies the availability filter in SQL. There is deliberately **no default `as_of=now`** — callers must state their information time.

```python
# alphaforge/data/store/reader.py
class PITDataReader:
    """Point-in-time reads over the Parquet lake via DuckDB.
    Every method filters on availability: a record is visible iff available_at <= as_of."""

    def __init__(self, paths: LakePaths, instruments: InstrumentStore) -> None:
        # duckdb.connect() in-memory; read_parquet(glob, hive_partitioning=true)
        ...

    def read_ohlcv(self, instrument_ids: Sequence[str], timeframe: Timeframe,
                   start_ms: int, end_ms: int, *, as_of_ms: int) -> pd.DataFrame:
        """Bars with ts_open in [start_ms, end_ms) AND ts_open + Δ <= as_of_ms.
        Returns MultiIndex (ts_open, instrument_id), columns = ohlcv schema."""

    def read_ohlcv_window(self, instrument_ids: Sequence[str], timeframe: Timeframe,
                          n_bars: int, *, as_of_ms: int) -> pd.DataFrame:
        """Last n_bars finalized bars per instrument as of as_of_ms (live-loop path)."""

    def read_funding(self, instrument_ids: Sequence[str],
                     start_ms: int, end_ms: int, *, as_of_ms: int) -> pd.DataFrame:
        """Funding records with ts_funding in range AND available_at <= as_of_ms."""

    def universe_members(self, universe: str, *, as_of_ms: int) -> list[str]:
        """instrument_ids with effective_from <= as_of < coalesce(effective_to, +inf)."""

    def instrument(self, instrument_id: str, *, as_of_ms: int) -> Instrument:
        """SCD2 lookup: row with valid_from <= as_of < coalesce(valid_to, +inf)."""
```

The OHLCV availability predicate, in DuckDB SQL (Δ in ms from the `Timeframe` enum):

```sql
WHERE ts_open >= ?start AND ts_open < ?end
  AND ts_open + INTERVAL (?delta_ms) MILLISECOND <= ?as_of
  AND symbol IN (...)          -- partition pruning
  AND year BETWEEN year(?start) AND year(?end)
```

### 3.2 Availability semantics per dataset (exact)

| dataset | `available_at` | default lag parameter | justification |
|---|---|---|---|
| OHLCV bar | `ts_open + Δ_tf` | — (definitional) | a bar is final at its close; Binance klines are immutable once closed |
| funding | `ts_funding + δ_funding`, **δ_funding = 300,000 ms (5 min)** | configurable | the realized rate is determined at settlement, but API propagation isn't instant; 5 min is a conservative buffer that costs nothing at 1h frequency |
| universe membership | `effective_from = rebalance_ts` where the ranking uses **only data through the prior UTC day** | — | builder computes ADV with `as_of = rebalance_ts`; PIT reader makes peeking impossible |
| instruments | `valid_from = ingestion time of the change` | — | we can only know a fee/filter change when we observe it; SCD2 records observation time |

### 3.3 Bar finality vs. ingestion grace

The live updater must never persist an in-progress bar. Two independent guards:

1. **Scheduling guard:** the updater requests OHLCV only up to `until_ms = floor(now, Δ)` (the most recent boundary) and runs at `floor(now, Δ) + γ`, **γ = 30,000 ms (30 s)** grace for exchange-side kline finalization and clock skew.
2. **Write guard (belt and braces):** `LakeWriter.upsert_ohlcv` **drops any row with `ts_open + Δ > ingested_at`** and logs a warning. Even if a buggy caller fetches the live candle, it cannot reach disk.

Checkpoint overlap: every incremental run re-fetches from `watermark_ms − 3·Δ` (**3 bars overlap**) and upserts idempotently — protects against a previous run having written a bar from a lagging exchange node. Dedupe makes this free.

---

## 4. Ingestion

### 4.1 `DataSource` interface (asset-agnostic)

```python
# alphaforge/data/sources/base.py
class DataSource(ABC):
    """A market-data vendor adapter. Implementations are dumb fetchers:
    they normalize to canonical schemas and NEVER write to the lake."""

    name: str                                   # e.g. "ccxt.binanceusdm"

    @property
    @abstractmethod
    def calendar(self) -> TradingCalendar: ...  # Always24x7Calendar for crypto

    @abstractmethod
    def list_instruments(self) -> pa.Table: ...
        """Current exchange metadata, conforming to the instruments schema
        (without SCD2 columns; InstrumentStore adds versioning)."""

    @abstractmethod
    def fetch_ohlcv(self, instrument: Instrument, timeframe: Timeframe,
                    since_ms: int, until_ms: int) -> pa.Table: ...
        """Closed bars with ts_open in [since_ms, until_ms), ohlcv schema,
        paginated internally, rate-limited, sorted, deduped."""

    @abstractmethod
    def fetch_funding_history(self, instrument: Instrument,
                              since_ms: int, until_ms: int) -> pa.Table: ...
        """Settled funding records in range; funding schema. Raises
        UnsupportedDataset for sources without funding (spot/equities)."""
```

```python
# alphaforge/core/calendar.py
class TradingCalendar(ABC):
    """Defines when bars exist. Crypto: every Δ. Equities later: exchange sessions
    (via the `exchange_calendars` package) — gap detection and bar-availability
    math consult this, so the equities adapter requires no engine changes."""
    @abstractmethod
    def expected_bar_opens(self, timeframe: Timeframe,
                           start_ms: int, end_ms: int) -> npt.NDArray[np.int64]: ...
    @abstractmethod
    def is_session(self, ts_ms: int) -> bool: ...

class Always24x7Calendar(TradingCalendar):
    """expected_bar_opens = arange(ceil(start, Δ), end, Δ)."""
```

### 4.2 `CCXTDataSource`

```python
# alphaforge/data/sources/ccxt_source.py
class CCXTDataSource(DataSource):
    """ccxt adapter. market='perp' -> ccxt.binanceusdm, market='spot' -> ccxt.binance.
    Sync ccxt, sequential pagination — determinism over speed (40 symbols × 5y of
    1h ≈ 1,800 requests at limit=1000; ~10 min wall clock, run once)."""

    def __init__(self, exchange_id: str, market: MarketType,
                 *, page_limit: int = 1000, request_timeout_ms: int = 30_000) -> None: ...
```

Implementation specifics (the builder must follow these):

- `enableRateLimit=True` on the ccxt instance (token bucket honoring Binance weight limits) **plus** tenacity retry: `retry=retry_if_exception_type((ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.ExchangeNotAvailable))`, `wait=wait_exponential_jitter(initial=1, max=60)`, `stop=stop_after_attempt(6)`. `ccxt.BadSymbol` / `ccxt.AuthenticationError` are **not** retried — they propagate.
- **Pagination loop:** call `fetch_ohlcv(symbol_ccxt, tf, since=cursor, limit=page_limit)`; advance `cursor = last_ts + Δ`; stop when page is empty or `last_ts + Δ >= until_ms`; drop any row with `ts >= until_ms`. Defensive: assert page timestamps strictly increasing.
- **Extended kline columns:** ccxt's unified `fetch_ohlcv` returns only `[ts,o,h,l,c,v]`. For Binance, the adapter uses the implicit raw endpoints to obtain `quote_volume` / `n_trades` / `taker_buy_volume`: `exchange.fapipublic_get_klines(...)` (perp) / `exchange.public_get_klines(...)` (spot), which return 12-element arrays (index 7 = quote asset volume, 8 = number of trades, 9 = taker buy base volume). Non-Binance sources leave these columns null — the rest of the system treats them as optional.
- **Funding:** `fetch_funding_rate_history(symbol, since, limit=1000)` paginated identically; sets `available_at = ts_funding + δ_funding`.
- **No API keys needed**: all v1 data endpoints are public. Keys enter only with the (separate-area) broker.

### 4.3 Backfill + incremental updater (one code path)

The incremental updater **is** the backfill with `since = watermark − 3Δ`. One engine, two entrypoints — this is deliberate: live and historical data flow through identical code.

```python
# alphaforge/data/ingest/checkpoints.py
class CheckpointStore:
    """SQLite-backed watermarks. watermark_ms = available_at of the last
    finalized record persisted for (source, dataset, symbol, timeframe)."""
    def __init__(self, ops_db: Path) -> None: ...
    def get(self, source: str, dataset: str, symbol: str, timeframe: str) -> int | None: ...
    def set(self, source: str, dataset: str, symbol: str, timeframe: str,
            watermark_ms: int, rows_total: int) -> None: ...

# alphaforge/data/ingest/backfill.py
class BackfillJob:
    """Resumable, idempotent ingestion: per (symbol, dataset), fetch from
    max(requested_since, watermark - 3Δ) to floor(now,Δ), validate, upsert, advance watermark."""
    def __init__(self, source: DataSource, writer: LakeWriter,
                 checkpoints: CheckpointStore, settings: DataConfig) -> None: ...
    def run(self, instruments: Sequence[Instrument], timeframes: Sequence[Timeframe],
            datasets: Sequence[Dataset], *, since_ms: int | None = None,
            until_ms: int | None = None) -> BackfillReport: ...
        """Iterates symbols sequentially; a crash mid-run loses at most one
        symbol-year leaf write (atomic), and rerunning resumes from watermarks."""

# alphaforge/data/ingest/updater.py
class LiveUpdater:
    """24/7 follow loop: sleep until floor(now,Δ)+γ each hour, run BackfillJob
    incrementally for 1h, trigger resample to 4h/1d when those boundaries close,
    run inline quality checks on new rows, beat heartbeat."""
    def __init__(self, job: BackfillJob, resampler: Resampler,
                 validator: InlineValidator, ops_db: Path) -> None: ...
    def run_forever(self) -> NoReturn: ...
    def run_once(self, *, now_ms: int | None = None) -> UpdateReport: ...
        """now_ms injectable for tests; never uses wall clock directly inside logic."""
```

Watermark advance rule: `watermark = max(ts_open) + Δ` of rows actually persisted — i.e., the watermark is an `available_at`, so resumption math never mixes open/close conventions.

### 4.4 Resampling 1h → 4h/1d

4h and 1d bars are **always derived from stored 1h bars, never fetched** — one source of truth, guaranteed consistency.

Window: bars are aggregated into windows aligned to **00:00 UTC** (4h windows start 00,04,08,12,16,20; 1d at 00). For a window `W = [T, T+Δ′)` containing 1h bars `b_1..b_n` ordered by time:

```
open(W)   = open(b_1)
high(W)   = max_i high(b_i)
low(W)    = min_i low(b_i)
close(W)  = close(b_n)
volume(W) = Σ_i volume(b_i)            (same for quote_volume, n_trades, taker_buy_volume;
                                        null if ANY constituent is null)
quality_flag(W) = OR_i quality_flag(b_i)   (bitwise)
```

**Completeness rule:** a resampled bar is written only if **all** expected constituent bars (per the calendar: 4 for 4h, 24 for 1d) are present and `quality_flag` does not include `MISSING_NEIGHBOR`-class flags. Otherwise the window is written with flag `INCOMPLETE_AGGREGATE` set and OHLC from available bars — flagged, queryable, but feature code can exclude it explicitly. Resampled bar `available_at = T + Δ′` (close of the *window*), enforced by the PIT reader identically to native bars.

```python
# alphaforge/data/store/resample.py
class Resampler:
    """Deterministic 1h → {4h, 1d} aggregation with completeness flags."""
    def resample_symbol(self, instrument: Instrument, target: Timeframe,
                        start_ms: int, end_ms: int) -> pa.Table: ...
    def run_incremental(self, instruments: Sequence[Instrument],
                        targets: Sequence[Timeframe]) -> None: ...
```

---

## 5. Data Quality

### 5.1 Architecture

Two execution modes of the same checks:
- **Batch:** `af quality run` over any date range → full `ValidationReport` artifact.
- **Inline:** `LiveUpdater` runs the cheap subset (sanity, duplicate, gap-vs-previous, outlier) on each new batch before upsert; failures set `quality_flag` bits or, for hard failures (negative price), reject the row and log `severity=error`.

```python
# alphaforge/data/quality/checks.py
class Finding(NamedTuple):
    check: str; severity: Literal["info","warn","error"]
    instrument_id: str; ts_ms: int | None; message: str; payload: dict[str, Any]

class Check(Protocol):
    name: str
    def run(self, df: pd.DataFrame, instrument: Instrument,
            timeframe: Timeframe, calendar: TradingCalendar) -> list[Finding]: ...

class GapCheck: ...
class DuplicateCheck: ...
class OhlcSanityCheck: ...
class BadPrintCheck: ...
class StaleSeriesCheck: ...
class CrossSymbolDowntimeCheck: ...   # operates on the full panel, not per-symbol

# alphaforge/data/quality/report.py
class ValidationReport:
    """Aggregates findings; persists JSON + renders Markdown; writes summary rows
    to ops.sqlite (quality_findings)."""
    def add(self, findings: Iterable[Finding]) -> None: ...
    def persist(self, out_dir: Path, run_id: str) -> Path: ...
    @property
    def worst_severity(self) -> str: ...

def run_validation(reader: PITDataReader, instruments: Sequence[Instrument],
                   timeframe: Timeframe, start_ms: int, end_ms: int,
                   settings: QualityConfig) -> ValidationReport: ...
```

### 5.2 Exact check definitions and defaults

**Gap detection.** Expected opens `E = calendar.expected_bar_opens(tf, max(start, listing_ts), min(end, delisting_ts or end))`; missing `M = E \ actual`. Consecutive missing opens are merged into gap intervals. Severity: `warn` if gap ≤ 3 bars, `error` if longer. Note: Binance has genuine maintenance gaps (e.g., 2021-04 outages) — see downtime check.

**Cross-symbol downtime classification.** For each missing timestamp `t`, compute the fraction of active universe symbols also missing `t`:
`f(t) = |{s : t missing for s}| / |{s active at t}|`. If `f(t) ≥ 0.8` (**default 0.8**) classify as `EXCHANGE_DOWNTIME` (`info` severity, expected; recorded in report so backtests can exclude the window) else `SYMBOL_GAP` (`warn`). Justification: exchange outages hit (nearly) all symbols simultaneously; 0.8 tolerates a few symbols whose fetches straddled the outage.

**Duplicates.** `count(ts_open) > 1` within a partition → `error`. Should be impossible post-writer (writer dedupes); the check exists to catch writer regressions.

**OHLC sanity (hard rejects at ingest, `error` in batch).**
```
high >= max(open, close)
low  <= min(open, close)
low  <= high
open, high, low, close > 0
volume >= 0;  quote_volume >= 0 (if present)
```

**Bad-print / outlier detection (flag-only, never modifies data).** Let `r_t = ln(close_t / close_{t-1})`. Robust scale over a rolling window of **W = 720 bars** (30 days of 1h — long enough to be stable, short enough to track crypto vol regimes):

```
MAD_t  = median_{i ∈ [t-W, t)} | r_i − median(r) |
σ_t    = 1.4826 · MAD_t                      (Gaussian-consistent MAD scaling)
z_t    = r_t / σ_t
```

Flag `BAD_PRINT_SUSPECT` iff **all three** hold:

1. `|z_t| > k`, **k = 8** — crypto 1h returns genuinely reach 5–6 robust sigmas during liquidation cascades; 8 keeps real crashes (which we must NOT flag) out while catching fat-finger prints. Flag-only design makes a false positive cheap.
2. **Volume disconfirmation:** `volume_t < v_frac · median(volume_{t-W..t-1})`, **v_frac = 0.25** — a real 8σ move comes with elevated volume; a bad print does not.
3. **Reversion:** `|ln(close_{t+1} / close_{t-1})| < 0.5 · |r_t|` — the price snaps back. (In the inline/live path `close_{t+1}` doesn't exist yet; inline applies only conditions 1–2 and sets the weaker `OUTLIER_RETURN` flag; the batch run upgrades/clears it next day.)

Additionally flag `WICK_ANOMALY` if `(high_t − low_t) / close_t > 0.5` with condition 2 — catches single-print wicks that don't move the close.

**Stale series.** `close_t == close_{t-1}` and `volume_t == 0` for ≥ **24 consecutive bars** → `warn` (halted/zombie listing; universe builder consumes this).

### 5.3 `quality_flag` bitmask

```
0x00 CLEAN
0x01 OUTLIER_RETURN        (inline, conditions 1–2)
0x02 BAD_PRINT_SUSPECT     (batch, conditions 1–3)
0x04 WICK_ANOMALY
0x08 STALE
0x10 EXCHANGE_DOWNTIME_ADJACENT   (bar immediately after a downtime gap; its return spans the gap)
0x20 INCOMPLETE_AGGREGATE  (resampled bars only)
```

Feature code receives flags and applies a declared policy (Section 7); default policy: treat `BAD_PRINT_SUSPECT` closes as NaN then forward-fill ≤ 2 bars.

### 5.4 Validation report artifact

`data/quality/reports/<run_id>/report.json` (machine: full findings list, config used, git SHA, package version) + `report.md` (human summary: per-check counts, worst offenders table, gap timeline). Summary row per (symbol, check) into `ops.sqlite:quality_findings`. The `af quality run` exit code is non-zero if `worst_severity == "error"` — so it can gate research jobs.

**UTC discipline enforcement:** `alphaforge/core/time.py:require_utc()` is called at every public API boundary that accepts datetimes; pyarrow schemas declare `tz=UTC` so a naive write fails schema validation; a unit test greps the codebase for `datetime.now()`/`datetime.utcnow()` and fails if found outside `core/time.py` (only `utc_now_ms()` is allowed).

---

## 6. Universe Management

### 6.1 Definition (exact math)

Universe `perp_top40`, rebalanced at `rebalance_ts` = **first day of each month, 00:00 UTC**, using only data with `available_at ≤ rebalance_ts` (the builder reads via `PITDataReader` with `as_of_ms = rebalance_ts` — peeking is structurally impossible).

For each candidate perp `s`, daily dollar volume on UTC day `d`:

```
QV(s, d) = Σ_{bars b in day d} quote_volume(b)        # exact, from raw klines
           fallback: Σ volume(b) · close(b)            # if quote_volume null
ADV30(s) = median over the last 30 complete UTC days d of QV(s, d)
```

Median (not mean) over **30 days**: robust to single-day volume spikes from listings/news; 30 days matches the monthly rebalance cadence.

**Eligibility filters** (all must pass; failures recorded with `reason`):
- `min_history`: first bar ≥ **90 days** before `rebalance_ts` (features need ≥ 720-bar lookbacks plus labeling horizon).
- ≥ **95%** bar completeness over the 30-day window (excludes zombie listings).
- Quote = USDT; **exclude** stablecoin bases (`USDC, FDUSD, TUSD, DAI, USDP, EUR...` — config list) and leveraged tokens (`*UP`, `*DOWN`, `*BULL`, `*BEAR` suffix match).
- `status == active` at `rebalance_ts`.

**Ranking + hysteresis.** Rank eligible instruments by `ADV30` descending. With **N_in = 40, N_out = 60**:

```
member_after(s) = True   if rank(s) ≤ N_in                        ("enter"/"stay")
                = member_before(s)  if N_in < rank(s) ≤ N_out     (hysteresis band: incumbents stay)
                = False  if rank(s) > N_out or ineligible          ("exit")
```

N_out = 1.5 × N_in: wide enough that rank noise around the cutoff doesn't churn membership monthly (turnover costs nothing in data terms but creates spurious entry/exit effects in backtests), tight enough that genuinely faded coins leave within a month or two. **Forced exit regardless of band:** delisting or eligibility failure, with `effective_to = min(rebalance_ts, delisting_ts)`.

### 6.2 Survivorship-bias-free guarantees

- Bars of delisted instruments are **never deleted**; `instruments.delisting_ts` is set when the symbol vanishes from `list_instruments()` output while history exists.
- Backtests obtain the tradable set per timestamp via `reader.universe_members(universe, as_of_ms=t)` — there is no "current universe" constant anywhere in the codebase.
- `rebuild_history` reconstructs membership from the earliest data forward, month by month, each month using only PIT data — so adding the universe later (or changing parameters) regenerates an unbiased history. Snapshots table records every decision including rejections, for audit.
- Listing-date probe: at first backfill of a symbol, binary-search `fetch_ohlcv` for the earliest available bar; store as `listing_ts` (exchange info's `onboardDate` is used when present, cross-checked against first bar).

```python
# alphaforge/data/universe/builder.py
class UniverseBuilder:
    """Liquidity-ranked PIT universe with entry/exit hysteresis."""
    def __init__(self, reader: PITDataReader, store: UniverseStore,
                 cfg: UniverseConfig) -> None: ...
    def snapshot(self, *, as_of_ms: int,
                 prior_members: frozenset[str]) -> pd.DataFrame:
        """One rebalance decision; returns the snapshots-schema frame."""
    def rebuild_history(self, *, start_ms: int, end_ms: int) -> None:
        """Walk monthly rebalances chronologically; emit membership intervals + snapshots."""
    def update_current(self, *, as_of_ms: int) -> None:
        """Live-loop entrypoint: apply this month's rebalance if due; close intervals on delistings."""
```

---

## 7. Feature Store (no train/serve skew — the critical invariant)

### 7.1 Design principle

**One registry, one function body, two callers.** A feature is a registered pure function of a `FeatureContext`. Research/backtest calls `FeatureEngine.compute_history(...)` (vectorized over years, cached); the live loop calls `FeatureEngine.compute_asof(...)` (minimal window, no cache). **Both call the identical function object**; the only difference is the window of PIT data placed in the context. Skew is then reduced to window-boundary bugs — which the parity test (7.5) catches mechanically.

### 7.2 Spec, registry, context

```python
# alphaforge/features/spec.py
@dataclass(frozen=True)
class FeatureSpec:
    """Identity + contract of one feature. params and version participate in the
    cache key; lookback_bars tells the live path exactly how much history to load."""
    name: str                       # "ret_log"
    version: str                    # "1" — bump on ANY semantic change to the fn
    params: Mapping[str, Any]       # {"window": 24} — canonical-JSON-serializable
    timeframe: Timeframe
    lookback_bars: int              # max history the fn touches, INCLUDING label of t
    inputs: frozenset[Dataset]      # {Dataset.OHLCV} / {Dataset.OHLCV, Dataset.FUNDING}
    nan_policy: NanPolicy = NanPolicy.PROPAGATE   # explicit, part of the contract

    @property
    def key(self) -> str:
        """sha256 over canonical JSON of (name, version, sorted params, timeframe,
        schema_version, code_hash) — first 16 hex chars. code_hash =
        sha256(inspect.getsource(fn)) captured at registration, so editing the
        function body without bumping version still invalidates the cache."""

# alphaforge/features/registry.py
class FeatureRegistry:
    """Global singleton mapping name -> (spec_factory, fn). Importing
    alphaforge.features.library populates it; live and research import the same module."""
    def register(self, name: str, version: str, *, lookback_bars: int,
                 inputs: frozenset[Dataset], timeframe_agnostic: bool = True
                 ) -> Callable[[FeatureFn], FeatureFn]: ...
    def get(self, name: str) -> tuple[FeatureFn, FeatureMeta]: ...
    def spec(self, name: str, *, timeframe: Timeframe, **params: Any) -> FeatureSpec: ...

FeatureFn = Callable[["FeatureContext", Mapping[str, Any]], pd.Series]
# Returns a Series indexed by (ts_decision, instrument_id); ts_decision = bar CLOSE time.

# alphaforge/features/context.py
class FeatureContext:
    """PIT-windowed data handed to feature fns. The engine constructs it so the
    last visible bar closes exactly at the decision timestamp — fns CANNOT
    request future data because the context simply does not contain it."""
    @property
    def ohlcv(self) -> pd.DataFrame: ...        # MultiIndex (ts_open, instrument_id)
    @property
    def funding(self) -> pd.DataFrame: ...      # only rows with available_at <= decision ts
    @property
    def decision_ts(self) -> pd.DatetimeIndex: ...   # timestamps to emit values for
    @property
    def timeframe(self) -> Timeframe: ...
```

Example registration (pattern the library follows):

```python
@registry.register("ret_log", version="1", lookback_bars=2, inputs=frozenset({Dataset.OHLCV}))
def ret_log(ctx: FeatureContext, params: Mapping[str, Any]) -> pd.Series:
    """r_t = ln(close_t / close_{t-w}); value indexed at the close time of bar t."""
    w = int(params.get("window", 1))
    close = ctx.ohlcv["close"].unstack("instrument_id")
    out = np.log(close / close.shift(w))
    out.index = out.index + ctx.timeframe.delta     # relabel open -> close = decision ts
    return out.stack().rename("value")
```

The **open→close index relabeling** happens in exactly one sanctioned helper (`ctx.to_decision_index(df)` — the snippet above shown expanded for clarity); feature outputs are always indexed by decision time. The engine asserts `output.index ⊆ ctx.decision_ts × instruments`.

### 7.3 Engine and cache

```python
# alphaforge/features/engine.py
class FeatureEngine:
    def __init__(self, reader: PITDataReader, cache: FeatureCache,
                 registry: FeatureRegistry) -> None: ...

    def compute_history(self, specs: Sequence[FeatureSpec],
                        instrument_ids: Sequence[str],
                        start_ms: int, end_ms: int,
                        *, use_cache: bool = True) -> pd.DataFrame:
        """Research/backtest path. Per spec: cache hit -> load; miss -> build context
        with data window [start - lookback·Δ, end), as_of = end of each decision ts
        (vectorized: PIT-safe because only finalized bars enter the lake and funding
        is filtered by available_at <= each decision ts via merge_asof), run fn,
        write cache. Returns wide frame: MultiIndex (ts, instrument_id) × one column
        per spec, column name = f"{name}__{params_slug}"."""

    def compute_asof(self, specs: Sequence[FeatureSpec],
                     instrument_ids: Sequence[str], *, as_of_ms: int) -> pd.DataFrame:
        """Live path. Loads exactly max(lookback_bars)+3 bars ending at the last bar
        with close <= as_of, builds context with decision_ts = [that close], runs the
        SAME fns, returns one row per instrument. No cache."""
```

Vectorized-history PIT note (important implementation detail): for OHLCV-only features, computing the whole history in one pass is PIT-safe *because* causality is positional — `shift`/`rolling` only look backward, and the context contains only finalized bars. For **funding** (irregular availability), the context pre-joins funding onto the decision grid with `pd.merge_asof(decision_ts, funding, left_on=ts, right_on=available_at, direction="backward")` so each decision row sees only funding available at that moment. Feature fns consume the already-aligned column and cannot mis-join.

```python
# alphaforge/features/cache.py
class FeatureCache:
    """Content-addressed parquet cache: a key change (params/version/code/schema)
    is a different directory; stale entries are never read, only garbage-collected."""
    def load(self, spec: FeatureSpec, instrument_ids: Sequence[str],
             start_ms: int, end_ms: int) -> pd.DataFrame | None: ...
    def store(self, spec: FeatureSpec, df: pd.DataFrame) -> None: ...
    def gc(self, keep_keys: set[str]) -> int: ...
```

Cache layout and schema:

```
data/features/name=ret_log/key=3fa9c2d41b07ee21/year=2024/data.parquet
   columns: ts timestamp[ms,UTC]   # decision time (bar close)
            instrument_id string
            value float64           # float64 so parity checks are exact; cast to
                                    # float32 only inside the ML training area
   parquet metadata: full spec JSON (name, version, params, code_hash,
                     alphaforge_version, created_at) — self-describing artifacts
```

### 7.4 Dataset assembly (handoff to the ML area)

```python
class DatasetBuilder:
    """Assembles the model matrix: features (this module) × labels (ML area plugs in
    a LabelFn with the same Context pattern) × universe membership mask, with a
    manifest hash so any trained model records exactly which data built it."""
    def build(self, feature_specs: Sequence[FeatureSpec], universe: str,
              timeframe: Timeframe, start_ms: int, end_ms: int) -> DatasetHandle: ...

@dataclass(frozen=True)
class DatasetHandle:
    manifest: dict[str, Any]      # specs, universe def, date range, git SHA, lib versions
    manifest_hash: str
    frame: pd.DataFrame           # rows only where instrument ∈ universe at ts
```

Universe masking rule: a row `(t, s)` exists iff `s ∈ universe_members(as_of=t)` — applied here, once, so neither features nor models ever see out-of-universe rows inconsistently.

### 7.5 Parity verification (the anti-skew safeguard, run in CI and nightly)

```python
# alphaforge/features/parity.py
def verify_parity(engine: FeatureEngine, specs: Sequence[FeatureSpec],
                  instrument_ids: Sequence[str], sample_ts_ms: Sequence[int],
                  *, atol: float = 0.0) -> ParityReport:
    """For each sampled historical timestamp T: compute features via
    compute_history (batch, cached) and via compute_asof(as_of=T) (live path).
    Assert exact equality (atol=0 — both paths are deterministic float64 on the
    same data; ANY difference is a window/alignment bug). Default sample: 16
    random Ts per month over the last 6 months."""
```

A second mandatory test, **truncation invariance** (anti-lookahead): for random T, compute features over `[start, T]` and over `[start, T + 30 days]`; values at all `ts ≤ T` must be bit-identical. Catches any feature that accidentally uses centered windows, full-sample normalization, or future rows.

---

## 8. Config, Secrets, Logging

### 8.1 Config: **pydantic-settings v2** (not Hydra)

Rationale: this is one long-running application plus CLI jobs, not a sweep-orchestration problem. pydantic-settings gives typed, validated, IDE-completable config with env-var overrides in ~100 lines; Hydra brings OmegaConf's untyped DictConfig, working-directory mutation surprises, and composition machinery we don't need. (Hyperparameter sweeps in the ML area use plain loops + the dataset manifest.)

```python
# alphaforge/config/settings.py
class PathsConfig(BaseModel):
    root: Path = Path("~/alphaforge").expanduser()
    lake: Path | None = None        # default: root / "data" / "lake"  (validator fills)
    features: Path | None = None
    ops_db: Path | None = None
    reports: Path | None = None

class DataConfig(BaseModel):
    exchange_id: str = "binance"
    markets: list[MarketType] = [MarketType.PERP, MarketType.SPOT]
    timeframes: list[Timeframe] = [Timeframe.H1]
    derived_timeframes: list[Timeframe] = [Timeframe.H4, Timeframe.D1]
    backfill_start: datetime = datetime(2020, 1, 1, tzinfo=UTC)
    page_limit: int = 1000
    bar_grace_ms: int = 30_000
    funding_lag_ms: int = 300_000
    refetch_overlap_bars: int = 3

class QualityConfig(BaseModel):
    outlier_k_sigma: float = 8.0
    outlier_window_bars: int = 720
    outlier_volume_frac: float = 0.25
    downtime_cross_frac: float = 0.8
    stale_bars: int = 24

class UniverseConfig(BaseModel):
    name: str = "perp_top40"
    n_in: int = 40
    n_out: int = 60
    adv_window_days: int = 30
    min_history_days: int = 90
    min_completeness: float = 0.95
    excluded_bases: list[str] = ["USDC","FDUSD","TUSD","DAI","USDP","BUSD","EUR","AEUR"]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALPHAFORGE__",
                                      env_nested_delimiter="__", env_file=".env")
    env: Literal["research","paper","live"] = "research"
    paths: PathsConfig = PathsConfig()
    data: DataConfig = DataConfig()
    quality: QualityConfig = QualityConfig()
    universe: UniverseConfig = UniverseConfig()
    log_level: str = "INFO"

def load_settings(config_file: Path | None = None) -> Settings:
    """Precedence (low→high): code defaults → configs/base.yaml → configs/{env}.yaml
    → environment variables → .env. YAML loaded with yaml.safe_load and fed through
    Settings.model_validate (deep-merged dicts)."""
```

Every job logs the **fully resolved settings JSON + git SHA** into `run_log.detail_json` — reproducibility requires knowing exactly what config produced an artifact.

### 8.2 Secrets

- v1 data layer needs **no secrets** (public endpoints). Broker keys (later area) follow this policy now:
- Lookup order: macOS Keychain via `keyring` (`keyring.get_password("alphaforge", "binance_api_key")`) → env var `ALPHAFORGE__BROKER__API_KEY` → fail loudly. Never in YAML, never in git; `.env` is gitignored and `.env.example` documents names only. A pre-commit hook (`gitleaks`) guards against accidents.

### 8.3 Logging / observability

- **structlog** (over loguru): structured key-value JSON logs are queryable with DuckDB (`read_json_auto('var/log/*.jsonl')`) and ship cleanly to any cloud sink later. Dual sinks: pretty console (dev) + JSONL file with daily rotation (`var/log/alphaforge-YYYYMMDD.jsonl`).
- Conventions: every log line carries `run_id`, `component`; ingestion logs per-symbol `UpsertStats`; warnings for every dropped/flagged row with full payload.
- 24/7 loop health: `heartbeat` table updated each cycle; `af status` prints watermarks vs. wall clock, last heartbeat age, last quality severity — one command tells you if the system is healthy. (Alerting/notifications: execution area's concern; the table is the interface.)

---

## 9. Research Environment

**marimo** (over Jupyter) as the primary notebook environment: notebooks are plain `.py` files (git-diffable), reactive execution eliminates stale-cell-state bugs (a real source of silent research errors), and `uv run marimo edit notebooks/eda.py` just works. Jupyter remains usable — nothing in the package depends on the notebook layer.

Hard rule enforced by convention + code review: **notebooks contain zero business logic.** They import the package and call it:

```python
# alphaforge/research/session.py
class ResearchSession:
    """One-line wiring for notebooks: loads settings, builds reader/engine/registry.
    Guarantees notebooks exercise the exact production code path."""
    def __init__(self, env: str = "research",
                 config_file: Path | None = None) -> None: ...
    @property
    def reader(self) -> PITDataReader: ...
    @property
    def features(self) -> FeatureEngine: ...
    @property
    def settings(self) -> Settings: ...
    def duckdb(self) -> duckdb.DuckDBPyConnection:
        """Ad-hoc SQL over the lake with views pre-registered:
        ohlcv, funding, instruments, universe_membership."""
```

A checked-in template `notebooks/_template.py` starts every notebook with `sess = ResearchSession()`. Promotion path: a promising notebook computation becomes a registered feature in `features/library/`, gets a spec + tests, and is then available to backtest **and** live identically.

---

## 10. Library Choices (consolidated) + Apple Silicon notes

| concern | choice | rationale / arm64 notes |
|---|---|---|
| packaging | **uv** | pins Python 3.12 itself (system is 3.9), lockfile, `uv run` ergonomics; faster than poetry; native arm64 |
| lint/format | **ruff** (lint+format), **mypy --strict** on `alphaforge.*` | single fast tool; typing is load-bearing for the PIT APIs |
| exchange API | **ccxt** (sync) | unified pagination/rate limits; implicit raw-endpoint access for extended klines; pure Python (no arm64 issues). WebSocket (`ccxt.pro` namespace, free) deliberately deferred — hourly REST suffices at 1h bars |
| dataframes | **pandas ≥ 2.2** + **numpy ≥ 2.0** | LightGBM/sklearn interop; one dataframe library across the codebase (no pandas/polars duplication = no subtle semantic skew). Native arm64 wheels |
| storage | **pyarrow ≥ 16**, **duckdb ≥ 1.0** | both ship arm64 wheels; DuckDB hive partitioning + filter pushdown |
| ops state | **sqlite3** (stdlib) WAL | zero deps, concurrent-safe enough |
| retry | **tenacity** | declarative backoff policies |
| config | **pydantic ≥ 2.7**, **pydantic-settings** | see 8.1; pydantic-core arm64 wheel fine |
| secrets | **keyring** | macOS Keychain backend is native |
| logging | **structlog** | see 8.3 |
| CLI | **typer** | typed subcommands map 1:1 to job classes |
| tests | **pytest**, **hypothesis**, **freezegun** | property tests for resampler/PIT; time-freezing for updater scheduling tests |
| notebooks | **marimo**, plotly | see 9 |
| **avoid** | TA-Lib | C build pain on arm64 and opaque formulas — indicators implemented in `features/library/` with explicit math instead |

Apple Silicon gotchas to document in README (affect adjacent areas but pin now): `lightgbm` on macOS requires `brew install libomp` (OpenMP runtime) before `uv add lightgbm`; `hmmlearn` ships arm64 wheels but pin the version in `uv.lock`. Nothing in *this* area needs compiled extras beyond wheel-available packages.

CLI surface (typer app `af`):

```
af instruments refresh                  # SCD2 update from exchange info
af data backfill  [--market perp] [--since 2020-01-01] [--symbols BTCUSDT,...]
af data update    [--once | --follow]   # incremental / 24-7 loop
af data resample  [--target 4h,1d]
af quality run    [--start ... --end ...]
af universe rebuild | af universe update
af features build --set configs/featureset.yaml --start ... --end ...
af features parity                      # CI/nightly skew check
af status                               # watermarks, heartbeat, last quality severity
```

---

## 11. Build Order (dependency-driven)

1. **Skeleton + core** — `pyproject.toml` (uv, ruff, mypy, pytest), `core/time.py` (Timeframe, UTC guards, bar arithmetic + exhaustive unit tests — everything depends on this being right), `core/types.py`, `core/errors.py`, `core/logging.py`, `config/settings.py`. *Gate: `floor_ts`/`next_bar_close` property tests pass.*
2. **Instrument model + symbols + calendar** — `core/instruments.py`, `core/symbols.py`, `core/calendar.py`; `data/schemas.py` (all pyarrow schemas). *Gate: SCD2 round-trip test.*
3. **Storage layer** — `store/lake.py`, `store/writer.py` (atomic upsert + dedupe + partial-bar write-guard), `store/reader.py` (PIT predicates). *Gate: golden-file tests; PIT test proving a bar is invisible at `as_of = close − 1ms` and visible at `close`.*
4. **CCXT source + backfill + checkpoints** — `sources/ccxt_source.py`, `ingest/{retry,checkpoints,backfill}.py`, `af data backfill`. First real data lands. *Gate: kill -9 mid-backfill, rerun, byte-identical lake.*
5. **Quality** — `quality/{checks,report}.py`, `af quality run` over the freshly backfilled history; tune nothing until you've *seen* real findings.
6. **Resampler** — `store/resample.py` (+ hypothesis test: resample(random 1h panel) satisfies the aggregation identities; 4h-of-1h equals direct 1d-of-1h composition).
7. **Universe** — `universe/{builder,store}.py`, `af universe rebuild` over full history. *Gate: at least one historically delisted symbol appears in past membership.*
8. **Feature store** — `features/{spec,registry,context,engine,cache,parity}.py` + 3–5 library features. *Gate: parity + truncation-invariance tests green.*
9. **Live updater** — `ingest/updater.py`, heartbeat, `af status`; run `af data update --follow` for 48h and verify watermarks track wall clock and quality stays clean.
10. **Research session + notebook template** — `research/session.py`, `notebooks/_template.py`.

Steps 4–5 and 6–7 are parallelizable; everything downstream of step 3 depends on the reader/writer contract being frozen first.

---

## 12. Top 5 Silent-Wrong-Results Risks and Safeguards

1. **Open-labeled vs close-labeled bar confusion → systematic 1-bar lookahead** (features at decision time T secretly include the bar that closes at T+1h; backtests look brilliant, live trading doesn't). *Safeguards:* `ts_open` is the only stored label; availability `= ts_open + Δ` is computed in exactly one place (PIT reader); feature outputs are re-indexed to decision time by one sanctioned helper; the **truncation-invariance test** (7.5) fails CI if any feature value at T changes when future data is appended.

2. **In-progress (partial) bar persisted as final** — the live loop ingests the currently-forming candle; its close mutates later, so live features were computed on data that "changes history." *Safeguards:* updater requests only `until = floor(now, Δ)` with 30s grace; **writer hard-drops rows where `ts_open + Δ > ingested_at`**; 3-bar overlap re-fetch with keep-latest dedupe corrects anything that slipped through; ingestion logs every dropped row.

3. **Funding rate availability mishandled** — joining funding by `ts_funding` lets a 16:00 decision see the 16:00 settlement before it propagated, or worse, vectorized joins leak the *next* rate backward. *Safeguards:* explicit `available_at = ts_funding + 5 min` column; PIT reader filters on it; the feature context pre-joins funding via backward `merge_asof` on `available_at` so feature authors physically cannot mis-align it.

4. **Universe lookahead / survivorship bias** — ranking with volume data from after the rebalance date, or building "the universe" from today's listings (dead coins vanish, long-bias inflation of every backtest). *Safeguards:* builder receives only a `PITDataReader` pinned to `as_of = rebalance_ts`; membership is an interval table consumed per-timestamp; history is rebuilt chronologically; a regression test asserts known-delisted symbols hold historical membership; snapshots record every decision for audit.

5. **Train/serve skew in features** — research uses a vectorized pandas path, live uses a "quick reimplementation," and a NaN-fill or window-boundary difference quietly degrades live performance with no error anywhere. *Safeguards:* single registry, single function body for both paths; cache keys include `code_hash` (function-source SHA) so silent edits can't serve stale values; declared `lookback_bars` makes the live window deterministic; **`af features parity`** compares batch vs as-of computation at sampled timestamps with `atol=0` in CI and nightly; `uv.lock` pins pandas/numpy so library-version drift can't alter semantics between research and the live host.

(Honorable mentions handled in the design: duplicate bars double-counting volume — writer-level dedupe + checks; silent gap-filling — forbidden in the lake, explicit `nan_policy` per feature; naive-datetime contamination — UTC schema enforcement + `utcnow` grep test; bad prints poisoning vol estimates — flag-only quarantine with robust MAD scaling.)

---

### Critical Files for Implementation
- /Users/arhancanli/alphaforge/src/alphaforge/core/time.py
- /Users/arhancanli/alphaforge/src/alphaforge/data/store/reader.py
- /Users/arhancanli/alphaforge/src/alphaforge/data/store/writer.py
- /Users/arhancanli/alphaforge/src/alphaforge/data/ingest/backfill.py
- /Users/arhancanli/alphaforge/src/alphaforge/features/engine.py
