from dataclasses import replace
from decimal import Decimal as D

import pytest

from alphaforge.execution.spot_plan import Asset, Holding, Quote, Snapshot, plan_orders
from alphaforge.execution.spot_rehearsal import reserve_daily_plan
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, DailyClose, target_weights


def inputs():
    return {
        "epoch": "paper-epoch-1",
        "decision_ms": 100_000,
        "expected_account_binding": "dedicated-paper-digest",
        "snapshot": Snapshot(
            "dedicated-paper-digest", 99_900, D(1000), D(1000), D(1000), {}, 0, 0, True, False
        ),
        "assets": {s: Asset(s, D("0.001"), D("0.001"), D("0.01")) for s in SYMBOLS},
        "quotes": {s: Quote(D("99.9"), D(100), 99_500, 99_600) for s in SYMBOLS},
        "targets": {s: D("0.45") for s in SYMBOLS},
    }


def test_buys_reserve_cash_and_fees_across_both_orders():
    args = inputs()
    orders = plan_orders(**args)
    assert len(orders) == 2
    cost = sum(D(o["qty"]) * D(o["limit_price"]) * D("1.0025") for o in orders)
    assert cost <= D(900)
    for order in orders:
        assert order["type"] == "limit" and order["time_in_force"] == "ioc"
        assert D(order["qty"]) % D("0.001") == 0
        assert D(order["limit_price"]) <= D("100.10")
    assert plan_orders(**args) == orders
    changed = plan_orders(**{**args, "epoch": "paper-epoch-2"})
    assert changed[0]["client_order_id"] != orders[0]["client_order_id"]


def test_sell_only_available_and_never_spend_unconfirmed_sale_proceeds():
    args = inputs()
    args["snapshot"] = replace(
        args["snapshot"], cash=D(0), holdings={"BTC/USD": Holding(D(10), D("9.975"))}
    )
    args["targets"]["BTC/USD"] = D(0)
    orders = plan_orders(**args)
    assert len(orders) == 1
    assert orders[0]["side"] == "sell"
    assert D(orders[0]["qty"]) == D("9.975")


@pytest.mark.parametrize(
    "change",
    [
        {"account_binding": "other-sleeve"},
        {"open_order_count": 1},
        {"unresolved_intent_count": 1},
        {"open_order_count": False},
        {"reconciled": False},
        {"trading_blocked": True},
        {"observed_ms": 94_999},
        {"observed_ms": 100_001},
        {"cash": D("NaN")},
        {"equity": D(0)},
        {"holdings": {"SPY": Holding(D(1), D(1))}},
        {"holdings": {"BTC/USD": Holding(D(-1), D(0))}},
        {"holdings": {"BTC/USD": Holding(D(1), D(2))}},
    ],
)
def test_bad_account_blocks_entire_plan(change):
    args = inputs()
    args["snapshot"] = replace(args["snapshot"], **change)
    with pytest.raises(ValueError):
        plan_orders(**args)


@pytest.mark.parametrize(
    "change",
    [
        {"source_ms": 98_999},
        {"received_ms": 99_499},
        {"received_ms": 100_001},
        {"bid": D(101)},
        {"ask": D(110)},
        {"ask": D("Infinity")},
    ],
)
def test_bad_quote_blocks_entire_plan(change):
    args = inputs()
    args["quotes"]["ETH/USD"] = replace(args["quotes"]["ETH/USD"], **change)
    with pytest.raises(ValueError):
        plan_orders(**args)


@pytest.mark.parametrize(
    "change",
    [{"qty_step": D(0)}, {"asset_class": "us_equity"}, {"tradable": False}, {"symbol": "ETHUSD"}],
)
def test_bad_asset_metadata_blocks(change):
    args = inputs()
    args["assets"]["ETH/USD"] = replace(args["assets"]["ETH/USD"], **change)
    with pytest.raises(ValueError):
        plan_orders(**args)


def test_size_caps_and_unusable_price_tick():
    args = inputs()
    args["snapshot"] = replace(
        args["snapshot"],
        equity=D(1_000_000),
        cash=D(1_000_000),
        non_marginable_buying_power=D(1_000_000),
    )
    for order in plan_orders(**args):
        assert D(order["qty"]) * D(order["limit_price"]) <= 200_000
    args["quotes"]["BTC/USD"] = Quote(D("100.20"), D("100.25"), 99_500, 99_600)
    args["assets"]["BTC/USD"] = replace(args["assets"]["BTC/USD"], price_step=D(1))
    assert all(o["symbol"] != "BTC/USD" for o in plan_orders(**args))


def histories():
    return {s: tuple(DailyClose((i + 1) * DAY_MS, D(i + 1)) for i in range(200)) for s in SYMBOLS}


def test_fixed_trend_and_flat_signal():
    bars = histories()
    assert target_weights(bars, decision_ms=200 * DAY_MS) == {s: D("0.45") for s in SYMBOLS}
    bars["ETH/USD"] = tuple(replace(b, close=D(100)) for b in bars["ETH/USD"])
    assert target_weights(bars, decision_ms=200 * DAY_MS)["ETH/USD"] == 0


@pytest.mark.parametrize("fault", ["gap", "future", "nan", "missing", "stale"])
def test_bad_history_is_blocked_not_a_cash_signal(fault):
    bars = histories()
    series = list(bars["BTC/USD"])
    decision = 200 * DAY_MS
    if fault == "gap":
        series[1] = series[0]
    elif fault == "future":
        series[-1] = replace(series[-1], end_ms=201 * DAY_MS)
    elif fault == "nan":
        series[-1] = replace(series[-1], close=D("NaN"))
    elif fault == "missing":
        series.pop()
    else:
        decision += DAY_MS
    bars["BTC/USD"] = tuple(series)
    with pytest.raises(ValueError):
        target_weights(bars, decision_ms=decision)


def test_daily_composition_restart_and_changed_market_conflict(tmp_path):
    args = inputs()
    now = 200 * DAY_MS + 100_000
    args["decision_ms"] = now
    args["snapshot"] = replace(args["snapshot"], observed_ms=now - 100)
    args["quotes"] = {
        s: replace(q, source_ms=now - 500, received_ms=now - 400) for s, q in args["quotes"].items()
    }
    del args["targets"]
    args["account_binding"] = args.pop("expected_account_binding")
    args.update(journal_path=tmp_path / "daily.sqlite", histories=histories())
    first = reserve_daily_plan(**args)
    assert first["status"] == "NEW"
    assert first["submission_authorized"] is False
    assert reserve_daily_plan(**args)["status"] == "REPLAY_PENDING"
    args["quotes"]["BTC/USD"] = replace(args["quotes"]["BTC/USD"], bid=D(100), ask=D("100.1"))
    with pytest.raises(ValueError, match="conflicting"):
        reserve_daily_plan(**args)
