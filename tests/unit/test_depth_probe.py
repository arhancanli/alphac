from copy import deepcopy

import pytest

from alphaforge.validation.depth_probe import sweep_book


@pytest.fixture
def book():
    return {
        "recv_ns": 100,
        "event_ns": 90,
        "quality_ok": True,
        "action": "M",
        "market_open": True,
        "bids": [(99.0, 2), (98.0, 3)],
        "asks": [(101.0, 2), (102.0, 3)],
    }


def test_crosses_correct_side_and_preserves_partial(book):
    buy = sweep_book(book, as_of_ns=100, side="buy", quantity=6)
    sell = sweep_book(book, as_of_ns=100, side="sell", quantity=5)
    assert (buy["filled"], buy["unfilled"], buy["vwap_native"]) == (5, 1, 101.6)
    assert sell["vwap_native"] == 98.4
    assert buy["status"] == "PARTIAL_DEPTH_ONLY"
    assert not buy["execution_eligible"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"recv_ns": 101}, "timestamp_order"),
        ({"event_ns": 101}, "timestamp_order"),
        ({"event_ns": 0}, "stale_book"),
        ({"quality_ok": False}, "flagged_or_incomplete_event"),
        ({"action": "T"}, "non_book_update"),
        ({"action": "R"}, "non_book_update"),
        ({"market_open": False}, "market_not_confirmed_open"),
        ({"bids": [(101.0, 2)]}, "locked_or_crossed"),
        ({"asks": [(101.0, 2), (100.0, 2)]}, "unordered_depth"),
        ({"asks": [(101.0, 0), (102.0, 2)]}, "invalid_depth"),
        ({"asks": [(float("nan"), 1)]}, "invalid_depth"),
        ({"asks": [(101.0, 1.5)]}, "invalid_size"),
        ({"asks": []}, "empty_side"),
    ],
)
def test_unsafe_latest_book_blocks(book, change, reason):
    result = sweep_book(book | change, as_of_ns=100, side="buy", quantity=1, max_age_ns=20)
    assert result["reason"] == reason
    assert result["filled"] == 0 and result["unfilled"] == 1


def test_scenarios_do_not_mutate_input(book):
    before = deepcopy(book)
    sweep_book(book, as_of_ns=100, side="buy", quantity=1)
    assert book == before


@pytest.mark.parametrize("quantity", [True, 0, -1, 1.5])
def test_invalid_order_size(book, quantity):
    with pytest.raises(ValueError):
        sweep_book(book, as_of_ns=100, side="buy", quantity=quantity)


def test_missing_book():
    assert sweep_book(None, as_of_ns=100, side="buy", quantity=1)["reason"] == "missing_book"
