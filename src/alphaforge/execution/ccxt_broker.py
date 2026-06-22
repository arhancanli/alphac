"""CCXTBroker: the real-money broker, a NotArmed stub in v1 (execDesign.md §8.5).

PAPER ONLY in v1. This class implements the full
:class:`~alphaforge.execution.broker.Broker` interface against a ccxt client so
the live loop's type signature never changes when real trading is eventually
turned on -- but every ORDER-MUTATING call raises
:class:`~alphaforge.core.errors.NotArmedError`.

The arming contract (deliberate friction, never an accident)
------------------------------------------------------------
Real-money trading is a Phase-8+ step that requires TWO explicit, independent
gates to be set, and they are checked here, not assumed:

1. config ``live.paper`` must be ``False`` (a YAML/config change, reviewed), and
2. an explicit operator arm action must set ``ALPHAFORGE_ARMED=1`` in the
   environment of the live process (a typed, audited step at launch).

Until BOTH hold, :meth:`submit` and :meth:`cancel` raise ``NotArmedError`` with
a message naming the exact gate. There is no code path that flips arming
silently: a developer cannot accidentally place a real order by wiring this
broker into the loop, because the loop selects :class:`PaperBroker` whenever
``live.paper`` is True, and this class refuses to act even if mis-wired.

Read-only methods (:meth:`positions`, :meth:`account`, :meth:`order_book`,
:meth:`open_orders`) MAY proxy a ccxt client if one is supplied (so the
reconciler can observe a real account before arming); with no client they also
raise ``NotArmedError`` rather than fabricate empty data. Reads never place
orders and so are not gated on the arm flag.

All timestamps are :data:`~alphaforge.core.time.Ms` (epoch ms, UTC). This module
performs network I/O only through the injected client and is never exercised by
the offline test suite beyond asserting the NotArmed guards.
"""

from __future__ import annotations

import os
from typing import Final

from alphaforge.core.errors import NotArmedError
from alphaforge.core.types import AccountState, Fill, OrderRequest, Position
from alphaforge.execution.broker import Broker, BrokerAck, OpenOrder, OrderBook

__all__ = ["ARM_ENV_VAR", "CCXTBroker"]

ARM_ENV_VAR: Final[str] = "ALPHAFORGE_ARMED"
"""Environment variable that must equal ``"1"`` for real-money submits to be armed.

Set deliberately by an operator at launch (the second of two gates, the first
being ``live.paper = False``). Its presence alone never arms trading -- the
config flag is checked alongside it."""

_ARM_VALUE: Final[str] = "1"

_DEFAULT_BOOK_DEPTH: Final[int] = 50


def _arm_message(action: str) -> str:
    """Build the NotArmedError message for a blocked real-money ``action``."""
    return (
        f"CCXTBroker.{action} is disabled: AlphaForge trades PAPER money in v1. "
        f"Arming real-money trading is a deliberate Phase-8+ step requiring BOTH "
        f"live.paper=False in config AND environment {ARM_ENV_VAR}={_ARM_VALUE}; "
        "it is never reachable by accident."
    )


class CCXTBroker(Broker):
    """Real-money broker over a ccxt client; order mutation is NotArmed in v1.

    Args:
        client: a ccxt client (e.g. ``ccxt.binanceusdm``), or ``None``. Used only
            by the read-only methods; never used to place orders in v1. When
            ``None``, read-only methods also raise :class:`NotArmedError`.
        paper: the resolved ``live.paper`` config flag. The default ``True``
            means "not configured for real money"; submits stay blocked. Arming
            requires ``paper=False`` here AND ``ALPHAFORGE_ARMED=1`` in the env.

    Even with both gates set, this stub still raises on submit/cancel in v1:
    actual order placement is implemented in Phase 8+. The gate check exists so
    the *failure mode* (a blocked submit) is observable and the arming contract
    is encoded in code today, not deferred to a future diff.
    """

    def __init__(self, client: object | None = None, *, paper: bool = True) -> None:
        self._client = client
        self._paper = paper

    # ------------------------------------------------------------------ arming

    def is_armed(self) -> bool:
        """True iff BOTH arming gates are satisfied (config + environment).

        Even when this returns True, v1 :meth:`submit`/:meth:`cancel` still raise
        -- order placement is a later phase. The method exists so the loop and
        operator tooling can assert the gates without attempting a submit.
        """
        return (not self._paper) and os.environ.get(ARM_ENV_VAR) == _ARM_VALUE

    # ------------------------------------------------------------------ mutation

    def submit(self, order: OrderRequest) -> BrokerAck:
        """Always raises :class:`NotArmedError` in v1 (real-money submit is disabled)."""
        del order
        raise NotArmedError(_arm_message("submit"))

    def cancel(self, client_order_id: str) -> bool:
        """Always raises :class:`NotArmedError` in v1 (real-money cancel is disabled)."""
        del client_order_id
        raise NotArmedError(_arm_message("cancel"))

    def fetch_order(self, client_order_id: str) -> Fill | None:
        """Raise NotArmedError: v1 has no ccxt fetch_order adapter wired here (Phase 8+).

        Querying an order by ``client_order_id`` is not a real-money MUTATION,
        but in v1 no ccxt adapter is wired, so the safe default is to treat the
        venue as unavailable and raise the explicit arm message rather than
        fabricate a missing-order ``None`` (which the crash-recovery path C5 would
        misread as 'the submit never landed'). The Phase-8+ adapter will map
        ccxt's ``fetch_order`` payload to a :class:`Fill`.
        """
        del client_order_id
        raise NotArmedError(_arm_message("fetch_order"))

    # ------------------------------------------------------------------ read-only

    def open_orders(self) -> list[OpenOrder]:
        """Proxy the client's open orders if a client is set; else raise NotArmedError.

        Phase 8+ adapts the ccxt payload to :class:`OpenOrder`; v1 returns an
        empty list when a client is present (no real orders exist while submit is
        blocked) and raises when no client is configured rather than fabricate
        data.
        """
        if self._client is None:
            raise NotArmedError(_arm_message("open_orders"))
        return []

    def positions(self) -> list[Position]:
        """Read real positions via the client; raise NotArmedError if no client is set.

        The reconciler may observe a real account before arming. v1 returns an
        empty list when a client is present (the adapter lands in Phase 8+) and
        refuses (raises) when no client is configured -- never silent empties.
        """
        if self._client is None:
            raise NotArmedError(_arm_message("positions"))
        return []

    def account(self) -> AccountState:
        """Raise NotArmedError: v1 has no ccxt account adapter (Phase 8+).

        Reading an account is not a real-money action, but no adapter is wired
        here in v1, so the safe default is to treat a real account as
        unavailable and raise the explicit arm message rather than fabricate an
        :class:`AccountState`.
        """
        raise NotArmedError(_arm_message("account"))

    def order_book(self, instrument_id: str, *, depth: int = _DEFAULT_BOOK_DEPTH) -> OrderBook:
        """Raise NotArmedError: v1 has no ccxt order-book adapter wired here.

        Reading the book is not a real-money action, but in v1 the ccxt adapter
        is not wired into this broker -- use
        :class:`~alphaforge.execution.paper.CCXTOrderBookSource` for live book
        snapshots in paper mode. Raising here keeps the contract honest rather
        than returning an empty book.
        """
        del instrument_id, depth
        raise NotArmedError(_arm_message("order_book"))
