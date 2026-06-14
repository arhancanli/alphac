"""Execution layer (execDesign.md §8): the Broker interface and its brokers.

PAPER ONLY in v1. The live loop holds a :class:`Broker` and is agnostic to
whether fills are simulated or real::

    Broker (ABC, sync)
      |- PaperBroker  -- simulated fills by WALKING a real order-book snapshot
      |                  (leakageCritique.md finding 8: never priced by the cost
      |                  model; the model is a slippage CROSS-CHECK only)
      `- CCXTBroker   -- real money, a NotArmed STUB; every order-mutating call
                         raises NotArmedError (arming is a deliberate Phase-8+
                         step, never reachable by accident)

Order books are supplied to :class:`PaperBroker` through an
:class:`OrderBookSource` -- :class:`CCXTOrderBookSource` live,
:class:`FakeOrderBookSource` for offline deterministic tests. The paper account
serializes to a plain :class:`PaperState` so a crashed live process resumes the
identical book.

All timestamps are :data:`~alphaforge.core.time.Ms` (epoch ms, UTC); all money
is float64 quote units. Nothing here imports network at module load.
"""

from alphaforge.execution.broker import Broker, BrokerAck, OpenOrder, OrderBook
from alphaforge.execution.ccxt_broker import ARM_ENV_VAR, CCXTBroker
from alphaforge.execution.paper import (
    CCXTOrderBookSource,
    FakeOrderBookSource,
    OrderBookSource,
    PaperBroker,
    PaperFillAudit,
    PaperPosition,
    PaperState,
    WalkedFill,
    walk_book,
)

__all__ = [
    "ARM_ENV_VAR",
    "Broker",
    "BrokerAck",
    "CCXTBroker",
    "CCXTOrderBookSource",
    "FakeOrderBookSource",
    "OpenOrder",
    "OrderBook",
    "OrderBookSource",
    "PaperBroker",
    "PaperFillAudit",
    "PaperPosition",
    "PaperState",
    "WalkedFill",
    "walk_book",
]
