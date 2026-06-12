"""``af quality`` — batch data-quality runs and report inspection.

``af quality run`` executes the full check suite (gaps, outlier returns, bad-print
suspects, stale closes, cross-sectional exchange downtime) over the stored history,
writes flag upgrades back through the sanctioned LakeWriter path (flags ANNOTATE
bars; prices are never altered), persists the JSON ValidationReport under
``settings.paths.quality_dir / "reports"``, and prints the summary. ``af quality
show`` renders a persisted report (latest by default).

Wiring mirrors ``data_cmds``: the lake at ``settings.paths.lake_dir``, structlog
JSONL under ``settings.paths.var_dir / "log"``; heavy imports (pyarrow, duckdb,
pandas) are deferred into command bodies so ``af --help`` stays fast. Exit code 1
when the run produced any ``error``-severity finding (dataDesign.md §5.4), so the
command can gate research jobs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

from alphaforge.core.errors import SchemaError
from alphaforge.core.time import now_ms
from alphaforge.core.types import MarketType

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.config.settings import Settings

__all__ = ["quality_app"]

quality_app = typer.Typer(
    name="quality",
    help="Data quality: batch checks, flag application, validation reports.",
    no_args_is_help=True,
)

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _load_settings(profile: str | None) -> Settings:
    """Load settings, mapping ConfigError to a clean CLI failure."""
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


def _setup_logging(settings: Settings) -> None:
    from alphaforge.core.logging import setup_logging

    setup_logging(settings.paths.var_dir / "log")


def _resolve_instrument_id(token: str) -> str:
    """CLI symbol → canonical instrument id (same convention as ``af data``):
    a token containing ``:`` must be a valid canonical id; a bare exchange symbol
    resolves to the v1 default venue ``BINANCE:PERP:<SYMBOL>``."""
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


def _reports_dir(settings: Settings) -> Path:
    return settings.paths.quality_dir / "reports"


@quality_app.command()
def run(
    symbols: Annotated[
        str | None,
        typer.Option(
            "--symbols",
            help="Comma-separated symbols (BTCUSDT or BINANCE:PERP:BTCUSDT). "
            "Default: every instrument with bars in the lake.",
        ),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Run all quality checks, apply flag upgrades, and persist the report.

    Flags annotate bars in place (prices untouched, gaps never filled); rerunning
    is idempotent. Exit code 1 if any finding has ``error`` severity.
    """
    from alphaforge.data.quality.checks import apply_flags
    from alphaforge.data.quality.report import ValidationReport
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.store.writer import LakeWriter

    settings = _load_settings(profile)
    _setup_logging(settings)
    tf = settings.data.timeframe

    paths = LakePaths(settings.paths.lake_dir)
    if symbols is not None:
        instrument_ids = [_resolve_instrument_id(tok) for tok in symbols.split(",")]
    else:
        instrument_ids = paths.instrument_ids(ohlcv_dataset(tf))
        if not instrument_ids:
            typer.echo("no instruments with bars in the lake — run `af data backfill` first")
            raise typer.Exit(1)

    generated_at = now_ms()
    stats = apply_flags(
        PITDataReader(paths),
        LakeWriter(paths),
        instrument_ids,
        tf=tf,
        cfg=settings.quality,
        now=generated_at,
    )
    report = ValidationReport.build(stats, tf=tf, generated_at=generated_at)
    artifact = report.persist(_reports_dir(settings))

    typer.echo(report.render_text())
    typer.echo(
        f"scanned {stats.instruments} instrument(s), {stats.bars_scanned} bar(s); "
        f"reflagged {stats.rows_reflagged} row(s)"
    )
    typer.echo(f"report: {artifact}")
    if report.worst_severity == "error":
        raise typer.Exit(1)


@quality_app.command()
def show(
    last: Annotated[
        bool,
        typer.Option(
            "--last/--no-last",
            help="Show the most recent persisted report (the default behaviour).",
        ),
    ] = True,
    report: Annotated[
        str | None,
        typer.Option("--report", help="Path to a specific report JSON (overrides --last)."),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Render a persisted validation report (latest by default)."""
    from pathlib import Path

    from alphaforge.data.quality.report import ValidationReport

    settings = _load_settings(profile)
    if report is not None:
        path = Path(report)
        if not path.is_file():
            typer.echo(f"error: report not found: {path}", err=True)
            raise typer.Exit(1)
    else:
        if not last:
            raise typer.BadParameter("--no-last requires --report <path>")
        reports = sorted(_reports_dir(settings).glob("*.json"))
        if not reports:
            typer.echo("no quality reports yet — run `af quality run` first")
            raise typer.Exit(1)
        path = reports[-1]
    typer.echo(ValidationReport.load(path).render_text())
