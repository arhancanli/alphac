"""Repeated account reads for spot settlement; REST reads are not atomic snapshots."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from alphaforge.execution.spot_activities import PAIRS
from alphaforge.execution.spot_paper import PaperReader, account_digest, number, validate_account
from alphaforge.execution.spot_settlement import Balance


@dataclass(frozen=True)
class AccountObservation:
    balance: Balance
    available_positions: dict[str, Decimal]
    non_marginable_buying_power: Decimal


def parse_account(account: dict, positions: list, *, expected_binding: str) -> AccountObservation:
    binding = account_digest(account)
    if binding != expected_binding:
        raise ValueError("account binding mismatch")
    validate_account(account, require_funding=False)
    if not isinstance(positions, list) or len(positions) > 2:
        raise ValueError("unexpected dedicated-account positions")
    quantities, available = {}, {}
    for position in positions:
        if not isinstance(position, dict):
            raise ValueError("invalid position record")
        symbol = PAIRS.get(position.get("symbol"))
        if (
            symbol is None
            or symbol in quantities
            or position.get("asset_class") != "crypto"
            or position.get("side") != "long"
        ):
            raise ValueError("foreign, duplicate, or non-long spot position")
        quantity = number(position.get("qty"))
        free = number(position.get("qty_available"))
        if free > quantity:
            raise ValueError("available quantity exceeds total")
        quantities[symbol], available[symbol] = quantity, free
    return AccountObservation(
        Balance(binding, number(account.get("cash")), quantities),
        available,
        number(account.get("non_marginable_buying_power")),
    )


async def observe_quiescent_account(
    reader: PaperReader, *, expected_binding: str
) -> AccountObservation:
    """Require two equal cash/position/power observations and no open orders.

    Mark-to-market equity is deliberately not compared: changing prices do not
    indicate a fill. Repeated agreement is evidence of quiescence, not a broker
    transaction lock or proof that no late fee can arrive. Settlement must also
    explain these balances with complete fill and fee activities.
    """

    async def observe():
        account = await reader.get("/v2/account")
        positions = await reader.get("/v2/positions")
        orders = await reader.get("/v2/orders", params={"status": "open", "limit": 500})
        if not isinstance(orders, list) or orders:
            raise ValueError("open orders or invalid order list prevent quiescent read")
        return parse_account(account, positions, expected_binding=expected_binding)

    async with asyncio.timeout(20):
        first = await observe()
        second = await observe()
    if first != second:
        raise ValueError("cash, position, availability or buying power changed during observation")
    return second
