"""Offline execution-cost prototype. Not imported by trading or publication code.

No broker client, filesystem path, migration or automatic historical backfill.
Callers supply evidence and an explicitly opened fixture SQLite connection.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Benchmark:
    instrument: str
    currency: str
    price: float | None
    kind: str  # quote_mid or last_trade; NEVER an order limit
    source: str
    feed: str  # explicitly verified feed; an unspecified default is unknown
    market_ms: int | None
    received_ms: int | None


@dataclass(frozen=True)
class Observation:
    profile: str
    epoch: str
    client_order_id: str
    instrument: str
    currency: str
    execution_basis: str  # alpaca_paper or funded; never pooled
    side: str
    requested_qty: float
    filled_qty: float  # cumulative order quantity, NOT an incremental fill
    average_fill_price: float | None
    decision_ms: int
    submit_ms: int
    observed_ms: int
    fill_ms: int | None
    status: str
    source: str
    decision: Benchmark | None = None
    arrival: Benchmark | None = None
    fee_amount: float | None = None  # cumulative, signed charge; negative = rebate
    fee_currency: str | None = None
    fee_source: str | None = None
    fee_complete: bool = False


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _benchmark_reason(
    ref: Benchmark | None, event_ms: int, row: Observation, max_age_ms: int
) -> str | None:
    if ref is None:
        return "missing_benchmark"
    if (ref.instrument, ref.currency) != (row.instrument, row.currency):
        return "benchmark_identity_mismatch"
    if ref.kind not in {"quote_mid", "last_trade"}:
        return "not_an_independent_benchmark"
    if not _positive(ref.price):
        return "invalid_benchmark_price"
    if not ref.source or ref.feed.lower() in {"", "unknown", "default", "unspecified"}:
        return "unverified_source_or_feed"
    if (
        type(ref.market_ms) is not int
        or type(ref.received_ms) is not int
        or ref.market_ms <= 0
        or ref.received_ms <= 0
    ):
        return "missing_benchmark_timestamp"
    if not (0 < ref.market_ms <= ref.received_ms <= event_ms):
        return "benchmark_not_known_at_event"
    if event_ms - ref.market_ms > max_age_ms:
        return "stale_benchmark"
    return None


def measure(row: Observation, *, max_age_ms: int, policy_id: str) -> dict:
    """One cumulative snapshot. Never sum repeated snapshots as separate fills.

    Positive bps means worse execution. Missing evidence remains null, not zero.
    Freshness policy is explicitly supplied; this prototype sets no live threshold.
    """
    if not policy_id or type(max_age_ms) is not int or max_age_ms < 0:
        raise ValueError("An explicit freshness policy is required")
    if not all(
        (row.profile, row.epoch, row.client_order_id, row.instrument, row.currency, row.source)
    ):
        raise ValueError("Missing observation identity or provenance")
    if row.side not in {"buy", "sell"} or row.execution_basis not in {"alpaca_paper", "funded"}:
        raise ValueError("Invalid side or execution basis")
    if not _positive(row.requested_qty) or not math.isfinite(row.filled_qty):
        raise ValueError("Invalid quantities")
    if not 0 <= row.filled_qty <= row.requested_qty:
        raise ValueError("Cumulative fill outside requested quantity")
    if (
        any(type(ts) is not int for ts in (row.decision_ms, row.submit_ms, row.observed_ms))
        or not 0 < row.decision_ms <= row.submit_ms <= row.observed_ms
    ):
        raise ValueError("Invalid event chronology")
    if row.status not in {
        "new",
        "accepted",
        "partially_filled",
        "filled",
        "canceled",
        "expired",
        "rejected",
        "replaced",
        "done_for_day",
    }:
        raise ValueError("Unmapped broker status; preserve raw evidence for review")
    if row.status == "filled" and row.filled_qty != row.requested_qty:
        raise ValueError("Filled status disagrees with cumulative quantity")
    if row.filled_qty and (
        not _positive(row.average_fill_price)
        or type(row.fill_ms) is not int
        or not row.submit_ms <= row.fill_ms <= row.observed_ms
    ):
        raise ValueError("Invalid fill price or chronology")
    result = {
        "schema": "alphac.execution-cost-prototype.v1",
        "policy_id": policy_id,
        "profile": row.profile,
        "epoch": row.epoch,
        "client_order_id": row.client_order_id,
        "instrument": row.instrument,
        "currency": row.currency,
        "observed_ms": row.observed_ms,
        "status": row.status,
        "max_age_ms": max_age_ms,
        "execution_basis": row.execution_basis,
        "measurement_unit": "cumulative_order_snapshot",
        "filled_qty": row.filled_qty,
        "unfilled_qty": row.requested_qty - row.filled_qty,
        "fill_fraction": row.filled_qty / row.requested_qty,
        "decision_slippage_bps": None,
        "arrival_slippage_bps": None,
        "decision_price_cost": None,
        "fee_bps": None,
        "all_in_cost_bps": None,
        "limitations": ["filled_quantity_only; opportunity_cost_not_measured"],
    }
    sign = 1 if row.side == "buy" else -1
    for name, ref, event_ms in [
        ("decision", row.decision, row.decision_ms),
        ("arrival", row.arrival, row.submit_ms),
    ]:
        reason = _benchmark_reason(ref, event_ms, row, max_age_ms)
        if reason:
            result["limitations"].append(f"{name}:{reason}")
        elif row.filled_qty:
            # Validation above guarantees non-null, positive prices.
            cost = sign * (row.average_fill_price - ref.price) * row.filled_qty
            result[f"{name}_slippage_bps"] = cost / (row.filled_qty * ref.price) * 10_000
            if name == "decision":
                result["decision_price_cost"] = cost
    if not row.filled_qty:
        result["limitations"].append("no_executed_quantity")
    fee_known = (
        row.fee_complete
        and row.fee_amount is not None
        and math.isfinite(row.fee_amount)
        and bool(row.fee_source)
        and row.fee_currency == row.currency
    )
    if not fee_known:
        result["limitations"].append("fees:unknown_incomplete_or_currency_mismatch")
    elif result["decision_slippage_bps"] is not None:
        result["fee_bps"] = row.fee_amount / (row.filled_qty * row.decision.price) * 10_000
        result["all_in_cost_bps"] = result["decision_slippage_bps"] + result["fee_bps"]
    result["measurable"] = result["decision_slippage_bps"] is not None
    # Overflow is invalid evidence, not JSON Infinity or a hidden zero.
    if any(isinstance(value, float) and not math.isfinite(value) for value in result.values()):
        raise ValueError("Non-finite calculated measurement")
    return result


def create_fixture_journal(con: sqlite3.Connection) -> None:
    """Draft additive schema; caller must supply a disposable test database."""
    con.execute("""CREATE TABLE IF NOT EXISTS execution_evidence_v1 (
        profile TEXT NOT NULL, epoch TEXT NOT NULL, basis TEXT NOT NULL,
        client_order_id TEXT NOT NULL, event_id TEXT NOT NULL,
        payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(profile, epoch, basis, client_order_id, event_id))""")


def append_fixture_observation(con: sqlite3.Connection, event_id: str, row: Observation) -> bool:
    """Exact replay is idempotent; altered evidence under the same id is rejected.

    Caller owns transactions. This is not an operational migration or writer.
    A new cumulative snapshot gets a new event id, not an incremental-fill label.
    """
    if not event_id:
        raise ValueError("Missing event identity")
    payload = json.dumps(asdict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    key = (row.profile, row.epoch, row.execution_basis, row.client_order_id, event_id)
    prior = con.execute(
        """SELECT payload, sha256 FROM execution_evidence_v1
        WHERE profile=? AND epoch=? AND basis=? AND client_order_id=? AND event_id=?""",
        key,
    ).fetchone()
    if prior:
        if prior != (payload, digest):
            raise ValueError("Conflicting immutable evidence; append a correction with a new id")
        return False
    con.execute("INSERT INTO execution_evidence_v1 VALUES (?,?,?,?,?,?,?)", (*key, payload, digest))
    return True
