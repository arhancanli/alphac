"""``af instruments`` — instrument catalog commands: refresh (seed) and show (SCD2).

``refresh`` merges the venue's live listing with the Binance Vision archive catalog
(:class:`~alphaforge.data.ingest.seed.InstrumentSeeder`) so pre-go-live delistings
enter the SCD2 store — the survivorship-bias fix (leakage finding 1). ``show``
prints an instrument's full SCD2 version history.

State lives in ``settings.paths.var_dir / "ops.sqlite"`` (shared with the ingest
watermarks). Heavy imports (ccxt, httpx) are deferred into command bodies so
``af --help`` stays fast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import SchemaError
from alphaforge.core.time import Ms, from_ms, now_ms
from alphaforge.core.types import MarketType

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.config.settings import Settings

__all__ = ["instruments_app"]

instruments_app = typer.Typer(
    name="instruments",
    help="Instrument catalog: SCD2 refresh from venue + archive, version history.",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"
_VISION_DELAY_S: Final[float] = 0.1

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _fmt_ts(ms: Ms | None) -> str:
    """Epoch ms UTC → compact ISO string (``-`` for None)."""
    if ms is None:
        return "-"
    return from_ms(ms).isoformat().replace("+00:00", "Z")


def _resolve_instrument_id(token: str) -> str:
    """CLI symbol → canonical instrument id (bare symbols → ``BINANCE:PERP:*``)."""
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
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


def _ops_db_path(settings: Settings) -> Path:
    return settings.paths.var_dir / _OPS_DB


@instruments_app.command()
def refresh(profile: _ProfileOpt = None) -> None:
    """Seed/refresh the SCD2 instrument store from the live venue + Vision archive.

    Live instruments are upserted with real exchange filters/fees; archive-only
    symbols (delisted before go-live) become HISTORY-ONLY records so backtest
    universes see the full point-in-time listing. Idempotent: unchanged inputs
    write zero new SCD2 versions.
    """
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.ingest.seed import InstrumentSeeder
    from alphaforge.data.sources.ccxt_source import CCXTDataSource
    from alphaforge.data.sources.vision import BinanceVisionClient

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    as_of = now_ms()
    with InstrumentStore(_ops_db_path(settings)) as store:
        seeder = InstrumentSeeder(
            CCXTDataSource(settings.data.exchange, rate_budget=RateBudget()),
            BinanceVisionClient(delay_s=_VISION_DELAY_S),
            store,
        )
        report = seeder.seed(as_of=as_of)
    typer.echo(f"seeded as of {_fmt_ts(as_of)}")
    typer.echo(f"  live instruments upserted:    {report.live_count}")
    typer.echo(f"  archive-only symbols found:   {report.vision_only_count}")
    typer.echo(f"  HISTORY-ONLY records written: {report.delisted}")
    if report.examples:
        typer.echo(f"  examples: {', '.join(report.examples)}")


@instruments_app.command()
def show(
    instrument: Annotated[
        str,
        typer.Argument(help="Canonical id (BINANCE:PERP:BTCUSDT) or bare symbol (BTCUSDT)."),
    ],
    profile: _ProfileOpt = None,
) -> None:
    """Print an instrument's full SCD2 version history (oldest first).

    Each row is one observed version with its half-open validity window
    ``[valid_from, valid_to)`` (``valid_to = -`` means current). Exit code 1 if
    the instrument is unknown.
    """
    from alphaforge.core.instruments import InstrumentStore

    settings = _load_settings(profile)
    instrument_id = _resolve_instrument_id(instrument)
    with InstrumentStore(_ops_db_path(settings)) as store:
        history = store.history(instrument_id)
    if not history:
        typer.echo(f"unknown instrument {instrument_id!r} — run `af instruments refresh`", err=True)
        raise typer.Exit(1)

    typer.echo(f"{instrument_id} — {len(history)} version(s)")
    for valid_from, valid_to, inst in history:
        typer.echo(f"[{_fmt_ts(valid_from)} -> {_fmt_ts(valid_to)})")
        typer.echo(
            f"  filters: tick_size={inst.tick_size:g} lot_size={inst.lot_size:g} "
            f"min_qty={inst.min_qty:g} min_notional={inst.min_notional:g}"
        )
        typer.echo(
            f"  fees: maker={inst.maker_fee_bps:g}bps taker={inst.taker_fee_bps:g}bps  "
            f"funding_interval={inst.funding_interval_hours}h  can_short={inst.can_short}"
        )
        typer.echo(
            f"  lifecycle: listed={_fmt_ts(inst.listed_ts)} "
            f"delisted={_fmt_ts(inst.delisted_ts)}  asset_class={inst.asset_class.value}"
        )
