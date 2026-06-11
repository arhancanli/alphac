"""AlphaForge command-line interface.

Subcommand groups are registered here as phases land: data (Phase 2), quality/universe
(Phase 3), features (Phase 4), backtest (Phase 5+), paper/status/arm (Phase 7+).
"""

import typer

app = typer.Typer(
    name="af",
    help="AlphaForge — institutional-grade mid-frequency quant trading system.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed alphaforge version."""
    from importlib.metadata import version as pkg_version

    typer.echo(pkg_version("alphaforge"))


if __name__ == "__main__":
    app()
