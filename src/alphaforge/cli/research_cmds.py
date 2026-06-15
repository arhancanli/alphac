"""``af research`` — research diagnostics: the per-factor Rank-IC evidence report.

Wiring follows ``af universe``: the lake lives at ``settings.paths.lake_dir``; the
SCD2 instrument record lives in ``settings.paths.var_dir / "ops.sqlite"``; structlog
JSONL goes to ``settings.paths.var_dir / "log"``. All printed timestamps are UTC; all
CLI date/time inputs are interpreted as UTC (a bare ``YYYY-MM-DD`` means UTC
midnight).

The report itself is pure research output (read-only over the lake): JSON + text are
persisted under ``--out`` (default ``<lake parent>/research``, i.e. ``data/research``
with the stock layout) and the table is echoed to stdout.

Heavy imports (pyarrow, duckdb, pandas via the feature library) are deferred into
the command body so ``af --help`` stays fast.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError
from alphaforge.core.time import Ms, now_ms, parse_utc

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings

__all__ = ["research_app"]

research_app = typer.Typer(
    name="research",
    help="Research diagnostics: factor Rank-IC evidence over full history.",
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


def _parse_horizons(value: str) -> tuple[int, ...]:
    """``"24,72"`` → ``(24, 72)``; loud on anything non-positive or malformed."""
    try:
        horizons = tuple(int(tok.strip()) for tok in value.split(",") if tok.strip())
    except ValueError as exc:
        raise typer.BadParameter(
            f"--horizons: cannot parse {value!r} (expected comma-separated integers)"
        ) from exc
    if not horizons:
        raise typer.BadParameter(f"--horizons: no horizons in {value!r}")
    if any(h <= 0 for h in horizons):
        raise typer.BadParameter(f"--horizons: horizons must be > 0, got {horizons}")
    if len(set(horizons)) != len(horizons):
        raise typer.BadParameter(f"--horizons: horizons must be unique, got {horizons}")
    return horizons


def _load_settings(profile: str | None) -> Settings:
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


@research_app.callback()
def _research() -> None:
    """Research diagnostics over the lake (read-only; artifacts under --out)."""
    # Explicit callback: keeps `ic` a named subcommand (`af research ic`) even
    # while it is the only command — typer otherwise collapses single-command
    # apps, which would silently change the CLI surface when a second command
    # lands.


@research_app.command()
def ic(
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help="Decision-span start, UTC (YYYY-MM-DD or ISO-8601). "
            "Default: data.backfill_start from configs.",
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="Decision-span end (exclusive), UTC. Default: now."),
    ] = None,
    horizons: Annotated[
        str,
        typer.Option("--horizons", help="Comma-separated forward-return horizons in 1h bars."),
    ] = "24,72",
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            help="Output directory for ic_report.json/.txt. Default: <lake parent>/research.",
        ),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Per-factor Rank-IC report over [start, end) — the Phase-4 go/no-go evidence.

    Computes every registered DIRECTIONAL factor point-in-time, processes
    cross-sectional factors under the PIT universe mask, correlates against
    execution-aware forward returns per horizon on the non-overlapping h-grid,
    and prints/persists the Newey-West-summarized evidence table.
    """
    # Argument parsing FIRST — bad input must exit before any filesystem touch.
    horizon_bars = _parse_horizons(horizons)
    start_arg = None if start is None else _parse_cli_utc(start, param="--start")
    end_arg = None if end is None else _parse_cli_utc(end, param="--end")

    # Heavy wiring deferred: importing the library/engine pulls pandas + duckdb.
    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research.ic_report import JSON_FILENAME, TEXT_FILENAME, ICReportRunner

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    start_ms = settings.data.backfill_start_ms if start_arg is None else start_arg
    end_ms = now_ms() if end_arg is None else end_arg
    out_dir = settings.paths.lake_dir.parent / "research" if out is None else Path(out)

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / _OPS_DB) as instruments:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        runner = ICReportRunner(
            FeatureEngine(reader, instruments, universe),
            reader,
            universe,
            default_registry(),
            paths=paths,
        )
        try:
            report = runner.run(start=start_ms, end=end_ms, horizons=horizon_bars, out_dir=out_dir)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc

    typer.echo(report.render_text())
    typer.echo("")
    typer.echo(f"json: {out_dir / JSON_FILENAME}")
    typer.echo(f"text: {out_dir / TEXT_FILENAME}")


@research_app.command()
def evaluate(
    run_dir: Annotated[
        str,
        typer.Argument(
            help="A walk-forward run directory (containing equity.parquet from "
            "`af research walkforward`)."
        ),
    ],
    config_matrix: Annotated[
        str | None,
        typer.Option(
            "--config-matrix",
            help="Optional parquet of a T x N per-period return matrix (columns = "
            "config variants) for the PBO CSCV test. Without it PBO is reported as "
            "not-available (a single config cannot be ranked cross-sectionally).",
        ),
    ] = None,
    log: Annotated[
        str | None,
        typer.Option(
            "--log",
            help="Experiment ledger path. Default: settings.paths.var_dir / experiments.jsonl.",
        ),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """The honest anti-overfit verdict over a walk-forward run (alphaDesign.md section 7.4).

    Loads the run's stitched OOS equity and the experiment ledger, computes the
    Deflated Sharpe Ratio (PSR vs the expected-max Sharpe of every distinct trial
    on the ledger) and prints the verdict: does it clear the DSR >= 0.95 deployment
    gate? When a ``--config-matrix`` of variant returns is supplied, also runs the
    PBO CSCV test (section 7.3) and reports whether PBO < 0.2.

    Read-only: no artifacts are written, the clock is not read, the ledger is not
    mutated. The trial count N is whatever the ledger already measured.
    """
    import numpy as np
    import pandas as pd

    from alphaforge.analytics.metrics import daily_returns
    from alphaforge.core.logging import setup_logging
    from alphaforge.validation import ExperimentLog, dsr_from_returns

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")

    equity_path = Path(run_dir) / "equity.parquet"
    if not equity_path.exists():
        typer.echo(f"error: no equity.parquet in {run_dir}", err=True)
        raise typer.Exit(1)

    frame = pd.read_parquet(equity_path)
    equity = pd.Series(
        frame["equity"].to_numpy(dtype="float64"),
        index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
        name="equity",
    )
    rets = daily_returns(equity)
    if len(rets) < 2:
        typer.echo("error: OOS curve spans < 2 UTC days; DSR is undefined", err=True)
        raise typer.Exit(1)

    ledger = ExperimentLog(Path(log) if log is not None else None)
    if log is None:
        ledger = ExperimentLog(settings.paths.var_dir / "experiments.jsonl")
    n_trials = ledger.n_trials()
    var_sr = ledger.trial_sharpe_variance()
    n_trials_used = max(2, n_trials)
    report = dsr_from_returns(rets, n_trials_used, var_sr)
    dsr_ok = report.dsr >= 0.95

    typer.echo(f"run: {run_dir}")
    typer.echo(f"ledger: {ledger.path}  (N_trials={n_trials}, used={n_trials_used})")
    typer.echo("")
    typer.echo(f"  SR (annualized) : {report.sr_ann: .4f}")
    typer.echo(f"  PSR(0)          : {report.psr: .4f}")
    typer.echo(f"  expected max SR*: {report.expected_max_sr: .4f}  (per period)")
    typer.echo(f"  DSR             : {report.dsr: .4f}")
    typer.echo(f"  DSR gate (>=0.95): {'CLEARS' if dsr_ok else 'FAILS'}")

    if config_matrix is not None:
        from alphaforge.validation import pbo_cscv

        matrix_path = Path(config_matrix)
        if not matrix_path.exists():
            typer.echo(f"error: config matrix {config_matrix} not found", err=True)
            raise typer.Exit(1)
        matrix = pd.read_parquet(matrix_path)
        try:
            pbo = pbo_cscv(matrix)
        except ValueError as exc:
            typer.echo(f"error: PBO: {exc}", err=True)
            raise typer.Exit(1) from exc
        pbo_ok = pbo.pbo < 0.2
        median_degradation = float(np.median(pbo.is_oos_pairs[:, 1]))
        typer.echo("")
        typer.echo(f"  PBO (CSCV)      : {pbo.pbo: .4f}  over {len(pbo.lambdas)} combinations")
        typer.echo(f"  median OOS SR of IS-best: {median_degradation: .4f}")
        typer.echo(f"  PBO gate (<0.20): {'CLEARS' if pbo_ok else 'FAILS'}")
    else:
        typer.echo("")
        typer.echo("  PBO (CSCV)      : not available (supply --config-matrix of >=2 variants)")

    typer.echo("")
    eligible = dsr_ok if config_matrix is None else (dsr_ok and pbo_ok)
    typer.echo(f"verdict: {'LIVE-ELIGIBLE' if eligible else 'NOT live-eligible'}")
