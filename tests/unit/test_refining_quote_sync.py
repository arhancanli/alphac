from dataclasses import replace

import pytest

from alphaforge.validation.refining_quote_sync import (
    SCALE,
    Contract,
    Quote,
    QuoteTimeline,
    quote_indication,
    select_month,
)

T = 1_750_000_000_000_000_000


def contracts():
    return {
        root: Contract(
            root,
            root + "Q5",
            1,
            i,
            2025,
            8,
            T - 100,
            0,
            T + 100_000_000_000,
            "USD",
            "BBL" if root == "CL" else "GAL",
            1000 if root == "CL" else 42000,
            10_000_000 if root == "CL" else 100_000,
        )
        for i, root in enumerate(["CL", "RB", "HO"], 1)
    }


def quotes():
    prices = {
        "CL": (75 * SCALE, 75 * SCALE + 10_000_000),
        "RB": (2 * SCALE, 2 * SCALE + 100_000),
        "HO": (2_200_000_000, 2_200_100_000),
    }
    return {
        r: Quote(c.publisher_id, c.instrument_id, T, T - 100, 128, *prices[r], 6, 6)
        for r, c in contracts().items()
    }


def check(q, **kwargs):
    return quote_indication(
        contracts(), q, decision_ns=T, max_age_ns=1_000_000_000, max_skew_ns=250_000_000, **kwargs
    )


def test_full_maturity_and_different_expiries():
    cs = contracts()
    cs["RB"] = replace(cs["RB"], expiration_ns=T + 200_000_000_000)
    assert select_month(cs.values(), as_of_ns=T, expiry_buffer_ns=0) == cs
    bad = replace(cs["CL"], year=2015)
    bad.validate(as_of_ns=T, expiry_buffer_ns=0)  # short suffix alone cannot distinguish decades
    with pytest.raises(ValueError, match="No complete"):
        select_month([bad, cs["RB"], cs["HO"]], as_of_ns=T, expiry_buffer_ns=0)


@pytest.mark.parametrize(
    "change",
    [
        {"year": 2026},
        {"month": 9},
        {"size": 100},
        {"observed_ns": T + 1},
        {"expiration_ns": T},
        {"currency": "EUR"},
    ],
)
def test_invalid_definitions_rejected(change):
    with pytest.raises(ValueError):
        replace(contracts()["CL"], **change).validate(as_of_ns=T, expiry_buffer_ns=0)


def test_ambiguous_month_fails():
    cs = list(contracts().values())
    with pytest.raises(ValueError, match="Ambiguous"):
        select_month([*cs, replace(cs[0], instrument_id=99)], as_of_ns=T, expiry_buffer_ns=0)


def test_recipe_width_uses_executable_sides_and_dollar_multipliers():
    result = check(quotes())
    assert result["valid"]
    assert result["roundtrip_width_fixed_usd"] == 42_600_000_000
    assert result["displayed_two_way_recipes"] == 2


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"recv_ns": T + 1}, "invalid_clock"),
        ({"recv_ns": T - 2_000_000_000, "event_ns": T - 2_000_000_100}, "stale"),
        ({"flags": 0}, "feed_state"),
        ({"flags": 136}, "feed_state"),
        ({"flags": 132}, "feed_state"),
        ({"flags": 160}, "feed_state"),
        ({"bid_size": 0}, "invalid_book"),
        ({"bid_fixed": 80 * SCALE}, "invalid_book"),
        ({"bid_fixed": 75 * SCALE + 1}, "off_tick"),
        ({"bid_size": 2}, "insufficient_recipe_size"),
    ],
)
def test_bad_latest_quotes_refuse(change, reason):
    q = quotes()
    q["CL"] = replace(q["CL"], **change)
    result = check(q)
    assert not result["valid"]
    assert result["reason"].endswith(reason)


def test_cross_leg_skew_is_not_hidden_by_recent_each_leg():
    q = quotes()
    q["RB"] = replace(q["RB"], recv_ns=T - 300_000_000, event_ns=T - 300_000_100)
    assert check(q)["reason"] == "cross_leg_skew"


def test_negative_crude_keeps_absolute_width_valid():
    q = quotes()
    q["CL"] = replace(q["CL"], bid_fixed=-SCALE, ask_fixed=-990_000_000)
    assert check(q)["roundtrip_width_fixed_usd"] == 42_600_000_000


def test_latest_invalid_is_not_replaced_by_older_good_or_future():
    good = quotes()["CL"]
    bad = replace(good, recv_ns=T + 10, event_ns=T + 9, bid_size=0)
    future = replace(good, recv_ns=T + 20, event_ns=T + 19)
    timeline = QuoteTimeline([good, bad, future])
    assert timeline.at(T - 1) is None
    assert timeline.at(T + 15) == bad
    assert timeline.at(T + 20) == future
    assert QuoteTimeline([good, bad, replace(bad, ask_size=0)]).at(T + 10).ask_size == 0
    with pytest.raises(ValueError, match="Nonmonotonic"):
        QuoteTimeline([future, good])
