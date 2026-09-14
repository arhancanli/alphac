from dataclasses import replace
from decimal import Decimal as D

import pytest

from alphaforge.execution.spot_plan import Asset, Quote
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, DailyClose
from alphaforge.validation.spot_evaluation import EvaluationDay, evaluate


def day(index=200, price="100", *, rising=True):
    now = index * DAY_MS + 300_000
    return EvaluationDay(
        now,
        {
            s: tuple(
                DailyClose(i * DAY_MS, D(i if rising else 100))
                for i in range(index - 199, index + 1)
            )
            for s in SYMBOLS
        },
        {s: Asset(s, D("0.001"), D("0.001"), D("0.01")) for s in SYMBOLS},
        {s: Quote(D(price), D(price), now - 100, now - 50) for s in SYMBOLS},
        {s: D(1000) for s in SYMBOLS},
        {s: D(1000) for s in SYMBOLS},
    )


def test_flat_signal_stays_cash_without_fees():
    rows = evaluate((day(rising=False), day(201, rising=False)), initial_cash=D(1000))["rows"]
    assert all(r["equity"] == "1000" and r["fills"] == [] for r in rows)


def test_buy_fee_debits_base_and_cash_only_pays_gross_notional():
    row = evaluate((day(),), initial_cash=D(1000))["rows"][0]
    notional = sum(D(f["filled_qty"]) * D(f["price"]) for f in row["fills"])
    assert D(row["cash"]) == D(1000) - notional
    for fill in row["fills"]:
        assert fill["fee_asset"] == fill["symbol"].split("/")[0]
        assert D(row["holdings"][fill["symbol"]]) == D(fill["filled_qty"]) * D("0.9975")
    assert D(row["return"]) < 0


def test_future_mark_never_improves_previous_return():
    first = day()
    baseline = evaluate((first, day(201)), initial_cash=D(1000))
    rally = evaluate((first, day(201, "150")), initial_cash=D(1000))
    assert baseline["rows"][0] == rally["rows"][0]
    assert D(rally["rows"][1]["return"]) > 0
    assert D(rally["rows"][1]["equity"]) > D(baseline["rows"][1]["equity"])


def test_no_liquidity_means_no_fill_not_assumed_full_execution():
    frame = replace(day(), ask_sizes={s: D(0) for s in SYMBOLS})
    row = evaluate((frame,), initial_cash=D(1000))["rows"][0]
    assert row["fills"] == [] and D(row["equity"]) == 1000


def test_partial_liquidity_caps_and_rounds_fill():
    frame = replace(day(), ask_sizes={s: D("0.0105") for s in SYMBOLS})
    row = evaluate((frame,), initial_cash=D(1000))["rows"][0]
    assert all(D(f["filled_qty"]) == D("0.010") for f in row["fills"])


@pytest.mark.parametrize("fault", ["gap", "time_drift", "revised_close", "missing_quotes"])
def test_invalid_path_fails_without_partial_result(fault):
    second = day(201)
    if fault == "gap":
        second = day(202)
    elif fault == "time_drift":
        second = replace(second, decision_ms=second.decision_ms + 1)
    elif fault == "revised_close":
        bars = list(second.histories["BTC/USD"])
        bars[0] = replace(bars[0], close=D(999))
        second.histories["BTC/USD"] = tuple(bars)
    else:
        second.quotes.pop("BTC/USD")
    with pytest.raises(ValueError):
        evaluate((day(), second), initial_cash=D(1000))


def test_sell_fee_is_usd_and_quantity_cannot_go_short():
    # A one-day crash in the last close switches both signals off without
    # modifying any historical observation used at the previous decision.
    second = day(201, "10")
    for symbol in SYMBOLS:
        bars = list(second.histories[symbol])
        bars[-1] = replace(bars[-1], close=D(1))
        second.histories[symbol] = tuple(bars)
    result = evaluate((day(), second), initial_cash=D(1000))
    row = result["rows"][1]
    assert row["fills"] and all(f["side"] == "sell" for f in row["fills"])
    assert all(f["fee_asset"] == "USD" for f in row["fills"])
    assert all(D(q) >= 0 for q in row["holdings"].values())


def test_stale_trade_quote_preserves_held_loss_and_blocks_whole_rebalance():
    second = day(201, "50")
    second.quotes["BTC/USD"] = replace(
        second.quotes["BTC/USD"], source_ms=second.decision_ms - 2000
    )
    rows = evaluate((day(), second), initial_cash=D(1000))["rows"]
    assert rows[1]["fills"] == []
    assert rows[1]["holdings"] == rows[0]["holdings"]
    assert D(rows[1]["return"]) < 0
    assert rows[1]["blocked_rebalance_reasons"] == ["BTC/USD:stale_for_trade"]


def test_missing_valuation_cannot_be_hidden_by_blocked_trading():
    second = day(201)
    second.quotes["BTC/USD"] = replace(
        second.quotes["BTC/USD"], source_ms=second.decision_ms - 60_001
    )
    with pytest.raises(ValueError, match="valuation quote"):
        evaluate((day(), second), initial_cash=D(1000))
