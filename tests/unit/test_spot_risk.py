from copy import deepcopy
from decimal import Decimal as D

import pytest

from alphaforge.execution.spot_account import AccountObservation
from alphaforge.execution.spot_book import SpotBook
from alphaforge.execution.spot_plan import Asset, Quote
from alphaforge.execution.spot_risk import validate_current_risk
from alphaforge.execution.spot_settlement import Balance
from alphaforge.portfolio.spot_restart import SYMBOLS


def inputs():
    orders = tuple(
        {
            "client_order_id": s,
            "symbol": s,
            "qty": "4",
            "limit_price": "100.10",
            "side": "buy",
            "type": "limit",
            "time_in_force": "ioc",
        }
        for s in SYMBOLS
    )
    return {
        "order": orders[0],
        "planned": orders,
        "attempted_ids": set(),
        "original": {"cash": "1000", "equity": "1000", "holdings": {}},
        "observation": AccountObservation(Balance("fixture", D(1000), {}), {}, D(1000)),
        "equity": D(1000),
        "assets": {s: Asset(s, D(".001"), D(".001"), D(".01")) for s in SYMBOLS},
        "books": {
            s: SpotBook(
                Quote(D("99.99"), D(100), 1000, 1000), D(100), D(100), 1_000_000_000, 1_000_000_000
            )
            for s in SYMBOLS
        },
        "now_ns": 1_100_000_000,
    }


def test_current_batch_and_partly_filled_batch_pass():
    args = inputs()
    validate_current_risk(**args)
    args["order"] = args["planned"][1]
    args["attempted_ids"] = {SYMBOLS[0]}
    args["observation"] = AccountObservation(
        Balance("fixture", D("599.6"), {SYMBOLS[0]: D(4)}), {SYMBOLS[0]: D(4)}, D("599.6")
    )
    validate_current_risk(**args)


@pytest.mark.parametrize("fault", ["stale", "cash", "power", "equity", "tick", "price"])
def test_current_risk_blocks_changed_market_and_account(fault):
    args = inputs()
    if fault == "stale":
        args["now_ns"] += 1_000_000_000
    if fault in {"cash", "power"}:
        args["observation"] = AccountObservation(
            Balance("fixture", D(850 if fault == "cash" else 1000), {}),
            {},
            D(100 if fault == "power" else 1000),
        )
    if fault == "equity":
        args["equity"] = D(800)
    if fault == "tick":
        args["assets"][SYMBOLS[0]] = Asset(SYMBOLS[0], D(".001"), D(".001"), D(1))
    if fault == "price":
        args["books"][SYMBOLS[0]] = SpotBook(
            Quote(D("100.19"), D("100.20"), 1000, 1000),
            D(100),
            D(100),
            1_000_000_000,
            1_000_000_000,
        )
    with pytest.raises(ValueError):
        validate_current_risk(**args)


def test_sale_proceeds_do_not_fund_new_purchases():
    args = inputs()
    args["original"]["cash"] = "500"
    # Extra current cash may be an unreconciled sale; it cannot enlarge budget.
    with pytest.raises(ValueError, match="cash"):
        validate_current_risk(**args)


def test_risk_reducing_sale_can_exit_an_overweight_position():
    args = inputs()
    sale = {**args["order"], "side": "sell", "limit_price": "99.90", "qty": "5"}
    args.update(
        order=sale,
        planned=(sale,),
        equity=D(1000),
        observation=AccountObservation(
            Balance("fixture", D(0), {SYMBOLS[0]: D(10)}), {SYMBOLS[0]: D(10)}, D(0)
        ),
    )
    validate_current_risk(**args)
    bad = deepcopy(args)
    bad["observation"] = AccountObservation(
        Balance("fixture", D(0), {SYMBOLS[0]: D(10)}), {SYMBOLS[0]: D(4)}, D(0)
    )
    with pytest.raises(ValueError, match="available"):
        validate_current_risk(**bad)
