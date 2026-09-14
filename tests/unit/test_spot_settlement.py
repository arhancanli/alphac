from dataclasses import replace
from decimal import Decimal as D

import pytest

from alphaforge.execution.spot_settlement import Balance, FeeActivity, FillActivity, reconcile


def scenario():
    intent = {
        "client_order_id": "afspot-1",
        "symbol": "BTC/USD",
        "side": "buy",
        "type": "limit",
        "time_in_force": "ioc",
        "qty": "1",
        "limit_price": "100",
    }
    order = {
        **intent,
        "id": "broker-1",
        "asset_class": "crypto",
        "status": "filled",
        "filled_qty": "1",
        "filled_avg_price": "100",
    }
    return {
        "before": Balance("dedicated", D(1000), {}),
        "after": Balance("dedicated", D(900), {"BTC/USD": D("0.9975")}),
        "intents": (intent,),
        "orders": (order,),
        "fills": (FillActivity("fill-1", "broker-1", "BTC/USD", "buy", D(1), D(100)),),
        "fees": (FeeActivity("fee-1", "BTC", D("0.0025")),),
        "open_orders": (),
        "activity_window_complete": True,
    }


def test_gross_buy_and_base_fee_explain_net_holdings():
    report = reconcile(**scenario())
    assert report["status"] == "BALANCE_CONSERVATION_VERIFIED_FROM_SUPPLIED_INPUTS"
    assert report["journal_clearance"] is False
    assert report["input_authenticity_verified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "fees_pending",
        "gross_position",
        "cash_difference",
        "other_account",
        "duplicate_activity",
        "foreign_fill",
        "unexplained_quantity",
        "incomplete_window",
        "open_order",
        "wrong_fee_asset",
        "unresolved_order",
    ],
)
def test_unsettled_or_inconsistent_account_cannot_clear(fault):
    args = scenario()
    if fault == "fees_pending":
        args["fees"] = ()
    elif fault == "gross_position":
        args["after"] = replace(args["after"], positions={"BTC/USD": D(1)})
    elif fault == "cash_difference":
        args["after"] = replace(args["after"], cash=D("900.00000001"))
    elif fault == "other_account":
        args["after"] = replace(args["after"], account_binding="other")
    elif fault == "duplicate_activity":
        args["fills"] *= 2
    elif fault == "foreign_fill":
        args["fills"] = (replace(args["fills"][0], order_id="foreign"),)
    elif fault == "unexplained_quantity":
        args["fills"] = (replace(args["fills"][0], qty=D("0.9")),)
    elif fault == "incomplete_window":
        args["activity_window_complete"] = False
    elif fault == "open_order":
        args["open_orders"] = ({"id": "open"},)
    elif fault == "wrong_fee_asset":
        args["fees"] = (FeeActivity("fee-1", "USD", D("0.25")),)
    else:
        args["orders"][0]["status"] = "pending_cancel"
    with pytest.raises(ValueError):
        reconcile(**args)


def test_zero_fill_cancellation_requires_unchanged_balances_not_fees():
    args = scenario()
    args["orders"][0].update(status="canceled", filled_qty="0", filled_avg_price=None)
    args.update(after=args["before"], fills=(), fees=())
    assert reconcile(**args)["fills_checked"] == 0


def test_partial_sell_cancellation_reconciles_usd_fee_and_remaining_position():
    args = scenario()
    args["intents"][0]["side"] = "sell"
    args["orders"][0].update(side="sell", status="canceled", filled_qty="0.5")
    args.update(
        before=Balance("dedicated", D(100), {"BTC/USD": D(1)}),
        after=Balance("dedicated", D("149.875"), {"BTC/USD": D("0.5")}),
        fills=(FillActivity("fill-1", "broker-1", "BTC/USD", "sell", D("0.5"), D(100)),),
        fees=(FeeActivity("fee-1", "USD", D("0.125")),),
    )
    assert reconcile(**args)["fees_checked"] == 1


def test_conserved_balances_do_not_hide_excessive_fees():
    args = scenario()
    args["fees"] = (FeeActivity("fee-1", "BTC", D("0.003")),)
    args["after"] = replace(args["after"], positions={"BTC/USD": D("0.997")})
    with pytest.raises(ValueError, match="cost ceiling"):
        reconcile(**args)
