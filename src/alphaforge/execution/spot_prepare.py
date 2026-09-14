"""Read-only preparation using live broker inputs and caller-supplied daily history.

This reserves plans but never authorizes execution. Historical source provenance,
research admission, account dedication and clock clearance remain separate gates.
"""

import hashlib
import json
import os
import time
from dataclasses import asdict

from alphaforge.execution.spot_account import observe_quiescent_account, parse_account
from alphaforge.execution.spot_paper import number
from alphaforge.execution.spot_plan import Asset, Holding, Snapshot, plan_orders
from alphaforge.execution.spot_reconcile import balance_payload, verify_baseline_continuity
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, target_weights


def parse_assets(rows):
    if not isinstance(rows, list):
        raise ValueError("asset list required")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed asset")
        symbol = row.get("symbol")
        if symbol not in SYMBOLS:
            continue
        if (
            symbol in result
            or row.get("class") != "crypto"
            or row.get("status") != "active"
            or row.get("tradable") is not True
        ):
            raise ValueError("ambiguous or untradable spot asset")
        result[symbol] = Asset(
            symbol,
            number(row.get("min_order_size"), positive=True),
            number(row.get("min_trade_increment"), positive=True),
            number(row.get("price_increment"), positive=True),
        )
    if set(result) != set(SYMBOLS):
        raise ValueError("required spot assets missing")
    return result


async def prepare_daily_decision(reader, journal, *, histories=None, history_receipt_path=None):
    """Collect fresh inputs and reserve once; never return submission permission.

    No network is used on daily replay or while a previous decision is pending.
    Reservation and baseline sealing commit together, including cash-only days.
    """
    started_ns = time.time_ns()
    started_mono = time.monotonic_ns()
    day = started_ns // 1_000_000 // DAY_MS * DAY_MS
    existing = journal.conn.execute(
        "SELECT state FROM decisions WHERE decision_ms=?", (day,)
    ).fetchone()
    if existing:
        return {
            "status": "REPLAY_" + existing[0].upper(),
            "decision_ms": day,
            "network_requests": 0,
            "submission_authorized": False,
        }
    if journal.conn.execute("SELECT 1 FROM decisions WHERE state='pending'").fetchone():
        raise ValueError("prior pending decision requires recovery before preparation")
    binding, epoch = journal.conn.execute("SELECT account,epoch FROM binding").fetchone()
    history_receipt = None
    if histories is None:
        if history_receipt_path is None:
            raise ValueError("durable history receipt path required for broker collection")
        from alphaforge.execution.spot_history import collect_daily_history

        histories, packet = await collect_daily_history(reader, day_end_ms=day)
        encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        # Exclusive creation retains previous receipts; a failed write cannot
        # create a reserved decision. Its checksum is bound to the journal below.
        with history_receipt_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        history_receipt = {
            "path": str(history_receipt_path.resolve()),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    # Copy the caller's histories before the first await: mutation during reads
    # cannot change the signal without being reflected in this decision.
    frozen_histories = {s: tuple(rows) for s, rows in histories.items()}
    targets = target_weights(frozen_histories, decision_ms=started_ns // 1_000_000)
    observed = await observe_quiescent_account(reader, expected_binding=binding)
    baseline = balance_payload(observed.balance)
    verify_baseline_continuity(journal, decision_ms=day, payload=baseline)
    assets = parse_assets(
        await reader.get("/v2/assets", params={"asset_class": "crypto", "status": "active"})
    )
    observed_ms = time.time_ns() // 1_000_000
    account = await reader.get("/v2/account")
    positions = await reader.get("/v2/positions")
    if parse_account(account, positions, expected_binding=binding) != observed:
        raise ValueError("account changed during plan preparation")
    orders = await reader.get("/v2/orders", params={"status": "open", "limit": 500})
    if not isinstance(orders, list) or orders:
        raise ValueError("open orders prevent plan preparation")
    books = await reader.read_books()
    decision_ns, mono = time.time_ns(), time.monotonic_ns()
    decision_ms = (decision_ns + 999_999) // 1_000_000
    if abs((decision_ns - started_ns) - (mono - started_mono)) > 10_000_000:
        raise ValueError("clock discontinuity during plan preparation")
    if decision_ms // DAY_MS * DAY_MS != day:
        raise ValueError("UTC day changed during preparation")
    snapshot = Snapshot(
        binding,
        observed_ms,
        number(account.get("equity"), positive=True),
        observed.balance.cash,
        observed.non_marginable_buying_power,
        {
            s: Holding(q, observed.available_positions[s])
            for s, q in observed.balance.positions.items()
        },
        0,
        0,
        True,
        False,
    )
    planned = plan_orders(
        epoch=epoch,
        decision_ms=decision_ms,
        expected_account_binding=binding,
        snapshot=snapshot,
        assets=assets,
        quotes={s: b.quote for s, b in books.items()},
        targets=targets,
    )
    evidence = {
        "schema": "alphaforge.spot-preparation.v1",
        "decision_ms": day,
        "planned_at_ms": decision_ms,
        "account_binding": binding,
        "epoch": epoch,
        "histories": {s: [asdict(b) for b in rows] for s, rows in frozen_histories.items()},
        "snapshot": asdict(snapshot),
        "assets": {s: asdict(a) for s, a in assets.items()},
        "quotes": {s: asdict(b.quote) for s, b in books.items()},
        "history_receipt": history_receipt,
    }
    evidence = json.loads(json.dumps(evidence, default=str, allow_nan=False))
    status = journal.reserve(
        day, planned, baseline={**baseline, "observed_at_ms": observed_ms}, evidence=evidence
    )
    return {
        "status": status,
        "decision_ms": day,
        "planned_at_ms": decision_ms,
        "orders": planned,
        "targets": {s: str(w) for s, w in targets.items()},
        "submission_authorized": False,
        "history_source_verified": False,
        "authenticated_history_receipt": history_receipt,
        "clock_accuracy_verified": False,
    }
