"""Independent displayed-depth scenarios, never executable orders or P&L.

Each scenario consumes one book once. Repeated calls are alternative scenarios,
not sequential orders; the caller must not sum their liquidity.
"""

from __future__ import annotations

import math


def sweep_book(
    row: dict | None,
    *,
    as_of_ns: int,
    side: str,
    quantity: int,
    max_age_ns: int = 1_000_000_000,
) -> dict:
    """Reject the latest observation if unsafe; never fall back to an older good row."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    if type(max_age_ns) is not int or max_age_ns < 0:
        raise ValueError("max_age_ns must be a nonnegative integer")
    result = {
        "requested": quantity,
        "filled": 0,
        "unfilled": quantity,
        "vwap_native": None,
        "execution_eligible": False,
    }

    def blocked(reason):
        return {**result, "status": "BLOCKED", "reason": reason}

    if row is None:
        return blocked("missing_book")
    recv, event = row["recv_ns"], row["event_ns"]
    if event > recv or recv > as_of_ns:
        return blocked("timestamp_order")
    if as_of_ns - min(recv, event) > max_age_ns:
        return blocked("stale_book")
    if not row["quality_ok"]:
        return blocked("flagged_or_incomplete_event")
    # Trades can carry pre-trade depth; do not spend that liquidity again.
    if row["action"] not in {"A", "C", "M"}:
        return blocked("non_book_update")
    if not row["market_open"]:
        return blocked("market_not_confirmed_open")
    books = []
    for key, direction in (("bids", -1), ("asks", 1)):
        levels = []
        ended = False
        for price, size in row[key]:
            if size == 0:
                ended = True
                continue
            if ended or not math.isfinite(price) or price <= 0:
                return blocked("invalid_depth")
            if isinstance(size, bool) or not math.isfinite(size) or size <= 0 or int(size) != size:
                return blocked("invalid_size")
            if levels and direction * (price - levels[-1][0]) <= 0:
                return blocked("unordered_depth")
            levels.append((price, int(size)))
        if not levels:
            return blocked("empty_side")
        books.append(levels)
    if books[0][0][0] >= books[1][0][0]:
        return blocked("locked_or_crossed")
    remaining, total = quantity, 0.0
    for price, size in books[1 if side == "buy" else 0]:
        take = min(remaining, size)
        total += take * price
        remaining -= take
        if remaining == 0:
            break
    filled = quantity - remaining
    return {
        **result,
        "status": "DEPTH_ONLY" if remaining == 0 else "PARTIAL_DEPTH_ONLY",
        "filled": filled,
        "unfilled": remaining,
        "vwap_native": total / filled,
        "quote_age_ns": as_of_ns - recv,
    }
