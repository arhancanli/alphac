"""``af universe`` — PIT universe commands: rebuild history, show members, spans.

Wiring follows ``af data``: the lake lives at ``settings.paths.lake_dir``; the SCD2
instrument record lives in ``settings.paths.var_dir / "ops.sqlite"``; structlog JSONL
goes to ``settings.paths.var_dir / "log"``. All printed timestamps are UTC; all CLI
date/time inputs are interpreted as UTC (a bare ``YYYY-MM-DD`` means UTC midnight).

``rebuild`` is full-replace by design: membership is derived data — a deterministic
pure function of the OHLCV lake plus the instrument record — so regenerating it is
always safe and never loses information (dataDesign.md §6.2).

Heavy imports (pyarrow, duckdb) are deferred into command bodies so ``af --help``
stays fast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError, SchemaError
from alphaforge.core.time import Ms, from_ms, now_ms, parse_utc
from alphaforge.core.types import MarketType

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.config.settings import Settings
    from alphaforge.data.universe.store import UniverseStore

__all__ = ["universe_app"]

universe_app = typer.Typer(
    name="universe",
    help="PIT tradable universe: monthly rebalance history, members, membership spans.",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _fmt_ts(ms: Ms | None) -> str:
    """Epoch ms UTC → compact ISO string (``-`` for None)."""
    if ms is None:
        return "-"
    return from_ms(ms).isoformat().replace("+00:00", "Z")


def _parse_cli_utc(value: str, *, param: str) -> Ms:
    """Parse a CLI timestamp to epoch ms UTC (bare ``YYYY-MM-DD`` = UTC midnight)."""
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


def _open_store(settings: Settings) -> UniverseStore:
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.universe.store import UniverseStore

    return UniverseStore(LakePaths(settings.paths.lake_dir))


@universe_app.command()
def rebuild(
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help="History start, UTC (YYYY-MM-DD or ISO-8601). "
            "Default: data.backfill_start from configs.",
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="History end (inclusive), UTC. Default: now."),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Rebuild the full PIT membership history (full replace; deterministic).

    Walks every monthly rebalance (00:00 UTC, 1st) in [start, end]; each decision
    reads the lake point-in-time at the rebalance instant, so the result is free of
    survivorship and lookahead bias by construction. Rerun-safe: rebuilding twice
    yields identical intervals.
    """
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.builder import UniverseBuilder
    from alphaforge.data.universe.store import UniverseStore

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    now = now_ms()
    start_ms = (
        settings.data.backfill_start_ms if start is None else _parse_cli_utc(start, param="--start")
    )
    end_ms = now if end is None else _parse_cli_utc(end, param="--end")

    # The liquidity-ranking read timeframe is the sleeve's anchor TF: H1 for crypto (intraday
    # bars summed into a daily ADV — unchanged), D1 for equities (native daily bars are the
    # ADV). Crypto resolves H1, so this is byte-identical to the prior hard-coded default.
    rank_tf = sleeve_for(settings.data.asset_class).anchor_tf

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(_ops_db_path(settings)) as instruments:
        builder = UniverseBuilder(
            PITDataReader(paths),
            instruments,
            UniverseStore(paths),
            settings.universe,
            rank_tf=rank_tf,
        )
        try:
            stats = builder.rebuild(start=start_ms, end=end_ms, now=now)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc

    typer.echo(
        f"universe rebuilt over [{_fmt_ts(start_ms)}, {_fmt_ts(end_ms)}]: "
        f"{stats.rebalances} rebalance(s), {stats.intervals} interval(s) "
        f"({stats.entries} entries, {stats.exits} exits, {stats.open_members} open)"
    )


@universe_app.command()
def show(
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Decision instant, UTC. Default: now."),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Members at an instant, with entry date, entry rank, and rationale.

    Reads the stored membership intervals with half-open [effective_from,
    effective_to) semantics — historical --as-of values include instruments that were
    delisted later (the survivorship-bias-free view backtests join against).
    """
    import pyarrow as pa

    settings = _load_settings(profile)
    ts = now_ms() if as_of is None else _parse_cli_utc(as_of, param="--as-of")
    tbl = _open_store(settings).read_intervals()

    ids: list[str] = tbl.column("instrument_id").to_pylist()
    froms: list[int] = tbl.column("effective_from").cast(pa.int64()).to_pylist()
    tos: list[int | None] = tbl.column("effective_to").cast(pa.int64()).to_pylist()
    ranks: list[int] = tbl.column("rank").to_pylist()
    reasons: list[str] = tbl.column("reason").to_pylist()

    members = [
        (iid, eff_from, rank, reason)
        for iid, eff_from, eff_to, rank, reason in zip(ids, froms, tos, ranks, reasons, strict=True)
        if eff_from <= ts and (eff_to is None or eff_to > ts)
    ]
    typer.echo(f"universe as of {_fmt_ts(ts)}: {len(members)} member(s)")
    if not members:
        typer.echo("(empty — run `af universe rebuild` after backfilling the lake)")
        return
    typer.echo(f"{'instrument':<30} {'member since (UTC)':<22} {'rank@entry':>10} reason")
    for iid, eff_from, rank, reason in members:
        typer.echo(f"{iid:<30} {_fmt_ts(eff_from):<22} {rank:>10} {reason}")


@universe_app.command()
def history(
    symbol: Annotated[
        str,
        typer.Argument(help="Canonical id (BINANCE:PERP:BTCUSDT) or bare symbol (BTCUSDT)."),
    ],
    profile: _ProfileOpt = None,
) -> None:
    """One instrument's full membership history (spans, oldest first)."""
    import pyarrow as pa

    settings = _load_settings(profile)
    instrument_id = _resolve_instrument_id(symbol)
    tbl = _open_store(settings).read_intervals()

    ids: list[str] = tbl.column("instrument_id").to_pylist()
    froms: list[int] = tbl.column("effective_from").cast(pa.int64()).to_pylist()
    tos: list[int | None] = tbl.column("effective_to").cast(pa.int64()).to_pylist()
    ranks: list[int] = tbl.column("rank").to_pylist()
    reasons: list[str] = tbl.column("reason").to_pylist()

    spans = [
        (eff_from, eff_to, rank, reason)
        for iid, eff_from, eff_to, rank, reason in zip(ids, froms, tos, ranks, reasons, strict=True)
        if iid == instrument_id
    ]
    if not spans:
        typer.echo(f"{instrument_id}: never a universe member")
        return
    typer.echo(f"{instrument_id}: {len(spans)} membership span(s)")
    typer.echo(f"{'effective_from (UTC)':<22} {'effective_to (UTC)':<22} {'rank@entry':>10} reason")
    for eff_from, eff_to, rank, reason in spans:
        to_str = _fmt_ts(eff_to) if eff_to is not None else "open"
        typer.echo(f"{_fmt_ts(eff_from):<22} {to_str:<22} {rank:>10} {reason}")
