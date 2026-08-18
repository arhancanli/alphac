"""Offline contract tests for Alpaca order-to-fill recovery."""

from __future__ import annotations

from typing import Any

import pytest

from alphaforge.core.types import Liquidity, Side
from alphaforge.execution.alpaca_broker import AlpacaBroker


class StubAlpacaBroker(AlpacaBroker):
    """No-network adapter exposing one canned order response."""

    def __init__(self, raw: dict[str, Any] | None) -> None:
        self.raw = raw

    def _raw_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        assert client_order_id == "cycle-SPY"
        return self.raw


def raw_order(
    *,
    status: str,
    filled_qty: str,
    filled_avg_price: str | None,
    filled_at: str | None = None,
    updated_at: str = "2026-08-17T13:30:05Z",
) -> dict[str, Any]:
    return {
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "filled_at": filled_at,
        "updated_at": updated_at,
        "symbol": "SPY",
        "side": "buy",
    }


@pytest.mark.parametrize("status", ["partially_filled", "canceled"])
def test_fetch_order_recovers_partial_execution(status: str) -> None:
    broker = StubAlpacaBroker(
        raw_order(status=status, filled_qty="2.5", filled_avg_price="641.25")
    )

    fill = broker.fetch_order("cycle-SPY")

    assert fill is not None
    assert fill.instrument_id == "XUSE:CASH:SPYUSD"
    assert fill.side is Side.BUY
    assert fill.qty == 2.5
    assert fill.price == 641.25
    assert fill.fee_quote == 0.0
    assert fill.liquidity is Liquidity.TAKER
    assert fill.ts == 1_786_973_405_000


def test_fetch_order_prefers_filled_timestamp_for_complete_fill() -> None:
    broker = StubAlpacaBroker(
        raw_order(
            status="filled",
            filled_qty="3",
            filled_avg_price="640",
            filled_at="2026-08-17T13:30:01Z",
        )
    )

    fill = broker.fetch_order("cycle-SPY")

    assert fill is not None
    assert fill.qty == 3.0
    assert fill.ts == 1_786_973_401_000


@pytest.mark.parametrize(
    "raw",
    [
        None,
        raw_order(status="new", filled_qty="0", filled_avg_price=None),
        raw_order(status="partially_filled", filled_qty="2", filled_avg_price=None),
    ],
)
def test_fetch_order_returns_none_without_valid_execution(raw: dict[str, Any] | None) -> None:
    assert StubAlpacaBroker(raw).fetch_order("cycle-SPY") is None
