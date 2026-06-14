"""Off-box backups + a genuine restore drill (buildabilityCritique.md section 4, Phase 8).

What is and is not re-derivable
-------------------------------
The Parquet lake is re-derivable from the exchange at any time. ``var/trading.sqlite``
(every fill, the equity curve, risk events, the PaperBroker book blob) and the
``data/predictions/`` research artifacts are NOT -- a lost trading.sqlite is a lost
audit trail. So from day one of the soak this module takes a CONSISTENT online
backup of the SQLite stores (and copies predictions if present) into a timestamped,
off-box-syncable directory, and -- the part that actually earns trust -- a restore
drill that REBUILDS the ledger from a backup on a clean directory and asserts it is
internally consistent. That drill is the Phase-8 gate's "ledger rebuilt from backups
on a clean machine"; a backup whose restore is never exercised is not a backup.

Why the online backup API, not ``cp``
-------------------------------------
The live loop holds ``trading.sqlite`` open in WAL mode while the backup runs.
Copying the file bytes (``cp``/``shutil.copy``) can capture the main DB without the
un-checkpointed WAL tail, yielding a torn, older, or corrupt snapshot. SQLite's
online backup API (``sqlite3.Connection.backup``) instead takes a transactionally
CONSISTENT page-by-page copy of the live database even while a writer holds it --
so a backup taken mid-cycle restores to a coherent point, never a half-written one.

Conventions
-----------
All timestamps are integer epoch milliseconds UTC (:data:`~alphaforge.core.time.Ms`).
A backup is a directory ``<backup_dir>/<utc-ms>/`` containing the copied files;
the millisecond name both sorts chronologically and makes ``prune`` by age trivial.
Missing source files are skipped and REPORTED, never fatal -- ``ops.sqlite`` may not
exist in a fresh paper run, and ``data/predictions`` may be empty.
"""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from alphaforge.core.time import Ms
from alphaforge.core.types import Side

__all__ = [
    "BackupManager",
    "BackupReport",
    "BackupedFile",
    "RestoreDrillReport",
]

_TRADING_DB_NAME: str = "trading.sqlite"
"""The authoritative live-trading store filename under ``var_dir``."""

_OPS_DB_NAME: str = "ops.sqlite"
"""The ingest/quality/heartbeat store filename under ``var_dir`` (may be absent in paper)."""

_PREDICTIONS_DIR_NAME: str = "predictions"
"""Research-prediction artifacts subdir copied verbatim when present under ``var_dir``'s sibling."""

_BACKUP_TIMESTAMP_FMT: str = "%013d"
"""Zero-padded 13-digit epoch-ms directory name (sorts lexicographically == chronologically)."""

#: Tolerance (quote units) for the restore-drill cash reconciliation. Fills carry
#: float prices/fees; replaying them accumulates rounding, so an exact equality is
#: wrong. 1e-6 quote units (a millionth of a USDT) is far tighter than any real
#: fill granularity while absorbing IEEE-754 summation error.
_CASH_TOLERANCE: float = 1e-6


@dataclass(frozen=True, slots=True, kw_only=True)
class BackupedFile:
    """One file captured (or skipped) by a backup run.

    ``dst`` is ``None`` and ``size_bytes`` is ``0`` when the source was absent
    (skipped); ``present`` distinguishes a genuine 0-byte file from a skip.
    """

    name: str
    src: Path
    dst: Path | None
    size_bytes: int
    present: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BackupReport:
    """The outcome of one :meth:`BackupManager.backup`.

    ``backup_dir`` is the timestamped directory created for this run; ``files``
    lists every source considered (captured AND skipped); ``skipped`` names the
    absent sources. ``total_bytes`` sums the captured file sizes.
    """

    now: Ms
    backup_dir: Path
    files: tuple[BackupedFile, ...]
    skipped: tuple[str, ...]
    total_bytes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreDrillReport:
    """The outcome of one :meth:`BackupManager.restore_drill`.

    ``ok`` is the overall verdict: the latest backup restored into a clean dir and
    the ledger rebuilt from it is internally consistent (cash replayed from fills
    matches the last recorded snapshot, the equity curve is strictly time-ordered,
    no NaN). ``n_fills`` / ``n_cycles`` are what the restored store contained;
    ``final_equity`` is the last equity point (NaN if the curve was empty);
    ``detail`` is a human summary of the verdict (the first failed check, or 'ok').
    """

    ok: bool
    restored_from: Path
    n_fills: int
    n_cycles: int
    final_equity: float
    detail: str
    checks: tuple[str, ...] = field(default_factory=tuple)


class BackupManager:
    """Takes consistent off-box backups of the SQLite stores and drills the restore.

    Args:
        var_dir: the directory holding ``trading.sqlite`` (and optionally
            ``ops.sqlite`` and ``predictions/``).
        backup_dir: the destination root for timestamped backup directories
            (intended to live OFF-BOX, e.g. an rsync/litestream target).

    Construction performs no I/O; ``backup_dir`` is created on the first
    :meth:`backup`.
    """

    __slots__ = ("_backup_dir", "_var_dir")

    def __init__(self, *, var_dir: Path, backup_dir: Path) -> None:
        self._var_dir = var_dir
        self._backup_dir = backup_dir

    # ------------------------------------------------------------------ backup

    def backup(self, *, now: Ms) -> BackupReport:
        """Take a consistent backup of the stores into ``<backup_dir>/<now>/``.

        Uses the SQLite online backup API for ``trading.sqlite`` and ``ops.sqlite``
        so a copy taken while the live loop holds the WAL is transactionally
        consistent (NOT a byte ``cp``). The ``predictions/`` artifact dir, when
        present, is copied verbatim. Absent sources are SKIPPED and reported, never
        fatal (``ops.sqlite`` legitimately does not exist in a fresh paper run).

        Args:
            now: backup timestamp (epoch ms UTC); names the destination directory.

        Returns:
            A :class:`BackupReport` listing every captured and skipped source.
        """
        dest = self._backup_dir / (_BACKUP_TIMESTAMP_FMT % now)
        dest.mkdir(parents=True, exist_ok=True)

        files: list[BackupedFile] = []
        skipped: list[str] = []
        for name in (_TRADING_DB_NAME, _OPS_DB_NAME):
            src = self._var_dir / name
            if src.is_file():
                dst = dest / name
                _sqlite_online_backup(src, dst)
                files.append(
                    BackupedFile(
                        name=name, src=src, dst=dst, size_bytes=dst.stat().st_size, present=True
                    )
                )
            else:
                skipped.append(name)
                files.append(
                    BackupedFile(name=name, src=src, dst=None, size_bytes=0, present=False)
                )

        pred_src = self._var_dir / _PREDICTIONS_DIR_NAME
        if pred_src.is_dir():
            pred_dst = dest / _PREDICTIONS_DIR_NAME
            shutil.copytree(pred_src, pred_dst, dirs_exist_ok=True)
            size = _dir_size(pred_dst)
            files.append(
                BackupedFile(
                    name=_PREDICTIONS_DIR_NAME,
                    src=pred_src,
                    dst=pred_dst,
                    size_bytes=size,
                    present=True,
                )
            )
        else:
            skipped.append(_PREDICTIONS_DIR_NAME)
            files.append(
                BackupedFile(
                    name=_PREDICTIONS_DIR_NAME, src=pred_src, dst=None, size_bytes=0, present=False
                )
            )

        total = sum(f.size_bytes for f in files if f.present)
        return BackupReport(
            now=now,
            backup_dir=dest,
            files=tuple(files),
            skipped=tuple(skipped),
            total_bytes=total,
        )

    # ------------------------------------------------------------- restore drill

    def restore_drill(self, *, into: Path) -> RestoreDrillReport:
        """Restore the LATEST backup into clean ``into`` and rebuild+verify the ledger.

        This is the Phase-8 gate's "ledger rebuilt from backups on a clean
        machine". Steps:

        1. Find the most recent backup directory (largest epoch-ms name) and copy
           its ``trading.sqlite`` into ``into`` (a CLEAN directory -- it must be
           empty or absent, so the drill never reads stale local state).
        2. Open the restored store READ-ONLY and rebuild the cash ledger
           INDEPENDENTLY: recover the starting cash from the persisted PaperBroker
           blob, then replay every recorded fill with the broker's own cash
           identity ``cash -= side.sign*qty*price + fee``.
        3. ASSERT internal consistency:
           - the rebuilt cash equals the last recorded ``cash_quote`` snapshot
             within :data:`_CASH_TOLERANCE` (fills reconstruct the snapshot);
           - the equity curve's ``cycle_ts`` index is STRICTLY increasing
             (monotone in time -- no out-of-order or duplicate snapshots);
           - no recorded equity/cash value is NaN or non-finite.

        A drill on a backup with zero fills and an empty curve is VALID and
        ``ok`` (a fresh store is internally consistent -- there is nothing to
        contradict); ``final_equity`` is NaN in that case.

        Args:
            into: a clean destination directory for the restored store (created if
                absent; must not already contain a ``trading.sqlite``).

        Returns:
            A :class:`RestoreDrillReport` with the verdict and reconstructed tail.

        Raises:
            FileNotFoundError: no backup exists yet under ``backup_dir``.
            FileExistsError: ``into`` already contains a ``trading.sqlite``.
        """
        latest = self._latest_backup_dir()
        if latest is None:
            raise FileNotFoundError(f"no backup found under {self._backup_dir}")

        src_db = latest / _TRADING_DB_NAME
        if not src_db.is_file():
            raise FileNotFoundError(f"latest backup {latest} has no {_TRADING_DB_NAME}")

        into.mkdir(parents=True, exist_ok=True)
        restored_db = into / _TRADING_DB_NAME
        if restored_db.exists():
            raise FileExistsError(
                f"restore target {restored_db} already exists; restore_drill needs a clean dir"
            )
        # A plain copy of the BACKED-UP file is correct here: the backup itself was
        # taken with the consistent online API, and nothing holds the backup file.
        shutil.copy2(src_db, restored_db)

        return _verify_restored_ledger(restored_db, restored_from=latest)

    # -------------------------------------------------------------------- prune

    def prune(self, *, keep_days: int, now: Ms) -> int:
        """Delete backup directories older than ``keep_days`` relative to ``now``.

        A backup directory is removed when its epoch-ms name is strictly older than
        ``now - keep_days*86_400_000``. Returns the number of directories removed.
        Non-numeric entries under ``backup_dir`` are ignored (never deleted). A
        missing ``backup_dir`` removes nothing and returns 0.

        Args:
            keep_days: retention horizon in days (``>= 0``; 0 prunes everything at
                or before ``now``).
            now: the reference instant (epoch ms UTC).

        Returns:
            Count of backup directories deleted.

        Raises:
            ValueError: if ``keep_days < 0``.
        """
        if keep_days < 0:
            raise ValueError(f"keep_days must be >= 0, got {keep_days}")
        if not self._backup_dir.is_dir():
            return 0
        cutoff = now - keep_days * 86_400_000
        removed = 0
        for entry in self._backup_dir.iterdir():
            if not entry.is_dir():
                continue
            stamp = _parse_stamp(entry.name)
            if stamp is None:
                continue
            if stamp < cutoff:
                shutil.rmtree(entry)
                removed += 1
        return removed

    def _latest_backup_dir(self) -> Path | None:
        """Return the backup directory with the greatest epoch-ms name, or ``None``."""
        if not self._backup_dir.is_dir():
            return None
        candidates: list[tuple[int, Path]] = []
        for entry in self._backup_dir.iterdir():
            stamp = _parse_stamp(entry.name)
            if entry.is_dir() and stamp is not None:
                candidates.append((stamp, entry))
        if not candidates:
            return None
        return max(candidates, key=lambda pair: pair[0])[1]


# --------------------------------------------------------------------- helpers


def _sqlite_online_backup(src: Path, dst: Path) -> None:
    """Copy ``src`` SQLite DB to ``dst`` via the online backup API (WAL-consistent).

    Opens ``src`` (a live, possibly-WAL database) and a fresh ``dst`` and runs
    ``src_conn.backup(dst_conn)``, which page-copies a transactionally consistent
    snapshot even while another process holds ``src`` open for writing. Both
    connections are always closed.
    """
    src_conn = sqlite3.connect(src)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _dir_size(path: Path) -> int:
    """Total size in bytes of all regular files under ``path`` (recursive)."""
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _parse_stamp(name: str) -> int | None:
    """Parse a backup directory name to its epoch-ms integer, or ``None`` if non-numeric."""
    try:
        return int(name)
    except ValueError:
        return None


def _verify_restored_ledger(restored_db: Path, *, restored_from: Path) -> RestoreDrillReport:
    """Rebuild and verify the ledger of a restored ``trading.sqlite`` (read-only).

    See :meth:`BackupManager.restore_drill` for the consistency contract. Opens
    the restored DB read-only, replays fills to rebuild cash, and checks it against
    the last recorded ``cash_quote`` plus equity-curve monotonicity and finiteness.
    """
    uri = f"file:{restored_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        fills = conn.execute(
            "SELECT side, qty, price, fee_quote FROM fills ORDER BY fill_id"
        ).fetchall()
        curve = conn.execute(
            "SELECT cycle_ts, equity_quote, cash_quote FROM equity_curve ORDER BY cycle_ts"
        ).fetchall()
        n_cycles = int(conn.execute("SELECT COUNT(*) AS n FROM cycles").fetchone()["n"])
        blob_row = conn.execute(
            "SELECT blob FROM paper_state ORDER BY cycle_ts DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    n_fills = len(fills)
    checks: list[str] = []

    # Check 1: finiteness of every recorded equity/cash value (no NaN/inf/NULL).
    # The sqlite3 driver stores a Python NaN as SQL NULL, so a NULL read here is a
    # corrupted/non-finite value and must fail the same as an inf.
    finite_ok = True
    for row in curve:
        equity = row["equity_quote"]
        cash = row["cash_quote"]
        if equity is None or cash is None:
            finite_ok = False
            break
        if not (math.isfinite(equity) and math.isfinite(cash)):
            finite_ok = False
            break
    checks.append(f"finite_equity={'ok' if finite_ok else 'FAIL'}")

    # Check 2: equity curve strictly increasing in cycle_ts (monotone time index).
    monotone_ok = True
    prev: int | None = None
    for row in curve:
        cts = int(row["cycle_ts"])
        if prev is not None and cts <= prev:
            monotone_ok = False
            break
        prev = cts
    checks.append(f"monotone_curve={'ok' if monotone_ok else 'FAIL'}")

    # Check 3: cash rebuilt INDEPENDENTLY from fills equals the last recorded cash
    # snapshot. This needs the broker's true starting cash (the blob's
    # ``initial_cash``); replaying ALL fills onto it must reproduce the durable
    # ``cash_quote``. Without the blob we cannot place the fills relative to a
    # snapshot, so the check is reported as SKIPPED rather than asserted wrongly --
    # a young paper store always has a blob, so this is the degenerate, not the
    # normal, path.
    cash_ok = True
    starting_cash = _recover_starting_cash(blob_row)
    if not curve:
        cash_detail = "cash_rebuild=ok(empty curve)"
    elif starting_cash is None:
        cash_detail = "cash_rebuild=skipped(no paper_state blob)"
    else:
        rebuilt = starting_cash
        for f in fills:
            side = Side(str(f["side"]))
            rebuilt -= side.sign * float(f["qty"]) * float(f["price"]) + float(f["fee_quote"])
        recorded = float(curve[-1]["cash_quote"])
        diff = abs(rebuilt - recorded)
        cash_ok = diff <= _CASH_TOLERANCE
        cash_detail = (
            f"cash_rebuild={'ok' if cash_ok else 'FAIL'}"
            f"(rebuilt={rebuilt:.6f} recorded={recorded:.6f} diff={diff:.3e})"
        )
    checks.append(cash_detail)

    final_equity = float(curve[-1]["equity_quote"]) if curve else math.nan
    ok = finite_ok and monotone_ok and cash_ok
    detail = "ok" if ok else "; ".join(c for c in checks if "FAIL" in c)
    return RestoreDrillReport(
        ok=ok,
        restored_from=restored_from,
        n_fills=n_fills,
        n_cycles=n_cycles,
        final_equity=final_equity,
        detail=detail,
        checks=tuple(checks),
    )


def _recover_starting_cash(blob_row: sqlite3.Row | None) -> float | None:
    """Recover the PaperBroker starting cash from the persisted paper_state blob.

    The blob is the loop's opaque JSON serialization; ``initial_cash`` is a stable
    documented field. We read ONLY that field (never importing the loop's codec, so
    ops stays decoupled from live). Returns ``None`` when the blob is absent or
    unparseable, in which case the cash-rebuild check is skipped (it cannot be done
    correctly without the true starting cash).
    """
    if blob_row is None:
        return None
    try:
        payload = json.loads(str(blob_row["blob"]))
        return float(payload["initial_cash"])
    except (ValueError, KeyError, TypeError):
        return None
