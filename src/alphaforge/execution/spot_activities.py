"""Strict activity conversion for USD spot pairs; unknown account flows block."""

from decimal import Decimal, InvalidOperation

from alphaforge.execution.spot_settlement import FeeActivity, FillActivity

PAIRS = {"BTCUSD": "BTC/USD", "BTC/USD": "BTC/USD", "ETHUSD": "ETH/USD", "ETH/USD": "ETH/USD"}


def _signed(value):
    if not isinstance(value, str):
        raise ValueError("activity numeric strings required")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("invalid activity number") from None
    if not number.is_finite():
        raise ValueError("nonfinite activity number")
    return number


def convert_activities(
    records: tuple[dict, ...],
) -> tuple[tuple[FillActivity, ...], tuple[FeeActivity, ...]]:
    """Return explicit gross fills and positive received-asset fee debits.

    Transfers, deposits, reversals, pending fees and unknown types are not silently
    omitted. Caller must reconcile the complete account interval and associate
    every fill with its reserved order before settlement can be considered.
    """
    fills, fees = [], []
    seen = set()
    if len(records) > 2000:
        raise ValueError("activity count budget exceeded")
    for record in records:
        identity = record.get("id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("duplicate or missing activity ID")
        seen.add(identity)
        kind = record.get("activity_type")
        if kind == "FILL":
            symbol = PAIRS.get(record.get("symbol"))
            side, order = record.get("side"), record.get("order_id")
            if (
                symbol is None
                or side not in {"buy", "sell"}
                or record.get("type") not in {"fill", "partial_fill"}
                or not isinstance(order, str)
                or not order
            ):
                raise ValueError("unsupported fill activity")
            qty, price = _signed(record.get("qty")), _signed(record.get("price"))
            if qty <= 0 or price <= 0:
                raise ValueError("invalid fill economics")
            fills.append(FillActivity(identity, order, symbol, side, qty, price))
        elif kind in {"CFEE", "FEE"}:
            if record.get("status") not in (None, "executed"):
                raise ValueError("fee not executed")
            net = _signed(record.get("net_amount"))
            qty = _signed(record["qty"]) if "qty" in record else Decimal(0)
            if net == 0 and qty < 0 and kind == "CFEE":
                symbol = PAIRS.get(record.get("symbol"))
                if symbol is None:
                    raise ValueError("unverified base-asset fee denomination")
                fees.append(FeeActivity(identity, symbol.split("/")[0], -qty))
            elif net < 0 and qty == 0:
                if record.get("symbol") is not None and record["symbol"] not in PAIRS:
                    raise ValueError("foreign fee symbol")
                fees.append(FeeActivity(identity, "USD", -net))
            else:
                raise ValueError("ambiguous fee, credit, or correction requires reconciliation")
        else:
            raise ValueError("unsupported account flow requires explicit reconciliation")
    return tuple(fills), tuple(fees)
