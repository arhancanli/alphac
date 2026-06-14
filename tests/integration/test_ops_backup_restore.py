"""Phase-8 GATE: ledger rebuilt from backups on a clean machine (buildabilityCritique.md section 4).

This is the integration gate the Phase-8 hardening exists to pass: drive a few
REAL :class:`~alphaforge.live.loop.LiveLoop` cycles through the full Phase-6/7
decision stack (reusing the offline soak harness in ``test_paper_soak``) so a
genuine ``trading.sqlite`` accumulates -- fills the PaperBroker produced by
WALKING a real (canned) order book, an equity curve, and the broker state blob --
then prove the three Phase-8 promises end to end:

1. **Ledger rebuilt from backups ALONE on a clean machine.** Take a consistent
   online backup with :class:`~alphaforge.ops.backup.BackupManager`, restore the
   latest into a CLEAN tmp dir the live store never touched, rebuild the cash
   ledger INDEPENDENTLY from the restored fills + the persisted ``initial_cash``,
   and assert it reconstructs the live store's recorded cash/equity tail. The
   drill reads ONLY the restored copy -- the source store is closed first -- so a
   pass means the backup is a complete, self-sufficient recovery artifact.
2. **The gate command behaves as a gate.** ``af ops restore-drill`` exits 0 on a
   good backup and 1 on a CORRUPTED one (a truncated fill ledger whose replayed
   cash no longer matches the recorded snapshot), so cron can fail the soak on a
   bad backup instead of trusting it silently.
3. **The genuine slippage signal survives the round trip.** The walked-vs-modeled
   audit columns the PaperBroker wrote (leakageCritique.md finding 8) are present
   in the live store and render through :class:`SlippageReport` -- the one
   non-circular validation signal of paper mode is reviewable post-soak.

Fully OFFLINE and deterministic: synthetic Parquet lake, canned books, injected
clock (all inherited from the soak harness); no network, no ``./data``/``./var``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from alphaforge.cli.ops_cmds import ops_app
from alphaforge.core.types import Side
from alphaforge.ops.backup import BackupManager
from alphaforge.ops.slippage import SlippageReport

# Reuse the REAL soak harness. Its non-fixture helpers (the `_World`/`_Stack`
# types and the bar/cycle constants) are imported directly; its `world` fixture is
# made available by registering the soak module as a pytest plugin (cleaner than
# importing the fixture by name, which would shadow the test parameter). The
# bare-module import path -- pytest 'prepend' import mode puts each test dir on
# sys.path -- mirrors the existing cross-test reuse in tests/unit/test_backfill_lock.py.
pytest_plugins = ["test_paper_soak"]

from test_paper_soak import (  # type: ignore[import-not-found]  # noqa: E402
    HOUR,
    N_BARS,
    SOAK_CYCLES,
    T0,
    _Stack,
    _World,
)

runner = CliRunner()

# A handful of cycles is enough to accumulate fills + an equity curve; the gate is
# about the backup/restore CONTRACT, not soak duration (that is owner calendar time).
_GATE_CYCLES = 6


def _run_cycles(world: _World, stack: _Stack, *, n: int) -> list[int]:
    """Drive ``n`` consecutive real LiveLoop cycles; return the cycle_ts list.

    Each cycle reaches an 'ok' terminal decision, walking the canned book through
    the PaperBroker so fills + audit columns + equity rows land in trading.sqlite.
    """
    stack.loop.recover_on_boot()
    first_idx = N_BARS - n
    cycles: list[int] = []
    for k in range(n):
        idx = first_idx + k
        cts = T0 + idx * HOUR
        cycles.append(cts)
        world.set_books(stack, idx=idx, ts=cts)
        report = stack.loop.run_cycle(cts)
        assert report.status == "ok", f"cycle {k} -> {report.status}: {report.detail}"
    return cycles


def _recorded_cash_equity_tail(db: Path) -> tuple[float, float]:
    """Read the LAST (cash_quote, equity_quote) the live store recorded (ground truth)."""
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT cash_quote, equity_quote FROM equity_curve ORDER BY cycle_ts DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "soak produced no equity curve"
    return float(row["cash_quote"]), float(row["equity_quote"])


# --------------------------------------------------------------------- the gate


def test_ledger_rebuilt_from_backup_alone_on_clean_machine(world: _World, tmp_path: Path) -> None:
    """GATE: a backup of a real soak store restores+rebuilds a consistent ledger alone.

    Drives real cycles, takes a consistent online backup, CLOSES the live store
    (the 'machine' is gone), then restores the latest backup into a clean dir the
    live store never saw and rebuilds the ledger purely from that copy. The
    rebuilt cash must reproduce the live store's recorded tail, the equity curve
    must be finite + strictly time-ordered, and the drill must report ``ok``.
    """
    var_dir = tmp_path / "live-var"
    var_dir.mkdir()
    stack = world.new_stack(restore_blob=None, db_name="trading.sqlite")
    # Point the live store at the isolated var_dir the BackupManager will read.
    db = var_dir / "trading.sqlite"
    # The harness writes into world.tmp_path; relocate to var_dir for clean semantics.
    stack.store.close()
    fresh = _restack_in_var(world, var_dir)
    cycles = _run_cycles(world, fresh, n=_GATE_CYCLES)

    # N/M accounting is exact and the store accumulated genuine, audited fills.
    expected, run_, skipped = fresh.store.expected_vs_run(cycles[0], cycles[-1], HOUR)
    assert (expected, run_, skipped) == (_GATE_CYCLES, _GATE_CYCLES, 0)
    assert fresh.broker.fills, "the gate needs at least one real fill to rebuild from"
    assert fresh.broker.audits, "fills must carry walked-vs-modeled audit rows"
    recorded_cash, recorded_equity = _recorded_cash_equity_tail(db)

    # Independently recompute the expected rebuilt cash from the broker's fills +
    # initial cash, using the SAME identity the restore drill uses. This makes the
    # gate assert a concrete number, not merely the drill's internal self-check.
    expected_rebuilt = 100_000.0
    fills_rows = _fills_from_db(db)
    for side, qty, price, fee in fills_rows:
        expected_rebuilt -= side.sign * qty * price + fee
    assert expected_rebuilt == pytest.approx(recorded_cash, abs=1e-6)

    # ---- the machine is gone: only the backup survives ----
    backup_dir = tmp_path / "offbox-backups"
    manager = BackupManager(var_dir=var_dir, backup_dir=backup_dir)
    report = manager.backup(now=cycles[-1] + HOUR)
    assert (report.backup_dir / "trading.sqlite").is_file()
    fresh.store.close()  # close the LIVE store so the drill reads the backup ALONE.

    clean = tmp_path / "clean-machine"  # a dir the live store NEVER touched.
    drill = manager.restore_drill(into=clean)

    assert drill.ok, f"restore drill failed: {drill.detail} ({drill.checks})"
    assert drill.n_fills == len(fills_rows)
    assert drill.n_cycles == _GATE_CYCLES
    # The rebuilt ledger reproduces the live store's recorded equity tail.
    assert drill.final_equity == pytest.approx(recorded_equity, abs=1e-6)
    # The restored copy is a real, independent file on the clean machine.
    assert (clean / "trading.sqlite").is_file()
    assert drill.restored_from == report.backup_dir
    # The drill's three internal checks all passed (no FAIL token anywhere).
    assert all("FAIL" not in c for c in drill.checks), drill.checks


def test_restore_drill_cli_exit_zero_good_then_one_on_corrupt(
    world: _World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``af ops restore-drill`` exits 0 on a good backup and 1 on a corrupted one.

    Uses the REAL CLI wiring (no monkeypatched ops machinery) pointed at an
    isolated var_dir via ``AF_PATHS__VAR_DIR``. After a good backup the drill
    passes (exit 0). We then corrupt the backed-up ledger -- delete the last fill
    so replayed cash no longer matches the recorded snapshot -- and the SAME
    command must fail the gate (exit 1), proving cron can trust the exit code.
    """
    var_dir = tmp_path / "var"
    var_dir.mkdir()
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))

    stack = _restack_in_var(world, var_dir)
    _run_cycles(world, stack, n=_GATE_CYCLES)
    stack.store.close()

    # Good backup -> good drill -> exit 0.
    assert runner.invoke(ops_app, ["backup"]).exit_code == 0
    good = runner.invoke(ops_app, ["restore-drill", "--into", str(tmp_path / "ok")])
    assert good.exit_code == 0, good.output
    assert "RESTORE DRILL PASSED" in good.output
    assert "ok: True" in good.output

    # Corrupt the BACKED-UP ledger: drop the last fill so the independent cash
    # rebuild diverges from the recorded snapshot (a torn/incomplete backup).
    backup_db = _latest_backup_trading_db(var_dir / "backups")
    _delete_last_fill(backup_db)

    bad = runner.invoke(ops_app, ["restore-drill", "--into", str(tmp_path / "bad")])
    assert bad.exit_code == 1, bad.output
    assert "RESTORE DRILL FAILED" in bad.output
    assert "cash_rebuild=FAIL" in bad.output


def test_slippage_signal_renders_from_real_soak_store(world: _World, tmp_path: Path) -> None:
    """The walked-vs-modeled audit (finding 8) survives the soak and renders.

    The genuine slippage signal must be present in the real store the soak wrote
    and reviewable via the report the Phase-8 gate requires.
    """
    var_dir = tmp_path / "var"
    var_dir.mkdir()
    stack = _restack_in_var(world, var_dir)
    _run_cycles(world, stack, n=_GATE_CYCLES)
    n_audited = len(stack.broker.audits)
    stack.store.close()

    db = var_dir / "trading.sqlite"
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_fills == n_audited, "every audited fill must surface in the report"
    assert summary.per_instrument, "the report must break down by instrument"
    # The aggregate is the count-weighted whole of the per-instrument rows.
    assert sum(r.n_fills for r in summary.per_instrument) == summary.n_fills
    # Every reported statistic is finite (no NaN leaked from an empty bucket).
    for r in summary.per_instrument:
        assert all(np.isfinite(x) for x in (r.mean_bps, r.median_bps, r.p90_bps, r.p99_bps))

    text = SlippageReport.from_store(db).render_text()
    assert "modeled-vs-realized slippage" in text
    assert f"n={summary.n_fills}" in text


# ------------------------------------------------------------------- harness glue


def _restack_in_var(world: _World, var_dir: Path) -> _Stack:
    """Build a soak ``_Stack`` whose TradingStore lives under ``var_dir``.

    The soak harness writes ``trading.sqlite`` under ``world.tmp_path``; for the
    Phase-8 gate the store must sit in the var_dir the BackupManager/CLI read, so
    we temporarily point the harness's base dir at ``var_dir`` while building the
    stack, then restore it (the lake/universe live under the original tmp_path).
    """
    original = world.tmp_path
    object.__setattr__(world, "tmp_path", var_dir)
    try:
        return world.new_stack(restore_blob=None, db_name="trading.sqlite")
    finally:
        object.__setattr__(world, "tmp_path", original)


def _fills_from_db(db: Path) -> list[tuple[Side, float, float, float]]:
    """Read ``(side, qty, price, fee_quote)`` for every fill, ordered by fill_id."""
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT side, qty, price, fee_quote FROM fills ORDER BY fill_id"
        ).fetchall()
    finally:
        conn.close()
    return [
        (Side(str(r["side"])), float(r["qty"]), float(r["price"]), float(r["fee_quote"]))
        for r in rows
    ]


def _latest_backup_trading_db(backup_root: Path) -> Path:
    """Return the ``trading.sqlite`` inside the most recent (largest-epoch-ms) backup."""
    dirs = [d for d in backup_root.iterdir() if d.is_dir() and d.name.isdigit()]
    assert dirs, f"no backup directories under {backup_root}"
    latest = max(dirs, key=lambda d: int(d.name))
    return latest / "trading.sqlite"


def _delete_last_fill(db: Path) -> None:
    """Delete the highest-fill_id row, corrupting the cash-replay invariant."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM fills WHERE fill_id = (SELECT MAX(fill_id) FROM fills)")
        conn.commit()
    finally:
        conn.close()


def _blob_initial_cash(db: Path) -> float:
    """Recover ``initial_cash`` from the latest persisted paper_state blob (sanity helper)."""
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT blob FROM paper_state ORDER BY cycle_ts DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None
    return float(json.loads(str(row["blob"]))["initial_cash"])


def test_soak_window_covers_at_least_the_gate(world: _World, tmp_path: Path) -> None:
    """Guardrail: the gate runs fewer than the full soak window (fast) but >1 cycle.

    Keeps the gate honest if the soak constants change: it must drive at least 2
    real cycles (so the equity curve's monotonicity check is non-trivial) and stay
    within the harness's bar budget.
    """
    assert 2 <= _GATE_CYCLES <= SOAK_CYCLES <= N_BARS
    # The blob's initial_cash is the documented field the restore drill relies on.
    var_dir = tmp_path / "var"
    var_dir.mkdir()
    stack = _restack_in_var(world, var_dir)
    _run_cycles(world, stack, n=_GATE_CYCLES)
    stack.store.close()
    assert _blob_initial_cash(var_dir / "trading.sqlite") == 100_000.0
