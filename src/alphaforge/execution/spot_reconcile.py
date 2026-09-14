"""Join account reads, activity ingestion and settlement to the durable journal.

No activation or order submission. REST quiescence does not guarantee that the
broker cannot later post a correction; baseline continuity detects such changes.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from decimal import Decimal

from alphaforge.execution.spot_account import observe_quiescent_account
from alphaforge.execution.spot_activities import convert_activities
from alphaforge.execution.spot_settlement import Balance, reconcile


def balance_payload(balance):
    def canonical(value):
        return "0" if value == 0 else format(value.normalize(), "f")

    return {
        "account_binding": balance.account_binding,
        "cash": canonical(balance.cash),
        "positions": {s: canonical(q) for s, q in sorted(balance.positions.items()) if q != 0},
    }


def verify_baseline_continuity(journal, *, decision_ms: int, payload: dict):
    previous = journal.conn.execute(
        "SELECT d.evidence,b.payload,d.payload FROM decisions d LEFT JOIN decision_baselines b "
        "ON d.decision_ms=b.decision_ms WHERE d.state='terminal' "
        "AND d.decision_ms<? ORDER BY d.decision_ms DESC LIMIT 1",
        (decision_ms,),
    ).fetchone()
    if previous and previous[0] is None:
        if previous[2] != "[]" or previous[1] is None:
            raise ValueError("prior terminal decision has no verifiable balance anchor")
        prior_balance = json.loads(previous[1])
        prior_balance.pop("observed_at_ms")
        if prior_balance != payload:
            raise ValueError("account changed since last settlement; do not reset baseline")
        return
    if previous:
        record = json.loads(previous[0])
        evidence = bytes.fromhex(record["hex"])
        if hashlib.sha256(evidence).hexdigest() != record["sha256"]:
            raise ValueError("prior settlement evidence hash mismatch")
        prior = json.loads(evidence)
        if prior.get("schema") != "alphaforge.spot-settlement.v1" or prior.get("after") != payload:
            raise ValueError("account changed since last settlement; do not reset baseline")


async def capture_baseline(reader, journal, *, decision_ms: int):
    existing = journal.conn.execute(
        "SELECT payload FROM decision_baselines WHERE decision_ms=?", (decision_ms,)
    ).fetchone()
    if existing:
        return json.loads(existing[0])
    binding = journal.conn.execute("SELECT account FROM binding").fetchone()[0]
    observation = await observe_quiescent_account(reader, expected_binding=binding)
    payload = balance_payload(observation.balance)
    verify_baseline_continuity(journal, decision_ms=decision_ms, payload=payload)
    payload["observed_at_ms"] = time.time_ns() // 1_000_000
    journal.seal_baseline(decision_ms, payload)
    return payload


async def settle_decision(reader, journal, *, decision_ms: int, until: str):
    row = journal.conn.execute(
        "SELECT d.payload,d.state,b.payload FROM decisions d JOIN decision_baselines b "
        "ON d.decision_ms=b.decision_ms WHERE d.decision_ms=?",
        (decision_ms,),
    ).fetchone()
    if row is None:
        raise ValueError("decision or sealed baseline missing")
    if row[1] == "terminal":
        return {"status": "ALREADY_RECORDED", "network_requests": 0}
    intents, baseline = tuple(json.loads(row[0])), json.loads(row[2])
    attempted_ids = set(journal.stop_submissions(decision_ms))
    abandoned = [o["client_order_id"] for o in intents if o["client_order_id"] not in attempted_ids]
    attempted = tuple(o for o in intents if o["client_order_id"] in attempted_ids)
    binding = baseline["account_binding"]
    first = await observe_quiescent_account(reader, expected_binding=binding)
    raw_orders = tuple(
        [
            await reader.get(
                "/v2/orders:by_client_order_id",
                params={"client_order_id": order["client_order_id"]},
            )
            for order in attempted
        ]
    )
    after = datetime.fromtimestamp(baseline["observed_at_ms"] / 1000, UTC).isoformat()
    activities = await reader.read_activities(
        after=after, until=until, expected_account_binding=binding
    )
    second = await observe_quiescent_account(reader, expected_binding=binding)
    if first != second:
        raise ValueError("account changed across activity scan")
    fills, fees = convert_activities(activities["records"])
    before = Balance(
        binding,
        Decimal(baseline["cash"]),
        {s: Decimal(q) for s, q in baseline["positions"].items()},
    )
    if attempted:
        report = reconcile(
            before=before,
            after=second.balance,
            intents=attempted,
            orders=raw_orders,
            fills=fills,
            fees=fees,
            open_orders=(),
            activity_window_complete=activities["pagination_exhausted"],
        )
    else:
        if activities["pagination_exhausted"] is not True or activities["records"]:
            raise ValueError("unattempted batch has incomplete scan or unexplained activities")
        if balance_payload(before) != balance_payload(second.balance):
            raise ValueError("unattempted batch has unexplained balance changes")
        report = {"status": "UNATTEMPTED_BATCH_ABANDONED", "orders_checked": 0}
    packet = {
        "schema": "alphaforge.spot-settlement.v1",
        "decision_ms": decision_ms,
        "before": balance_payload(before),
        "after": balance_payload(second.balance),
        "orders": raw_orders,
        "abandoned_unattempted_ids": abandoned,
        "activity_scan": activities,
        "reconciliation": report,
        "observation": "repeated_rest_reads_not_atomic_broker_lock",
    }
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), default=str).encode()
    journal.record_terminal(
        decision_ms,
        reconciled_payload_sha256=hashlib.sha256(row[0].encode()).hexdigest(),
        evidence=encoded,
    )
    return {
        "status": "SETTLEMENT_RECORDED",
        "decision_ms": decision_ms,
        "orders_checked": report["orders_checked"],
        "late_corrections_still_possible": True,
        "abandoned_unattempted_ids": abandoned,
    }
