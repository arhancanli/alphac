"""Unit tests for :class:`alphaforge.live.store.TradingStore` (offline, tmp_path only).

Covers: cycle idempotency (a second ``start_cycle`` on a terminal cycle returns
False), ``expected_vs_run`` accounting across a slept-through gap, the order
lifecycle round-trip (intent -> submitted -> filled with VWAP accumulation),
fills with the PaperBroker walked-book audit columns, the paper_state blob
round-trip, position/equity snapshots, the live ladder-state snapshot (record /
last / max-cycle_ts upsert / NaN round-trip / rearm), and a WAL crash-sim with
two concurrent connections.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from alphaforge.core.types import (
    AccountState,
    Fill,
    Liquidity,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from alphaforge.live.store import FillAudit, LadderSnapshot, TradingStore

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000  # an aligned-enough cycle anchor for tests


def _order(
    *,
    coid: str = "af-c0-BTC",
    instrument_id: str = "BINANCE:PERP:BTCUSDT",
    side: Side = Side.BUY,
    qty: float = 2.0,
    reduce_only: bool = False,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=coid,
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        reduce_only=reduce_only,
        decision_ts=T0,
        decision_price=100.0,
        reason="rebalance",
    )


def _fill(
    *,
    coid: str = "af-c0-BTC",
    instrument_id: str = "BINANCE:PERP:BTCUSDT",
    side: Side = Side.BUY,
    qty: float = 2.0,
    price: float = 100.0,
    fee_quote: float = 0.1,
    ts: int = T0 + 10,
) -> Fill:
    return Fill(
        client_order_id=coid,
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        price=price,
        fee_quote=fee_quote,
        liquidity=Liquidity.TAKER,
        ts=ts,
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TradingStore]:
    with TradingStore(tmp_path / "trading.sqlite") as s:
        yield s


# ---------------------------------------------------------------------- cycles


class TestCycleIdempotency:
    def test_start_cycle_first_time_returns_true(self, store: TradingStore) -> None:
        assert store.start_cycle(T0, now=T0 + 90) is True
        rec = store.get_cycle(T0)
        assert rec is not None
        assert rec.status == "running"
        assert rec.finished_ms is None

    def test_start_cycle_twice_while_running_returns_true(self, store: TradingStore) -> None:
        """A same-bar restart of a crash-interrupted (still 'running') cycle may proceed."""
        assert store.start_cycle(T0, now=T0 + 90) is True
        assert store.start_cycle(T0, now=T0 + 95) is True  # re-entry allowed

    def test_start_cycle_after_terminal_returns_false(self, store: TradingStore) -> None:
        """The idempotency gate: a finished cycle never re-runs (missed bars skip)."""
        store.start_cycle(T0, now=T0 + 90)
        store.finish_cycle(T0, "ok", "traded 3", now=T0 + 120)
        assert store.start_cycle(T0, now=T0 + 200) is False

    def test_finish_cycle_rejects_non_terminal_status(self, store: TradingStore) -> None:
        store.start_cycle(T0, now=T0 + 90)
        with pytest.raises(ValueError, match="terminal"):
            store.finish_cycle(T0, "running", "", now=T0 + 100)

    def test_finish_cycle_unknown_cycle_raises(self, store: TradingStore) -> None:
        with pytest.raises(ValueError, match="unknown cycle_ts"):
            store.finish_cycle(T0, "ok", "", now=T0 + 100)

    def test_last_and_running_cycles(self, store: TradingStore) -> None:
        store.start_cycle(T0, now=T0 + 90)
        store.finish_cycle(T0, "ok", "", now=T0 + 120)
        store.start_cycle(T0 + HOUR_MS, now=T0 + HOUR_MS + 90)
        last = store.last_cycle()
        assert last is not None and last.cycle_ts == T0 + HOUR_MS
        running = store.running_cycles()
        assert [c.cycle_ts for c in running] == [T0 + HOUR_MS]

    def test_cycles_since(self, store: TradingStore) -> None:
        for k in range(3):
            ts = T0 + k * HOUR_MS
            store.start_cycle(ts, now=ts + 90)
            store.finish_cycle(ts, "ok", "", now=ts + 120)
        since = store.cycles_since(T0 + HOUR_MS)
        assert [c.cycle_ts for c in since] == [T0 + HOUR_MS, T0 + 2 * HOUR_MS]


class TestExpectedVsRun:
    def test_no_gap_all_run(self, store: TradingStore) -> None:
        for k in range(4):
            ts = T0 + k * HOUR_MS
            store.start_cycle(ts, now=ts + 90)
            store.finish_cycle(ts, "ok", "", now=ts + 120)
        expected, run, skipped = store.expected_vs_run(T0, T0 + 3 * HOUR_MS, HOUR_MS)
        assert (expected, run, skipped) == (4, 4, 0)

    def test_gap_counts_skipped(self, store: TradingStore) -> None:
        """Laptop slept through bars 1 and 2; only bars 0 and 3 ran -> 4/2, 2 skipped."""
        for k in (0, 3):
            ts = T0 + k * HOUR_MS
            store.start_cycle(ts, now=ts + 90)
            store.finish_cycle(ts, "ok", "", now=ts + 120)
        expected, run, skipped = store.expected_vs_run(T0, T0 + 3 * HOUR_MS, HOUR_MS)
        assert expected == 4
        assert run == 2
        assert skipped == 2

    def test_failed_cycle_is_not_counted_as_run(self, store: TradingStore) -> None:
        store.start_cycle(T0, now=T0 + 90)
        store.finish_cycle(T0, "failed", "boom", now=T0 + 120)
        expected, run, skipped = store.expected_vs_run(T0, T0, HOUR_MS)
        assert (expected, run, skipped) == (1, 0, 1)

    def test_halted_counts_as_run(self, store: TradingStore) -> None:
        store.start_cycle(T0, now=T0 + 90)
        store.finish_cycle(T0, "halted", "dd tier2", now=T0 + 120)
        assert store.expected_vs_run(T0, T0, HOUR_MS) == (1, 1, 0)

    def test_invalid_args(self, store: TradingStore) -> None:
        with pytest.raises(ValueError, match="bar_ms"):
            store.expected_vs_run(T0, T0, 0)
        with pytest.raises(ValueError, match="end"):
            store.expected_vs_run(T0 + HOUR_MS, T0, HOUR_MS)


# ---------------------------------------------------------------------- orders


class TestOrderLifecycle:
    def test_record_intent_round_trip(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        rec = store.get("af-c0-BTC")
        assert rec is not None
        assert rec.status == OrderStatus.NEW
        assert rec.cycle_ts == T0
        assert rec.side is Side.BUY
        assert rec.qty == 2.0
        assert rec.filled_qty == 0.0
        assert rec.avg_fill_price is None
        assert rec.reason == "rebalance"

    def test_record_intent_is_idempotent(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        store.record_intent(_order(), T0, now=T0 + 95)  # replay after crash
        assert len(store.orders_for_cycle(T0)) == 1

    def test_mark_submitted_then_filled(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        store.mark_submitted("af-c0-BTC", now=T0 + 95)
        assert store.get("af-c0-BTC").status == OrderStatus.SUBMITTED  # type: ignore[union-attr]
        store.mark_filled(_fill(), now=T0 + 100)
        rec = store.get("af-c0-BTC")
        assert rec is not None
        assert rec.status == OrderStatus.FILLED
        assert rec.filled_qty == 2.0
        assert rec.avg_fill_price == 100.0

    def test_partial_then_full_fill_accumulates_vwap(self, store: TradingStore) -> None:
        store.record_intent(_order(qty=4.0), T0, now=T0 + 90)
        store.mark_filled(_fill(qty=1.0, price=100.0, ts=T0 + 100), now=T0 + 100)
        mid = store.get("af-c0-BTC")
        assert mid is not None and mid.status == OrderStatus.PARTIAL
        assert mid.filled_qty == 1.0
        store.mark_filled(_fill(qty=3.0, price=104.0, ts=T0 + 110), now=T0 + 110)
        done = store.get("af-c0-BTC")
        assert done is not None
        assert done.status == OrderStatus.FILLED
        assert done.filled_qty == 4.0
        # VWAP = (1*100 + 3*104) / 4 = 103.0
        assert done.avg_fill_price == pytest.approx(103.0)

    def test_mark_rejected(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        store.mark_rejected("af-c0-BTC", now=T0 + 95)
        assert store.get("af-c0-BTC").status == OrderStatus.REJECTED  # type: ignore[union-attr]

    def test_mark_status_unknown_order_raises(self, store: TradingStore) -> None:
        with pytest.raises(ValueError, match="unknown client_order_id"):
            store.mark_submitted("nope", now=T0)

    def test_mark_filled_without_intent_raises(self, store: TradingStore) -> None:
        with pytest.raises(ValueError, match="no recorded intent"):
            store.mark_filled(_fill(coid="ghost"), now=T0)

    def test_open_intents_excludes_terminal(self, store: TradingStore) -> None:
        store.record_intent(_order(coid="a"), T0, now=T0)
        store.record_intent(_order(coid="b"), T0, now=T0)
        store.record_intent(_order(coid="c"), T0, now=T0)
        store.mark_submitted("b", now=T0 + 1)  # still open
        store.mark_rejected("c", now=T0 + 1)  # terminal
        open_ids = {o.client_order_id for o in store.open_intents()}
        assert open_ids == {"a", "b"}


# ---------------------------------------------------------------------- fills


class TestFillsAudit:
    def test_fill_with_walked_book_audit(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        audit = FillAudit(
            walked_price=100.12,
            modeled_price=100.05,
            slippage_bps=7.0,
            book_exhausted=False,
        )
        store.mark_filled(_fill(price=100.12), now=T0 + 100, audit=audit)
        records = store.fills_for("af-c0-BTC")
        assert len(records) == 1
        fr = records[0]
        assert fr.fill.price == 100.12
        assert fr.audit is not None
        assert fr.audit.walked_price == 100.12
        assert fr.audit.modeled_price == 100.05
        assert fr.audit.slippage_bps == 7.0
        assert fr.audit.book_exhausted is False

    def test_fill_without_audit_has_none(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        store.mark_filled(_fill(), now=T0 + 100)
        records = store.fills_for("af-c0-BTC")
        assert records[0].audit is None

    def test_book_exhausted_flag_round_trips(self, store: TradingStore) -> None:
        store.record_intent(_order(), T0, now=T0 + 90)
        audit = FillAudit(
            walked_price=101.0, modeled_price=100.0, slippage_bps=99.5, book_exhausted=True
        )
        store.mark_filled(_fill(price=101.0), now=T0 + 100, audit=audit)
        fr = store.fills_for("af-c0-BTC")[0]
        assert fr.audit is not None and fr.audit.book_exhausted is True

    def test_fills_since_window(self, store: TradingStore) -> None:
        store.record_intent(_order(coid="a", qty=4.0), T0, now=T0)
        store.mark_filled(_fill(coid="a", qty=1.0, ts=T0 + 50), now=T0 + 50)
        store.mark_filled(_fill(coid="a", qty=1.0, ts=T0 + 250), now=T0 + 250)
        recent = store.fills_since(T0 + 100)
        assert [r.fill.ts for r in recent] == [T0 + 250]


# ------------------------------------------------------ snapshots + paper_state


class TestSnapshots:
    def test_position_snapshot_round_trip(self, store: TradingStore) -> None:
        positions = (
            Position(
                instrument_id="BINANCE:PERP:BTCUSDT",
                qty=2.0,
                avg_entry_price=100.0,
                opened_ts=T0,
            ),
            Position(
                instrument_id="BINANCE:PERP:ETHUSDT",
                qty=-5.0,
                avg_entry_price=50.0,
                opened_ts=T0,
            ),
        )
        store.snapshot_positions(T0, positions)
        got = store.positions_at(T0)
        assert {p.instrument_id: p.qty for p in got} == {
            "BINANCE:PERP:BTCUSDT": 2.0,
            "BINANCE:PERP:ETHUSDT": -5.0,
        }

    def test_position_snapshot_is_replaced_per_cycle(self, store: TradingStore) -> None:
        p1 = Position(
            instrument_id="BINANCE:PERP:BTCUSDT", qty=2.0, avg_entry_price=100.0, opened_ts=T0
        )
        store.snapshot_positions(T0, (p1,))
        # Re-run the persist stage with a different book; must replace, not append.
        p2 = Position(
            instrument_id="BINANCE:PERP:ETHUSDT", qty=1.0, avg_entry_price=50.0, opened_ts=T0
        )
        store.snapshot_positions(T0, (p2,))
        got = store.positions_at(T0)
        assert [p.instrument_id for p in got] == ["BINANCE:PERP:ETHUSDT"]

    def test_position_snapshot_persists_exact_mark_and_unrealized_pnl(
        self, store: TradingStore
    ) -> None:
        position = Position(
            instrument_id="BINANCE:PERP:BTCUSDT",
            qty=-2.0,
            avg_entry_price=100.0,
            opened_ts=T0,
        )
        store.snapshot_positions(
            T0,
            (position,),
            marks={position.instrument_id: (90.0, "order_book_mid")},
        )

        snapshot = store.position_snapshots_at(T0)[0]
        assert snapshot.mark_price == 90.0
        assert snapshot.mark_source == "order_book_mid"
        assert snapshot.market_value_quote == -180.0
        assert snapshot.unrealized_pnl_quote == 20.0

    def test_legacy_position_table_is_migrated_without_rewriting_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE positions_snapshots ("
                "cycle_ts INTEGER NOT NULL, instrument_id TEXT NOT NULL, qty REAL NOT NULL, "
                "avg_entry_price REAL NOT NULL, opened_ts INTEGER NOT NULL, "
                "PRIMARY KEY (cycle_ts, instrument_id)) WITHOUT ROWID"
            )
            connection.execute(
                "INSERT INTO positions_snapshots VALUES (?, ?, ?, ?, ?)",
                (T0, "BINANCE:PERP:BTCUSDT", 2.0, 100.0, T0),
            )

        with TradingStore(path) as migrated:
            snapshot = migrated.position_snapshots_at(T0)[0]

        assert snapshot.qty == 2.0
        assert snapshot.mark_price is None
        assert snapshot.unrealized_pnl_quote is None

    def test_equity_snapshot_and_curve(self, store: TradingStore) -> None:
        for k in range(3):
            ts = T0 + k * HOUR_MS
            acct = AccountState(
                equity_quote=100_000.0 + k * 1_000.0,
                cash_quote=50_000.0,
                positions=(),
                ts=ts + 90,
            )
            store.snapshot_equity(ts, acct)
        curve = store.equity_curve()
        assert [row[1] for row in curve] == [100_000.0, 101_000.0, 102_000.0]
        windowed = store.equity_curve(start=T0 + HOUR_MS)
        assert [row[0] for row in windowed] == [T0 + HOUR_MS, T0 + 2 * HOUR_MS]

    def test_equity_snapshot_upsert_is_idempotent(self, store: TradingStore) -> None:
        a = AccountState(equity_quote=100.0, cash_quote=100.0, positions=(), ts=T0)
        b = AccountState(equity_quote=200.0, cash_quote=150.0, positions=(), ts=T0 + 1)
        store.snapshot_equity(T0, a)
        store.snapshot_equity(T0, b)  # same cycle_ts -> overwrite
        curve = store.equity_curve()
        assert curve == [(T0, 200.0, 150.0, 0)]

    def test_paper_state_blob_round_trip(self, store: TradingStore) -> None:
        store.save_paper_state(T0, '{"cash": 100000.0, "positions": []}', now=T0 + 100)
        store.save_paper_state(
            T0 + HOUR_MS, '{"cash": 99000.0, "positions": [["BTC", 1.0]]}', now=T0 + HOUR_MS + 100
        )
        latest = store.latest_paper_state()
        assert latest is not None
        cycle_ts, blob = latest
        assert cycle_ts == T0 + HOUR_MS
        assert blob == '{"cash": 99000.0, "positions": [["BTC", 1.0]]}'

    def test_paper_state_none_when_empty(self, store: TradingStore) -> None:
        assert store.latest_paper_state() is None

    def test_paper_state_upsert_overwrites_same_cycle(self, store: TradingStore) -> None:
        store.save_paper_state(T0, "v1", now=T0 + 1)
        store.save_paper_state(T0, "v2", now=T0 + 2)
        latest = store.latest_paper_state()
        assert latest == (T0, "v2")


# ----------------------------------------------------------------- ladder state


class TestLadderState:
    def test_none_when_never_recorded(self, store: TradingStore) -> None:
        assert store.last_ladder_state() is None

    def test_record_and_last_round_trip(self, store: TradingStore) -> None:
        store.record_ladder_state(
            cycle_ts=T0,
            state="half_gross",
            hwm=120_000.0,
            drawdown=0.10,
            gross_mult=0.5,
        )
        snap = store.last_ladder_state()
        assert snap == LadderSnapshot(
            cycle_ts=T0,
            state="half_gross",
            hwm=120_000.0,
            drawdown=0.10,
            gross_mult=0.5,
        )

    def test_upsert_keeps_max_cycle_ts(self, store: TradingStore) -> None:
        """A newer cycle overwrites; an OLDER out-of-order replay never clobbers it."""
        store.record_ladder_state(
            cycle_ts=T0, state="normal", hwm=100_000.0, drawdown=0.0, gross_mult=1.0
        )
        store.record_ladder_state(
            cycle_ts=T0 + HOUR_MS,
            state="flat_halted",
            hwm=100_000.0,
            drawdown=0.20,
            gross_mult=0.0,
        )
        # An out-of-order replay of the OLDER bar must NOT overwrite the newer row.
        store.record_ladder_state(
            cycle_ts=T0, state="normal", hwm=100_000.0, drawdown=0.0, gross_mult=1.0
        )
        snap = store.last_ladder_state()
        assert snap is not None
        assert snap.cycle_ts == T0 + HOUR_MS
        assert snap.state == "flat_halted"
        assert snap.gross_mult == 0.0

    def test_same_cycle_overwrites_in_place(self, store: TradingStore) -> None:
        store.record_ladder_state(
            cycle_ts=T0, state="normal", hwm=100_000.0, drawdown=0.0, gross_mult=1.0
        )
        store.record_ladder_state(
            cycle_ts=T0, state="half_gross", hwm=100_000.0, drawdown=0.10, gross_mult=0.5
        )
        snap = store.last_ladder_state()
        assert snap is not None and snap.state == "half_gross" and snap.gross_mult == 0.5

    def test_nan_hwm_and_drawdown_round_trip(self, store: TradingStore) -> None:
        """Before the ladder's first equity mark hwm/drawdown are NaN (stored NULL)."""
        store.record_ladder_state(
            cycle_ts=T0,
            state="normal",
            hwm=math.nan,
            drawdown=math.nan,
            gross_mult=1.0,
        )
        snap = store.last_ladder_state()
        assert snap is not None
        assert math.isnan(snap.hwm)
        assert math.isnan(snap.drawdown)
        assert snap.gross_mult == 1.0

    def test_rearm_state_reflects_normal(self, store: TradingStore) -> None:
        """After a (simulated) rearm the persisted state reflects NORMAL again."""
        store.record_ladder_state(
            cycle_ts=T0, state="flat_halted", hwm=100_000.0, drawdown=0.20, gross_mult=0.0
        )
        # The loop re-records the ladder each cycle; post-rearm it is NORMAL.
        store.record_ladder_state(
            cycle_ts=T0 + HOUR_MS,
            state="normal",
            hwm=80_000.0,
            drawdown=0.0,
            gross_mult=1.0,
        )
        snap = store.last_ladder_state()
        assert snap is not None and snap.state == "normal" and snap.gross_mult == 1.0


# -------------------------------------------------------------- WAL / crash-sim


class TestWalConcurrency:
    def test_two_connections_share_committed_state(self, tmp_path: Path) -> None:
        """WAL: a writer's committed cycle is visible to a second independent reader."""
        db = tmp_path / "trading.sqlite"
        with TradingStore(db) as writer, TradingStore(db) as reader:
            writer.start_cycle(T0, now=T0 + 90)
            writer.finish_cycle(T0, "ok", "traded", now=T0 + 120)
            seen = reader.last_cycle()
            assert seen is not None
            assert seen.cycle_ts == T0
            assert seen.status == "ok"

    def test_running_cycle_survives_reopen_as_crash_sim(self, tmp_path: Path) -> None:
        """A 'running' row left by a dead process is still 'running' on a fresh open."""
        db = tmp_path / "trading.sqlite"
        with TradingStore(db) as s:
            s.start_cycle(T0, now=T0 + 90)
            s.record_intent(_order(), T0, now=T0 + 95)
            s.mark_submitted("af-c0-BTC", now=T0 + 96)
        # Process "crashes" here without finishing; reopen the same file.
        with TradingStore(db) as s2:
            running = s2.running_cycles()
            assert [c.cycle_ts for c in running] == [T0]
            open_ids = {o.client_order_id for o in s2.open_intents()}
            assert open_ids == {"af-c0-BTC"}
