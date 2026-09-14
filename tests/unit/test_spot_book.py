from copy import deepcopy
from decimal import Decimal as D

import pytest

from alphaforge.execution.spot_book import parse_rest_books
from alphaforge.validation.spot_dataset import utc_ns


def payload():
    return {
        "orderbooks": {
            s: {
                "t": "2024-01-01T00:00:00.000000001Z",
                "b": [{"p": "100", "s": "2"}, {"p": "99", "s": "3"}],
                "a": [{"p": "101", "s": "4"}, {"p": "102", "s": "5"}],
            }
            for s in ("BTC/USD", "ETH/USD")
        }
    }


def test_snapshot_keeps_best_levels_sizes_and_conservative_timing():
    received = utc_ns("2024-01-01T00:00:00.500000001Z")
    book = parse_rest_books(payload(), received_ns=received)["BTC/USD"]
    assert book.quote.bid == D(100) and book.quote.ask == D(101)
    assert book.bid_size == D(2) and book.ask_size == D(4)
    assert book.quote.received_ms - book.quote.source_ms == 501
    assert book.received_ns - book.source_ns == 500_000_000


@pytest.mark.parametrize(
    "fault",
    [
        "crossed",
        "unordered",
        "duplicate",
        "zero_size",
        "empty",
        "stream",
        "float",
        "foreign",
        "future",
    ],
)
def test_invalid_or_ambiguous_books_block(fault):
    data = deepcopy(payload())
    book = data["orderbooks"]["ETH/USD"]
    received = utc_ns("2024-01-01T00:00:01Z")
    if fault == "crossed":
        book["b"][0]["p"] = "103"
    elif fault == "unordered":
        book["b"].reverse()
    elif fault == "duplicate":
        book["a"][1]["p"] = "101"
    elif fault == "zero_size":
        book["b"][0]["s"] = "0"
    elif fault == "empty":
        book["a"] = []
    elif fault == "stream":
        book["r"] = True
    elif fault == "float":
        book["b"][0]["p"] = 100.0
    elif fault == "foreign":
        data["orderbooks"]["SPY"] = book
    else:
        received = utc_ns("2024-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        parse_rest_books(data, received_ns=received)
