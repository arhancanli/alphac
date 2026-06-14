"""AlphaForge command-line interface.

Subcommand groups are registered here as phases land: data + instruments (Phase 2),
quality/universe (Phase 3), features (Phase 4), backtest (Phase 5+), paper/status/arm
(Phase 7+).
"""

import typer

from alphaforge.cli.backtest_cmds import backtest_app
from alphaforge.cli.data_cmds import data_app
from alphaforge.cli.instruments_cmds import instruments_app
from alphaforge.cli.ops_cmds import ops_app
from alphaforge.cli.paper_cmds import paper_app
from alphaforge.cli.quality_cmds import quality_app
from alphaforge.cli.research_cmds import research_app
from alphaforge.cli.universe_cmds import universe_app
from alphaforge.cli.walkforward_cmds import walkforward

app = typer.Typer(
    name="af",
    help="AlphaForge — institutional-grade mid-frequency quant trading system.",
    no_args_is_help=True,
)
app.add_typer(backtest_app, name="backtest")
app.add_typer(data_app, name="data")
app.add_typer(instruments_app, name="instruments")
app.add_typer(ops_app, name="ops")
app.add_typer(paper_app, name="paper")
app.add_typer(quality_app, name="quality")
app.add_typer(research_app, name="research")
app.add_typer(universe_app, name="universe")

# `af research walkforward` — the purged walk-forward OOS evaluation (Phase 6).
research_app.command("walkforward")(walkforward)


@app.callback()
def _root() -> None:
    """Root callback.

    Forces Typer into multi-command mode so ``af version`` (and future subcommand
    groups) resolve as subcommands even while only one command is registered.
    """


@app.command()
def version() -> None:
    """Print the installed alphaforge version."""
    from importlib.metadata import version as pkg_version

    typer.echo(pkg_version("alphaforge"))


if __name__ == "__main__":
    app()
