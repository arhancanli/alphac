"""Unit tests for :mod:`alphaforge.ops.backup` (offline, tmp_path only).

Covers: backup -> restore_drill round-trip on a synthetic TradingStore (seed
fills/equity/paper_state, back up, restore into a CLEAN dir, assert the ledger
rebuilds and reconciles); the online-backup-of-a-live-WAL-db case (a second
connection holds the source open mid-backup, the restored copy is still
consistent); a corrupted/inconsistent backup is CAUGHT by the drill (cash rebuilt
from fills disagrees with the recorded snapshot -> ok is False); prune by age;
missing ops.sqlite is skipped not fatal; predictions dir copied when present;
restore into a non-clean dir refused; no-backup restore raises. Nothing touches
./var or the network; every path is under tmp_path.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from alphaforge.core.types import AccountState, Fill, Liquidity, OrderRequest, OrderType, Side
from alphaforge.live.store import FillAudit, TradingStore
from alphaforge.ops.backup import BackupManager

T0 = 1_700_000_000_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
BTC = "BINANCE:PERP:BTCUSDT"
INITIAL_CASH = 100_000.0


def _stamp(ms: int) -> str:
    """Backup directory name for ``ms`` (must match BackupManager's 13-digit format)."""
    return f"{ms:013d}"


def _seed_coherent_store(db: Path) -> float:
    """Seed a TradingStore whose fills, equity curve, and blob reconcile.

    Two BUY fills of BTC; cash moves by ``-(qty*price + fee)`` each. The last
    equity point records the rebuilt cash so the restore drill's cash check passes.
    Returns the final cash for the caller to corrupt in negative tests.
    """
    cash = INITIAL_CASH
    fills_spec = [
        ("af-c0-BTC", 2.0, 100.0, 0.1, T0),
        ("af-c1-BTC", 1.0, 110.0, 0.05, T0 + HOUR_MS),
    ]
    with TradingStore(db) as store:
        for coid, qty, price, fee, cts in fills_spec:
            store.start_cycle(cts, now=cts + 90)
            req = OrderRequest(
                client_order_id=coid,
                instrument_id=BTC,
                side=Side.BUY,
                qty=qty,
                order_type=OrderType.MARKET,
                decision_ts=cts,
                decision_price=price,
                reason="rebalance",
            )
            store.record_intent(req, cts, now=cts + 90)
            fill = Fill(
                client_order_id=coid,
                instrument_id=BTC,
                side=Side.BUY,
                qty=qty,
                price=price,
                fee_quote=fee,
                liquidity=Liquidity.TAKER,
                ts=cts + 100,
            )
            audit = FillAudit(
                walked_price=price, modeled_price=price, slippage_bps=1.0, book_exhausted=False
            )
            store.mark_filled(fill, now=cts + 100, audit=audit)
            # PaperBroker cash identity: cash -= side.sign*qty*price + fee
            cash -= Side.BUY.sign * qty * price + fee
            # equity = cash + qty*mark; use mark == price so equity = cash + qty*price
            equity = cash + qty * price
            account = AccountState(equity_quote=equity, cash_quote=cash, positions=(), ts=cts + 110)
            store.snapshot_equity(cts, account)
            store.finish_cycle(cts, "ok", "traded", now=cts + 120)
        blob = json.dumps({"version": 1, "initial_cash": INITIAL_CASH, "cash": cash})
        store.save_paper_state(T0 + HOUR_MS, blob, now=T0 + HOUR_MS + 120)
    return cash


def test_backup_restore_drill_round_trip(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")

    report = mgr.backup(now=T0 + 2 * HOUR_MS)
    assert report.backup_dir.is_dir()
    assert (report.backup_dir / "trading.sqlite").is_file()
    assert report.total_bytes > 0

    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.ok is True, drill.detail
    assert drill.n_fills == 2
    assert drill.n_cycles == 2
    # final equity = last cash + qty*price = cash + 1*110
    assert drill.final_equity == pytest.approx(_expected_final_equity())
    assert "cash_rebuild=ok" in " ".join(drill.checks)


def _expected_final_equity() -> float:
    cash = INITIAL_CASH
    cash -= 2.0 * 100.0 + 0.1
    cash -= 1.0 * 110.0 + 0.05
    return cash + 1.0 * 110.0


def test_backup_of_live_wal_db_is_consistent(tmp_path: Path) -> None:
    """A second open connection holds the WAL during backup; the restore still reconciles."""
    var = tmp_path / "var"
    var.mkdir()
    db = var / "trading.sqlite"
    _seed_coherent_store(db)
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")

    # Hold a live writer connection in WAL mode across the backup (uncheckpointed
    # WAL tail present). A byte-cp could tear this; the online backup API must not.
    holder = sqlite3.connect(db)
    try:
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("BEGIN")
        holder.execute(
            "INSERT INTO equity_curve (cycle_ts, equity_quote, cash_quote, n_pos, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (T0 + 5 * HOUR_MS, 1.0, 1.0, 0, T0 + 5 * HOUR_MS),
        )
        # NOT committed: this uncommitted row must NOT appear in the consistent backup.
        mgr.backup(now=T0 + 3 * HOUR_MS)
    finally:
        holder.rollback()
        holder.close()

    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.ok is True, drill.detail
    # The uncommitted phantom row must be absent -> still exactly 2 cycles of equity.
    assert drill.n_fills == 2


def test_corrupted_ledger_is_caught(tmp_path: Path) -> None:
    """Deleting a fill from the backup breaks cash reconciliation -> drill reports NOT ok."""
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    report = mgr.backup(now=T0 + 2 * HOUR_MS)

    # Tamper the BACKUP: drop one fill so replaying fills no longer reproduces cash.
    conn = sqlite3.connect(report.backup_dir / "trading.sqlite")
    try:
        conn.execute("DELETE FROM fills WHERE client_order_id = 'af-c1-BTC'")
        conn.commit()
    finally:
        conn.close()

    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.ok is False
    assert "cash_rebuild=FAIL" in " ".join(drill.checks)


def test_nan_equity_is_caught(tmp_path: Path) -> None:
    """A non-finite recorded equity value trips the finiteness check -> drill NOT ok.

    The store's PRIMARY KEY on ``equity_curve.cycle_ts`` already guarantees the
    monotonicity invariant for a healthy DB; this exercises the OTHER consistency
    guard (no NaN/inf) on a backup whose equity value was corrupted to NaN.
    """
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    report = mgr.backup(now=T0 + 2 * HOUR_MS)

    # equity_quote is NOT NULL, so inject a true IEEE infinity via the SQL literal
    # 9e999 (stored as float inf, which the finiteness read must reject).
    conn = sqlite3.connect(report.backup_dir / "trading.sqlite")
    try:
        conn.execute("UPDATE equity_curve SET equity_quote = 9e999 WHERE cycle_ts = ?", (T0,))
        conn.commit()
    finally:
        conn.close()
    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.ok is False
    assert "finite_equity=FAIL" in " ".join(drill.checks)


def test_missing_ops_sqlite_skipped_not_fatal(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")  # no ops.sqlite created
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    report = mgr.backup(now=T0)
    assert "ops.sqlite" in report.skipped
    assert "predictions" in report.skipped
    # trading.sqlite still captured
    assert any(f.name == "trading.sqlite" and f.present for f in report.files)
    assert not (report.backup_dir / "ops.sqlite").exists()


def test_ops_sqlite_backed_up_when_present(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    # create a small ops.sqlite
    ops = sqlite3.connect(var / "ops.sqlite")
    ops.execute("CREATE TABLE heartbeat (ts INTEGER)")
    ops.execute("INSERT INTO heartbeat VALUES (1)")
    ops.commit()
    ops.close()
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    report = mgr.backup(now=T0)
    assert "ops.sqlite" not in report.skipped
    assert (report.backup_dir / "ops.sqlite").is_file()


def test_predictions_dir_copied_when_present(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    preds = var / "predictions"
    preds.mkdir()
    (preds / "p.parquet").write_bytes(b"x" * 64)
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    report = mgr.backup(now=T0)
    assert "predictions" not in report.skipped
    assert (report.backup_dir / "predictions" / "p.parquet").is_file()


def test_restore_into_non_clean_dir_refused(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    mgr.backup(now=T0)
    into = tmp_path / "restore"
    into.mkdir()
    (into / "trading.sqlite").write_bytes(b"stale")
    with pytest.raises(FileExistsError, match="clean dir"):
        mgr.restore_drill(into=into)


def test_restore_with_no_backup_raises(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    with pytest.raises(FileNotFoundError, match="no backup found"):
        mgr.restore_drill(into=tmp_path / "restore")


def test_restore_uses_latest_backup(tmp_path: Path) -> None:
    """With multiple backups, the drill restores the most recent (largest ms name)."""
    var = tmp_path / "var"
    var.mkdir()
    db = var / "trading.sqlite"
    _seed_coherent_store(db)
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    mgr.backup(now=T0)
    mgr.backup(now=T0 + DAY_MS)  # newer
    mgr.backup(now=T0 + 2 * DAY_MS)  # newest
    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.restored_from.name == _stamp(T0 + 2 * DAY_MS)
    assert drill.ok is True


def test_prune_by_age(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    backups = tmp_path / "backups"
    mgr = BackupManager(var_dir=var, backup_dir=backups)
    # three backups at day 0, 10, 40
    mgr.backup(now=T0)
    mgr.backup(now=T0 + 10 * DAY_MS)
    mgr.backup(now=T0 + 40 * DAY_MS)
    now = T0 + 40 * DAY_MS
    # keep_days=30 -> cutoff = now - 30d; the day-0 backup (40d old) is pruned,
    # the day-10 (30d old) is NOT (>= cutoff), the day-40 stays.
    removed = mgr.prune(keep_days=30, now=now)
    assert removed == 1
    remaining = sorted(p.name for p in backups.iterdir() if p.is_dir())
    assert remaining == [_stamp(T0 + 10 * DAY_MS), _stamp(T0 + 40 * DAY_MS)]


def test_prune_keep_zero_removes_all_past(tmp_path: Path) -> None:
    var = tmp_path / "var"
    var.mkdir()
    _seed_coherent_store(var / "trading.sqlite")
    backups = tmp_path / "backups"
    mgr = BackupManager(var_dir=var, backup_dir=backups)
    mgr.backup(now=T0)
    mgr.backup(now=T0 + DAY_MS)
    removed = mgr.prune(keep_days=0, now=T0 + 2 * DAY_MS)
    assert removed == 2


def test_prune_negative_keep_days_rejected(tmp_path: Path) -> None:
    mgr = BackupManager(var_dir=tmp_path / "var", backup_dir=tmp_path / "backups")
    with pytest.raises(ValueError, match="keep_days must be >= 0"):
        mgr.prune(keep_days=-1, now=T0)


def test_prune_ignores_non_numeric_dirs(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "not-a-stamp").mkdir()
    mgr = BackupManager(var_dir=tmp_path / "var", backup_dir=backups)
    assert mgr.prune(keep_days=0, now=T0) == 0
    assert (backups / "not-a-stamp").is_dir()  # untouched


def test_prune_missing_backup_dir_returns_zero(tmp_path: Path) -> None:
    mgr = BackupManager(var_dir=tmp_path / "var", backup_dir=tmp_path / "nope")
    assert mgr.prune(keep_days=7, now=T0) == 0


def test_drill_on_empty_store_is_ok(tmp_path: Path) -> None:
    """A fresh store with no fills/curve is internally consistent (nothing to contradict)."""
    var = tmp_path / "var"
    var.mkdir()
    with TradingStore(var / "trading.sqlite"):
        pass
    mgr = BackupManager(var_dir=var, backup_dir=tmp_path / "backups")
    mgr.backup(now=T0)
    drill = mgr.restore_drill(into=tmp_path / "restore")
    assert drill.ok is True
    assert drill.n_fills == 0
    assert drill.n_cycles == 0
    import math

    assert math.isnan(drill.final_equity)
