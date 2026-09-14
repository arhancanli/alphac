from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from fractions import Fraction

import pytest

from alphaforge.validation.treasury_trade_identity import (
    ExecutionKey,
    aggregate_instructions,
    duration_hedge,
    validate_settlement,
)

DURATIONS = {"bill_6m": D(".5"), "note_2y": D("2"), "note_10y": D("8")}
PRICES = {"bill_6m": D("98"), "note_2y": D("101.125"), "note_10y": D("103.5")}


def test_cash_and_duration_neutral_with_unequal_dirty_prices():
    h = duration_hedge(D("-1000000"), DURATIONS, PRICES)
    assert h["market_values"] == {"note_2y": -1000000, "bill_6m": 800000, "note_10y": 200000}
    assert sum(h["face_values"][k] * Fraction(PRICES[k]) / 100 for k in PRICES) == 0
    assert sum(h["market_values"][k] * Fraction(DURATIONS[k]) for k in PRICES) == 0
    reverse = duration_hedge(D("1000000"), DURATIONS, PRICES)
    assert all(reverse["face_values"][k] == -v for k, v in h["face_values"].items())


@pytest.mark.parametrize("target", [0.0, D("NaN"), D("Infinity"), D("0")])
def test_bad_target_refuses(target):
    with pytest.raises(ValueError):
        duration_hedge(target, DURATIONS, PRICES)


def test_nonbracketing_and_nonpositive_price_refuse():
    with pytest.raises(ValueError):
        duration_hedge(D("-1"), dict(DURATIONS, note_10y=D("1")), PRICES)
    with pytest.raises(ValueError):
        duration_hedge(D("-1"), DURATIONS, dict(PRICES, bill_6m=D("0")))


def key():
    return ExecutionKey(
        "912828UK4", date(2013, 2, 1), "regular", "venue", "paper", "USD", "funding-A"
    )


def test_same_identity_nets_and_preserves_events():
    k = key()
    r = aggregate_instructions([("pre", k, D("-100")), ("post", k, D("100"))])
    assert r[k]["net_face"] == 0
    assert r[k]["by_event"] == {"pre": -100, "post": 100}


@pytest.mark.parametrize(
    "change",
    [
        {"settlement_date": date(2013, 2, 4)},
        {"settlement_regime": "reopening"},
        {"venue": "other"},
        {"account": "other"},
        {"financing_id": "other"},
        {"cusip": "912828UP3"},
    ],
)
def test_different_identity_does_not_net(change):
    k = key()
    other = replace(k, **change)
    r = aggregate_instructions([("a", k, D("-100")), ("b", other, D("100"))])
    assert len(r) == 2
    assert r[k]["net_face"] == -100


def test_settlement_uses_supplied_holiday_calendar():
    fri = date(2020, 1, 17)
    tue = date(2020, 1, 21)
    issue = date(2020, 1, 15)
    validate_settlement(fri, tue, "regular", issue, issue, {fri, tue})
    with pytest.raises(ValueError):
        validate_settlement(fri, date(2020, 1, 20), "regular", issue, issue, {fri, tue})


def test_existing_cusip_reopening_is_distinct_from_original_wi():
    trade = date(2020, 1, 10)
    original = date(2015, 1, 15)
    tranche = date(2020, 1, 15)
    validate_settlement(trade, tranche, "reopening", original, tranche, {tranche})
    with pytest.raises(ValueError):
        validate_settlement(trade, tranche, "when_issued", original, tranche, {tranche})
    validate_settlement(trade, tranche, "when_issued", tranche, tranche, {tranche})


def test_future_security_cannot_settle_regular():
    with pytest.raises(ValueError):
        validate_settlement(
            date(2020, 1, 10),
            date(2020, 1, 13),
            "regular",
            date(2020, 1, 15),
            date(2020, 1, 15),
            {date(2020, 1, 13)},
        )
