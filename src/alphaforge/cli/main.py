"""AlphaForge command-line interface.

Subcommand groups are registered here as phases land: data + instruments (Phase 2),
quality/universe (Phase 3), features (Phase 4), backtest (Phase 5+), paper/status/arm
(Phase 7+).
"""

import typer

from alphaforge.cli.data_cmds import data_app
from alphaforge.cli.instruments_cmds import instruments_app

app = typer.Typer(
    name="af",
    help="AlphaForge — institutional-grade mid-frequency quant trading system.",
    no_args_is_help=True,
)
app.add_typer(data_app, name="data")
app.add_typer(instruments_app, name="instruments")


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
