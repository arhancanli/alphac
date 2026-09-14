"""Pure, conservative Alpaca spot IOC limit planner. Does not authorize submission.

Inputs must come from independently reconciled, account-bound snapshots. No sale
proceeds are recycled until a later snapshot confirms them. Crypto fee activities
must reconcile base-asset debits separately from gross executed quantities.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from hashlib import sha256

from alphaforge.portfolio.spot_restart import DAY_MS, STRATEGY_ID, SYMBOLS

D = Decimal


@dataclass(frozen=True)
class Asset:
    symbol: str
    min_qty: Decimal
    qty_step: Decimal
    price_step: Decimal
    asset_class: str = "crypto"
    tradable: bool = True
    status: str = "active"


@dataclass(frozen=True)
class Quote:
    bid: Decimal
    ask: Decimal
    source_ms: int
    received_ms: int


@dataclass(frozen=True)
class Holding:
    qty: Decimal
    available: Decimal


@dataclass(frozen=True)
class Snapshot:
    account_binding: str
    observed_ms: int
    equity: Decimal
    cash: Decimal
    non_marginable_buying_power: Decimal
    holdings: dict[str, Holding]
    open_order_count: int
    unresolved_intent_count: int
    reconciled: bool
    trading_blocked: bool


def _number(value: Decimal, *, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("expected finite nonnegative Decimal")


def _stamp(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer timestamp")


def _round(value: Decimal, step: Decimal, *, up: bool = False) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN) * step


def plan_orders(
    *,
    epoch: str,
    decision_ms: int,
    expected_account_binding: str,
    snapshot: Snapshot,
    assets: dict[str, Asset],
    quotes: dict[str, Quote],
    targets: dict[str, Decimal],
) -> tuple[dict[str, str], ...]:
    """Build deterministic intents, never a live clearance.

    Max gross target 90%, per coin 45%; 10% cash plus 25bps reserve on buys.
    Limit prices cap displacement at 10bps from the observed side. Wide/stale
    quotes, unresolved orders, short positions and foreign holdings block all.
    """
    _stamp(decision_ms)
    _stamp(snapshot.observed_ms)
    if not isinstance(epoch, str) or not epoch.strip() or len(epoch) > 96:
        raise ValueError("new nonempty epoch required")
    if (
        not isinstance(expected_account_binding, str)
        or not expected_account_binding
        or snapshot.account_binding != expected_account_binding
    ):
        raise ValueError("dedicated account binding mismatch")
    if snapshot.reconciled is not True or snapshot.trading_blocked is not False:
        raise ValueError("account not reconciled or trading blocked")
    for count in (snapshot.open_order_count, snapshot.unresolved_intent_count):
        if type(count) is not int or count != 0:
            raise ValueError("outstanding or uncertain orders block planning")
    if not 0 <= decision_ms - snapshot.observed_ms <= 5_000:
        raise ValueError("stale or future account snapshot")
    if any(set(mapping) != set(SYMBOLS) for mapping in (assets, quotes, targets)):
        raise ValueError("exact strategy universe required")
    if not set(snapshot.holdings).issubset(SYMBOLS):
        raise ValueError("foreign position in dedicated account")
    _number(snapshot.equity, positive=True)
    _number(snapshot.cash)
    _number(snapshot.non_marginable_buying_power)
    for weight in targets.values():
        _number(weight)
        if weight > D("0.45"):
            raise ValueError("per-coin exposure exceeded")
    if sum(targets.values()) > D("0.90"):
        raise ValueError("gross exposure exceeded")
    for symbol in SYMBOLS:
        asset, quote = assets[symbol], quotes[symbol]
        if (
            asset.symbol != symbol
            or asset.asset_class != "crypto"
            or asset.status != "active"
            or asset.tradable is not True
        ):
            raise ValueError("untradable or mismatched spot asset")
        for value in (asset.min_qty, asset.qty_step, asset.price_step, quote.bid, quote.ask):
            _number(value, positive=True)
        _stamp(quote.source_ms)
        _stamp(quote.received_ms)
        if not quote.source_ms <= quote.received_ms <= decision_ms <= quote.source_ms + 1_000:
            raise ValueError("stale or disordered quote")
        if quote.ask < quote.bid or (quote.ask - quote.bid) / quote.bid > D("0.005"):
            raise ValueError("crossed or wide quote")
        holding = snapshot.holdings.get(symbol, Holding(D(0), D(0)))
        _number(holding.qty)
        _number(holding.available)
        if holding.available > holding.qty:
            raise ValueError("available quantity exceeds held quantity")

    budget = max(
        D(0), min(snapshot.cash - snapshot.equity * D("0.10"), snapshot.non_marginable_buying_power)
    )
    orders = []
    for symbol in SYMBOLS:
        asset, quote = assets[symbol], quotes[symbol]
        holding = snapshot.holdings.get(symbol, Holding(D(0), D(0)))
        # Ask marks avoid understating held exposure when buying.
        wanted = snapshot.equity * targets[symbol] / quote.ask
        delta = wanted - holding.qty
        side = "buy" if delta > 0 else "sell"
        if side == "buy":
            limit = _round(quote.ask * D("1.001"), asset.price_step)
            if limit < quote.ask:
                continue  # No marketable tick fits the price cap.
            capped_delta = max(D(0), snapshot.equity * targets[symbol] / limit - holding.qty)
            qty = min(capped_delta, budget / (limit * D("1.0025")), D("200000") / limit)
        else:
            limit = _round(quote.bid * D("0.999"), asset.price_step, up=True)
            if limit > quote.bid:
                continue
            # Base fees may post later; available must already reserve pending CFEE.
            qty = min(-delta, holding.available, D("200000") / limit)
        qty = _round(qty, asset.qty_step)
        if qty < asset.min_qty or qty == 0:
            continue
        if side == "buy":
            budget -= qty * limit * D("1.0025")
        identity = json.dumps(
            [STRATEGY_ID, epoch, expected_account_binding, decision_ms // DAY_MS, symbol],
            separators=(",", ":"),
        )
        orders.append(
            {
                "symbol": symbol,
                "qty": format(qty, "f"),
                "side": side,
                "type": "limit",
                "time_in_force": "ioc",
                "limit_price": format(limit, "f"),
                "client_order_id": "afspot-" + sha256(identity.encode()).hexdigest()[:40],
            }
        )
    return tuple(orders)
