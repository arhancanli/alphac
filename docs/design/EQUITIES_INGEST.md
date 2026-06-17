# AlphaForge — Equities Bar Ingest via Polygon S3 Flat Files (build-ready spec)

ARCHITECT spec for the REAL equities-bars path. The committed scaffold (96b23d1) gave us
the REST *reference* adapter (`PolygonEquitiesSource`: `list_instruments` incl. delisted,
`list_splits`, `list_dividends`, and an `fetch_ohlcv` that targets `/v2/aggs`), the
survivorship universe builder, the NYSE calendar, and the price factors with a fully
unit-tested PIT `adjusted_close()`. The problem this spec solves: **`/v2/aggs` is not
entitled on this account; the S3 flat files ARE.** So the bars do not come from REST —
they come from one gzipped CSV per trading day in S3. This document pins exactly how to
build the flat-files bar ingester, how corporate-actions adjustment fits (it does NOT
change — it already lives at the feature layer), the CLI, and the no-network test plan.

This is companion to `docs/design/EQUITIES_SLEEVE.md`; section references like "§1.3" are
to that doc unless prefixed `INGEST §`.

---

## 0. What is genuinely new vs reused

| Concern | Decision |
|---|---|
| **Bar source** | NEW `PolygonFlatFilesSource` (boto3 S3 client). The REST `PolygonEquitiesSource.fetch_ohlcv` (`/v2/aggs`) is **dead on this entitlement** — keep it (works once the aggregates entitlement lands; the integration probe covers it) but it is NOT the ingest path. |
| **Bar shape** | Per-DAY panel files (every ticker that traded that day), NOT per-instrument time series. This drives a NEW ingest pipeline (`EquitiesFlatFilesJob`), because `BackfillJob` walks per-(instrument, dataset) and would re-download the whole day file once per ticker. The day-file is the natural batch + checkpoint unit. |
| **Survivorship** | FREE by construction — the day file contains delisted names too. No Vision-archive merge, no HISTORY-ONLY seeding needed for *bars*. We still seed the SCD2 instrument store (for lifecycle/MIC) from the flat-files universe (INGEST §1.6). |
| **Corp-actions adjustment** | UNCHANGED and ALREADY BUILT. The lake stays RAW. `features/library/equity_price.adjusted_close()` does the PIT split+dividend reconstruction at *feature* time. Splits/dividends come from the committed `PolygonEquitiesSource.list_splits/list_dividends` (REST reference IS entitled). INGEST §2 only pins how those land in the lake as the `corporate_actions` dataset and how the reader/context serve them. |
| **Writer / dedupe / atomic** | REUSED verbatim — `LakeWriter.write(Dataset.OHLCV_1D, tbl, tf=Timeframe.D1, now=...)`. |
| **Resume / checkpoints** | REUSED `CheckpointStore`, but keyed differently: the natural unit is the **day file**, not (instrument, ts). See INGEST §1.5. |
| **Schema** | REUSED `OHLCV_SCHEMA` for bars (`Dataset.OHLCV_1D`). `CORPORATE_ACTIONS_SCHEMA` / `Dataset.CORPORATE_ACTIONS` must be **promoted** from `polygon_source.py` into `data/schemas.py` (it is declared there provisionally today; INGEST §2.1) — a hard prerequisite. |
| **Dependency** | ADD `boto3` (`uv add boto3`). Tests stub the S3 client (in-memory fake, default) — `moto` only for an optional belt-and-braces integration test. |

---

## 1. `PolygonFlatFilesSource` + the ingest pipeline

### 1.1 Confirmed flat-files layout (tested by operator, pinned here)

- Endpoint: `https://files.polygon.io` ; bucket `flatfiles` ; signature_version `s3v4`.
- Daily stock bars key: `us_stocks_sip/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
  (one gzipped CSV per trading day, ~210 KB). No file exists for a non-session day.
- CSV columns (header row present): `ticker, volume, open, close, high, low,
  window_start, transactions`.
  - `window_start` is **nanoseconds** epoch (UTC). The session date open is
    `floor(window_start_ns / 1e6, day)` in ms.
  - One row per ticker that traded that day → the panel is **survivorship-free**.
  - Prices are **UNADJUSTED** (raw). This is exactly what the lake wants (§1.3).

### 1.2 Credentials (env, sourced by operator, NEVER committed)

`POLYGON_S3_ACCESS_KEY_ID`, `POLYGON_S3_SECRET_ACCESS_KEY`, `POLYGON_S3_ENDPOINT`,
`POLYGON_S3_BUCKET`, `POLYGON_API_KEY` (the last is for the REST reference adapter, splits/
dividends). Construction reads them at the edge; a missing key with no injected client
raises `ConfigError` (mirror `PolygonEquitiesSource.__init__`). NO unauthenticated call.

### 1.3 New module + class — `src/alphaforge/data/sources/polygon_flatfiles.py`

A thin S3 client behind a `Protocol` (so tests inject a fake, exactly like
`PolygonClientProtocol`), plus the source that lists / downloads / gunzips / parses.

```python
# src/alphaforge/data/sources/polygon_flatfiles.py
from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any, Final, Protocol

import pyarrow as pa

from alphaforge.core.errors import ConfigError, SchemaError
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms, Timeframe, floor_bar, from_ms, now_ms
from alphaforge.data.schemas import OHLCV_SCHEMA, Dataset, validate_table

__all__ = [
    "DAY_AGGS_PREFIX",
    "FlatFilesClientProtocol",
    "PolygonFlatFilesSource",
    "day_aggs_key",
]

DAY_AGGS_PREFIX: Final[str] = "us_stocks_sip/day_aggs_v1"
"""Flat-files prefix for daily US stock bars (one gzipped CSV per session)."""

_DAY_MS: Final[int] = 86_400_000
_NS_PER_MS: Final[int] = 1_000_000
#: Default MIC for a flat-files ticker. The day-aggs file carries no listing exchange,
#: so flat-files bars use a single synthetic venue segment and the *real* MIC is attached
#: later by the SCD2 record (joined on ticker) via the reference adapter (INGEST §1.6).
#: This keeps bar ids stable and collision-free without a per-row reference lookup.
_FLATFILES_MIC: Final[str] = "XUSE"   # "US equities, exchange-unspecified" — documented sentinel


class FlatFilesClientProtocol(Protocol):
    """The exact S3 surface PolygonFlatFilesSource calls (boto3-shaped, structural)."""

    def list_keys(self, *, prefix: str) -> list[str]:
        """List object keys under ``prefix`` (paginated internally), sorted ascending."""
        ...

    def get_object_bytes(self, *, key: str) -> bytes:
        """Download one object's RAW (still-gzipped) bytes; raises KeyError if absent."""
        ...


def day_aggs_key(d: date) -> str:
    """Session date -> flat-files object key ``.../YYYY/MM/YYYY-MM-DD.csv.gz``."""
    return f"{DAY_AGGS_PREFIX}/{d.year:04d}/{d.month:02d}/{d.isoformat()}.csv.gz"


class PolygonFlatFilesSource:
    """US equities daily bars from the Polygon S3 flat files (the entitled bar path).

    NOT a DataSource subclass: the ABC's per-instrument fetch_ohlcv/fetch_funding shape
    does not fit a per-DAY panel file, and forcing it would re-download each day file once
    per ticker. This source's unit of work is one trading day -> one bar table for EVERY
    ticker that traded. The ingest job (INGEST §1.5) owns the date loop + checkpoints.
    """

    def __init__(
        self,
        *,
        client: FlatFilesClientProtocol | None = None,
        endpoint: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str | None = None,
        mic: str = _FLATFILES_MIC,
    ) -> None:
        if client is None:
            client = _Boto3FlatFilesClient.from_env(   # reads POLYGON_S3_* (INGEST §1.2)
                endpoint=endpoint, access_key_id=access_key_id,
                secret_access_key=secret_access_key, bucket=bucket,
            )   # raises ConfigError on a missing credential
        self._client = client
        self._mic = mic
        self.name = "polygon.flatfiles"

    # ---- listing -------------------------------------------------------------
    def available_sessions(self, *, start: Ms, until: Ms) -> list[date]:
        """Session dates with a day-aggs object whose UTC midnight is in [start, until).

        Lists S3 under the YYYY/MM prefixes covering the span and parses each
        ``YYYY-MM-DD.csv.gz`` key back to a date; returns sorted, de-duplicated dates.
        A non-session day simply has no object (survivorship-/gap-free by absence)."""
        ...

    # ---- fetch one day -------------------------------------------------------
    def fetch_day(self, d: date, *, now: Ms | None = None) -> pa.Table:
        """Download+gunzip+parse one day-aggs CSV -> OHLCV_SCHEMA bar table for ALL tickers.

        Mapping (INGEST §1.4): instrument_id = equity id from (mic, canonical(ticker));
        ts_open = floor_bar(window_start_ns // 1e6, D1) (the UTC day open, 00:00);
        OHLCV from open/high/low/close/volume; quote_volume = close*volume (no vwap in
        flat files — documented fallback, matches the universe ADV ranking); n_trades =
        transactions; quality_flags = 0; ingested_at = wall clock.

        Closed-bar guard: a bar whose close ts_open + D1.ms > now is dropped here (a
        same-day in-progress file should never appear, but the guard is belt-and-braces
        and lets the writer's guard be redundant rather than load-bearing).

        Returns a table conforming to OHLCV_SCHEMA, sorted+unique on (instrument_id,
        ts_open). Raises SchemaError on a malformed CSV (missing column / unparseable
        number) — a bad file fails LOUD, never silently drops the day."""
        raw_gz = self._client.get_object_bytes(key=day_aggs_key(d))
        rows = _parse_day_csv(gzip.decompress(raw_gz))   # INGEST §1.4
        ...
        validate_table(table, Dataset.OHLCV_1D)
        return table
```

Notes that are load-bearing:

- `instrument_id` derivation: reuse `SymbolMapper.equity_instrument_id(mic, canonical)`
  where `canonical = ticker.replace(".", "").replace("/", "").upper()` (the same
  `_canonical_ticker` rule as `polygon_source.py`). Dotted tickers (`BRK.B`) canonicalize
  to `BRKB` exactly as the REST adapter does, so bar ids JOIN the SCD2 record built by the
  reference adapter. **Survivorship regression depends on this matching** (INGEST §3).
- A ticker that ends in a crypto quote token (`BTC`, `ETH`) round-trips intact — it goes
  through `equity_instrument_id`, never `split_exchange_symbol` (critique B4). No change.
- `quote_volume = close * volume`. The flat files carry no VWAP, so the exact-dollar-volume
  path of `polygon_source._dollar_volume` (vwap*v) is unavailable; `close*v` is the
  documented fallback that module already uses when `vw` is absent. The equity universe
  ranks ADV on `quote_volume`, so this is the ADV input — correct and consistent.
- Dataset is `Dataset.OHLCV_1D` (the daily OHLCV family member), tf `Timeframe.D1`.

### 1.4 CSV parse helper (pure, unit-testable in isolation)

`_parse_day_csv(data: bytes) -> list[_Row]` using `csv.DictReader` over a
`io.StringIO(data.decode("utf-8"))`. Per row:
- `ts_open = floor_bar(int(window_start) // _NS_PER_MS, Timeframe.D1)` — ns→ms→day floor.
  (Defensive: flat-files `window_start` is already 00:00 UTC, but the floor makes a stray
  intraday value total and keeps the bar labeled by its session open.)
- numeric coercions via a local `_to_float`/`_to_int` that raise `SchemaError` (not
  `ValueError`) on a non-numeric cell, naming the column + ticker — mirrors
  `polygon_source._opt_float` discipline but non-nullable for OHLCV.
- skip the header; an empty/whitespace `ticker` raises `SchemaError`.
The helper is exported (or at least directly importable) so a fixture-CSV test exercises
it with zero S3 involvement (INGEST §4).

### 1.5 The ingest pipeline — `src/alphaforge/data/ingest/equities.py`

A NEW resumable job. It does NOT reuse `BackfillJob` (per-instrument walk) but mirrors its
durability loop and contracts exactly.

```python
# src/alphaforge/data/ingest/equities.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True, kw_only=True)
class EquitiesIngestResult:
    """Outcome of ingesting ONE session day."""
    session: str            # "YYYY-MM-DD"
    status: ResultStatus    # "ok" | "failed" | "skipped"  (reuse backfill.ResultStatus)
    tickers: int            # distinct instrument ids written this day
    rows: int               # rows handed to the writer (post max-tickers cap + guard)
    error: str = ""

@dataclass(frozen=True, slots=True, kw_only=True)
class EquitiesIngestReport:
    run_id: str
    started: Ms
    finished: Ms
    results: tuple[EquitiesIngestResult, ...]
    # ok_count / failed_count / skipped_count / total_rows / summary() — mirror BackfillReport

class EquitiesFlatFilesJob:
    """Resumable, idempotent daily-bar ingest from the Polygon S3 flat files.

    Durability loop, per session day (mirrors BackfillJob exactly):
        fetch_day -> LakeWriter.write -> CheckpointStore.set(checkpoint for that day) -> next
    A day's checkpoint is advanced ONLY after the write returns. Crash/interrupt resumes
    from the first not-yet-checkpointed session; an overlap re-fetch dedupes in the writer.
    """
    def __init__(
        self,
        source: PolygonFlatFilesSource,
        writer: LakeWriter,
        checkpoints: CheckpointStore,
        *,
        max_tickers: int | None = None,
        lock_path: Path | None = None,
    ) -> None: ...

    def run(self, *, start: Ms, until: Ms, now: Ms | None = None) -> EquitiesIngestReport:
        """Ingest every available session day in [start, until); resume-safe.

        Holds the OS exclusive ingest lock (reuse BackfillJob._exclusive_lock pattern,
        lock_path = var/ingest.lock — the SAME lock, so an equities ingest and a crypto
        backfill cannot race the lake). Lists available_sessions, skips any whose day is
        already checkpointed (resume), and processes the rest in date order. Failure of one
        day is isolated (status='failed') and the run continues; BaseException stamps the
        run-log failed and propagates after the in-flight day's durability point."""
```

#### Checkpoint keying (the one subtle bit — pin it)

`CheckpointStore` is keyed `(Dataset, instrument_id)` with a monotonic ms watermark. The
flat-files unit is a *day*, not an instrument. Two pinned choices, **choose A**:

- **(A) — chosen.** Use a SINGLE reserved key: `(Dataset.OHLCV_1D, _FLATFILES_WATERMARK_ID)`
  where `_FLATFILES_WATERMARK_ID = "__polygon_flatfiles_day_watermark__"` (an id with no
  `:`/`=`/NUL so it never collides with a real canonical id and never reaches
  `lake_relpath`). The watermark stores the **ms of the last fully-written session day's
  open**. Resume = skip every available session whose `session_open_ms <= watermark`.
  Monotonic + crash-safe for free. Cost: a single resume granularity (you cannot "redo day
  N but keep day N+2") — acceptable, days are processed strictly ascending, and `reset()`
  is the operator rewind. This reuses the existing store with ZERO schema change.
- (B — rejected) per-(instrument) watermarks like the crypto path: wrong unit, would
  require reading back what each ticker has, and a delisted ticker that stops appearing
  would never converge. The day-watermark is the correct, simpler model.

`max_tickers` cap: when set, `fetch_day` (or the job, post-fetch) keeps the top-N tickers
**by `quote_volume` that day**, deterministic tie-break by `instrument_id` ascending. This
is a dev/smoke convenience (a full day is ~10k names); it must be documented as
NON-survivorship-safe for research (it changes the membership) and is NEVER the default.
The cap is applied AFTER parsing the full file, so a capped run that later re-runs
uncapped simply adds rows (writer dedupes) — the lake is never poisoned.

#### Closed-bar / partial-day guard

`fetch_day` drops `ts_open + D1.ms > now` rows (a day file for "today" before the session
closed). The writer re-applies the same guard with the same `now` (`LakeWriter.write(...,
tf=Timeframe.D1, now=now)`), so the day-watermark — computed from the written table's max
`ts_open` — can never run ahead of what is durable. Same belt-and-braces as
`BackfillJob._write_batch`.

### 1.6 Instrument-store seeding for equities (lifecycle + real MIC)

Bars are survivorship-free on their own, but the **universe builder** and **adjusted-close**
need the SCD2 `Instrument` records (listed/delisted lifecycle, real listing MIC). Those come
from the committed `PolygonEquitiesSource.list_instruments(as_of=...)` (REST reference IS
entitled — it returns delisted names too). This is a SEPARATE, already-scaffolded path:
`af instruments refresh` wiring should call the equities source's `list_instruments` into the
`InstrumentStore` (the crypto seeder analogue). Pin the contract here, but the seeder edit is
out of this build's file scope (note the gap; INGEST §5 build order):

- The bar `instrument_id` uses the `_FLATFILES_MIC = "XUSE"` sentinel; the reference record
  uses the real MIC (`XNAS`/`XNYS`/...). To JOIN them, the universe read and the factor read
  must address bars by their **flat-files id**. Decision, pinned: **the SCD2 record for an
  equity is stored under the flat-files id** (MIC `XUSE`) so bar partitions, universe
  intervals, and factor reads all key identically; the real listing MIC is carried as an
  Instrument attribute (not in the id). This avoids a per-row MIC lookup at ingest time and
  keeps the id stable across a venue change. (If the team prefers the real MIC in the id, the
  alternative is an ingest-time ticker→MIC map from the reference adapter — heavier; rejected
  for v1. Document whichever is chosen in `EQUITIES_SLEEVE.md §1.1`.)

---

## 2. Corporate-actions adjustment — where it lives, and the exact mechanism

**It does NOT happen at ingest time and the lake is NEVER adjusted.** This is already
designed and the core math is already BUILT and unit-tested. This section pins the wiring so
the critic can verify PIT-correctness.

### 2.1 Promote the schema (HARD prerequisite, blocks everything below)

`CORPORATE_ACTIONS_SCHEMA` and `Dataset.CORPORATE_ACTIONS` are declared **provisionally** in
`data/sources/polygon_source.py` today (with a local validator) and are NOT yet in
`data/schemas.py`. Promote them verbatim:
- Add `CORPORATE_ACTIONS = "corporate_actions"` to `data/schemas.Dataset`.
- Add `CORPORATE_ACTIONS_SCHEMA` to `data/schemas.py` (byte-identical to the literal in
  `polygon_source.py`, incl. the `b"alphaforge.dataset" = b"corporate_actions"` metadata).
- Register it in `_SCHEMAS`, and add `NATURAL_KEY_COLUMN[Dataset.CORPORATE_ACTIONS] =
  "ex_date"` in `data/store/writer.py` (it is the within-leaf dedupe/sort key; a re-fetch of
  an action row dedupes by recency of `ingested_at`, same as funding).
- Then `polygon_source.py` imports both from `data.schemas` and DELETES its local copies +
  `_validate_corporate_actions` (it was always documented as a temporary mirror). The
  source's `fetch_corporate_actions` becomes a real `validate_table(tbl,
  Dataset.CORPORATE_ACTIONS)` call.

`lake_relpath` already forbids `/`,`=`,NUL in ids and the corp-actions id is a normal
canonical id, so partitioning is `corporate_actions/instrument_id=<id>/year=<year>/...`
keyed by `year(ex_date)` — works unchanged.

### 2.2 Ingest the corporate actions (cheap, REST reference)

Splits + dividends come from `PolygonEquitiesSource.fetch_corporate_actions(instrument_id,
since, until)` (already built; uses the entitled `/v3/reference/splits` +
`/v3/reference/dividends`). Each row already carries the PIT `available_at =
knowable_date + CA_PUBLICATION_LAG_MS` (declaration_date when present, else ex/effective)
— the funding-finding-18 discipline. They write via `LakeWriter.write(Dataset.
CORPORATE_ACTIONS, tbl)` (no `tf`/partial-bar guard — it's not OHLCV).

Where this runs: a small `corporate-actions` step inside the equities ingest CLI (INGEST
§3), iterating the instrument ids present in the lake's `ohlcv_1d` dataset (or the SCD2
record). It is per-instrument (the reference endpoints are per-ticker), metered by a
`RateBudget`, and resumable on the existing `(Dataset.CORPORATE_ACTIONS, instrument_id)`
watermark keyed on `ex_date` — i.e. the standard `BackfillJob`-style per-instrument
watermark, which is the RIGHT unit here (unlike bars). **Pin:** corporate actions are NOT
ingested through `EquitiesFlatFilesJob` (different source, different unit); they get their
own tiny loop in the CLI command, reusing `CheckpointStore.set/get`.

### 2.3 The adjustment mechanism (PIT, already implemented)

`features/library/equity_price.adjusted_close(raw_close, actions, *, tf_ms)` — read it; it
is the spec. For each grid row `s` (itself a decision usable at `s + Δ`):

```
CF(i,s) = Π { ratio_a : a split of i, available_at_a <= s+Δ  AND  ex_date_a > s }
DF(i,s) = Π { 1 - cash_a / C_raw(i, ex_open_a) : a dividend, available_at_a <= s+Δ AND ex_date_a > s }
C*(i,s) = C_raw(i,s) · CF(i,s) · DF(i,s)
```

PIT-correctness, for the critic:
- A split/dividend folds **backward** into pre-ex bars (`ex_date > s`) — that is the
  mechanical price adjustment, NOT lookahead: it only restates a past price in post-action
  share terms. A 2:1 split must not print as a -50% return; the adjusted series is
  continuous across the split. This is the data-correctness step the prompt asks for.
- The fold is gated by `available_at <= s + Δ`: an action **announced after** a historical
  decision is invisible to that decision (`decision >= avail` is False), so no future
  corporate action leaks into a past decision beyond the mechanical adjustment. A bar before
  the announcement is genuinely unadjusted to a PIT observer standing there (documented, not
  a bug — splits are typically declared weeks before ex, so all but the earliest pre-announce
  bars fold).
- Dividends use the total-return factor `1 - cash/C_raw(ex_open)` (reinvest-at-ex-price), so
  factor *returns* (momentum/reversal/vol/beta — all return-based) are continuous across the
  dividend. This is why adjustment is a data-correctness requirement for our factors.
- Batch/asof parity: each row's factor depends only on its own `ts_open` and the served
  actions, never on the window end → the batch panel and a live minimal window agree
  bit-for-bit (atol 0). The unit test plants a split and checks cross-row PIT — keep it.

### 2.4 The remaining wiring gap (read path), pinned but in separate files

`equity_price._adjusted_close_panel(ctx)` feature-detects `ctx.corporate_actions` and falls
back to the RAW close panel until it exists. To make the adjusted series live, two edits
land (SEPARATE build — engine/context/reader, NOT this ingest build's files; note the gap):
- `data/store/reader.py`: add `corporate_actions(instrument_ids, *, start, end, as_of)` that
  reads `Dataset.CORPORATE_ACTIONS` with the PIT predicate `available_at <= as_of` (mirror
  `funding()` exactly — same shape, `ex_date` is the natural key, `available_at` is the PIT
  gate; NEVER filter on `ex_date` for visibility).
- `features/context.py`: add `FeatureContext.corporate_actions()` returning the `_CA_COLUMNS`
  frame for the panel's instruments/window, served as-of the context's decision time.

This spec PINS those signatures so the corp-actions ingest (INGEST §2.2) and the adjustment
(INGEST §2.3) are immediately consumable the moment that read-path build lands. **Decision:
adjustment is a DERIVED FEATURE LAYER step, never ingest-time.** Rationale: the lake is
immutable raw (a new split must not silently rewrite stored prices — Polygon `adjusted=true`
is adjusted-to-today and leaks); PIT correctness requires the per-decision-row gate which
only the feature layer (with `as_of`) can apply.

---

## 3. CLI — `af data ingest-equities`

Extend `src/alphaforge/cli/data_cmds.py` with a new command (keep the deferred-import,
`_load_settings`/`_setup_logging`/`_open_stores` idioms; heavy imports inside the body).

```
af data ingest-equities --start YYYY-MM-DD [--until YYYY-MM-DD] [--max-tickers N]
                        [--corp-actions/--no-corp-actions] [--profile P]
```

- `--start` (required): first session, UTC (`_parse_cli_utc`). `--until`: exclusive end,
  default now.
- `--max-tickers N` (`min=1`, default None): the dev cap (INGEST §1.5) — echo a loud
  "NON-survivorship-safe; research must run uncapped" warning when set.
- `--corp-actions/--no-corp-actions` (default ON): after the bar ingest, run the per-
  instrument splits/dividends ingest (INGEST §2.2) for the ids now present in the lake.
- Behaviour: build `PolygonFlatFilesSource` from env (operator has sourced `POLYGON_S3_*`),
  `LakeWriter(LakePaths(settings.paths.lake_dir))`, `CheckpointStore(ops.sqlite)`,
  `lock_path = var/ingest.lock`. Run `EquitiesFlatFilesJob.run(...)`, print a report with the
  existing `_print_report`-style table (session, status, tickers, rows, notes) + a one-line
  summary, **with progress** (echo per-day "session X: tickers=… rows=…" as it goes — the
  job logs per day via structlog and the CLI tees a compact line). Exit 1 if any day failed.
- Resume: rerun the same command — already-checkpointed sessions are skipped; the CLI prints
  "+ K session(s) skipped (already ingested)".

A `--help`-fast contract holds: boto3/pyarrow/duckdb imports stay inside the body.

---

## 4. Synthetic-fixture test plan (NO network, NO live lake — ever)

All under `tests/unit/`, mirroring `test_polygon_source.py` / `test_backfill.py` discipline.
The S3 client is a small in-memory fake; fixture day-CSVs are synthetic.

### 4.1 `tests/unit/test_polygon_flatfiles.py` — source against a fake S3 client

- `FakeFlatFilesClient`: an in-memory `dict[str, bytes]` of `{key: gzipped_csv_bytes}`
  implementing `FlatFilesClientProtocol` (`list_keys(prefix=...)` filters + sorts; 
  `get_object_bytes(key=...)` raises `KeyError` if absent). NO boto3, NO network.
- A `make_day_csv(rows: list[dict]) -> bytes` helper that writes the exact 8-column header +
  rows and `gzip.compress`es it (synthetic fixtures; `window_start` in **ns**).
- Tests:
  - `test_fetch_day_maps_schema` — parsed table conforms to `OHLCV_SCHEMA`, `ts_open` =
    UTC day open (00:00 ms) derived from ns `window_start`, OHLCV/`quote_volume`(=close*vol)/
    `n_trades`/`quality_flags=0` correct, sorted+unique on (id, ts_open).
  - `test_instrument_id_mapping` — `AAPL`→`equity_instrument_id(XUSE,"AAPL")`; `BRK.B`→
    canonical `BRKB`; a `BTC`-suffix ticker round-trips intact (critique B4).
  - `test_available_sessions` — only dates with an object in the fake under the span are
    returned, sorted/deduped; non-session days (no object) absent.
  - `test_closed_bar_guard` — a row whose `ts_open + D1.ms > now` is dropped.
  - `test_malformed_csv_raises` — a non-numeric `close` / empty `ticker` / missing column
    raises `SchemaError` naming the column (fails loud, never silent-drop).
  - `test_missing_object_raises` — `fetch_day` of a date with no S3 object surfaces the
    `KeyError`/`DataGapError` (the job, not the source, decides skip vs fail).
  - `test_no_credentials_raises_configerror` — construct with no client and no env →
    `ConfigError` (monkeypatch env empty); NO network attempt.

### 4.2 `tests/unit/test_equities_ingest.py` — the pipeline (fake S3 + tmp lake)

- Wire `EquitiesFlatFilesJob(FakeFlatFilesSource_or_real_source_with_fake_client, LakeWriter(
  LakePaths(tmp_path)), CheckpointStore(tmp_path/"ops.sqlite"))`. The lake is `tmp_path` — a
  real `LakeWriter` against a temp dir, never the live lake.
- Tests:
  - `test_ingest_writes_partitions` — N synthetic days ingest; read back via `PITDataReader.
    ohlcv(..., tf=D1, as_of=large)` and assert exact rows per ticker per day.
  - `test_resume_skips_checkpointed` — run over days 1-2, then run over days 1-4; assert days
    1-2 are skipped (status='skipped') and the lake has no duplicate rows (writer dedupe; 
    `WriteStats.rows_deduped` accounting on the overlap).
  - `test_crash_between_write_and_checkpoint` — set the day watermark, then re-run; re-fetched
    day dedupes, watermark unchanged-or-advanced, monotonic guard holds.
  - `test_max_tickers_cap` — `max_tickers=2` keeps the top-2 by that day's `quote_volume`,
    deterministic id tie-break; a later uncapped run adds the rest (no poisoning).
  - `test_failed_day_isolated` — a fake that raises on day-3 yields status='failed' for day-3,
    'ok' for the rest, run continues, report.failed_count == 1.
  - `test_lock_is_exclusive` — two jobs sharing `lock_path` → second raises `LockHeldError`
    (reuse the `test_backfill_lock.py` pattern).

### 4.3 SURVIVORSHIP REGRESSION (the headline gate) — in `test_equities_ingest.py`

`test_delisted_ticker_survives`:
- A synthetic old day-file (e.g. `2008-09-15`) whose rows include a KNOWN delisted ticker
  (use `LEHMQ` — the Lehman analogue already used in `test_polygon_source.py`) ALONGSIDE a
  survivor (`AAPL`).
- Ingest the day; read back the lake; assert the `LEHMQ` partition exists and its bar is
  present and correct — **it is NOT silently dropped** even though the ticker is dead today.
- Assert the survivor and the delisted name both land (the panel is survivorship-free by
  construction — the test proves the ingester preserves that property end-to-end, mirroring
  the crypto FTT/LUNA regression in `EQUITIES_SLEEVE §1.4`).

### 4.4 `tests/unit/test_data_cmds_equities.py` — CLI (typer `CliRunner`, fake source)

- Monkeypatch the command's source factory to return a fake-client-backed
  `PolygonFlatFilesSource`; point settings at a `tmp_path` lake + ops db. Assert exit 0,
  report table printed, resume message on second invocation, exit 1 on a failed day, and the
  `--max-tickers` warning is emitted. NO network, NO live lake.

### 4.5 Optional integration (deselected by default) — `tests/integration/test_flatfiles_network.py`

`@pytest.mark.network`, skipped unless `POLYGON_S3_ACCESS_KEY_ID` is set (mirror
`test_polygon_network.py`). Fetches ONE real recent day for a handful of tickers, asserts
shape/sanity only. Optionally a `moto`-mocked S3 variant of the boto3 client to validate the
real `_Boto3FlatFilesClient` wiring without credentials — but the canonical unit suite uses
the in-memory fake, never moto, never network.

---

## 5. Exact file manifest + build order (dependency-correct)

### Files (pin every path)

NEW:
- `src/alphaforge/data/sources/polygon_flatfiles.py` — `PolygonFlatFilesSource`,
  `FlatFilesClientProtocol`, `_Boto3FlatFilesClient`, `day_aggs_key`, `_parse_day_csv`.
- `src/alphaforge/data/ingest/equities.py` — `EquitiesFlatFilesJob`,
  `EquitiesIngestResult`, `EquitiesIngestReport`.
- `tests/unit/test_polygon_flatfiles.py`
- `tests/unit/test_equities_ingest.py`
- `tests/unit/test_data_cmds_equities.py`
- `tests/integration/test_flatfiles_network.py` (optional, network-marked)

EDIT:
- `pyproject.toml` — `uv add boto3` (adds to `[project.dependencies]`); dev-add `moto` only
  if the optional moto test is built. Add `types-boto3`/`boto3-stubs` to the dev group for
  `mypy --strict` (the boto3 client wrapper is the only typed-boundary; keep it thin and
  `# type: ignore[...]`-free by going through the `Protocol`).
- `src/alphaforge/data/schemas.py` — promote `Dataset.CORPORATE_ACTIONS` +
  `CORPORATE_ACTIONS_SCHEMA` + `_SCHEMAS` entry (INGEST §2.1).
- `src/alphaforge/data/store/writer.py` — `NATURAL_KEY_COLUMN[Dataset.CORPORATE_ACTIONS] =
  "ex_date"`.
- `src/alphaforge/data/sources/polygon_source.py` — import the promoted schema from
  `data.schemas`, delete the local copies + `_validate_corporate_actions`.
- `src/alphaforge/cli/data_cmds.py` — the `ingest-equities` command (+ corp-actions step).

SEPARATE BUILD (note the gap, do NOT edit here): `data/store/reader.py.corporate_actions(...)`
and `features/context.py.FeatureContext.corporate_actions()` (INGEST §2.4) — without them the
factors stay correctly raw-fallback; with them the SAME bodies become adjusted, no factor
change. The instrument-store equities seeder wiring (INGEST §1.6) is also separate.

### Build order

1. **Schema promotion** (INGEST §2.1) — add `CORPORATE_ACTIONS` to `schemas.py` + writer key;
   repoint `polygon_source.py`. Run the existing `test_polygon_source.py` → must stay green
   (the source now validates against the promoted schema; byte-identical, so it does).
2. **boto3 dep** — `uv add boto3` (+ stubs in dev). `uv run mypy --strict` baseline clean.
3. **`PolygonFlatFilesSource` + `_parse_day_csv`** + `test_polygon_flatfiles.py` (fake client,
   fixture CSVs). No network.
4. **`EquitiesFlatFilesJob`** + `test_equities_ingest.py` INCLUDING the survivorship
   regression (INGEST §4.3). Real `LakeWriter`/`CheckpointStore` against `tmp_path`.
5. **CLI `ingest-equities`** + `test_data_cmds_equities.py` (CliRunner, fake source).
6. (Optional) `test_flatfiles_network.py` — flips live the moment `POLYGON_S3_*` is set.
7. **Verify the whole tree**: `uv run ruff check`, `uv run mypy --strict`, `uv run pytest`
   (the default `-m 'not network'` keeps it offline). The crypto suite must stay green —
   nothing here touches the crypto ingest path.

Operator (separate, with keys): source `POLYGON_S3_*` + `POLYGON_API_KEY`, then
`af instruments refresh` (equities seeder, INGEST §1.6) → `af data ingest-equities --start
2004-01-02` → (corp-actions runs in the same command) → `af data resample`/universe as needed.
Never run the live ingest from a test.

---

## 6. Invariants the critic must verify

1. **No network / no live lake in any unit test** — S3 client is the in-memory fake; the lake
   is `tmp_path`. `grep` the unit tests for `boto3`/`files.polygon.io` → none.
2. **Survivorship-free end-to-end** — the delisted ticker in an old day-file lands in the lake
   and is readable (INGEST §4.3). Not silently dropped.
3. **Lake stays RAW** — `fetch_day` never adjusts; `adjusted=...` does not exist on this path.
   Adjustment is feature-layer only (INGEST §2.3) and PIT-gated on `available_at`.
4. **PIT corp-actions** — every `corporate_actions` row's `available_at = knowable +
   CA_PUBLICATION_LAG_MS`; reader/context filter on `available_at`, never `ex_date`; a split
   announced after a decision cannot touch that decision's prices.
5. **Resume durability** — day watermark advances only after the write returns; monotonic;
   re-fetch dedupes; `reset()` is the sole rewind. Shares the crypto `var/ingest.lock`.
6. **Schema conformance** — bars validate against `OHLCV_SCHEMA` (`Dataset.OHLCV_1D`),
   actions against the promoted `CORPORATE_ACTIONS_SCHEMA`, before any write.
7. **mypy --strict + ruff clean**, neighbour idioms matched (Protocol-injected client,
   deferred CLI imports, structlog, frozen kw_only dataclasses, epoch-ms everywhere).
