"""CLI tests for ``af ops`` (offline, tmp_path only, no real network).

The four commands are exercised through typer's :class:`CliRunner` against the
REAL ``alphaforge.ops`` machinery (builder A), seeded into a tmp store:

* ``backup`` / ``restore-drill`` -- a REAL :class:`~alphaforge.ops.backup.BackupManager`
  over a seeded :class:`TradingStore`: backup writes a timestamped copy, the drill
  restores the latest into a CLEAN dir and rebuilds+verifies the ledger. A missing
  backup is a FAILED drill (exit 1), proving the gate behavior end-to-end.
* ``slippage`` -- the real :class:`~alphaforge.ops.slippage.SlippageReport.from_store`
  reads the actual walked-vs-modeled audit columns.
* ``clock`` -- the network seam ``_build_exchange_time_source`` is monkeypatched
  to return builder A's offline :class:`FakeExchangeTimeSource`, so the real
  :class:`~alphaforge.ops.clock.ClockSanity` wiring runs with NO network.

Every command is pointed at an isolated var_dir via an env-injected
``AF_PATHS__VAR_DIR`` so nothing reads ./data or ./var.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alphaforge.cli.ops_cmds import ops_app
from alphaforge.core.types import AccountState, Fill, Liquidity, OrderRequest, OrderType, Side
from alphaforge.live.store import FillAudit, TradingStore

runner = CliRunner()

_CYCLE_TS = 1_700_000_000_000
_INITIAL_CASH = 100_000.0
# cash after the two seeded fills: 100000 - (1*30009 + 1) + (1*1999 - 1) = 71988.0
_FINAL_CASH = 71_988.0

# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate paths.var_dir under tmp via an ``AF_PATHS__VAR_DIR`` env override.

    ``load_settings`` infers the repo root from the alphaforge package, not this
    dir, so we steer only the var_dir (where every store/backup the commands touch
    lands) -- the env layer wins over YAML, so nothing reads ./var or ./data.
    """
    var_dir = tmp_path / "var"
    var_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))
    return tmp_path


def _seed_trading_store(db_path: Path) -> None:
    """Seed a TradingStore with two audited fills, an equity snapshot, and a blob.

    The blob carries ``initial_cash`` and the equity snapshot carries the cash that
    replaying the two fills onto that initial cash reproduces, so the real restore
    drill's INDEPENDENT cash-rebuild check passes (not just the finite/monotone
    checks).
    """
    with TradingStore(db_path) as store:
        store.start_cycle(_CYCLE_TS, now=_CYCLE_TS)
        specs = [
            ("BINANCE:PERP:BTCUSDT", Side.BUY, 30_000.0, 30_009.0, 3.0, False),
            ("BINANCE:PERP:ETHUSDT", Side.SELL, 2_000.0, 1_999.0, 5.0, True),
        ]
        for i, (iid, side, modeled, walked, slip_bps, exhausted) in enumerate(specs):
            coid = f"c-{i}"
            req = OrderRequest(
                client_order_id=coid,
                instrument_id=iid,
                side=side,
                qty=1.0,
                order_type=OrderType.MARKET,
                decision_ts=_CYCLE_TS,
                decision_price=modeled,
                reason="test",
            )
            store.record_intent(req, _CYCLE_TS, now=_CYCLE_TS)
            store.mark_submitted(coid, now=_CYCLE_TS)
            fill = Fill(
                client_order_id=coid,
                instrument_id=iid,
                side=side,
                qty=1.0,
                price=walked,
                fee_quote=1.0,
                liquidity=Liquidity.TAKER,
                ts=_CYCLE_TS,
            )
            audit = FillAudit(
                walked_price=walked,
                modeled_price=modeled,
                slippage_bps=slip_bps,
                book_exhausted=exhausted,
            )
            store.mark_filled(fill, now=_CYCLE_TS, audit=audit)

        store.snapshot_equity(
            _CYCLE_TS,
            AccountState(
                equity_quote=_FINAL_CASH,
                cash_quote=_FINAL_CASH,
                positions=(),
                ts=_CYCLE_TS,
            ),
        )
        store.save_paper_state(
            _CYCLE_TS, json.dumps({"initial_cash": _INITIAL_CASH}), now=_CYCLE_TS
        )


# --------------------------------------------------------------------------- backup


def test_backup_prints_report_and_exits_zero(repo: Path) -> None:
    _seed_trading_store(repo / "var" / "trading.sqlite")
    result = runner.invoke(ops_app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "af ops backup" in result.output
    assert "trading.sqlite" in result.output
    assert "pruned 0 backup(s)" in result.output
    # A timestamped backup directory was created under the isolated var_dir.
    backups = list((repo / "var" / "backups").iterdir())
    assert backups, "no backup directory created"
    assert (backups[0] / "trading.sqlite").is_file()


def test_backup_skips_absent_ops_db(repo: Path) -> None:
    # Only trading.sqlite is seeded -> ops.sqlite is SKIPPED, not fatal.
    _seed_trading_store(repo / "var" / "trading.sqlite")
    result = runner.invoke(ops_app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "ops.sqlite (absent)" in result.output


def test_backup_no_sources_is_not_fatal(repo: Path) -> None:
    # Nothing seeded at all -> backup still succeeds and reports nothing captured.
    result = runner.invoke(ops_app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "no source files found to back up" in result.output


# --------------------------------------------------------------------------- restore-drill


def test_restore_drill_passes_after_backup(repo: Path, tmp_path: Path) -> None:
    _seed_trading_store(repo / "var" / "trading.sqlite")
    assert runner.invoke(ops_app, ["backup"]).exit_code == 0
    into = tmp_path / "clean-restore"
    result = runner.invoke(ops_app, ["restore-drill", "--into", str(into)])
    assert result.exit_code == 0, result.output
    assert "ok: True" in result.output
    assert "RESTORE DRILL PASSED" in result.output
    assert "rebuilt ledger" in result.output
    assert (into / "trading.sqlite").exists()


def test_restore_drill_fails_when_no_backup_exists(repo: Path) -> None:
    # No `backup` was ever run -> no backups -> drill must FAIL and exit 1.
    result = runner.invoke(ops_app, ["restore-drill"])
    assert result.exit_code == 1, result.output
    assert "ok: False" in result.output
    assert "RESTORE DRILL FAILED" in result.output


def test_restore_drill_default_uses_temp_dir(repo: Path) -> None:
    _seed_trading_store(repo / "var" / "trading.sqlite")
    assert runner.invoke(ops_app, ["backup"]).exit_code == 0
    result = runner.invoke(ops_app, ["restore-drill"])  # no --into -> fresh temp dir
    assert result.exit_code == 0, result.output
    assert "RESTORE DRILL PASSED" in result.output


# --------------------------------------------------------------------------- slippage


def test_slippage_prints_stats_from_seeded_store(repo: Path) -> None:
    _seed_trading_store(repo / "var" / "trading.sqlite")
    result = runner.invoke(ops_app, ["slippage"])
    assert result.exit_code == 0, result.output
    assert "af ops slippage" in result.output
    assert "modeled-vs-realized slippage" in result.output
    assert "n=2" in result.output
    assert "BINANCE:PERP:BTCUSDT" in result.output
    assert "BINANCE:PERP:ETHUSDT" in result.output


def test_slippage_missing_store_is_graceful(repo: Path) -> None:
    result = runner.invoke(ops_app, ["slippage"])
    assert result.exit_code == 0, result.output
    assert "no trading store yet" in result.output


# --------------------------------------------------------------------------- clock


def test_clock_ok_with_injected_fake_source(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A small skew within tolerance -> OK and exit 0, no network."""
    import alphaforge.cli.ops_cmds as ops_cmds
    from alphaforge.ops.clock import FakeExchangeTimeSource

    # now_ms is read inside _run_clock_check; pin it so skew is deterministic.
    fixed_now = _CYCLE_TS
    monkeypatch.setattr(ops_cmds, "now_ms", lambda: fixed_now)
    monkeypatch.setattr(
        ops_cmds,
        "_build_exchange_time_source",
        lambda exchange_id: FakeExchangeTimeSource(fixed_now - 100),  # 100ms behind
    )
    result = runner.invoke(ops_app, ["clock"])
    assert result.exit_code == 0, result.output
    assert "af ops clock" in result.output
    assert "skew_ms:     +100" in result.output
    assert "clock: OK" in result.output


def test_clock_fail_when_skew_exceeds_tolerance(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skew beyond the 2s default -> FAIL and exit 1."""
    import alphaforge.cli.ops_cmds as ops_cmds
    from alphaforge.ops.clock import FakeExchangeTimeSource

    fixed_now = _CYCLE_TS
    monkeypatch.setattr(ops_cmds, "now_ms", lambda: fixed_now)
    monkeypatch.setattr(
        ops_cmds,
        "_build_exchange_time_source",
        lambda exchange_id: FakeExchangeTimeSource(fixed_now - 5_000),  # 5s behind
    )
    result = runner.invoke(ops_app, ["clock"])
    assert result.exit_code == 1, result.output
    assert "clock: FAIL" in result.output
    assert "skew_ms:     +5000" in result.output


# --------------------------------------------------------------------------- help / wiring


def test_ops_help_lists_all_commands() -> None:
    result = runner.invoke(ops_app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("backup", "restore-drill", "clock", "slippage"):
        assert cmd in result.output


def test_ops_registered_on_root_app() -> None:
    from alphaforge.cli.main import app

    result = runner.invoke(app, ["ops", "--help"])
    assert result.exit_code == 0
    assert "restore-drill" in result.output
