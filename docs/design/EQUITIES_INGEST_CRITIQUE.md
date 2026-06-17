# Correctness Critique — Equities Flat-Files Bar Ingest

**Role:** Correctness critic (PIT / survivorship / lookahead / schema / resumability).
**Verdict: BLOCK.**
**Reviewed at:** working tree of `/Users/arhancanli/alphaforge`, HEAD `96b23d1`, date 2026-06-17.

---

## 0. Headline finding — the build does not exist

The task was to BUILD (1) `PolygonFlatFilesSource`, (2) the corporate-actions adjustment
wiring, and (3) the `af data ingest-equities` CLI, all with synthetic-fixture tests
(including the survivorship regression). **None of it was implemented.** The only artifact
produced is the spec `docs/design/EQUITIES_INGEST.md` itself. There is nothing to verify
against, so this is a hard BLOCK: a critic cannot certify PIT/survivorship/schema/resume on
code that was never written.

Evidence (every check run against the live tree, no inference):

| Deliverable (spec §) | Expected path | State |
|---|---|---|
| `PolygonFlatFilesSource`, `_parse_day_csv`, `_Boto3FlatFilesClient`, `day_aggs_key` (§1.3–1.4, §5) | `src/alphaforge/data/sources/polygon_flatfiles.py` | **MISSING** (`ls` → No such file) |
| `EquitiesFlatFilesJob`, `EquitiesIngestResult/Report` (§1.5, §5) | `src/alphaforge/data/ingest/equities.py` | **MISSING** |
| Source unit tests incl. fake S3 client (§4.1) | `tests/unit/test_polygon_flatfiles.py` | **MISSING** |
| Pipeline + **survivorship regression** (§4.2–4.3) | `tests/unit/test_equities_ingest.py` | **MISSING** |
| CLI tests (§4.4) | `tests/unit/test_data_cmds_equities.py` | **MISSING** |
| `boto3` dependency (§0, §5) | `pyproject.toml` / `uv.lock` | **MISSING** (`grep boto3` → 0 hits in either) |
| `af data ingest-equities` command (§3) | `src/alphaforge/cli/data_cmds.py` | **MISSING** (`grep ingest-equities` → none) |
| Schema promotion `Dataset.CORPORATE_ACTIONS` + `CORPORATE_ACTIONS_SCHEMA` (§2.1, the "HARD prerequisite") | `src/alphaforge/data/schemas.py`, `data/store/writer.py` | **NOT DONE** — enum has only `ohlcv/ohlcv_4h/ohlcv_1d/funding/universe_membership`; `NATURAL_KEY_COLUMN` has no `corporate_actions` entry; the schema still lives provisionally in `polygon_source.py` exactly as the pre-build state |

`git status` shows a single untracked file: `docs/design/EQUITIES_INGEST.md`. No stash, no
branch, no recently-modified source file is the ingester (the files touched in the last day
are all the committed scaffold: `polygon_source.py`, `equity_price.py`, `universe/builder.py`,
etc.). `grep -rl 'boto3|files.polygon.io|day_aggs_v1|FlatFiles' --include=*.py` over the repo
(excluding `.venv`) returns **NONE**.

---

## 1. What IS true (the spec's dependencies were verified, so the spec is build-sound)

So the BLOCK is "not built", not "unbuildable". The committed scaffold the spec leans on is
real and the spec describes it accurately:

- `features/library/equity_price.adjusted_close(raw_close, actions, *, tf_ms)` **exists and
  is implemented** (`equity_price.py:143`). Its PIT gate is the correct one:
  `applies = (decision >= avail) & (grid < ex_date)` where `decision = grid + tf_ms`
  (`equity_price.py:201,224`). That is exactly the spec's §2.3 contract — a split/dividend
  folds backward into pre-ex bars (`grid < ex_date`) but only once knowable
  (`decision >= available_at`). It is per-row (a boolean mask per action, no window-end
  dependency) so batch/asof parity holds. **No lookahead** in the adjustment kernel: a future
  split factor cannot bias a past decision because the `decision >= avail` mask zeroes it out
  for any row whose close predates the announcement. This is the load-bearing math the prompt
  worried about, and it is correct in the committed code.
- `CORPORATE_ACTIONS_SCHEMA` + `_validate_corporate_actions` are provisionally in
  `polygon_source.py` (`:128`, `:810`) and absent from `schemas.py` — exactly the pre-promotion
  state §2.1 describes. So §2.1's "promote it" step is a real, pending prerequisite.
- The flat-files layout, the survivorship-free-by-construction argument (per-day panel file
  contains every ticker incl. later-delisted names), and the "lake stays RAW, adjust at feature
  layer" decision are all sound in principle.

The dividend kernel has one honest edge I would have flagged in review had it been in scope
(it is committed, not this build): a dividend whose `ex_date` is **not on the served grid**
is silently skipped (`equity_price.py:236-237`). For a continuous daily session grid that is
fine; flagging it only so the eventual reader/context build (§2.4) guarantees the ex-date row
is always within the served window when a dividend is served. Not a blocker for THIS task.

---

## 2. Why I cannot sign off on the actual deliverable

The whole point of this critique was to adversarially verify five properties of the *built*
ingester. Each is **unverifiable / unmet** because the code is absent:

1. **PIT (ts_open / available_at for daily equities).** No `fetch_day` exists, so there is no
   `ts_open = floor_bar(window_start_ns // 1e6, D1)` to check, and no `available_at = day
   close` mapping to confirm. UNVERIFIABLE — the single most important mapping in the task is
   not written.
2. **Survivorship (delisted ticker retained; regression test).** The headline gate
   `test_delisted_ticker_survives` (§4.3 — the `LEHMQ` + `AAPL` old-day-file test) **does not
   exist**. The property the prompt explicitly calls "the headline gate" is untested. The
   panel approach is survivorship-free in theory, but "the ingester preserves it end-to-end"
   is precisely what the missing regression was supposed to PROVE, and it does not.
3. **Split/dividend adjustment introduces no lookahead into return-based decisions.** The
   kernel (committed) is correct (§1 above), BUT the ingest of the `corporate_actions` dataset
   (§2.2) and the read-path that gates on `available_at` are not built, and the schema is not
   promoted — so there is no end-to-end path to verify "no future split factor biases a past
   signal" against. The mechanical adjustment is fine in isolation; the wiring that would let
   me confirm PIT at the system level is absent.
4. **Schema correctness (daily Timeframe, instrument_id mapping, dedupe).** No table is ever
   produced or `validate_table`'d, no `equity_instrument_id(XUSE, canonical)` mapping is
   written, no `Dataset.OHLCV_1D` write call exists. The "HARD prerequisite" schema promotion
   (§2.1) is itself not done. UNVERIFIABLE.
5. **Resumability (no double-write / no gap; day-watermark monotonic).** No
   `EquitiesFlatFilesJob`, no checkpoint keying, no lock acquisition, no
   `test_resume_skips_checkpointed` / `test_crash_between_write_and_checkpoint`. UNVERIFIABLE.

The no-network / no-live-lake invariant (§6.1) is trivially "satisfied" only because there are
no tests at all — which is itself the failure, not a pass.

---

## 3. Required to clear the BLOCK

Build the deliverable as the spec lays it out (the spec is sound; follow §5 build order):

1. **Schema promotion first** (§2.1): add `Dataset.CORPORATE_ACTIONS` + `CORPORATE_ACTIONS_SCHEMA`
   to `schemas.py`, register in `_SCHEMAS`, add `NATURAL_KEY_COLUMN[CORPORATE_ACTIONS] =
   "ex_date"`; repoint `polygon_source.py` and delete its local copy. Existing
   `test_polygon_source.py` must stay green.
2. `uv add boto3` (+ dev stubs), confirm `mypy --strict` baseline clean.
3. Build `polygon_flatfiles.py` (Protocol-injected S3 client, `_parse_day_csv`,
   `ts_open = floor_bar(ns//1e6, D1)`, `instrument_id = equity_instrument_id(XUSE, canonical)`,
   `validate_table(_, Dataset.OHLCV_1D)`, closed-bar guard) + its fake-S3-client unit tests.
4. Build `equities.py` ingest job (day-watermark checkpoint, shared `var/ingest.lock`,
   per-day isolation) + the pipeline tests **including the `LEHMQ` survivorship regression**.
5. Build the CLI command + its CliRunner tests.
6. Full tree green: `uv run ruff check`, `uv run mypy --strict`, `uv run pytest` (offline).

Re-submit for correctness review once the code exists and `test_delisted_ticker_survives`
passes. The spec is approved as a build plan; the build is the thing that was not delivered.
