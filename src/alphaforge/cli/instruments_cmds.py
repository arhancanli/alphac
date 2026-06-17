"""``af instruments`` — instrument catalog commands: refresh (seed) and show (SCD2).

``refresh`` seeds the SCD2 store survivorship-free, dispatching on ``--market``:

* ``crypto`` (default, back-compat) merges the venue's live listing with the Binance
  Vision archive catalog (:class:`~alphaforge.data.ingest.seed.InstrumentSeeder` with a
  :class:`~alphaforge.data.sources.vision.BinanceVisionClient`) so pre-go-live
  delistings enter the store — the survivorship-bias fix (leakage finding 1).
* ``equities`` seeds from :class:`~alphaforge.data.sources.polygon_source.PolygonEquitiesSource`
  whose ``list_instruments`` is *already* survivorship-free (Polygon's reference
  endpoints return delisted US stocks alongside active ones), so the same generic
  seeder runs with no Vision archive — active AND delisted instruments land in the
  SCD2 store in one pass (EQUITIES_INGEST.md §1.6).

``show`` prints an instrument's full SCD2 version history.

State lives in ``settings.paths.var_dir / "ops.sqlite"`` (shared with the ingest
watermarks). Heavy imports (ccxt, httpx) are deferred into command bodies so
``af --help`` stays fast.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import ConfigError, SchemaError
from alphaforge.core.time import Ms, from_ms, now_ms
from alphaforge.core.types import MarketType

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.ingest.seed import InstrumentSeeder

__all__ = ["instruments_app"]

instruments_app = typer.Typer(
    name="instruments",
    help="Instrument catalog: SCD2 refresh from venue + archive, version history.",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"
_VISION_DELAY_S: Final[float] = 0.1
_POLYGON_API_KEY_ENV: Final[str] = "POLYGON_API_KEY"
_POLYGON_REQ_PER_MIN_ENV: Final[str] = "POLYGON_REQ_PER_MIN"
_POLYGON_FREE_TIER_REQ_PER_MIN: Final[int] = 5
_POLYGON_PAID_TIER_REQ_PER_MIN: Final[int] = 1000
"""Polygon REST request budget for the reference walk, in req/min.

The free tier caps at 5 req/min; the paid Stocks plans lift that (effectively unlimited).
The seeder reads :data:`_POLYGON_REQ_PER_MIN_ENV` (default
:data:`_POLYGON_PAID_TIER_REQ_PER_MIN`) so a paid key seeds the full active+delisted
universe in seconds rather than minutes; set ``POLYGON_REQ_PER_MIN=5`` to fall back to the
free-tier pace. A :class:`RateBudget` of this capacity meters the walk so it never trips a
429; the source also retries transient 429s, so the budget is prevention, the retry the
backstop."""


def _polygon_req_per_min() -> int:
    """Resolve the Polygon REST budget (env override → paid-tier default), floored at 1."""
    raw = os.environ.get(_POLYGON_REQ_PER_MIN_ENV)
    if raw is None:
        return _POLYGON_PAID_TIER_REQ_PER_MIN
    try:
        return max(1, int(raw))
    except ValueError:
        return _POLYGON_PAID_TIER_REQ_PER_MIN


class Market(StrEnum):
    """Which sleeve ``refresh`` seeds — selects the live source + archive wiring."""

    CRYPTO = "crypto"
    EQUITIES = "equities"


_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]
_MarketOpt = Annotated[
    Market,
    typer.Option("--market", help="Sleeve to seed: crypto (live+Vision) or equities (Polygon)."),
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


def _crypto_seeder(settings: Settings, store: InstrumentStore) -> InstrumentSeeder:
    """Wire the crypto seeder: ccxt live source + Binance Vision archive (finding 1)."""
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.ingest.seed import InstrumentSeeder
    from alphaforge.data.sources.ccxt_source import CCXTDataSource
    from alphaforge.data.sources.vision import BinanceVisionClient

    return InstrumentSeeder(
        CCXTDataSource(settings.data.exchange, rate_budget=RateBudget()),
        BinanceVisionClient(delay_s=_VISION_DELAY_S),
        store,
    )


def _equities_seeder(store: InstrumentStore) -> InstrumentSeeder:
    """Wire the equities seeder: Polygon reference source, no Vision archive.

    Polygon's ``list_instruments`` already returns delisted tickers, so the listing is
    survivorship-free on its own and ``vision`` is left ``None`` — the generic seeder
    upserts active AND delisted US stocks in one pass. The free-tier 5 req/min cap is
    handled by a :class:`RateBudget`; transient 429s are retried inside the source. A
    missing ``POLYGON_API_KEY`` raises :class:`ConfigError` rather than issuing an
    unauthenticated call.
    """
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.ingest.seed import InstrumentSeeder
    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource

    api_key = os.environ.get(_POLYGON_API_KEY_ENV)
    if not api_key:
        raise ConfigError(
            f"{_POLYGON_API_KEY_ENV} is not set; cannot seed equities instruments "
            "(refusing to issue unauthenticated Polygon requests)"
        )
    source = PolygonEquitiesSource(
        api_key=api_key,
        rate_budget=RateBudget(capacity_per_min=_polygon_req_per_min()),
    )
    return InstrumentSeeder(source, store=store)


@instruments_app.command()
def refresh(market: _MarketOpt = Market.CRYPTO, profile: _ProfileOpt = None) -> None:
    """Seed/refresh the SCD2 instrument store survivorship-free (dispatched by ``--market``).

    ``crypto`` (default) merges the ccxt live listing with the Binance Vision archive:
    live instruments keep their real exchange filters/fees; archive-only symbols
    (delisted before go-live) become HISTORY-ONLY records. ``equities`` seeds from
    Polygon's reference endpoints, whose listing already includes delisted US stocks, so
    active AND delisted instruments land directly (no archive merge). Idempotent in both
    modes: unchanged inputs write zero new SCD2 versions.
    """
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    as_of = now_ms()
    with InstrumentStore(_ops_db_path(settings)) as store:
        seeder = (
            _equities_seeder(store)
            if market is Market.EQUITIES
            else _crypto_seeder(settings, store)
        )
        report = seeder.seed(as_of=as_of)
    typer.echo(f"seeded {market.value} as of {_fmt_ts(as_of)}")
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
