"""``af ops`` -- operational hardening for the unattended 30-day soak (Phase 8).

Four plain-text commands wiring the ``alphaforge.ops`` machinery (builder A) from
settings, each mapping to one Phase-8 gate item in buildabilityCritique.md
section 4:

* ``af ops backup`` -- ``sqlite3 .backup`` of the irreplaceable state
  (``var/trading.sqlite`` + ``var/ops.sqlite``, plus ``data/predictions`` if
  present) to a timestamped, off-box-copyable directory, then prune backups older
  than the retention window. The lake is re-derivable from the exchange; the
  trading store is NOT, so this is the nightly safety net.
* ``af ops restore-drill`` -- restore the LATEST backup into a CLEAN temp dir,
  rebuild the ledger/equity from the restored ``TradingStore``, and assert it is
  internally consistent. This is the gate command the owner runs to PROVE backups
  are restorable on a clean machine; it exits non-zero if the drill fails, so it
  can gate the soak from cron.
* ``af ops clock`` -- compare the exchange ``fetchTime`` against the local wall
  clock and report the skew + OK/FAIL (the per-cycle clock-sanity check surfaced
  as a one-shot operator command). HITS THE NETWORK when run (real ccxt client),
  so the ccxt import is deferred into the command body and there is no network
  test of this path -- the wiring is tested through a thin injectable seam.
* ``af ops slippage`` -- the modeled-vs-realized slippage review the gate
  requires (leakageCritique.md finding 8): PaperBroker fills carry walked-book vs
  cost-model audit columns, and this renders their distribution.

Wiring mirrors ``af paper`` / ``af backtest``: the trading store lives at
``settings.paths.var_dir / "trading.sqlite"``, ops state at ``.../ops.sqlite``,
backups under ``OpsCfg.backup_dir`` (default ``settings.paths.var_dir /
"backups"``) with ``OpsCfg.backup_keep_days`` retention (default 30). All heavy
imports (``alphaforge.ops.*``, ccxt) are deferred into command bodies so
``af ops --help`` stays fast and import-light.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.time import now_ms

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings
    from alphaforge.ops.backup import BackupManager, BackupReport, RestoreDrillReport
    from alphaforge.ops.clock import ClockCheck, ExchangeTimeSource

__all__ = ["ops_app"]

ops_app = typer.Typer(
    name="ops",
    help="Operational hardening: backups, restore drill, clock sanity, slippage review.",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"
_TRADING_DB: Final[str] = "trading.sqlite"
_BACKUPS_SUBDIR: Final[str] = "backups"
_DEFAULT_KEEP_DAYS: Final[int] = 30
_DEFAULT_MAX_SKEW_MS: Final[int] = 2000

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _load_settings(profile: str | None) -> Settings:
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


def _backup_dir(settings: Settings) -> Path:
    """Resolve the backup directory.

    Prefers ``settings.ops.backup_dir`` when an ``OpsCfg`` section exists (builder
    A may add one mirroring ``configs/base.yaml``); falls back to
    ``var_dir/backups`` so the command composes whether or not that section has
    landed. A relative ``backup_dir`` is resolved against ``var_dir``.
    """
    ops = getattr(settings, "ops", None)
    raw = getattr(ops, "backup_dir", None)
    if raw is None:
        return settings.paths.var_dir / _BACKUPS_SUBDIR
    path = Path(raw)
    return path if path.is_absolute() else settings.paths.var_dir / path


def _keep_days(settings: Settings) -> int:
    """Resolve the backup retention window in days (``OpsCfg`` or the 30d default)."""
    ops = getattr(settings, "ops", None)
    value = getattr(ops, "backup_keep_days", None)
    return _DEFAULT_KEEP_DAYS if value is None else int(value)


def _max_skew_ms(settings: Settings) -> int:
    """Resolve the clock-sanity skew tolerance in ms (``OpsCfg`` or the 2s default)."""
    ops = getattr(settings, "ops", None)
    value = getattr(ops, "max_skew_ms", None)
    return _DEFAULT_MAX_SKEW_MS if value is None else int(value)


def _build_exchange_time_source(exchange_id: str) -> ExchangeTimeSource:
    """Construct the real exchange clock source (HITS THE NETWORK on first use).

    Mirrors :class:`~alphaforge.data.sources.ccxt_source.CCXTDataSource`'s own
    lazy client construction, then wraps it in builder A's
    :class:`~alphaforge.ops.clock.CCXTExchangeTimeSource`. This is the ONLY code
    that reaches the live venue; it is a thin seam so tests inject a fake
    :class:`~alphaforge.ops.clock.ExchangeTimeSource` and never hit the network.
    Imported lazily so ``af ops --help`` and the offline test suite never import
    ccxt.
    """
    import ccxt

    from alphaforge.core.errors import ConfigError
    from alphaforge.ops.clock import CCXTExchangeTimeSource

    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise ConfigError(f"unknown ccxt exchange id {exchange_id!r}: no such class on ccxt")
    return CCXTExchangeTimeSource(exchange_cls({"enableRateLimit": True}))


@ops_app.callback()
def _ops() -> None:
    """Operational hardening commands (Phase 8: safe to run UNATTENDED)."""
    # Explicit callback keeps backup/restore-drill/clock/slippage as named subcommands.


# --------------------------------------------------------------------------- backup


@ops_app.command()
def backup(profile: _ProfileOpt = None) -> None:
    """Back up the irreplaceable trading state, then prune old backups.

    Runs ``BackupManager.backup()`` (a ``sqlite3 .backup`` of trading.sqlite +
    ops.sqlite into a timestamped subdirectory, copying ``data/predictions`` when
    present), prints every written path with its size, then prunes backups older
    than the retention window and reports how many were removed. The destination
    is meant to be copied OFF-BOX (rsync/litestream) by the operator -- this
    command only produces the local artifact.
    """
    from alphaforge.ops.backup import BackupManager

    settings = _load_settings(profile)
    backup_dir = _backup_dir(settings)
    keep_days = _keep_days(settings)
    now = now_ms()

    manager = BackupManager(var_dir=settings.paths.var_dir, backup_dir=backup_dir)
    report = manager.backup(now=now)
    _print_backup(report)

    removed = manager.prune(keep_days=keep_days, now=now)
    typer.echo(f"pruned {removed} backup(s) older than {keep_days}d")


# --------------------------------------------------------------------------- restore-drill


@ops_app.command("restore-drill")
def restore_drill(
    into: Annotated[
        Path | None,
        typer.Option(
            "--into",
            help="Restore into this directory instead of a fresh temp dir "
            "(must be empty/absent -- the drill demands a CLEAN target).",
        ),
    ] = None,
    profile: _ProfileOpt = None,
) -> None:
    """Prove backups are restorable: restore the latest, rebuild the ledger, assert it.

    Restores the LATEST backup into a clean directory (a fresh temp dir unless
    ``--into`` is given), rebuilds the ledger/equity from the restored
    ``TradingStore``, and checks it is internally consistent (equity == cash +
    position marks; fills replay). Prints the :class:`RestoreDrillReport` and
    EXITS 1 if the drill is not ``ok`` -- this is the gate command that fails the
    soak when backups cannot be restored on a clean machine. A missing or corrupt
    latest backup is a drill FAILURE (exit 1), never a crash.
    """
    from alphaforge.ops.backup import BackupManager

    settings = _load_settings(profile)
    backup_dir = _backup_dir(settings)
    manager = BackupManager(var_dir=settings.paths.var_dir, backup_dir=backup_dir)

    typer.echo("== af ops restore-drill ==")
    typer.echo(f"backup dir: {backup_dir}")

    ok = _run_restore_drill(manager, into=into)
    if not ok:
        raise typer.Exit(code=1)


def _run_restore_drill(manager: BackupManager, *, into: Path | None) -> bool:
    """Run the drill and print its report; return ``ok``.

    A drill against a MISSING or unreadable backup raises (``FileNotFoundError``
    when no backup exists, ``OSError``/``sqlite3.DatabaseError`` for a corrupt
    one); the gate treats every such failure as a FAILED drill (printed, exit 1
    by the caller), never a crash. ``into=None`` runs in a fresh temp dir that is
    cleaned up after the (in-memory) report is captured.
    """
    import sqlite3

    try:
        if into is not None:
            report = manager.restore_drill(into=into)
            _print_drill(report)
            return bool(report.ok)
        with tempfile.TemporaryDirectory(prefix="af-restore-drill-") as tmp:
            report = manager.restore_drill(into=Path(tmp))
            _print_drill(report)
            return bool(report.ok)
    except (FileNotFoundError, FileExistsError, OSError, sqlite3.DatabaseError) as exc:
        typer.echo("ok: False")
        typer.echo(f"detail: restore drill could not run: {exc}")
        typer.echo("RESTORE DRILL FAILED")
        return False


# --------------------------------------------------------------------------- clock


@ops_app.command()
def clock(profile: _ProfileOpt = None) -> None:
    """Report exchange-vs-local clock skew and OK/FAIL (per-cycle clock sanity).

    Builds :class:`~alphaforge.ops.clock.ClockSanity` over the REAL exchange
    (``CCXTExchangeTimeSource`` for ``settings.data.exchange``) and prints the
    local/exchange epoch-ms, the signed skew, and whether it is within the
    tolerance (``OpsCfg.max_skew_ms`` or 2000ms). HITS THE NETWORK when run; the
    ccxt import is deferred and there is no network test of this path. Exits 1 on
    FAIL so it doubles as a launchd/cron pre-flight gate.
    """

    settings = _load_settings(profile)
    source = _build_exchange_time_source(settings.data.exchange)
    result = _run_clock_check(source, max_skew_ms=_max_skew_ms(settings))
    _print_clock(result)
    if not bool(result.ok):
        raise typer.Exit(code=1)


def _run_clock_check(source: ExchangeTimeSource, *, max_skew_ms: int) -> ClockCheck:
    """Run one :class:`ClockSanity.check` against ``source`` (the testable seam).

    Factored out so a fake ``ExchangeTimeSource`` can drive the wiring offline:
    the command body builds the real (network) source, this runs the pure check.
    """
    from alphaforge.ops.clock import ClockSanity

    sanity = ClockSanity(source, max_skew_ms=max_skew_ms)
    return sanity.check(now=now_ms())


# --------------------------------------------------------------------------- slippage


@ops_app.command()
def slippage(profile: _ProfileOpt = None) -> None:
    """Render the modeled-vs-realized slippage review (leakageCritique.md finding 8).

    Reads the PaperBroker walked-vs-modeled audit columns from
    ``var/trading.sqlite`` via :meth:`SlippageReport.from_store` and prints
    :meth:`SlippageReport.render_text` -- n_fills, mean/median/p90/p99 of the
    walked-vs-modeled ``slippage_bps``, the count of book-exhausted fills, and a
    per-instrument breakdown. This is the one genuine validation signal in paper
    mode: paper fills walk a REAL order book, so this is not the cost model graded
    against itself.
    """
    from alphaforge.ops.slippage import SlippageReport

    settings = _load_settings(profile)
    db = settings.paths.var_dir / _TRADING_DB
    typer.echo("== af ops slippage ==")
    if not db.exists():
        typer.echo(f"no trading store yet at {db} (run `af paper run` first)")
        return
    report = SlippageReport.from_store(db)
    typer.echo(report.render_text())


# --------------------------------------------------------------------------- formatting


def _print_backup(report: BackupReport) -> None:
    """Print a :class:`BackupReport`: each captured/skipped source then the total.

    Captured files print their destination path and size; absent sources
    (``present`` false -- e.g. ``ops.sqlite`` in a fresh paper run) print a SKIP
    line so the operator sees they were considered and intentionally not fatal.
    """
    typer.echo("== af ops backup ==")
    typer.echo(f"backup dir: {report.backup_dir}")
    captured = 0
    for f in report.files:
        if f.present and f.dst is not None:
            captured += 1
            typer.echo(f"  {_fmt_size(f.size_bytes):>12}  {f.dst}")
        else:
            typer.echo(f"  {'SKIP':>12}  {f.name} (absent)")
    if captured == 0:
        typer.echo("  (no source files found to back up)")
    typer.echo(f"total: {_fmt_size(report.total_bytes)} across {captured} file(s)")


def _print_drill(report: RestoreDrillReport) -> None:
    """Print a :class:`RestoreDrillReport` (verdict + rebuilt-ledger figures)."""
    typer.echo(f"ok: {report.ok}")
    typer.echo(f"detail: {report.detail}")
    typer.echo(f"restored from: {report.restored_from}")
    typer.echo(
        f"rebuilt ledger: n_fills={report.n_fills}  n_cycles={report.n_cycles}  "
        f"final_equity={report.final_equity:.2f}"
    )
    for check in report.checks:
        typer.echo(f"  check: {check}")
    typer.echo("RESTORE DRILL PASSED" if report.ok else "RESTORE DRILL FAILED")


def _print_clock(result: ClockCheck) -> None:
    """Print a ClockCheck (local/exchange ms, skew, OK/FAIL)."""
    typer.echo("== af ops clock ==")
    typer.echo(f"local_ms:    {int(result.local_ms)}")
    typer.echo(f"exchange_ms: {int(result.exchange_ms)}")
    typer.echo(f"skew_ms:     {int(result.skew_ms):+d}")
    typer.echo("clock: OK" if result.ok else "clock: FAIL (skew exceeds tolerance)")


def _fmt_size(n: int) -> str:
    """Human-readable byte count (B/KiB/MiB/GiB, base-1024)."""
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"
