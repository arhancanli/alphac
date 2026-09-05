"""TradingStore: the source of truth for live PAPER trading state (execDesign.md section 9.1).

A single SQLite file in WAL mode holds everything the live loop cannot re-derive
from the exchange: the per-cycle status ladder, every order intent and its
lifecycle, every fill (with the PaperBroker walked-book audit), per-cycle
position/equity snapshots, and the PaperBroker serialization blob for exact
resume. The Parquet lake is re-derivable; ``var/trading.sqlite`` is not, so it is
backed up nightly (buildabilityCritique.md section 4) and treated as authoritative on
restart by :meth:`alphaforge.live.loop.LiveLoop.recover_on_boot`.

Crash-safety contract
----------------------
- Every write is a single transaction (``with self._conn``); SQLite serializes
  writers, WAL gives the tearsheet job a concurrent reader.
- A cycle is opened ``'running'`` and only ever moved to a terminal status
  (``'ok'``/``'skipped'``/``'failed'``/``'halted'``). A process that dies
  mid-cycle leaves a ``'running'`` row; recovery resolves it before the loop's
  first new decision. ``cycle_ts`` is the PRIMARY KEY, so a missed/replayed bar
  can never be double-processed.
- :meth:`start_cycle` is the idempotency gate: it returns ``False`` if the cycle
  already reached a terminal status, so a re-run of an already-finished bar is a
  silent no-op (missed cycles are SKIPPED, never back-filled by trading).
- Orders implement the OrderManager OrderStore protocol keyed by the
  deterministic ``client_order_id``; ``record_intent`` is idempotent, so a crash
  between intent and submit cannot create a duplicate intent on replay.

Conventions
-----------
All timestamps are epoch milliseconds UTC (:data:`~alphaforge.core.time.Ms`);
``cycle_ts`` is a bar-open ms. All money is quote units (USDT). All SQL is
parameterized. Patterns mirror :class:`alphaforge.core.instruments.InstrumentStore`
and :class:`alphaforge.data.ingest.checkpoints.CheckpointStore`.
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, Self

from alphaforge.core.time import Ms
from alphaforge.core.types import (
    AccountState,
    Fill,
    Liquidity,
    OrderRequest,
    OrderStatus,
    Position,
    Side,
)

__all__ = [
    "CycleRecord",
    "CycleStatus",
    "FillAudit",
    "FillRecord",
    "LadderSnapshot",
    "OrderRecord",
    "PositionSnapshot",
    "TradingStore",
]

CycleStatus = Literal["running", "ok", "skipped", "failed", "halted"]
"""Lifecycle of one live cycle. ``running`` is the only non-terminal state."""

_TERMINAL_CYCLE_STATUSES: Final[frozenset[str]] = frozenset({"ok", "skipped", "failed", "halted"})
_ALL_CYCLE_STATUSES: Final[frozenset[str]] = _TERMINAL_CYCLE_STATUSES | {"running"}


@dataclass(frozen=True, slots=True, kw_only=True)
class CycleRecord:
    """One row of the ``cycles`` ladder.

    ``started_ms`` is when :meth:`TradingStore.start_cycle` opened the cycle;
    ``finished_ms`` is ``None`` iff ``status == 'running'``. ``detail`` is
    free-form operator text (a stage name, an error summary, an 'N/M' count) and
    is never parsed by code.
    """

    cycle_ts: Ms
    started_ms: Ms
    finished_ms: Ms | None
    status: str
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionSnapshot:
    """One durable position mark used in a cycle's account equity."""

    cycle_ts: Ms
    instrument_id: str
    qty: float
    avg_entry_price: float
    opened_ts: Ms
    mark_price: float | None
    mark_source: str | None
    market_value_quote: float | None
    unrealized_pnl_quote: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderRecord:
    """One row of the ``orders`` table: an intent and its persisted lifecycle.

    ``qty`` is unsigned (``side`` carries the sign); ``filled_qty`` accumulates
    realized base units and ``avg_fill_price`` is the VWAP of fills (``None``
    until the first fill). ``status`` is an :class:`OrderStatus` value.
    """

    client_order_id: str
    cycle_ts: Ms
    instrument_id: str
    side: Side
    order_type: str
    qty: float
    reduce_only: bool
    status: str
    filled_qty: float
    avg_fill_price: float | None
    decision_ts: Ms
    decision_price: float
    reason: str
    created_ms: Ms
    updated_ms: Ms


@dataclass(frozen=True, slots=True, kw_only=True)
class EquityPoint:
    """One ``equity_curve`` row with the overlay scale that was in force at that cycle.

    ``overlay_scale`` is the strategy's vol-target scale ``s`` after the cycle's decision
    (BlendStrategy.last_scale), or NaN when none was recorded (rows written before the
    column existed, or a cycle whose strategy exposes no scale). It exists so a fresh
    ``--once`` process can rebuild the realized-vol leg's de-lever history on boot.
    """

    cycle_ts: Ms
    equity_quote: float
    cash_quote: float
    n_pos: int
    overlay_scale: float


@dataclass(frozen=True, slots=True, kw_only=True)
class LadderSnapshot:
    """The LIVE DrawdownLadder state persisted each cycle (execDesign.md section 7.2).

    A single 'latest' snapshot of the SAME ladder the strategy sizes off, so
    ``af paper status`` renders the TRUE current ladder rather than replaying the
    equity curve through a fresh ladder (which could disagree on hysteresis and
    the absorbing FLAT_HALTED state). ``state`` is the ladder-state label
    (``'normal'``/``'half_gross'``/``'flat_halted'``); ``hwm`` the high-water
    mark; ``drawdown`` the fraction ``1 - E/HWM``; ``gross_mult`` the sizing
    multiplier (1.0/0.5/0.0). ``cycle_ts`` is the bar-open the snapshot was taken
    at. ``hwm``/``drawdown`` may be NaN before the ladder's first equity mark.
    """

    cycle_ts: Ms
    state: str
    hwm: float
    drawdown: float
    gross_mult: float


_CREATE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_ts    INTEGER PRIMARY KEY,
    started_ms  INTEGER NOT NULL,
    finished_ms INTEGER,
    status      TEXT    NOT NULL
        CHECK (status IN ('running', 'ok', 'skipped', 'failed', 'halted')),
    detail      TEXT    NOT NULL DEFAULT ''
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_cycles_running
    ON cycles (cycle_ts) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT    PRIMARY KEY,
    cycle_ts        INTEGER NOT NULL,
    instrument_id   TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    order_type      TEXT    NOT NULL,
    qty             REAL    NOT NULL,
    reduce_only     INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL,
    filled_qty      REAL    NOT NULL DEFAULT 0,
    avg_fill_price  REAL,
    decision_ts     INTEGER NOT NULL,
    decision_price  REAL    NOT NULL,
    reason          TEXT    NOT NULL DEFAULT '',
    created_ms      INTEGER NOT NULL,
    updated_ms      INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_orders_cycle ON orders (cycle_ts);
CREATE INDEX IF NOT EXISTS ix_orders_open ON orders (status);

CREATE TABLE IF NOT EXISTS fills (
    fill_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id TEXT    NOT NULL REFERENCES orders (client_order_id),
    instrument_id   TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    qty             REAL    NOT NULL,
    price           REAL    NOT NULL,
    fee_quote       REAL    NOT NULL,
    liquidity       TEXT    NOT NULL,
    ts              INTEGER NOT NULL,
    walked_price    REAL,
    modeled_price   REAL,
    slippage_bps    REAL,
    book_exhausted  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_fills_coid ON fills (client_order_id);
CREATE INDEX IF NOT EXISTS ix_fills_ts ON fills (ts);

CREATE TABLE IF NOT EXISTS positions_snapshots (
    cycle_ts        INTEGER NOT NULL,
    instrument_id   TEXT    NOT NULL,
    qty             REAL    NOT NULL,
    avg_entry_price REAL    NOT NULL,
    opened_ts       INTEGER NOT NULL,
    mark_price      REAL,
    mark_source     TEXT,
    market_value_quote REAL,
    unrealized_pnl_quote REAL,
    PRIMARY KEY (cycle_ts, instrument_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS equity_curve (
    cycle_ts     INTEGER PRIMARY KEY,
    equity_quote REAL    NOT NULL,
    cash_quote   REAL    NOT NULL,
    n_pos        INTEGER NOT NULL,
    ts           INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS paper_state (
    cycle_ts INTEGER PRIMARY KEY,
    blob     TEXT    NOT NULL,
    ts       INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ladder_state (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    cycle_ts  INTEGER NOT NULL,
    state     TEXT    NOT NULL,
    hwm       REAL,
    drawdown  REAL,
    gross_mult REAL   NOT NULL
) WITHOUT ROWID;
"""


def _enable_wal(conn: sqlite3.Connection, *, budget_s: float = 5.0) -> None:
    """Switch ``conn`` to WAL journal mode, retrying briefly on lock contention.

    The DELETE->WAL upgrade needs exclusive access, and SQLite can return
    ``SQLITE_BUSY`` without consulting the busy handler in deadlock-prone lock
    upgrades, so stores racing to open the same file (the loop writer plus the
    tearsheet reader) can see ``database is locked`` despite ``busy_timeout``.
    WAL mode is persistent in the file, so the retry converges immediately once
    any opener succeeds. Re-raises after ``budget_s`` seconds of failures.
    """
    deadline = time.monotonic() + budget_s
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
        else:
            return


def _cycle_from_row(row: sqlite3.Row) -> CycleRecord:
    """SQL row -> :class:`CycleRecord`."""
    finished = row["finished_ms"]
    return CycleRecord(
        cycle_ts=int(row["cycle_ts"]),
        started_ms=int(row["started_ms"]),
        finished_ms=None if finished is None else int(finished),
        status=str(row["status"]),
        detail=str(row["detail"]),
    )


def _order_from_row(row: sqlite3.Row) -> OrderRecord:
    """SQL row -> :class:`OrderRecord`."""
    avg = row["avg_fill_price"]
    return OrderRecord(
        client_order_id=str(row["client_order_id"]),
        cycle_ts=int(row["cycle_ts"]),
        instrument_id=str(row["instrument_id"]),
        side=Side(str(row["side"])),
        order_type=str(row["order_type"]),
        qty=float(row["qty"]),
        reduce_only=bool(row["reduce_only"]),
        status=str(row["status"]),
        filled_qty=float(row["filled_qty"]),
        avg_fill_price=None if avg is None else float(avg),
        decision_ts=int(row["decision_ts"]),
        decision_price=float(row["decision_price"]),
        reason=str(row["reason"]),
        created_ms=int(row["created_ms"]),
        updated_ms=int(row["updated_ms"]),
    )


def _fill_from_row(row: sqlite3.Row) -> Fill:
    """SQL row -> :class:`Fill` (audit columns are read via :meth:`TradingStore.fills_for`)."""
    return Fill(
        client_order_id=str(row["client_order_id"]),
        instrument_id=str(row["instrument_id"]),
        side=Side(str(row["side"])),
        qty=float(row["qty"]),
        price=float(row["price"]),
        fee_quote=float(row["fee_quote"]),
        liquidity=Liquidity(str(row["liquidity"])),
        ts=int(row["ts"]),
    )


class TradingStore:
    """SQLite-backed source of truth for live PAPER trading state (WAL mode).

    See the module docstring for the crash-safety contract. Usable as a context
    manager (closes the connection on exit). One writer instance per process;
    concurrent readers (the tearsheet job) coordinate safely through WAL.
    """

    def __init__(self, db_path: Path) -> None:
        """Open (creating parent directories and schema if absent) the store."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        _enable_wal(self._conn)
        # C10b: trading.sqlite is the IRREPLACEABLE order/fill ledger -- it cannot
        # be re-derived from the exchange (unlike the Parquet lake, which stays at
        # NORMAL). synchronous=FULL fsyncs the WAL on every commit so a fill or
        # order transition that returned committed is durable across an OS crash /
        # power loss, not just a process crash (NORMAL can lose the last commit(s)
        # on a kernel panic in WAL mode). The mid-frequency loop commits at most a
        # handful of times per hour, so the extra fsync cost is negligible against
        # the value of never losing a recorded fill.
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._conn:
            self._conn.executescript(_CREATE_SQL)
            self._ensure_position_mark_columns()
            self._ensure_equity_curve_columns()

    def _ensure_position_mark_columns(self) -> None:
        """Add prospective attribution columns to legacy live databases in place."""
        present = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(positions_snapshots)").fetchall()
        }
        columns = {
            "mark_price": "REAL",
            "mark_source": "TEXT",
            "market_value_quote": "REAL",
            "unrealized_pnl_quote": "REAL",
        }
        for name, sql_type in columns.items():
            if name not in present:
                self._conn.execute(
                    f"ALTER TABLE positions_snapshots ADD COLUMN {name} {sql_type}"
                )

    def _ensure_equity_curve_columns(self) -> None:
        """Additive, nullable: ``overlay_scale`` on the equity curve (2026-09-06). Same
        migration shape as the position-mark columns, so an existing trading DB gains it on
        first open and its old rows read back as NaN."""
        present = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(equity_curve)").fetchall()
        }
        if "overlay_scale" not in present:
            self._conn.execute("ALTER TABLE equity_curve ADD COLUMN overlay_scale REAL")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying connection; the store is unusable afterwards."""
        self._conn.close()

    # ------------------------------------------------------------------ #
    # cycles                                                             #
    # ------------------------------------------------------------------ #

    def start_cycle(self, cycle_ts: Ms, *, now: Ms) -> bool:
        """Open cycle ``cycle_ts`` as ``'running'``; the idempotency gate.

        Returns ``True`` if the cycle is now (or was already) ``'running'`` and
        may proceed. Returns ``False`` if the cycle already reached a terminal
        status, in which case the caller must SKIP it (a missed bar replayed, or
        a duplicate wake) and never trade -- missed cycles are accounted for, not
        back-filled.

        Atomic: an INSERT that conflicts on the PRIMARY KEY leaves the existing
        row untouched, so two racing wakes cannot both open the cycle. Re-opening
        an already-``'running'`` cycle (a crash between open and finish, then a
        same-bar restart) is allowed and returns ``True``.
        """
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO cycles (cycle_ts, started_ms, status) VALUES (?, ?, 'running') "
                "ON CONFLICT (cycle_ts) DO NOTHING",
                (cycle_ts, now),
            )
            if cur.rowcount == 1:
                return True
            existing = self._conn.execute(
                "SELECT status FROM cycles WHERE cycle_ts = ?", (cycle_ts,)
            ).fetchone()
        # Existing row: proceed only if it has not reached a terminal status.
        return existing is not None and str(existing["status"]) == "running"

    def finish_cycle(self, cycle_ts: Ms, status: CycleStatus, detail: str, *, now: Ms) -> None:
        """Stamp cycle ``cycle_ts`` terminal (``finished_ms = now``, ``detail`` set).

        Raises ``ValueError`` for a non-terminal ``status`` or an unknown
        ``cycle_ts`` (the cycle must have been opened by :meth:`start_cycle`).
        """
        if status not in _TERMINAL_CYCLE_STATUSES:
            raise ValueError(f"finish_cycle status must be terminal, got {status!r}")
        with self._conn:
            cur = self._conn.execute(
                "UPDATE cycles SET status = ?, finished_ms = ?, detail = ? WHERE cycle_ts = ?",
                (status, now, detail, cycle_ts),
            )
            if cur.rowcount == 0:
                raise ValueError(f"finish_cycle: unknown cycle_ts {cycle_ts}")

    def get_cycle(self, cycle_ts: Ms) -> CycleRecord | None:
        """Return the cycle row for ``cycle_ts``, or ``None`` if never opened."""
        row = self._conn.execute("SELECT * FROM cycles WHERE cycle_ts = ?", (cycle_ts,)).fetchone()
        return None if row is None else _cycle_from_row(row)

    def last_cycle(self) -> CycleRecord | None:
        """Return the most recent cycle by ``cycle_ts``, or ``None`` if none yet.

        On restart this is the cycle to inspect: a ``'running'`` value means the
        process died mid-cycle and recovery must resolve it.
        """
        row = self._conn.execute("SELECT * FROM cycles ORDER BY cycle_ts DESC LIMIT 1").fetchone()
        return None if row is None else _cycle_from_row(row)

    def running_cycles(self) -> list[CycleRecord]:
        """All cycles still ``'running'`` (after a crash, exactly the interrupted ones)."""
        rows = self._conn.execute(
            "SELECT * FROM cycles WHERE status = 'running' ORDER BY cycle_ts"
        ).fetchall()
        return [_cycle_from_row(r) for r in rows]

    def cycles_since(self, ts: Ms) -> list[CycleRecord]:
        """All cycles with ``cycle_ts >= ts``, ascending (the live equity/audit window)."""
        rows = self._conn.execute(
            "SELECT * FROM cycles WHERE cycle_ts >= ? ORDER BY cycle_ts", (ts,)
        ).fetchall()
        return [_cycle_from_row(r) for r in rows]

    def expected_vs_run(self, start: Ms, end: Ms, bar_ms: int) -> tuple[int, int, int]:
        """Return ``(expected, run, skipped)`` cycle accounting over ``[start, end]``.

        ``expected`` is the number of aligned bar opens in the inclusive range
        ``start, start+bar_ms, ..., <= end`` (the cadence the loop *should* have
        hit). ``run`` counts cycles whose recorded status is terminal-and-traded
        (``'ok'`` or ``'halted'`` -- the loop reached a decision). ``skipped`` is
        ``expected - run`` clamped at 0: every bar the laptop slept through, plus
        any explicitly ``'skipped'``/``'failed'`` cycle, is a miss. This is the
        'N/M cycles' figure that buildabilityCritique.md section 4 demands be visible in
        ``af status`` and the daily tearsheet, never silent.

        Raises ``ValueError`` if ``bar_ms <= 0`` or ``end < start``.
        """
        if bar_ms <= 0:
            raise ValueError(f"bar_ms must be > 0, got {bar_ms}")
        if end < start:
            raise ValueError(f"end ({end}) must be >= start ({start})")
        expected = (end - start) // bar_ms + 1
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM cycles "
            "WHERE cycle_ts >= ? AND cycle_ts <= ? AND status IN ('ok', 'halted')",
            (start, end),
        ).fetchone()
        run = int(row["n"])
        skipped = max(expected - run, 0)
        return expected, run, skipped

    # ------------------------------------------------------------------ #
    # orders (OrderManager OrderStore protocol)                          #
    # ------------------------------------------------------------------ #

    def record_intent(self, req: OrderRequest, cycle_ts: Ms, *, now: Ms) -> None:
        """Persist ``req`` as a ``NEW`` intent BEFORE any broker submission.

        Idempotent on ``client_order_id``: a re-run of the same cycle's intent
        (crash between intent and submit, then replay) is a no-op, never a
        duplicate. The deterministic ``client_order_id`` is the idempotency
        backbone -- recording the intent first is what lets recovery query the
        broker by that id and adopt an order that may already have landed.
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO orders ("
                "client_order_id, cycle_ts, instrument_id, side, order_type, qty, "
                "reduce_only, status, filled_qty, avg_fill_price, decision_ts, "
                "decision_price, reason, created_ms, updated_ms"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?) "
                "ON CONFLICT (client_order_id) DO NOTHING",
                (
                    req.client_order_id,
                    cycle_ts,
                    req.instrument_id,
                    req.side.value,
                    req.order_type.value,
                    req.qty,
                    int(req.reduce_only),
                    OrderStatus.NEW.value,
                    req.decision_ts,
                    req.decision_price,
                    req.reason,
                    now,
                    now,
                ),
            )

    def mark_submitted(self, client_order_id: str, *, now: Ms) -> None:
        """Transition a recorded intent to ``SUBMITTED`` (the broker accepted it)."""
        self._set_order_status(client_order_id, OrderStatus.SUBMITTED, now=now)

    def mark_rejected(self, client_order_id: str, *, now: Ms) -> None:
        """Transition an order to ``REJECTED`` (pre-trade fail, broker reject, timeout cancel)."""
        self._set_order_status(client_order_id, OrderStatus.REJECTED, now=now)

    def mark_filled(self, fill: Fill, *, now: Ms, audit: FillAudit | None = None) -> None:
        """Persist ``fill`` and advance its order's ``filled_qty``/``avg_fill_price``/status.

        In one transaction: insert the fill row (with the optional PaperBroker
        walked-vs-modeled ``audit``), then recompute the parent order's running
        signed-VWAP fill price and accumulated quantity and set status to
        ``FILLED`` once ``filled_qty >= qty`` (within a lot epsilon) else
        ``PARTIAL``. Raises ``ValueError`` if the parent order is unknown (a fill
        for an intent that was never recorded is a contract violation).
        """
        with self._conn:
            parent = self._conn.execute(
                "SELECT qty, filled_qty, avg_fill_price FROM orders WHERE client_order_id = ?",
                (fill.client_order_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"mark_filled: no recorded intent for {fill.client_order_id!r}")
            self._conn.execute(
                "INSERT INTO fills ("
                "client_order_id, instrument_id, side, qty, price, fee_quote, liquidity, ts, "
                "walked_price, modeled_price, slippage_bps, book_exhausted"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fill.client_order_id,
                    fill.instrument_id,
                    fill.side.value,
                    fill.qty,
                    fill.price,
                    fill.fee_quote,
                    fill.liquidity.value,
                    fill.ts,
                    None if audit is None else audit.walked_price,
                    None if audit is None else audit.modeled_price,
                    None if audit is None else audit.slippage_bps,
                    0 if audit is None else int(audit.book_exhausted),
                ),
            )
            order_qty = float(parent["qty"])
            prev_filled = float(parent["filled_qty"])
            prev_avg = parent["avg_fill_price"]
            new_filled = prev_filled + fill.qty
            if prev_avg is None or prev_filled <= 0.0:
                new_avg = fill.price
            else:
                new_avg = (float(prev_avg) * prev_filled + fill.price * fill.qty) / new_filled
            status = (
                OrderStatus.FILLED if new_filled >= order_qty - _QTY_EPS else OrderStatus.PARTIAL
            )
            self._conn.execute(
                "UPDATE orders SET filled_qty = ?, avg_fill_price = ?, status = ?, "
                "updated_ms = ? WHERE client_order_id = ?",
                (new_filled, new_avg, status.value, now, fill.client_order_id),
            )

    def get(self, client_order_id: str) -> OrderRecord | None:
        """Return the order row for ``client_order_id``, or ``None`` if unknown."""
        row = self._conn.execute(
            "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
        ).fetchone()
        return None if row is None else _order_from_row(row)

    def open_intents(self) -> list[OrderRecord]:
        """All orders in a non-terminal status (``NEW``/``SUBMITTED``/``PARTIAL``).

        After a crash these are exactly the orders recovery must resolve against
        the broker by ``client_order_id`` before the loop's first new decision.
        """
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE status IN (?, ?, ?) ORDER BY cycle_ts, client_order_id",
            (OrderStatus.NEW.value, OrderStatus.SUBMITTED.value, OrderStatus.PARTIAL.value),
        ).fetchall()
        return [_order_from_row(r) for r in rows]

    def orders_for_cycle(self, cycle_ts: Ms) -> list[OrderRecord]:
        """All orders recorded under ``cycle_ts`` (the per-cycle trade audit)."""
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE cycle_ts = ? ORDER BY client_order_id", (cycle_ts,)
        ).fetchall()
        return [_order_from_row(r) for r in rows]

    def _set_order_status(self, client_order_id: str, status: OrderStatus, *, now: Ms) -> None:
        """Set an order's status (no fill bookkeeping); raises if the id is unknown."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE orders SET status = ?, updated_ms = ? WHERE client_order_id = ?",
                (status.value, now, client_order_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"unknown client_order_id {client_order_id!r}")

    # ------------------------------------------------------------------ #
    # fills                                                              #
    # ------------------------------------------------------------------ #

    def fills_for(self, client_order_id: str) -> list[FillRecord]:
        """All fills for ``client_order_id`` (Fill plus the walked-book audit), by id."""
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE client_order_id = ? ORDER BY fill_id", (client_order_id,)
        ).fetchall()
        return [_fill_record_from_row(r) for r in rows]

    def fills_since(self, ts: Ms) -> list[FillRecord]:
        """All fills with ``ts >= ts``, ascending -- recovery's missed-fill ingest window."""
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE ts >= ? ORDER BY ts, fill_id", (ts,)
        ).fetchall()
        return [_fill_record_from_row(r) for r in rows]

    # ------------------------------------------------------------------ #
    # snapshots: positions + equity + paper_state                        #
    # ------------------------------------------------------------------ #

    def snapshot_positions(
        self,
        cycle_ts: Ms,
        positions: tuple[Position, ...],
        *,
        marks: Mapping[str, tuple[float, str]] | None = None,
    ) -> None:
        """Replace the position snapshot for ``cycle_ts`` (idempotent per cycle).

        The full position set is written under the cycle key so the live
        tearsheet has a per-bar book and recovery can rebuild the in-memory
        ledger from the last snapshot plus subsequent fills.
        """
        def row_for(position: Position) -> tuple[object, ...]:
            mark = None if marks is None else marks.get(position.instrument_id)
            mark_price = None if mark is None else mark[0]
            mark_source = None if mark is None else mark[1]
            return (
                cycle_ts,
                position.instrument_id,
                position.qty,
                position.avg_entry_price,
                position.opened_ts,
                mark_price,
                mark_source,
                None if mark_price is None else position.qty * mark_price,
                None
                if mark_price is None
                else position.qty * (mark_price - position.avg_entry_price),
            )

        with self._conn:
            self._conn.execute("DELETE FROM positions_snapshots WHERE cycle_ts = ?", (cycle_ts,))
            self._conn.executemany(
                "INSERT INTO positions_snapshots ("
                "cycle_ts, instrument_id, qty, avg_entry_price, opened_ts, "
                "mark_price, mark_source, market_value_quote, unrealized_pnl_quote"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [row_for(position) for position in positions],
            )

    def position_snapshots_at(self, cycle_ts: Ms) -> tuple[PositionSnapshot, ...]:
        """Return durable position marks and P&L attribution for one cycle."""
        rows = self._conn.execute(
            "SELECT * FROM positions_snapshots WHERE cycle_ts = ? ORDER BY instrument_id",
            (cycle_ts,),
        ).fetchall()
        return tuple(
            PositionSnapshot(
                cycle_ts=int(row["cycle_ts"]),
                instrument_id=str(row["instrument_id"]),
                qty=float(row["qty"]),
                avg_entry_price=float(row["avg_entry_price"]),
                opened_ts=int(row["opened_ts"]),
                mark_price=None if row["mark_price"] is None else float(row["mark_price"]),
                mark_source=None if row["mark_source"] is None else str(row["mark_source"]),
                market_value_quote=(
                    None
                    if row["market_value_quote"] is None
                    else float(row["market_value_quote"])
                ),
                unrealized_pnl_quote=(
                    None
                    if row["unrealized_pnl_quote"] is None
                    else float(row["unrealized_pnl_quote"])
                ),
            )
            for row in rows
        )

    def positions_at(self, cycle_ts: Ms) -> tuple[Position, ...]:
        """Return the position snapshot recorded at ``cycle_ts`` (empty if none)."""
        rows = self._conn.execute(
            "SELECT * FROM positions_snapshots WHERE cycle_ts = ? ORDER BY instrument_id",
            (cycle_ts,),
        ).fetchall()
        return tuple(
            Position(
                instrument_id=str(r["instrument_id"]),
                qty=float(r["qty"]),
                avg_entry_price=float(r["avg_entry_price"]),
                opened_ts=int(r["opened_ts"]),
            )
            for r in rows
        )

    def snapshot_equity(
        self, cycle_ts: Ms, account: AccountState, *, overlay_scale: float | None = None
    ) -> None:
        """Record the equity point for ``cycle_ts`` (the live equity curve).

        Idempotent on ``cycle_ts`` (PRIMARY KEY upsert): re-running a cycle's
        persist stage overwrites the point rather than duplicating it.
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO equity_curve "
                "(cycle_ts, equity_quote, cash_quote, n_pos, ts, overlay_scale) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cycle_ts) DO UPDATE SET "
                "equity_quote = excluded.equity_quote, cash_quote = excluded.cash_quote, "
                "n_pos = excluded.n_pos, ts = excluded.ts, overlay_scale = excluded.overlay_scale",
                (
                    cycle_ts,
                    account.equity_quote,
                    account.cash_quote,
                    len(account.positions),
                    account.ts,
                    # NaN would be stored as NULL by the driver anyway; be explicit so the
                    # round-trip (NULL -> NaN) is a documented contract, not an accident.
                    None
                    if overlay_scale is None or not math.isfinite(overlay_scale)
                    else float(overlay_scale),
                ),
            )

    def equity_curve_points(self) -> list[EquityPoint]:
        """The whole equity curve as :class:`EquityPoint` rows, ascending, NULL scale -> NaN."""
        rows = self._conn.execute(
            "SELECT cycle_ts, equity_quote, cash_quote, n_pos, overlay_scale FROM equity_curve "
            "ORDER BY cycle_ts"
        ).fetchall()
        return [
            EquityPoint(
                cycle_ts=int(r["cycle_ts"]),
                equity_quote=float(r["equity_quote"]),
                cash_quote=float(r["cash_quote"]),
                n_pos=int(r["n_pos"]),
                overlay_scale=math.nan if r["overlay_scale"] is None else float(r["overlay_scale"]),
            )
            for r in rows
        ]

    def equity_curve(self, start: Ms | None = None) -> list[tuple[Ms, float, float, int]]:
        """Return ``(cycle_ts, equity_quote, cash_quote, n_pos)`` rows, ascending.

        ``start`` (a ``cycle_ts``) bounds the window from below when given; the
        full curve otherwise.
        """
        if start is None:
            rows = self._conn.execute(
                "SELECT cycle_ts, equity_quote, cash_quote, n_pos FROM equity_curve "
                "ORDER BY cycle_ts"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT cycle_ts, equity_quote, cash_quote, n_pos FROM equity_curve "
                "WHERE cycle_ts >= ? ORDER BY cycle_ts",
                (start,),
            ).fetchall()
        return [
            (int(r["cycle_ts"]), float(r["equity_quote"]), float(r["cash_quote"]), int(r["n_pos"]))
            for r in rows
        ]

    def save_paper_state(self, cycle_ts: Ms, blob: str, *, now: Ms) -> None:
        """Persist the PaperBroker serialization ``blob`` for exact resume at ``cycle_ts``.

        Idempotent on ``cycle_ts``. ``blob`` is the broker's own opaque
        serialization (typically a JSON string); the store never parses it.
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO paper_state (cycle_ts, blob, ts) VALUES (?, ?, ?) "
                "ON CONFLICT (cycle_ts) DO UPDATE SET blob = excluded.blob, ts = excluded.ts",
                (cycle_ts, blob, now),
            )

    def latest_paper_state(self) -> tuple[Ms, str] | None:
        """Return ``(cycle_ts, blob)`` of the most recent paper_state, or ``None``.

        Recovery restores the PaperBroker from this blob so a restart resumes the
        exact simulated book, not a re-derived approximation.
        """
        row = self._conn.execute(
            "SELECT cycle_ts, blob FROM paper_state ORDER BY cycle_ts DESC LIMIT 1"
        ).fetchone()
        return None if row is None else (int(row["cycle_ts"]), str(row["blob"]))

    # ------------------------------------------------------------------ #
    # ladder state (single-row latest live DrawdownLadder snapshot)       #
    # ------------------------------------------------------------------ #

    def record_ladder_state(
        self,
        *,
        cycle_ts: Ms,
        state: str,
        hwm: float,
        drawdown: float,
        gross_mult: float,
    ) -> None:
        """Upsert the latest live ladder snapshot (single row, keyed by max ``cycle_ts``).

        The table holds exactly one row (``id = 1``): the freshest ladder state
        the live loop recorded, so ``af paper status`` can render the TRUE current
        ladder instead of replaying the equity curve. The upsert keeps the row
        with the GREATEST ``cycle_ts`` -- a re-run / out-of-order replay of an
        OLDER cycle never clobbers a newer recorded state; recording the SAME
        ``cycle_ts`` again overwrites in place (idempotent per cycle). ``hwm`` and
        ``drawdown`` may be NaN (the ladder before its first equity mark); the
        Python sqlite3 driver stores a float NaN as SQL NULL, so the ``hwm`` and
        ``drawdown`` columns are nullable and :meth:`last_ladder_state` maps a NULL
        back to NaN -- the NaN round-trips. ``gross_mult`` is always a finite
        1.0/0.5/0.0, so it stays ``NOT NULL``.
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO ladder_state (id, cycle_ts, state, hwm, drawdown, gross_mult) "
                "VALUES (1, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET "
                "cycle_ts = excluded.cycle_ts, state = excluded.state, hwm = excluded.hwm, "
                "drawdown = excluded.drawdown, gross_mult = excluded.gross_mult "
                "WHERE excluded.cycle_ts >= ladder_state.cycle_ts",
                (cycle_ts, state, hwm, drawdown, gross_mult),
            )

    def last_ladder_state(self) -> LadderSnapshot | None:
        """Return the latest recorded live ladder snapshot, or ``None`` if never recorded."""
        row = self._conn.execute(
            "SELECT cycle_ts, state, hwm, drawdown, gross_mult FROM ladder_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        hwm = row["hwm"]
        drawdown = row["drawdown"]
        return LadderSnapshot(
            cycle_ts=int(row["cycle_ts"]),
            state=str(row["state"]),
            # NULL <-> NaN: the driver stored a Python float NaN as SQL NULL.
            hwm=math.nan if hwm is None else float(hwm),
            drawdown=math.nan if drawdown is None else float(drawdown),
            gross_mult=float(row["gross_mult"]),
        )


_QTY_EPS: Final[float] = 1e-12
"""Lot-rounding tolerance for declaring an order fully filled."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FillAudit:
    """PaperBroker walked-book audit attached to a persisted fill (leakageCritique #8).

    Paper fills are produced by WALKING a real order-book snapshot, not by the
    cost model; ``walked_price`` is that genuine fill price and ``modeled_price``
    is what :class:`~alphaforge.costs.model.TransactionCostModel` would have
    predicted. ``slippage_bps`` is their signed difference in basis points --
    the real modeled-vs-realized signal that makes paper-mode slippage
    validation non-circular. ``book_exhausted`` is ``True`` when the snapshot ran
    out of depth before the order filled (a flag worth alerting on).
    """

    walked_price: float
    modeled_price: float
    slippage_bps: float
    book_exhausted: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class FillRecord:
    """A persisted :class:`Fill` together with its optional :class:`FillAudit`.

    ``audit`` is ``None`` for fills recorded without walked-book provenance
    (e.g. a recovered broker fill); present for PaperBroker fills.
    """

    fill: Fill
    audit: FillAudit | None


def _fill_record_from_row(row: sqlite3.Row) -> FillRecord:
    """SQL row -> :class:`FillRecord` (reconstructs audit when present)."""
    walked = row["walked_price"]
    audit: FillAudit | None
    if walked is None:
        audit = None
    else:
        audit = FillAudit(
            walked_price=float(walked),
            modeled_price=float(row["modeled_price"]),
            slippage_bps=float(row["slippage_bps"]),
            book_exhausted=bool(row["book_exhausted"]),
        )
    return FillRecord(fill=_fill_from_row(row), audit=audit)
