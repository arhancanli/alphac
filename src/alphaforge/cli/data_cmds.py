"""``af data`` — lake ingestion commands: backfill, incremental update, status.

Wiring follows the configs: the lake lives at ``settings.paths.lake_dir``; mutable
operational state (instrument SCD2 versions, ingest watermarks, run log) lives in
``settings.paths.var_dir / "ops.sqlite"``; structlog JSONL goes to
``settings.paths.var_dir / "log"``. All timestamps printed are UTC; all CLI
date/time inputs are interpreted as UTC (a bare ``YYYY-MM-DD`` means UTC midnight).

Heavy imports (ccxt, pyarrow, duckdb) are deferred into command bodies so
``af --help`` / ``af version`` stay fast.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError, SchemaError
from alphaforge.core.time import Ms, Timeframe, floor_bar, from_ms, now_ms, parse_utc
from alphaforge.core.types import MarketType
from alphaforge.data.schemas import Dataset

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pyarrow as pa

    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.ingest.backfill import BackfillJob, BackfillReport
    from alphaforge.data.ingest.checkpoints import CheckpointStore
    from alphaforge.data.ingest.equities import EquitiesIngestReport
    from alphaforge.data.sources.polygon_flatfiles import PolygonFlatFilesSource
    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource

__all__ = ["data_app"]

data_app = typer.Typer(
    name="data",
    help="Lake ingestion: historical backfill, incremental update, watermark status.",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"
_SEVEN_DAYS_MS: Final[int] = 7 * 86_400_000
_VISION_DELAY_S: Final[float] = 0.1
_DEFAULT_DATASETS: Final[str] = "ohlcv,funding"

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _fmt_ts(ms: Ms | None) -> str:
    """Epoch ms UTC → compact ISO string (``-`` for None)."""
    if ms is None:
        return "-"
    return from_ms(ms).isoformat().replace("+00:00", "Z")


def _fmt_age(ms: Ms | None, *, now: Ms) -> str:
    """Watermark age vs ``now`` in hours, one decimal (``-`` for None)."""
    if ms is None:
        return "-"
    return f"{(now - ms) / 3_600_000:.1f}h"


def _parse_cli_utc(value: str, *, param: str) -> Ms:
    """Parse a CLI timestamp to epoch ms UTC.

    Accepts full ISO-8601 with an explicit offset (``2023-01-01T00:00:00Z``) or,
    as a documented CLI convenience, an offset-less ISO string / bare date which is
    interpreted as UTC (``2023-01-01`` = UTC midnight). Anything else is a
    ``typer.BadParameter``.
    """
    try:
        return parse_utc(value)
    except NaiveDatetimeError:
        candidate = f"{value}T00:00:00Z" if len(value) == 10 else f"{value}Z"
        try:
            return parse_utc(candidate)
        except (NaiveDatetimeError, ValueError) as exc:
            raise typer.BadParameter(
                f"{param}: cannot parse {value!r} as a UTC timestamp "
                "(use YYYY-MM-DD or ISO-8601 with an explicit offset)"
            ) from exc
    except ValueError as exc:
        raise typer.BadParameter(f"{param}: invalid timestamp {value!r}: {exc}") from exc


def _parse_datasets(value: str) -> list[Dataset]:
    """``"ohlcv,funding"`` → ``[Dataset.OHLCV, Dataset.FUNDING]`` (order kept)."""
    out: list[Dataset] = []
    for token in value.split(","):
        name = token.strip().lower()
        if not name:
            continue
        try:
            dataset = Dataset(name)
        except ValueError as exc:
            raise typer.BadParameter(
                f"--datasets: unknown dataset {name!r} (choose from: ohlcv, funding)"
            ) from exc
        if dataset not in (Dataset.OHLCV, Dataset.FUNDING):
            raise typer.BadParameter(f"--datasets: {name!r} is not ingestable from a vendor")
        if dataset not in out:
            out.append(dataset)
    if not out:
        raise typer.BadParameter("--datasets: at least one of ohlcv, funding is required")
    return out


def _resolve_instrument_id(token: str) -> str:
    """CLI symbol → canonical instrument id.

    A token containing ``:`` must already be a valid canonical id
    (``BINANCE:PERP:BTCUSDT``); a bare exchange symbol (``BTCUSDT``) resolves to
    the v1 default venue ``BINANCE:PERP:<SYMBOL>``.
    """
    from alphaforge.core.symbols import SymbolMapper

    cleaned = token.strip()
    if not cleaned:
        raise typer.BadParameter("empty instrument symbol")
    try:
        if ":" in cleaned:
            SymbolMapper.parse_instrument_id(cleaned)
            return cleaned
        return SymbolMapper.to_instrument_id("BINANCE", MarketType.PERP, cleaned)
    except SchemaError as exc:
        raise typer.BadParameter(f"invalid instrument {token!r}: {exc}") from exc


def _load_settings(profile: str | None) -> Settings:
    """Load settings, mapping ConfigError to a clean CLI failure."""
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


def _ops_db_path(settings: Settings) -> Path:
    return settings.paths.var_dir / _OPS_DB


@contextmanager
def _open_stores(settings: Settings) -> Iterator[tuple[InstrumentStore, CheckpointStore]]:
    """Open the shared ops SQLite file as (InstrumentStore, CheckpointStore)."""
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.ingest.checkpoints import CheckpointStore

    db = _ops_db_path(settings)
    with InstrumentStore(db) as instruments, CheckpointStore(db) as checkpoints:
        yield instruments, checkpoints


def _build_job(
    settings: Settings, instruments: InstrumentStore, checkpoints: CheckpointStore
) -> BackfillJob:
    """Wire the production BackfillJob from settings (one shared rate budget)."""
    from alphaforge.data.ingest.backfill import BackfillJob
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.sources.ccxt_source import CCXTDataSource
    from alphaforge.data.sources.vision import BinanceVisionClient
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.writer import LakeWriter

    budget = RateBudget()
    return BackfillJob(
        CCXTDataSource(settings.data.exchange, rate_budget=budget),
        BinanceVisionClient(delay_s=_VISION_DELAY_S),
        LakeWriter(LakePaths(settings.paths.lake_dir)),
        checkpoints,
        instruments,
        rate_budget=budget,
        tf=settings.data.timeframe,
        lock_path=settings.paths.var_dir / "ingest.lock",
    )


def _setup_logging(settings: Settings) -> None:
    from alphaforge.core.logging import setup_logging

    setup_logging(settings.paths.var_dir / "log")


def _print_report(report: BackfillReport) -> None:
    """Plain-text report table: every non-skipped pair plus a one-line summary."""
    typer.echo(f"run {report.run_id} [{report.job}]: {report.summary()}")
    shown = [r for r in report.results if r.status != "skipped"]
    if shown:
        typer.echo(
            f"{'instrument':<30} {'dataset':<8} {'status':<8} {'rows':>9} "
            f"{'batches':>7} {'watermark (UTC)':<24} notes"
        )
        for r in shown:
            notes = r.error
            if r.gap_months:
                gaps = f"archive gaps: {','.join(r.gap_months)}"
                notes = f"{notes}; {gaps}" if notes else gaps
            typer.echo(
                f"{r.instrument_id:<30} {r.dataset.value:<8} {r.status:<8} {r.rows:>9} "
                f"{r.batches:>7} {_fmt_ts(r.watermark):<24} {notes}"
            )
    if report.skipped_count:
        typer.echo(f"+ {report.skipped_count} pair(s) skipped (already up to date)")


@data_app.command()
def backfill(
    symbols: Annotated[
        str | None,
        typer.Option(
            "--symbols",
            help="Comma-separated symbols (BTCUSDT or BINANCE:PERP:BTCUSDT). "
            "Default: every instrument in the store.",
        ),
    ] = None,
    top: Annotated[
        int | None,
        typer.Option(
            "--top",
            min=1,
            help="First N LIVE instruments by name (universe ranking lands in Phase 3).",
        ),
    ] = None,
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help="Historical start, UTC (YYYY-MM-DD or ISO-8601). "
            "Default: data.backfill_start from configs.",
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Exclusive end, UTC. Default: now."),
    ] = None,
    datasets: Annotated[
        str,
        typer.Option("--datasets", help="Comma-separated subset of: ohlcv, funding."),
    ] = _DEFAULT_DATASETS,
    batch_days: Annotated[
        int,
        typer.Option("--batch-days", min=1, help="REST chunk size in days (durability cadence)."),
    ] = 30,
    profile: _ProfileOpt = None,
) -> None:
    """Backfill OHLCV/funding history into the lake (resumable; rerun-safe).

    Crash/interrupt at any point and rerun: ingestion resumes from the stored
    watermarks and the writer dedupes any overlap. Exit code 1 if any
    (instrument, dataset) pair failed.
    """
    if symbols is not None and top is not None:
        raise typer.BadParameter("--symbols and --top are mutually exclusive")
    settings = _load_settings(profile)
    _setup_logging(settings)
    dataset_list = _parse_datasets(datasets)
    start_ms = (
        settings.data.backfill_start_ms if start is None else _parse_cli_utc(start, param="--start")
    )
    until_ms = None if until is None else _parse_cli_utc(until, param="--until")
    now = now_ms()

    with _open_stores(settings) as (instruments, checkpoints):
        instrument_ids: list[str] | None = None
        if symbols is not None:
            instrument_ids = [_resolve_instrument_id(tok) for tok in symbols.split(",")]
        elif top is not None:
            live = [i for i in instruments.all_known(as_of=now) if i.delisted_ts is None]
            if not live:
                typer.echo("no live instruments in the store — run `af instruments refresh`")
                raise typer.Exit(1)
            instrument_ids = [i.instrument_id for i in live[:top]]
        job = _build_job(settings, instruments, checkpoints)
        try:
            report = job.run(
                datasets=dataset_list,
                instrument_ids=instrument_ids,
                start_default=start_ms,
                until=until_ms,
                batch_days=batch_days,
                now=now,
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc

    _print_report(report)
    if report.failed_count:
        raise typer.Exit(1)


def _parse_resample_targets(value: str) -> list[Timeframe]:
    """``--target`` → derived timeframes: ``4h``, ``1d``, or ``all`` (= 4h then 1d)."""
    name = value.strip().lower()
    if name == "all":
        return [Timeframe.H4, Timeframe.D1]
    try:
        target = Timeframe(name)
    except ValueError as exc:
        raise typer.BadParameter(f"--target: unknown timeframe {value!r} (4h, 1d, all)") from exc
    if target not in (Timeframe.H4, Timeframe.D1):
        raise typer.BadParameter(f"--target: {name!r} is not a derived timeframe (4h, 1d, all)")
    return [target]


@data_app.command()
def resample(
    symbols: Annotated[
        str | None,
        typer.Option(
            "--symbols",
            help="Comma-separated symbols (BTCUSDT or BINANCE:PERP:BTCUSDT). "
            "Default: every instrument with 1h bars in the lake.",
        ),
    ] = None,
    target: Annotated[
        str,
        typer.Option("--target", help="Derived timeframe to build: 4h, 1d, or all."),
    ] = "all",
    profile: _ProfileOpt = None,
) -> None:
    """Derive 4h/1d bars from stored 1h bars (incremental; rerun-safe).

    Only fully-populated, fully-closed buckets are written: a 1h gap leaves the
    covering 4h/1d bar MISSING (gaps propagate, never get synthesized), and
    quality flags OR up into the derived bar. Rerunning with no new 1h data
    reads and writes nothing.
    """
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.resample import Resampler

    targets = _parse_resample_targets(target)
    settings = _load_settings(profile)
    _setup_logging(settings)

    paths = LakePaths(settings.paths.lake_dir)
    if symbols is not None:
        instrument_ids = [_resolve_instrument_id(tok) for tok in symbols.split(",")]
    else:
        instrument_ids = paths.instrument_ids(Dataset.OHLCV)
        if not instrument_ids:
            typer.echo("no instruments with 1h bars in the lake — run `af data backfill` first")
            raise typer.Exit(1)

    resampler = Resampler(paths)
    now = now_ms()
    for tf_target in targets:
        stats = resampler.resample(instrument_ids, target=tf_target, now=now)
        typer.echo(
            f"{tf_target.value}: instruments={stats.instruments} "
            f"source_rows={stats.source_rows} bars_written={stats.bars_written} "
            f"buckets_incomplete={stats.buckets_incomplete} "
            f"buckets_unclosed={stats.buckets_unclosed}"
        )


@data_app.command()
def update(profile: _ProfileOpt = None) -> None:
    """Incrementally advance every watermark to now (the hourly follow path).

    Same engine as backfill: per pair, resume from ``watermark + 1`` up to now;
    never-watermarked instruments are skipped (bootstrap with ``af data backfill``).
    Exit code 1 if any pair failed.
    """
    settings = _load_settings(profile)
    _setup_logging(settings)
    with _open_stores(settings) as (instruments, checkpoints):
        job = _build_job(settings, instruments, checkpoints)
        report = job.update(as_of=now_ms())
    _print_report(report)
    if report.failed_count:
        raise typer.Exit(1)


@data_app.command()
def status(profile: _ProfileOpt = None) -> None:
    """Per-instrument ingestion health: watermarks vs now and 7-day gap counts.

    Gap counts compare the stored 1h bars against the 24/7 grid over the last 7
    days (clamped to each instrument's listed/delisted life and to the last bar
    whose ingest grace has elapsed). Gaps are reported, never filled.
    """
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader

    settings = _load_settings(profile)
    now = now_ms()
    tf = settings.data.timeframe

    with _open_stores(settings) as (instruments, checkpoints):
        ohlcv_marks = checkpoints.all_watermarks(Dataset.OHLCV)
        funding_marks = checkpoints.all_watermarks(Dataset.FUNDING)
        ids = sorted(set(ohlcv_marks) | set(funding_marks))
        if not ids:
            typer.echo("no ingestion watermarks yet — run `af data backfill`")
            return
        reader = PITDataReader(LakePaths(settings.paths.lake_dir))
        grid_end_now = floor_bar(now - settings.data.ingest_grace_ms, tf)

        typer.echo(f"now: {_fmt_ts(now)}  (grace {settings.data.ingest_grace_ms} ms)")
        typer.echo(
            f"{'instrument':<30} {'ohlcv watermark':<22} {'age':>7} "
            f"{'funding watermark':<22} {'age':>7} {'gaps(7d)':>8}"
        )
        for iid in ids:
            inst = instruments.get(iid, as_of=now)
            gap_start = now - _SEVEN_DAYS_MS
            gap_end = grid_end_now
            if inst is not None:
                gap_start = max(gap_start, inst.listed_ts)
                if inst.delisted_ts is not None:
                    gap_end = min(gap_end, inst.delisted_ts)
            gaps = (
                str(len(reader.gaps(iid, start=gap_start, end=gap_end, tf=tf)))
                if gap_end > gap_start
                else "-"
            )
            ohlcv_wm = ohlcv_marks.get(iid)
            funding_wm = funding_marks.get(iid)
            typer.echo(
                f"{iid:<30} {_fmt_ts(ohlcv_wm):<22} {_fmt_age(ohlcv_wm, now=now):>7} "
                f"{_fmt_ts(funding_wm):<22} {_fmt_age(funding_wm, now=now):>7} {gaps:>8}"
            )


# --------------------------------------------------------------------------- equities
#
# The REAL equities-bars path: Polygon S3 flat files (one gzipped CSV per session, every
# ticker that traded → survivorship-free). The REST aggregates endpoint is NOT entitled on
# this account; the flat files ARE (EQUITIES_INGEST.md §0). Corporate actions (splits +
# dividends) come from the entitled REST reference adapter and land RAW in the lake; split/
# dividend adjustment is reconstructed point-in-time at FEATURE time, never at ingest.


def _build_flatfiles_source() -> PolygonFlatFilesSource:
    """Construct the flat-files bar source from the ``POLYGON_S3_*`` env (operator-sourced).

    A seam: tests monkeypatch this to return a fake-client-backed source, so no boto3 / no
    network is ever touched offline. A missing credential raises ``ConfigError`` inside the
    source constructor.
    """
    from alphaforge.data.sources.polygon_flatfiles import PolygonFlatFilesSource

    return PolygonFlatFilesSource()


def _build_equities_reference() -> PolygonEquitiesSource:
    """Construct the REST reference adapter (splits/dividends) from ``POLYGON_API_KEY``.

    Another seam for tests. ``PolygonEquitiesSource`` reads the key at construction and
    raises ``ConfigError`` if it is absent with no injected client.
    """
    import os

    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource

    return PolygonEquitiesSource(
        api_key=os.environ.get("POLYGON_API_KEY"), rate_budget=RateBudget()
    )


def _print_equities_report(report: EquitiesIngestReport) -> None:
    """Plain-text per-session report table plus a one-line summary (mirrors _print_report)."""
    typer.echo(f"run {report.run_id} [ingest-equities]: {report.summary()}")
    shown = [r for r in report.results if r.status != "skipped"]
    if shown:
        typer.echo(f"{'session':<12} {'status':<8} {'tickers':>8} {'rows':>9} notes")
        for r in shown:
            typer.echo(f"{r.session:<12} {r.status:<8} {r.tickers:>8} {r.rows:>9} {r.error}")
    if report.skipped_count:
        typer.echo(f"+ {report.skipped_count} session(s) skipped (already ingested)")


#: Skip re-polling a per-ticker corporate-actions key confirmed within this window. Splits and
#: dividends are announced days-to-weeks before their ex-date, so a ~5-day recheck cannot miss one
#: before it becomes tradable-relevant, while it keeps a ~2500-name universe off a free-tier
#: reference API's rate-limit wall (the daily-``until`` re-fetch that stalled the equity tick).
_CORP_ACTIONS_RECHECK_MS: Final[Ms] = 5 * 24 * 60 * 60 * 1000
#: Fetch corporate actions this far past ``until`` so announced-but-future ex-dates are captured
#: BEFORE their ex-date. Must exceed _CORP_ACTIONS_RECHECK_MS so the cooldown cannot skip a key
#: past a split's ex-date (that pairing is what makes the cooldown safe against the ALIT bug class).
_CORP_ACTIONS_LOOKAHEAD_MS: Final[Ms] = 45 * 24 * 60 * 60 * 1000


def _ingest_corporate_actions(
    settings: Settings, checkpoints: CheckpointStore, *, until: Ms, now: Ms
) -> tuple[int, int]:
    """Per-instrument splits/dividends ingest for every id now present in ``ohlcv_1d``.

    The reference endpoints are per-ticker, so this is a small per-instrument loop (NOT the
    day-unit ``EquitiesFlatFilesJob``) resuming on the standard ``(CORPORATE_ACTIONS,
    instrument_id)`` watermark keyed on ``ex_date``. Each action row already carries its PIT
    ``available_at = knowable + CA_PUBLICATION_LAG_MS`` (set by the source); the lake stores
    it raw and the adjustment join uses ``available_at`` only. Returns ``(instruments,
    actions_written)``. A per-instrument failure is logged and isolated — it never aborts the
    whole corp-actions pass.
    """
    from alphaforge.core.logging import get_logger
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.writer import LakeWriter

    log = get_logger(__name__)
    paths = LakePaths(settings.paths.lake_dir)
    ids = paths.instrument_ids(Dataset.OHLCV_1D)
    if not ids:
        return 0, 0
    source = _build_equities_reference()
    writer = LakeWriter(paths)
    actions_total = 0
    # The reference endpoints are PER-TICKER and ``until`` advances daily, so a naive loop re-fetches
    # every one of a ~2500-name universe each run (``until > watermark+1`` is ~always true), which
    # rate-limit-walls a free-tier API and stalled the equity tick (2026-07-20). Two coupled guards:
    #  (1) a wall-clock RECHECK COOLDOWN: skip a key confirmed within CORP_ACTIONS_RECHECK_MS.
    #  (2) a FORWARD-LOOKING fetch window (now + CORP_ACTIONS_LOOKAHEAD_MS): each poll captures
    #      actions ANNOUNCED for future ex-dates. Because the lookahead (weeks) exceeds the cooldown
    #      (days), a key skipped by the cooldown already holds every action ex-ing before its next
    #      poll — so the cooldown can NEVER let a split reach its ex-date un-ingested (the ALIT bug
    #      class). The data watermark is advanced only to ``now`` (never to a future ex-date), so the
    #      near window keeps being rescanned for newly-announced actions; future rows are stored and
    #      gated by their own ``available_at`` at the adjustment join. First-seen keys are never
    #      skipped, so a fresh universe still backfills in full.
    recheck_floor = now - _CORP_ACTIONS_RECHECK_MS
    fetch_until = until + _CORP_ACTIONS_LOOKAHEAD_MS
    skipped_fresh = 0
    for instrument_id in ids:
        last = checkpoints.last_updated(Dataset.CORPORATE_ACTIONS, instrument_id)
        if last is not None and last >= recheck_floor:
            skipped_fresh += 1
            continue
        watermark = checkpoints.get(Dataset.CORPORATE_ACTIONS, instrument_id)
        since = 0 if watermark is None else watermark + 1
        try:
            tbl = source.fetch_corporate_actions(instrument_id, since=since, until=fetch_until)
        except Exception as exc:  # isolate: one bad ticker never aborts the pass
            log.error(
                "equities_ingest.corp_actions_failed",
                instrument_id=instrument_id,
                error=repr(exc),
            )
            continue
        if tbl.num_rows:
            writer.write(Dataset.CORPORATE_ACTIONS, tbl, now=now)
            actions_total += tbl.num_rows
        # Advance/refresh to ``now`` whether or not rows were found: confirms this key is scanned
        # through now (its recheck stamp enters the cooldown), and never past now so the near window
        # keeps being rescanned. Monotonic — max() guards against a stored future/equal watermark.
        checkpoints.set(Dataset.CORPORATE_ACTIONS, instrument_id, max(watermark or 0, now))
    if skipped_fresh:
        log.info(
            "equities_ingest.corp_actions_cooldown_skipped",
            n_skipped=skipped_fresh,
            n_total=len(ids),
        )
    return len(ids), actions_total


def _max_epoch_ms(tbl: pa.Table, column: str) -> int:
    """Max value of a ``timestamp[ms, UTC]`` column as epoch ms (exact)."""
    import numpy as np

    raw = tbl.column(column).to_numpy(zero_copy_only=False)
    arr = raw.astype("datetime64[ms]").astype(np.int64)
    return int(arr.max())


@data_app.command(name="ingest-equities")
def ingest_equities(
    start: Annotated[
        str,
        typer.Option("--start", help="First session, UTC (YYYY-MM-DD or ISO-8601). Required."),
    ],
    until: Annotated[
        str | None,
        typer.Option("--until", help="Exclusive end, UTC. Default: now."),
    ] = None,
    max_tickers: Annotated[
        int | None,
        typer.Option(
            "--max-tickers",
            min=1,
            help="Dev cap: keep the top-N tickers per day by dollar volume. "
            "NON-survivorship-safe — research must run uncapped.",
        ),
    ] = None,
    corp_actions: Annotated[
        bool,
        typer.Option(
            "--corp-actions/--no-corp-actions",
            help="After the bar ingest, pull splits/dividends for the ingested ids.",
        ),
    ] = True,
    profile: _ProfileOpt = None,
) -> None:
    """Ingest US equity daily bars from the Polygon S3 flat files (resumable; rerun-safe).

    One gzipped CSV per trading day holds EVERY ticker that traded — the lake is
    survivorship-free by construction (delisted names land too). Prices are stored RAW;
    split/dividend adjustment is reconstructed point-in-time at feature time, never here.
    Crash/interrupt at any point and rerun: already-ingested sessions are skipped (a single
    monotonic day watermark) and the writer dedupes any overlap. Exit code 1 if any session
    failed.
    """
    from alphaforge.core.errors import ConfigError
    from alphaforge.data.ingest.equities import EquitiesFlatFilesJob
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.writer import LakeWriter

    settings = _load_settings(profile)
    _setup_logging(settings)
    start_ms = _parse_cli_utc(start, param="--start")
    until_ms = None if until is None else _parse_cli_utc(until, param="--until")
    now = now_ms()

    if max_tickers is not None:
        typer.echo(
            f"WARNING: --max-tickers {max_tickers} caps each day to the top-{max_tickers} "
            "names by dollar volume — this is NON-survivorship-safe; research must run "
            "uncapped.",
            err=True,
        )

    with _open_stores(settings) as (_instruments, checkpoints):
        try:
            source = _build_flatfiles_source()
        except ConfigError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        job = EquitiesFlatFilesJob(
            source,
            LakeWriter(LakePaths(settings.paths.lake_dir)),
            checkpoints,
            max_tickers=max_tickers,
            lock_path=settings.paths.var_dir / "ingest.lock",
        )
        report = job.run(start=start_ms, until=until_ms, now=now)
        _print_equities_report(report)

        if corp_actions:
            try:
                instruments_n, actions_n = _ingest_corporate_actions(
                    settings, checkpoints, until=now, now=now
                )
                typer.echo(f"corporate-actions: instruments={instruments_n} actions={actions_n}")
            except ConfigError as exc:
                typer.echo(f"corporate-actions skipped: {exc}", err=True)

    if report.failed_count:
        raise typer.Exit(1)


def _universe_ever_members(settings: Settings) -> list[str]:
    """Distinct instrument ids that were EVER in the tradeable universe (incl. delisted).

    Read from the ``universe_membership`` intervals — the survivorship-free set fundamentals
    are worth fetching for (the live top-N alone would be survivorship-biased). Sorted,
    deterministic; empty if the universe has not been built yet.
    """
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.universe.store import UniverseStore

    store = UniverseStore(LakePaths(settings.paths.lake_dir))
    tbl = store.read_intervals()  # all intervals, knowable-to-now
    if tbl.num_rows == 0:
        return []
    return sorted(set(tbl.column("instrument_id").to_pylist()))


@data_app.command(name="ingest-fundamentals")
def ingest_fundamentals(
    since: Annotated[
        str,
        typer.Option("--since", help="First fiscal period_end, UTC (YYYY-MM-DD). Required."),
    ],
    until: Annotated[
        str | None,
        typer.Option("--until", help="Exclusive end on period_end, UTC. Default: now."),
    ] = None,
    all_lake: Annotated[
        bool,
        typer.Option(
            "--all-lake/--universe",
            help="Ingest for ALL ohlcv_1d ids instead of just the universe-ever-members "
            "(default: universe only — fundamentals matter for tradeable names).",
        ),
    ] = False,
    profile: _ProfileOpt = None,
) -> None:
    """Ingest PIT quarterly fundamentals (Polygon financials) for the equity universe.

    One instrument = one unit of work; resumable on the ``(FUNDAMENTALS, instrument_id)``
    watermark. Each row carries ``available_at`` (SEC filing_date, conservative fallback when
    absent) — the factor layer filters ``available_at <= decision_t``, so a quarter is unseen
    until its filing. Survivorship-free: the default id set is every universe-EVER-member
    (delisted names included). Crash/interrupt and rerun: done instruments are skipped, the
    writer dedupes. Exit code 1 if any instrument failed.
    """
    import os

    from alphaforge.core.errors import ConfigError
    from alphaforge.data.ingest.fundamentals import FundamentalsJob
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.writer import LakeWriter

    settings = _load_settings(profile)
    _setup_logging(settings)
    since_ms = _parse_cli_utc(since, param="--since")
    until_ms = None if until is None else _parse_cli_utc(until, param="--until")
    now = now_ms()

    paths = LakePaths(settings.paths.lake_dir)
    ids = paths.instrument_ids(Dataset.OHLCV_1D) if all_lake else _universe_ever_members(settings)
    if not ids:
        hint = (
            "ohlcv_1d lake is empty" if all_lake else "universe not built — run af universe rebuild"
        )
        typer.echo(f"error: no instruments to ingest ({hint})", err=True)
        raise typer.Exit(1)
    scope = "all-lake" if all_lake else "universe-ever-members"
    typer.echo(f"ingesting fundamentals for {len(ids)} instrument(s) ({scope})")

    with _open_stores(settings) as (_instruments, checkpoints):
        try:
            source = PolygonEquitiesSource(
                api_key=os.environ.get("POLYGON_API_KEY"), rate_budget=RateBudget()
            )
        except ConfigError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        job = FundamentalsJob(
            source,
            LakeWriter(paths),
            checkpoints,
            lock_path=settings.paths.var_dir / "ingest.lock",
        )
        report = job.run(ids, since=since_ms, until=until_ms, now=now)

    typer.echo(
        f"fundamentals: ok={report.ok_count} failed={report.failed_count} "
        f"skipped={report.skipped_count} rows={report.total_rows}"
    )
    for r in report.failures()[:10]:
        typer.echo(f"  FAILED {r.instrument_id}: {r.error}", err=True)
    if report.failed_count:
        raise typer.Exit(1)
