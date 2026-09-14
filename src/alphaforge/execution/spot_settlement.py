"""Exact balance conservation for a dedicated spot account with no external flows.

Pure reconciliation kernel. Inputs must be obtained and completeness verified by
an authenticated broker reader. This function does not authenticate input data
and cannot, by itself, clear a journal or authorize another submission.
"""

from dataclasses import dataclass
from decimal import Decimal

from alphaforge.execution.spot_paper import assess_order
from alphaforge.portfolio.spot_restart import SYMBOLS


@dataclass(frozen=True)
class Balance:
    account_binding: str
    cash: Decimal
    positions: dict[str, Decimal]


@dataclass(frozen=True)
class FillActivity:
    activity_id: str
    order_id: str
    symbol: str
    side: str
    qty: Decimal
    price: Decimal


@dataclass(frozen=True)
class FeeActivity:
    activity_id: str
    asset: str  # BTC, ETH, or USD; positive amount means a debit.
    amount: Decimal


def _number(value, *, positive=False):
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("invalid settlement number")


def reconcile(
    *,
    before: Balance,
    after: Balance,
    intents: tuple[dict, ...],
    orders: tuple[dict, ...],
    fills: tuple[FillActivity, ...],
    fees: tuple[FeeActivity, ...],
    open_orders: tuple[dict, ...],
    activity_window_complete: bool,
) -> dict:
    """Require complete terminal orders plus exact gross-fill/fee conservation.

    Unknown deposits, withdrawals, transfers or fee corrections produce an
    unexplained balance difference and remain blocked. Rounded display values
    are not acceptable inputs; no tolerance may hide lost funds or base units.
    Activity-window completeness is a caller assertion, not established here.
    """
    if (
        not before.account_binding
        or before.account_binding != after.account_binding
        or activity_window_complete is not True
        or open_orders
    ):
        raise ValueError("account, activity completeness or open-order gate failed")
    if not 1 <= len(intents) <= 2 or len(orders) != len(intents):
        raise ValueError("exact reserved order set required")
    if len(fills) > 1000 or len(fees) > 1000:
        raise ValueError("settlement activity budget exceeded")
    for balance in (before, after):
        _number(balance.cash)
        if not set(balance.positions).issubset(SYMBOLS):
            raise ValueError("foreign positions in dedicated account")
        for qty in balance.positions.values():
            _number(qty)
    raw_by_client = {order.get("client_order_id"): order for order in orders}
    if len(raw_by_client) != len(orders):
        raise ValueError("duplicate broker order")
    expected_order_ids = {}
    for intent in intents:
        if (
            intent.get("symbol") not in SYMBOLS
            or intent.get("side") not in {"buy", "sell"}
            or intent.get("type") != "limit"
            or intent.get("time_in_force") != "ioc"
        ):
            raise ValueError("unexpected spot intent semantics")
        client_id = intent.get("client_order_id")
        if client_id not in raw_by_client:
            raise ValueError("reserved order missing from reconciliation")
        raw = raw_by_client[client_id]
        assessment = assess_order(intent, raw)
        if not assessment["execution_terminal"]:
            raise ValueError("order execution remains unresolved")
        if raw["id"] in expected_order_ids:
            raise ValueError("duplicate broker identity")
        expected_order_ids[raw["id"]] = raw
    if len(expected_order_ids) != len(intents):
        raise ValueError("duplicate reserved identity")
    expected_cash = before.cash
    expected_positions = {s: before.positions.get(s, Decimal(0)) for s in SYMBOLS}
    totals = {order_id: Decimal(0) for order_id in expected_order_ids}
    seen = set()
    received_assets = set()
    received_amounts = {}
    for fill in fills:
        if (
            not isinstance(fill.activity_id, str)
            or not fill.activity_id
            or fill.activity_id in seen
        ):
            raise ValueError("duplicate or missing activity identity")
        seen.add(fill.activity_id)
        raw = expected_order_ids.get(fill.order_id)
        if raw is None or fill.symbol != raw["symbol"] or fill.side != raw["side"]:
            raise ValueError("fill activity does not match reserved order")
        _number(fill.qty, positive=True)
        _number(fill.price, positive=True)
        limit = Decimal(raw["limit_price"])
        if (fill.side == "buy" and fill.price > limit) or (
            fill.side == "sell" and fill.price < limit
        ):
            raise ValueError("activity fill violates limit")
        sign = 1 if fill.side == "buy" else -1
        expected_cash -= sign * fill.qty * fill.price
        expected_positions[fill.symbol] += sign * fill.qty
        totals[fill.order_id] += fill.qty
        received_asset = fill.symbol.split("/")[0] if sign == 1 else "USD"
        received_assets.add(received_asset)
        received_amounts[received_asset] = received_amounts.get(received_asset, Decimal(0)) + (
            fill.qty if sign == 1 else fill.qty * fill.price
        )
    for order_id, qty in totals.items():
        if qty != Decimal(expected_order_ids[order_id]["filled_qty"]):
            raise ValueError("fill activities do not explain broker executed quantity")
    fee_assets = set()
    fee_totals = {}
    for fee in fees:
        if not isinstance(fee.activity_id, str) or not fee.activity_id or fee.activity_id in seen:
            raise ValueError("duplicate or missing fee identity")
        seen.add(fee.activity_id)
        _number(fee.amount, positive=True)
        if fee.asset not in received_assets:
            raise ValueError("fee charged in an unexpected received asset")
        fee_assets.add(fee.asset)
        fee_totals[fee.asset] = fee_totals.get(fee.asset, Decimal(0)) + fee.amount
        if fee.asset == "USD":
            expected_cash -= fee.amount
        else:
            expected_positions[fee.asset + "/USD"] -= fee.amount
    if fee_assets != received_assets:
        raise ValueError("received-asset fees not yet evidenced")
    if any(fee_totals[a] > received_amounts[a] * Decimal("0.0025") for a in fee_assets):
        raise ValueError("fee exceeds frozen 25bps cost ceiling")
    if expected_cash != after.cash or any(
        expected_positions[s] != after.positions.get(s, Decimal(0)) for s in SYMBOLS
    ):
        raise ValueError("unexplained cash or base-position change")
    return {
        "status": "BALANCE_CONSERVATION_VERIFIED_FROM_SUPPLIED_INPUTS",
        "account_binding": before.account_binding,
        "orders_checked": len(orders),
        "fills_checked": len(fills),
        "fees_checked": len(fees),
        "input_authenticity_verified": False,
        "journal_clearance": False,
    }
