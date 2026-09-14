"""Reconstruct a reserved plan from immutable evidence; not execution clearance."""

import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

from alphaforge.execution.spot_plan import Asset, Holding, Quote, Snapshot, plan_orders
from alphaforge.execution.spot_reconcile import balance_payload
from alphaforge.execution.spot_settlement import Balance
from alphaforge.portfolio.spot_restart import DAY_MS, DailyClose, target_weights


def verify_preparation(journal, *, decision_ms: int) -> dict:
    packet = journal.evidence_for_decision(decision_ms)
    binding, epoch = journal.conn.execute("SELECT account,epoch FROM binding").fetchone()
    planned_ms = packet["planned_at_ms"]
    if (
        packet.get("schema") != "alphaforge.spot-preparation.v1"
        or packet["decision_ms"] != decision_ms
        or packet["account_binding"] != binding
        or packet["epoch"] != epoch
        or type(planned_ms) is not int
        or planned_ms // DAY_MS * DAY_MS != decision_ms
    ):
        raise ValueError("preparation does not bind account, epoch and UTC decision")
    source = packet["history_receipt"]
    if source is None:
        raise ValueError("injected history has no authenticated collection receipt")
    path = Path(source["path"])
    if path.stat().st_size > 16_777_216:
        raise ValueError("history receipt exceeds size budget")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("history receipt checksum mismatch")
    receipt = json.loads(raw)
    if (
        receipt.get("schema") != "alphaforge.spot-history-receipt.v1"
        or receipt["day_end_ms"] != decision_ms
        or receipt["daily_closes"] != packet["histories"]
        or type(receipt["observed_at_ns"]) is not int
        or not decision_ms * 1_000_000 <= receipt["observed_at_ns"] <= planned_ms * 1_000_000
    ):
        raise ValueError("history receipt does not bind observed decision inputs")
    histories = {
        s: tuple(DailyClose(b["end_ms"], D(b["close"])) for b in rows)
        for s, rows in packet["histories"].items()
    }
    targets = target_weights(histories, decision_ms=planned_ms)
    snapshot = dict(packet["snapshot"])
    for key in ("equity", "cash", "non_marginable_buying_power"):
        snapshot[key] = D(snapshot[key])
    snapshot["holdings"] = {
        s: Holding(D(h["qty"]), D(h["available"])) for s, h in snapshot["holdings"].items()
    }
    snapshot = Snapshot(**snapshot)
    assets = {
        s: Asset(**{**a, **{k: D(a[k]) for k in ("min_qty", "qty_step", "price_step")}})
        for s, a in packet["assets"].items()
    }
    quotes = {
        s: Quote(**{**q, "bid": D(q["bid"]), "ask": D(q["ask"])})
        for s, q in packet["quotes"].items()
    }
    rebuilt = plan_orders(
        epoch=epoch,
        decision_ms=planned_ms,
        expected_account_binding=binding,
        snapshot=snapshot,
        assets=assets,
        quotes=quotes,
        targets=targets,
    )
    row = journal.conn.execute(
        "SELECT payload FROM decisions WHERE decision_ms=?", (decision_ms,)
    ).fetchone()
    if row is None or tuple(json.loads(row[0])) != rebuilt:
        raise ValueError("reserved orders differ from reconstructed plan")
    baseline = journal.conn.execute(
        "SELECT payload FROM decision_baselines WHERE decision_ms=?", (decision_ms,)
    ).fetchone()
    if baseline is None:
        raise ValueError("sealed baseline missing")
    baseline = json.loads(baseline[0])
    observed = baseline.pop("observed_at_ms")
    if observed != snapshot.observed_ms or baseline != balance_payload(
        Balance(binding, snapshot.cash, {s: h.qty for s, h in snapshot.holdings.items()})
    ):
        raise ValueError("preparation snapshot differs from sealed baseline")
    return {
        "status": "RESERVED_PLAN_RECONSTRUCTED_FROM_BOUND_EVIDENCE",
        "decision_ms": decision_ms,
        "orders_checked": len(rebuilt),
        "history_receipt_sha256": source["sha256"],
        "submission_authorized": False,
        "current_market_account_clock_verified": False,
    }
