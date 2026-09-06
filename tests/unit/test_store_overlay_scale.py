"""The equity curve must carry the overlay scale in force, or the realized-vol leg cannot be
restored across `--once` processes.

Found 2026-09-05 beside the ladder defect: BlendStrategy._realized_vol_ann de-levers each bar's
return by the scale that was in force while it was earned (_scale_hist), and both histories live
only in memory. A fresh process per cycle has one equity point and no scale, so the fast regime
detector has been structurally 0.0 live. Persisting the scale per cycle (additive, nullable, the
same migration shape as the position-mark columns) is the precondition for seeding it on boot.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from alphaforge.core.types import AccountState
from alphaforge.live.store import TradingStore

T0 = 1_700_000_000_000
HOUR = 3_600_000


def _acct(equity: float, ts: int) -> AccountState:
    return AccountState(equity_quote=equity, cash_quote=equity, positions=(), ts=ts)


def test_snapshot_equity_records_the_overlay_scale_and_reads_it_back(tmp_path: Path) -> None:
    store = TradingStore(tmp_path / "t.sqlite")
    try:
        store.snapshot_equity(T0, _acct(100_000.0, T0), overlay_scale=0.83)
        store.snapshot_equity(T0 + HOUR, _acct(100_500.0, T0 + HOUR))  # no scale known this cycle
        pts = store.equity_curve_points()
        assert [p.cycle_ts for p in pts] == [T0, T0 + HOUR]
        assert pts[0].overlay_scale == 0.83
        assert math.isnan(pts[1].overlay_scale)
        assert pts[0].equity_quote == 100_000.0
        # the legacy tuple reader is untouched
        assert store.equity_curve()[0][:2] == (T0, 100_000.0)
    finally:
        store.close()


def test_an_old_database_gains_the_column_on_open(tmp_path: Path) -> None:
    """Frankfurt's trading DB predates the column: opening it must add the column and read the
    old rows as NaN scale, never fail or drop them."""
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE equity_curve (cycle_ts INTEGER PRIMARY KEY, equity_quote REAL NOT NULL, "
        "cash_quote REAL NOT NULL, n_pos INTEGER NOT NULL, ts INTEGER NOT NULL) WITHOUT ROWID;"
        f"INSERT INTO equity_curve VALUES ({T0}, 99000.0, 99000.0, 0, {T0});"
    )
    con.commit()
    con.close()
    store = TradingStore(path)
    try:
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(equity_curve)").fetchall()}
        assert "overlay_scale" in cols
        pts = store.equity_curve_points()
        assert len(pts) == 1 and math.isnan(pts[0].overlay_scale) and pts[0].equity_quote == 99000.0
        store.snapshot_equity(T0 + HOUR, _acct(99500.0, T0 + HOUR), overlay_scale=1.0)
        assert store.equity_curve_points()[1].overlay_scale == 1.0
    finally:
        store.close()


def test_a_nan_scale_is_stored_as_null_not_as_text(tmp_path: Path) -> None:
    store = TradingStore(tmp_path / "t.sqlite")
    try:
        store.snapshot_equity(T0, _acct(1.0, T0), overlay_scale=math.nan)
        raw = store._conn.execute("SELECT overlay_scale FROM equity_curve").fetchone()[0]
        assert raw is None
    finally:
        store.close()
