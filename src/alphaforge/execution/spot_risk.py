"""Current spot risk checks. Clock calibration and admission remain separate gates."""

import json
import time
from decimal import Decimal as D

from alphaforge.execution.spot_account import parse_account
from alphaforge.execution.spot_paper import number
from alphaforge.execution.spot_prepare import parse_assets
from alphaforge.portfolio.spot_restart import SYMBOLS


def validate_current_risk(
    *, order, planned, attempted_ids, original, observation, equity, assets, books, now_ns
):
    """Conservative batch bounds; never budget unconfirmed sale proceeds.

    Original account inputs and orders must already have passed preparation
    evidence verification. Pending purchases are counted at full quantity, even
    if partially filled. Sales receive no credit in purchase exposure headroom.
    """
    if order not in planned or not attempted_ids.issubset({o["client_order_id"] for o in planned}):
        raise ValueError("risk inputs differ from reserved batch")
    if set(books) != set(SYMBOLS) or set(assets) != set(SYMBOLS):
        raise ValueError("exact current market universe required")
    for symbol in SYMBOLS:
        book = books[symbol]
        if not book.source_ns <= book.received_ns <= now_ns <= book.source_ns + 1_000_000_000:
            raise ValueError("stale or disordered current book")
        if book.quote.ask < book.quote.bid or (
            book.quote.ask - book.quote.bid
        ) / book.quote.bid > D(".005"):
            raise ValueError("crossed or wide current book")
    qty, limit = D(order["qty"]), D(order["limit_price"])
    asset, book = assets[order["symbol"]], books[order["symbol"]]
    if qty < asset.min_qty or qty % asset.qty_step or limit % asset.price_step:
        raise ValueError("reserved order violates current asset increments")
    if qty * limit > D(200_000):
        raise ValueError("current notional cap exceeded")
    if order["side"] == "sell":
        if qty > observation.available_positions.get(order["symbol"], D(0)):
            raise ValueError("current available spot quantity cannot cover sale")
        if not book.quote.bid * D(".999") <= limit <= book.quote.bid:
            raise ValueError("sale limit no longer fits current price cap")
        return
    if not book.quote.ask <= limit <= book.quote.ask * D("1.001"):
        raise ValueError("purchase limit no longer fits current price cap")
    base_cash, initial_equity = D(original["cash"]), D(original["equity"])
    conservative_equity = min(
        equity,
        observation.balance.cash
        + sum((q * books[s].quote.bid for s, q in observation.balance.positions.items()), D(0)),
    )
    if conservative_equity <= 0:
        raise ValueError("nonpositive current equity")
    purchases = [o for o in planned if o["side"] == "buy"]
    spent_ceiling = sum(
        (
            D(o["qty"]) * D(o["limit_price"]) * D("1.0025")
            for o in purchases
            if o["client_order_id"] in attempted_ids
        ),
        D(0),
    )
    remaining_cost = sum(
        (
            D(o["qty"]) * D(o["limit_price"]) * D("1.0025")
            for o in purchases
            if o["client_order_id"] not in attempted_ids
        ),
        D(0),
    )
    available = min(observation.balance.cash, base_cash - spent_ceiling)
    reserve = max(initial_equity, conservative_equity) * D(".10")
    if (
        available - remaining_cost < reserve
        or remaining_cost > observation.non_marginable_buying_power
    ):
        raise ValueError("current cash or buying power cannot cover batch and cash reserve")
    exposure = D(0)
    for symbol in SYMBOLS:
        base_qty = D(original["holdings"].get(symbol, {}).get("qty", "0"))
        buy_qty = sum((D(o["qty"]) for o in purchases if o["symbol"] == symbol), D(0))
        worst_qty = max(observation.balance.positions.get(symbol, D(0)), base_qty + buy_qty)
        mark = max(
            [books[symbol].quote.ask]
            + [D(o["limit_price"]) for o in purchases if o["symbol"] == symbol]
        )
        value = worst_qty * mark
        if value > conservative_equity * D(".45"):
            raise ValueError("current per-coin exposure cap exceeded")
        exposure += value
    if exposure > conservative_equity * D(".90"):
        raise ValueError("current gross exposure cap exceeded")


async def check_current_risk(reader, journal, order):
    """Re-read authenticated account, asset metadata and books before claiming."""
    row = journal.conn.execute(
        "SELECT decision_ms FROM order_ids WHERE client_order_id=?", (order["client_order_id"],)
    ).fetchone()
    if row is None:
        raise ValueError("reserved decision missing")
    packet = journal.evidence_for_decision(row[0])
    planned = tuple(
        json.loads(
            journal.conn.execute(
                "SELECT payload FROM decisions WHERE decision_ms=?", (row[0],)
            ).fetchone()[0]
        )
    )
    attempted = {
        r[0]
        for r in journal.conn.execute(
            "SELECT a.client_order_id FROM submission_attempts a JOIN order_ids o "
            "ON a.client_order_id=o.client_order_id WHERE o.decision_ms=?",
            (row[0],),
        )
    }
    observed_ns = time.time_ns()
    account = await reader.get("/v2/account")
    positions = await reader.get("/v2/positions")
    observation = parse_account(account, positions, expected_binding=packet["account_binding"])
    open_orders = await reader.get("/v2/orders", params={"status": "open", "limit": 500})
    if not isinstance(open_orders, list) or open_orders:
        raise ValueError("open orders block current risk clearance")
    assets = parse_assets(
        await reader.get("/v2/assets", params={"asset_class": "crypto", "status": "active"})
    )
    books = await reader.read_books()
    now_ns = time.time_ns()
    if not 0 <= now_ns - observed_ns <= 5_000_000_000:
        raise ValueError("current risk account observation expired")
    validate_current_risk(
        order=order,
        planned=planned,
        attempted_ids=attempted,
        original=packet["snapshot"],
        observation=observation,
        equity=number(account["equity"], positive=True),
        assets=assets,
        books=books,
        now_ns=now_ns,
    )
