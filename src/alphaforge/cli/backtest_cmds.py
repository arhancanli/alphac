"""``af backtest`` — run the event-driven truth engine and inspect saved runs.

Wiring follows ``af research``: the lake lives at ``settings.paths.lake_dir``;
the SCD2 instrument record lives in ``settings.paths.var_dir / "ops.sqlite"``;
artifacts land under ``settings.paths.artifacts_dir / "backtests" / <run_id>``
(execDesign.md §4.5). All CLI date/time inputs are interpreted as UTC (a bare
``YYYY-MM-DD`` means UTC midnight).

The only built-in strategy is ``rank`` — :class:`RankStrategy`, an equal-weight
long top-K trailing-return DEMO that exists to exercise the full engine on real
lake data. It is NOT the product; Phase 6's signal stack + optimizer implement
the same :class:`~alphaforge.backtest.Strategy` protocol and replace it.

Heavy imports (pyarrow, duckdb, pandas, matplotlib via analytics) are deferred
into command bodies so ``af --help`` stays fast. This module is not registered
in ``cli/main.py`` here — the phase auditor wires it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError
from alphaforge.core.time import Ms, now_ms, parse_utc

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings

__all__ = ["backtest_app"]

backtest_app = typer.Typer(
    name="backtest",
    help="Event-driven backtests over the lake (the truth engine).",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


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


def _load_settings(profile: str | None) -> Settings:
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


@backtest_app.callback()
def _backtest() -> None:
    """Event-driven backtests (read-only over the lake; artifacts under --out)."""
    # Explicit callback: keeps `run`/`show` named subcommands even if one is
    # ever the sole command (typer otherwise collapses single-command apps).


@backtest_app.command()
def run(
    start: Annotated[
        str,
        typer.Option("--start", help="Run start, UTC (YYYY-MM-DD or ISO-8601), 1h-aligned."),
    ],
    end: Annotated[
        str,
        typer.Option("--end", help="Run end (exclusive), UTC, 1h-aligned."),
    ],
    strategy: Annotated[
        str,
        typer.Option("--strategy", help="Strategy name; only 'rank' exists in Phase 5 (a demo)."),
    ] = "rank",
    top: Annotated[
        int,
        typer.Option("--top", min=1, help="RankStrategy: number of names held long."),
    ] = 10,
    cash: Annotated[
        float,
        typer.Option("--cash", min=0.0, help="Initial cash in quote units (USDT)."),
    ] = 100_000.0,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Comma-separated canonical instrument ids; default: every perp "
            "known to the instrument store as of --end.",
        ),
    ] = None,
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            help="Run directory for artifacts. Default: <artifacts_dir>/backtests/<UTC timestamp>.",
        ),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Run a backtest and persist equity/fills/funding/orders/positions + tearsheet."""
    from alphaforge.analytics import render_text
    from alphaforge.backtest.engine import EventDrivenBacktester, RankStrategy
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.types import MarketType
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader

    settings = _load_settings(profile)
    start_ms = _parse_cli_utc(start, param="--start")
    end_ms = _parse_cli_utc(end, param="--end")
    if strategy != "rank":
        raise typer.BadParameter(f"--strategy: unknown strategy {strategy!r} (Phase 5 has 'rank')")

    reader = PITDataReader(LakePaths(settings.paths.lake_dir))
    cost_model = TransactionCostModel.from_settings(settings)
    with InstrumentStore(settings.paths.var_dir / _OPS_DB) as store:
        if ids is not None:
            instrument_ids = [tok.strip() for tok in ids.split(",") if tok.strip()]
            if not instrument_ids:
                raise typer.BadParameter(f"--ids: no instrument ids in {ids!r}")
        else:
            instrument_ids = [
                inst.instrument_id
                for inst in store.all_known(end_ms)
                if inst.market_type is MarketType.PERP
            ]
            if not instrument_ids:
                # SCD2 validity starts at first ingestion, so a historical
                # --end resolves no versions; fall back to currently-known
                # perps (the engine resolves each id's earliest version).
                instrument_ids = [
                    inst.instrument_id
                    for inst in store.all_known(now_ms())
                    if inst.market_type is MarketType.PERP
                ]
            if not instrument_ids:
                typer.echo("no perp instruments known; nothing to run", err=True)
                raise typer.Exit(code=1)

        engine = EventDrivenBacktester(
            reader,
            store,
            cost_model,
            no_trade_band_frac=settings.portfolio.no_trade_band,
            clamp_reduce_only_adv=settings.risk.clamp_reduce_only_adv,
            config_echo={
                "strategy": f"rank(top={top})",
                "costs": settings.costs.model_dump(),
            },
        )
        result = engine.run(
            RankStrategy(top_k=top),
            instrument_ids,
            start=start_ms,
            end=end_ms,
            initial_cash=cash,
        )

    if out is not None:
        out_dir = Path(out)
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_dir = settings.paths.artifacts_dir / "backtests" / run_id
    result.save(out_dir)
    typer.echo(render_text(result.summary))
    typer.echo(f"counters: {result.counters}")
    typer.echo(f"artifacts: {out_dir}")


@backtest_app.command()
def show(
    run_dir: Annotated[
        str,
        typer.Argument(help="A run directory previously written by `af backtest run`."),
    ],
) -> None:
    """Reload a saved run and print its (recomputed) performance summary."""
    from alphaforge.analytics import render_text
    from alphaforge.backtest.result import BacktestResult

    path = Path(run_dir)
    if not path.is_dir():
        typer.echo(f"not a run directory: {path}", err=True)
        raise typer.Exit(code=1)
    result = BacktestResult.load(path)
    typer.echo(render_text(result.summary))
    typer.echo(f"counters: {result.counters}")
