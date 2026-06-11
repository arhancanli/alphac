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
from alphaforge.core.time import Ms, floor_bar, from_ms, now_ms, parse_utc
from alphaforge.core.types import MarketType
from alphaforge.data.schemas import Dataset

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.ingest.backfill import BackfillJob, BackfillReport
    from alphaforge.data.ingest.checkpoints import CheckpointStore

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
