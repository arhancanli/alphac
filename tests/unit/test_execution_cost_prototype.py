"""Offline measurement fixtures; actual order/reconciliation code, no trading main()."""

from __future__ import annotations

import importlib.util
import json
import socket
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


M = load("execution_cost_prototype", "scripts/prototypes/execution_cost_measurement.py")
LIVE = load("execution_cost_live_fixture", "scripts/live_cycle.py")
T = 1_789_046_400_000


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No network allowed in execution-cost fixtures")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def sample(**changes):
    benchmark = M.Benchmark(
        "SPY", "USD", 100.0, "quote_mid", "synthetic_quote", "synthetic_feed", T - 50, T - 10
    )
    row = M.Observation(
        "equity",
        "fixture_epoch",
        "equity-fixture-order",
        "SPY",
        "USD",
        "alpaca_paper",
        "buy",
        10.0,
        10.0,
        101.0,
        T,
        T + 100,
        T + 300,
        T + 200,
        "filled",
        "synthetic_broker_snapshot",
        decision=benchmark,
        arrival=benchmark,
    )
    return replace(row, **changes)


def measure(row):
    return M.measure(row, max_age_ms=1_000, policy_id="fixture-only-1s")


@pytest.mark.parametrize(
    "side,price,expected",
    [
        ("buy", 101.0, 100.0),
        ("buy", 99.0, -100.0),
        ("sell", 99.0, 100.0),
        ("sell", 101.0, -100.0),
        ("buy", 100.0, 0.0),
        ("sell", 100.0, 0.0),
    ],
)
def test_side_normalized_cost(side, price, expected):
    report = measure(sample(side=side, average_fill_price=price))
    assert report["decision_slippage_bps"] == pytest.approx(expected)
    assert report["all_in_cost_bps"] is None  # unknown fees are not free


@pytest.mark.parametrize("fee,expected", [(1.0, 110.0), (0.0, 100.0), (-1.0, 90.0)])
def test_explicit_complete_fees_and_rebates(fee, expected):
    report = measure(
        sample(
            fee_amount=fee, fee_currency="USD", fee_source="synthetic_activity", fee_complete=True
        )
    )
    assert report["all_in_cost_bps"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"fee_currency": "EUR"},
        {"fee_complete": False},
        {"fee_source": None},
        {"fee_amount": None},
        {"fee_amount": float("nan")},
        {"fee_amount": float("inf")},
    ],
)
def test_fees_fail_unknown(changes):
    row = sample(fee_amount=1.0, fee_currency="USD", fee_source="fixture", fee_complete=True)
    assert measure(replace(row, **changes))["all_in_cost_bps"] is None


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"kind": "limit_price"}, "not_an_independent_benchmark"),
        ({"price": 0.0}, "invalid_benchmark_price"),
        ({"price": float("nan")}, "invalid_benchmark_price"),
        ({"feed": "unknown"}, "unverified_source_or_feed"),
        ({"source": ""}, "unverified_source_or_feed"),
        ({"market_ms": None}, "missing_benchmark_timestamp"),
        ({"market_ms": float("nan")}, "missing_benchmark_timestamp"),
        ({"received_ms": T + 1}, "benchmark_not_known_at_event"),
        ({"market_ms": T + 1}, "benchmark_not_known_at_event"),
        ({"market_ms": T - 1_001}, "stale_benchmark"),
        ({"instrument": "IWM"}, "benchmark_identity_mismatch"),
        ({"currency": "EUR"}, "benchmark_identity_mismatch"),
    ],
)
def test_invalid_benchmark_is_not_a_measurement(change, reason):
    row = sample()
    report = measure(replace(row, decision=replace(row.decision, **change)))
    assert not report["measurable"]
    assert report["decision_slippage_bps"] is None
    assert f"decision:{reason}" in report["limitations"]
    assert report["arrival_slippage_bps"] == pytest.approx(100.0)


def test_missing_historical_benchmark_stays_missing():
    report = measure(sample(decision=None, arrival=None))
    assert report["decision_slippage_bps"] is None
    assert report["arrival_slippage_bps"] is None
    assert not report["measurable"]


def test_decision_and_arrival_are_separate_benchmarks():
    row = sample()
    arrival = replace(row.arrival, price=100.5, market_ms=T + 50, received_ms=T + 80)
    report = measure(replace(row, arrival=arrival))
    assert report["decision_slippage_bps"] == pytest.approx(100.0)
    assert report["arrival_slippage_bps"] == pytest.approx((101 / 100.5 - 1) * 10_000)


@pytest.mark.parametrize("status,qty", [("canceled", 4.0), ("expired", 0.0), ("rejected", 0.0)])
def test_partial_and_unfilled_orders_remain_visible(status, qty):
    report = measure(
        sample(
            status=status,
            filled_qty=qty,
            average_fill_price=101.0 if qty else None,
            fill_ms=T + 200 if qty else None,
        )
    )
    assert report["unfilled_qty"] == 10 - qty
    assert report["fill_fraction"] == qty / 10
    assert report["measurable"] == bool(qty)
    assert report["decision_price_cost"] == (qty if qty else None)


@pytest.mark.parametrize(
    "change",
    [
        {"side": "invalid"},
        {"execution_basis": "paper_or_funded"},
        {"requested_qty": 0.0},
        {"filled_qty": -1.0},
        {"filled_qty": 11.0},
        {"filled_qty": float("nan")},
        {"average_fill_price": float("inf")},
        {"submit_ms": T - 1},
        {"fill_ms": T},
        {"fill_ms": None},
        {"observed_ms": T + 150},
        {"status": "unmapped"},
        {"filled_qty": 9.0},
        {"observed_ms": float("inf")},
        {"fill_ms": float("nan")},
    ],
)
def test_invalid_execution_evidence_rejected(change):
    with pytest.raises(ValueError):
        measure(sample(**change))


def test_journal_persistence_idempotence_conflicts_and_scope(tmp_path):
    path = tmp_path / "fixture.sqlite"
    row = sample()
    with sqlite3.connect(path) as con:
        M.create_fixture_journal(con)
        assert M.append_fixture_observation(con, "snapshot-1", row)
        assert not M.append_fixture_observation(con, "snapshot-1", row)
        with pytest.raises(ValueError, match="Conflicting"):
            M.append_fixture_observation(con, "snapshot-1", replace(row, average_fill_price=102.0))
        assert M.append_fixture_observation(con, "snapshot-1", replace(row, profile="alphavintage"))
        assert M.append_fixture_observation(con, "snapshot-1", replace(row, epoch="new_epoch"))
        assert M.append_fixture_observation(
            con, "snapshot-1", replace(row, execution_basis="funded")
        )
    with sqlite3.connect(path) as con:
        payload = con.execute(
            "SELECT payload FROM execution_evidence_v1 WHERE profile=? AND epoch=? AND basis=?",
            ("equity", "fixture_epoch", "alpaca_paper"),
        ).fetchone()[0]
        assert json.loads(payload) == asdict(row)
        assert con.execute("SELECT COUNT(*) FROM execution_evidence_v1").fetchone()[0] == 4


@pytest.mark.parametrize("age,policy", [(-1, "fixture"), (1000, ""), (1.5, "fixture")])
def test_no_implicit_freshness_policy(age, policy):
    with pytest.raises(ValueError, match="freshness policy"):
        M.measure(sample(), max_age_ms=age, policy_id=policy)


def test_journal_rollback_and_nonfinite_payload(tmp_path):
    with sqlite3.connect(tmp_path / "fixture.sqlite") as con:
        M.create_fixture_journal(con)
        con.commit()
        M.append_fixture_observation(con, "snapshot-1", sample())
        con.rollback()
        assert con.execute("SELECT COUNT(*) FROM execution_evidence_v1").fetchone()[0] == 0
        with pytest.raises(ValueError):
            M.append_fixture_observation(con, "snapshot-2", sample(fee_amount=float("nan")))


def test_real_order_builder_does_not_supply_an_independent_decision_price():
    orders = LIVE._delta_orders(
        profile="equity",
        cycle_ms=T,
        instrument_id="XUSE:CASH:SPYUSD",
        symbol="SPY",
        cur_shares=0.0,
        tgt_shares=10.0,
        mid=100.0,
        market_orders=False,
    )
    assert len(orders) == 1
    assert orders[0].decision_price == pytest.approx(100.75)
    assert orders[0].decision_price != 100.0  # Do not reuse this as a decision midpoint.


def test_real_reconciliation_persists_cumulative_not_incremental_fills(tmp_path):
    class Broker:
        quantity = "4"

        def closed_orders(self, **kwargs):
            return [
                {
                    "client_order_id": "equity-fixture-order",
                    "id": "fixture-broker-order",
                    "symbol": "SPY",
                    "side": "buy",
                    "status": "canceled",
                    "qty": "10",
                    "filled_qty": self.quantity,
                    "filled_avg_price": "101",
                    "limit_price": "102",
                    "submitted_at": "2026-09-10T12:00:00Z",
                    "filled_at": "2026-09-10T12:01:00Z",
                }
            ]

    broker = Broker()
    con = LIVE._audit_open(tmp_path / "actual-path-fixture.sqlite")
    try:
        for qty in ("4", "4", "6"):
            broker.quantity = qty
            assert LIVE._reconcile_fills(con, broker, profile="equity").succeeded
            assert con.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
        assert con.execute("SELECT filled_qty, fill_price FROM fills").fetchone() == (6.0, 101.0)
        columns = {r[1] for r in con.execute("PRAGMA table_info(fills)")}
        assert "decision_price" not in columns and "fee_amount" not in columns
        # Legacy rows alone cannot establish a decision benchmark or all-in costs.
        qty, price = con.execute("SELECT filled_qty, fill_price FROM fills").fetchone()
        report = measure(
            sample(
                filled_qty=qty,
                average_fill_price=price,
                status="canceled",
                decision=None,
                arrival=None,
            )
        )
        assert report["filled_qty"] == 6.0, "Never sum the 4, 4 and 6 snapshots"
        assert not report["measurable"] and report["all_in_cost_bps"] is None
    finally:
        con.close()
