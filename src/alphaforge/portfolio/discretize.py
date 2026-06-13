"""Target weights → integer-constrained orders (execDesign §6.4).

Pure function of (targets, book, closes, instrument filters): no I/O, no
randomness — the same inputs always produce the same orders, byte for byte
(client order ids are deterministic per ``(cycle_ts, instrument)`` so
crash-replay never double-submits).

Per asset:

1. ``Δ_notional = w_target · E - qty_current · close`` with
   ``E = cash + Σ qty·close`` (marked equity, computed here without touching
   the ledger's equity curve).
2. **No-trade band**: skip when ``|Δ_notional| < no_trade_band · E`` (default
   10 bps of equity — below this the ≈15-20 bps round-trip cost eats any
   rebalancing benefit; cuts churn dramatically at hourly cadence).
3. **Exchange filters**: qty is floored to the lot grid
   (``floor(|Δ|/close / lot_size) · lot_size``); risk-increasing orders are
   skipped when ``qty < min_qty`` or ``qty·close < 1.05 · min_notional`` (5%
   buffer so a price tick between sizing and submission cannot reject the
   order). Risk-REDUCING orders (``reduce_only=True``) are never skipped on
   min-size filters — you must always be able to de-risk.
4. **Position flips** (sign(target qty) ≠ sign(current qty)): emit TWO orders —
   a ``reduce_only`` close to flat, then an open — so live margin/position-mode
   accounting on Binance never sees an ambiguous netting order.
5. ``decision_price = close``, ``reason = "rebalance"``, market orders.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from alphaforge.backtest.ledger import Ledger
from alphaforge.core.instruments import Instrument
from alphaforge.core.time import Ms
from alphaforge.core.types import OrderRequest, OrderType, Side

__all__ = ["weights_to_orders"]

#: Safety buffer on the exchange min-notional filter (5%): survives a price
#: tick between sizing and submission.
_MIN_NOTIONAL_BUFFER = 1.05

#: Relative epsilon for lot flooring so an exact lot multiple stored in binary
#: floating point (e.g. 0.30000000000000004) is not floored a full step down.
_LOT_EPS = 1e-9


def _floor_to_lot(qty_abs: float, lot_size: float) -> float:
    """Floor an unsigned quantity to the exchange lot grid (epsilon-guarded)."""
    steps = math.floor(qty_abs / lot_size + _LOT_EPS)
    return steps * lot_size


def _marked_equity(ledger: Ledger, closes: Mapping[str, float]) -> float:
    """``E = cash + Σ qty·close`` over open positions, without mutating the ledger."""
    equity = ledger.cash
    for iid, pos in ledger.positions().items():
        close = closes.get(iid)
        if close is None or not math.isfinite(close) or close <= 0.0:
            raise ValueError(
                f"weights_to_orders: missing/invalid close for open position {iid!r}: {close!r}"
            )
        equity += pos.qty * close
    if not math.isfinite(equity) or equity <= 0.0:
        raise ValueError(f"weights_to_orders: marked equity must be > 0, got {equity!r}")
    return equity


def weights_to_orders(
    targets: Mapping[str, float],
    ledger: Ledger,
    closes: Mapping[str, float],
    instruments: Mapping[str, Instrument],
    no_trade_band: float = 0.0010,
    cycle_ts: Ms = 0,
) -> list[OrderRequest]:
    """Target weights → integer-constrained OrderRequests. Skips churn; splits flips.

    Instruments to exit must appear in ``targets`` with weight 0.0 — positions
    not mentioned in ``targets`` are left untouched.

    Args:
        targets: instrument_id → target weight (fraction of equity, signed).
        ledger: the live book; supplies positions and cash (equity is marked
            here from ``closes``; the ledger is NOT mutated).
        closes: instrument_id → decision-bar close. Required for every target
            and every open position.
        instruments: instrument_id → :class:`Instrument` (exchange filters).
        no_trade_band: per-asset ``|Δ_notional|`` threshold as a fraction of
            equity (default 10 bps).
        cycle_ts: decision timestamp (bar close, epoch ms) — stamped on every
            order and baked into the idempotent ``client_order_id``.

    Returns:
        Orders sorted by instrument id (flip legs adjacent, close before open).

    Raises:
        ValueError: unknown instrument, missing/invalid close, non-finite
            target, or non-positive marked equity.
    """
    if not math.isfinite(no_trade_band) or no_trade_band < 0.0:
        raise ValueError(f"no_trade_band must be finite and >= 0, got {no_trade_band!r}")
    equity = _marked_equity(ledger, closes)
    positions = ledger.positions()
    orders: list[OrderRequest] = []

    for iid in sorted(targets):
        w_target = float(targets[iid])
        if not math.isfinite(w_target):
            raise ValueError(f"weights_to_orders: target weight for {iid!r} must be finite")
        inst = instruments.get(iid)
        if inst is None:
            raise ValueError(f"weights_to_orders: unknown instrument {iid!r}")
        close = closes.get(iid)
        if close is None or not math.isfinite(close) or close <= 0.0:
            raise ValueError(f"weights_to_orders: missing/invalid close for {iid!r}: {close!r}")

        qty_current = positions[iid].qty if iid in positions else 0.0
        delta_notional = w_target * equity - qty_current * close

        # 2. No-trade band: churn below ~round-trip cost is pure bleed.
        if abs(delta_notional) < no_trade_band * equity:
            continue

        target_qty = w_target * equity / close
        flips = (
            qty_current != 0.0 and target_qty != 0.0 and (target_qty > 0.0) != (qty_current > 0.0)
        )

        if flips:
            # 4. Two orders: reduce_only close to flat, then a fresh open.
            qty_close = _floor_to_lot(abs(qty_current), inst.lot_size)
            if qty_close > 0.0:
                orders.append(
                    OrderRequest(
                        client_order_id=f"rb-{cycle_ts}-{iid}-close",
                        instrument_id=iid,
                        side=Side.SELL if qty_current > 0.0 else Side.BUY,
                        qty=qty_close,
                        order_type=OrderType.MARKET,
                        reduce_only=True,
                        decision_ts=cycle_ts,
                        decision_price=close,
                        reason="rebalance",
                    )
                )
            qty_open = _floor_to_lot(abs(target_qty), inst.lot_size)
            if (
                qty_open >= inst.min_qty
                and qty_open * close >= _MIN_NOTIONAL_BUFFER * inst.min_notional
            ):
                orders.append(
                    OrderRequest(
                        client_order_id=f"rb-{cycle_ts}-{iid}-open",
                        instrument_id=iid,
                        side=Side.BUY if target_qty > 0.0 else Side.SELL,
                        qty=qty_open,
                        order_type=OrderType.MARKET,
                        reduce_only=False,
                        decision_ts=cycle_ts,
                        decision_price=close,
                        reason="rebalance",
                    )
                )
            continue

        # 3. Same-direction adjust (open, add, reduce, or full close).
        qty = _floor_to_lot(abs(delta_notional) / close, inst.lot_size)
        if qty <= 0.0:
            continue
        # A reduce moves |position| toward zero without crossing it (flips were
        # split above): mark it reduce_only and exempt it from min-size skips.
        reducing = qty_current != 0.0 and (delta_notional > 0.0) != (qty_current > 0.0)
        if not reducing and (
            qty < inst.min_qty or qty * close < _MIN_NOTIONAL_BUFFER * inst.min_notional
        ):
            continue
        orders.append(
            OrderRequest(
                client_order_id=f"rb-{cycle_ts}-{iid}",
                instrument_id=iid,
                side=Side.BUY if delta_notional > 0.0 else Side.SELL,
                qty=qty,
                order_type=OrderType.MARKET,
                reduce_only=reducing,
                decision_ts=cycle_ts,
                decision_price=close,
                reason="rebalance",
            )
        )

    return orders
