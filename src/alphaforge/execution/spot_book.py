"""Normalize full REST book snapshots; never apply incremental stream updates here."""

from dataclasses import dataclass
from decimal import Decimal

from alphaforge.execution.spot_plan import Quote
from alphaforge.portfolio.spot_restart import SYMBOLS
from alphaforge.validation.spot_dataset import utc_ns


@dataclass(frozen=True)
class SpotBook:
    quote: Quote
    bid_size: Decimal
    ask_size: Decimal
    source_ns: int
    received_ns: int


def _positive(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError("book numbers must retain decimal precision")
    number = Decimal(value)
    if not number.is_finite() or number <= 0:
        raise ValueError("invalid book level")
    return number


def parse_rest_books(payload: dict, *, received_ns: int) -> dict[str, SpotBook]:
    """Use only full `/latest/orderbooks` responses decoded with parse_float=Decimal.

    Original nanoseconds are retained, with conservative source flooring and
    receipt ceiling for the millisecond planner. Parsing does not certify account
    routing, source authenticity, clock calibration, or current trading readiness.
    """
    if type(received_ns) is not int or received_ns < 0:
        raise ValueError("invalid local receipt")
    books = payload.get("orderbooks")
    if not isinstance(books, dict) or set(books) != set(SYMBOLS):
        raise ValueError("exact strategy book universe required")
    result = {}
    for symbol in SYMBOLS:
        book = books[symbol]
        if not isinstance(book, dict) or "r" in book or "T" in book:
            raise ValueError("full REST book required, not a stream update")
        source_ns = utc_ns(book["t"])
        if source_ns > received_ns:
            raise ValueError("future book source; verify clocks")
        sides = {}
        for key, descending in (("b", True), ("a", False)):
            rows = book.get(key)
            if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
                raise ValueError("empty or oversized book side")
            levels = [(_positive(row["p"]), _positive(row["s"])) for row in rows]
            prices = [price for price, _ in levels]
            if len(set(prices)) != len(prices):
                raise ValueError("duplicate book level")
            if prices != sorted(prices, reverse=descending):
                raise ValueError("unordered full book")
            sides[key] = levels[0]
        bid, bid_size = sides["b"]
        ask, ask_size = sides["a"]
        if bid > ask:
            raise ValueError("crossed full book")
        result[symbol] = SpotBook(
            Quote(bid, ask, source_ns // 1_000_000, (received_ns + 999_999) // 1_000_000),
            bid_size,
            ask_size,
            source_ns,
            received_ns,
        )
    return result
