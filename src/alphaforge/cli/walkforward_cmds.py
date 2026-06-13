"""``af research walkforward`` — the purged walk-forward OOS evaluation.

Wiring follows ``af backtest``/``af research``: lake at
``settings.paths.lake_dir``, SCD2 instruments in ``settings.paths.var_dir /
"ops.sqlite"``, artifacts under ``settings.paths.artifacts_dir /
"walkforward" / <run_id>``. All CLI timestamps are UTC (bare ``YYYY-MM-DD``
= UTC midnight).

Heavy imports (pandas, duckdb, cvxpy via the portfolio layer, matplotlib via
analytics) are deferred into the command body so ``af --help`` stays fast.
This module is not registered in ``cli/main.py`` here — the phase auditor
wires it (e.g. ``research_app.add_typer(walkforward_app)`` or
``research_app.command("walkforward")(walkforward)``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError
from alphaforge.core.time import Ms, Timeframe, floor_bar, now_ms, parse_utc

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings

__all__ = ["walkforward", "walkforward_app"]

walkforward_app = typer.Typer(
    name="walkforward",
    help="Purged walk-forward out-of-sample evaluation of the blend strategy.",
    no_args_is_help=False,
)

_OPS_DB: Final[str] = "ops.sqlite"
_BARS_PER_DAY: Final[int] = 24


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


@walkforward_app.command()
def walkforward(
    start: Annotated[
        str,
        typer.Option("--start", help="Window start, UTC (YYYY-MM-DD or ISO-8601), 1h-aligned."),
    ],
    end: Annotated[
        str | None,
        typer.Option("--end", help="Window end (exclusive), UTC; default: now, floored to 1h."),
    ] = None,
    train_days: Annotated[
        int,
        typer.Option("--train-days", min=4, help="Train/warm-up window per leg, in days."),
    ] = 365,
    test_days: Annotated[
        int,
        typer.Option("--test-days", min=1, help="Out-of-sample test span per leg, in days."),
    ] = 91,
    allocator: Annotated[
        str,
        typer.Option("--allocator", help="Portfolio allocator: 'rank' (v1 primary) or 'mvo'."),
    ] = "rank",
    cash: Annotated[
        float,
        typer.Option("--cash", min=0.0, help="Initial cash in quote units (USDT), leg 0 only."),
    ] = 100_000.0,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Comma-separated canonical instrument ids; default: the PIT "
            "universe members overlapping the window.",
        ),
    ] = None,
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            help="Artifact directory. Default: <artifacts_dir>/walkforward/<UTC timestamp>.",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
    ] = None,
) -> None:
    """Run the purged walk-forward and persist stitched equity + per-leg artifacts."""
    # Argument parsing FIRST — bad input must exit before any filesystem touch.
    start_ms = _parse_cli_utc(start, param="--start")
    end_ms = (
        floor_bar(now_ms(), Timeframe.H1) if end is None else _parse_cli_utc(end, param="--end")
    )
    if allocator not in ("rank", "mvo"):
        raise typer.BadParameter(f"--allocator: must be 'rank' or 'mvo', got {allocator!r}")
    alloc: str = allocator
    instrument_ids: list[str] | None = None
    if ids is not None:
        instrument_ids = [tok.strip() for tok in ids.split(",") if tok.strip()]
        if not instrument_ids:
            raise typer.BadParameter(f"--ids: no instrument ids in {ids!r}")

    # Heavy wiring deferred (registers the factor library on import).
    from datetime import UTC, datetime

    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.analytics import render_text
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    if out is not None:
        out_dir = Path(out)
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_dir = settings.paths.artifacts_dir / "walkforward" / run_id

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / _OPS_DB) as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe),
            universe,
            default_registry(),
            settings.signals,
        )
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
        )
        try:
            result = runner.run(
                start_ms,
                end_ms,
                train_bars=train_days * _BARS_PER_DAY,
                test_bars=test_days * _BARS_PER_DAY,
                allocator="mvo" if alloc == "mvo" else "rank",
                initial_cash=cash,
                instrument_ids=instrument_ids,
                out_dir=out_dir,
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc

    typer.echo(render_text(result.summary))
    typer.echo("")
    for leg in result.legs:
        s = leg.result.summary
        typer.echo(
            f"leg {leg.leg:02d}  test [{leg.test_start} .. {leg.test_end})  "
            f"equity {s.initial_equity:,.2f} -> {s.final_equity:,.2f}  "
            f"sharpe {s.sharpe:.2f}  max_dd {s.max_dd:.2%}"
        )
    typer.echo(f"artifacts: {out_dir}")
