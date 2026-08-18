"""The Broker abstraction and its order-book value types (execDesign.md §8.1).

This is the *real* execution interface, defined from day one so the paper and
live brokers are structurally interchangeable: the live loop holds a
:class:`Broker` and never knows whether fills are simulated
(:class:`~alphaforge.execution.paper.PaperBroker`) or real
(:class:`~alphaforge.execution.ccxt_broker.CCXTBroker`, a NotArmed stub in v1).

Synchronous on purpose
----------------------
Every method is **synchronous**. The mid-frequency live loop has a full hour of
wall-clock budget per cycle (buildabilityCritique.md §1: confine async out of
v1); a blocking submit/poll inside that budget is simpler to reason about,
crash-recover, and test than an event loop. The CCXT live broker (Phase 8+)
will wrap ccxt's sync client or bridge async internally behind this same sync
surface, so call sites never change.

Idempotency contract (the crash-recovery backbone, execDesign.md §8.3)
----------------------------------------------------------------------
``submit`` is keyed by ``OrderRequest.client_order_id`` (deterministic per
``(cycle_ts, instrument)``). Submitting a *known* id MUST return the prior
:class:`BrokerAck` verbatim and MUST NOT create a second fill. A crash between
submit and persistence therefore cannot double-order: on restart the loop
re-submits the same intent and the broker recognizes it.

Order book
----------
:meth:`Broker.order_book` returns a :class:`OrderBook` snapshot whose
``bids`` are price-descending and ``asks`` price-ascending ladders of
``(price, size)`` levels. The paper broker WALKS this real snapshot to price
fills (leakageCritique.md finding 8) rather than asking the cost model, so
modeled-vs-realized slippage is a genuine signal, not a tautology.

All timestamps are :data:`~alphaforge.core.time.Ms` (epoch ms, UTC). All
prices/sizes/amounts are float64 in quote/base units respectively.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from alphaforge.core.time import Ms
from alphaforge.core.types import AccountState, Fill, OrderRequest, OrderStatus, Position, Side

__all__ = [
    "Broker",
    "BrokerAck",
    "OpenOrder",
    "OrderBook",
]


def _require_positive_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` unless ``value`` is finite and strictly positive."""
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _require_nonnegative_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` unless ``value`` is finite and >= 0."""
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and >= 0, got {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerAck:
    """A broker's acknowledgement of a submitted order.

    ``accepted`` is True when the broker took the order (it may then be
    immediately filled, working, or queued); False when it was rejected
    outright (``reason`` explains why and no fill exists). ``broker_order_id``
    is the venue's own id (the paper broker mints a deterministic one); it is
    ``None`` only for a rejection. ``client_order_id`` echoes the submitted
    idempotency key so the caller can correlate without re-deriving it.
    """

    accepted: bool
    client_order_id: str
    broker_order_id: str | None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.accepted and self.broker_order_id is None:
            raise ValueError("BrokerAck: accepted=True requires a broker_order_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenOrder:
    """A working order as the broker currently sees it.

    ``filled_qty`` is unsigned base units already executed (0 .. ``qty``);
    ``status`` is the lifecycle position. The paper broker fills market orders
    synchronously inside :meth:`Broker.submit`, so it never reports anything
    here as still working; the type exists so the live broker (and partial-fill
    code paths) flow through the same surface.
    """

    client_order_id: str
    broker_order_id: str
    instrument_id: str
    side: Side
    qty: float
    filled_qty: float
    status: OrderStatus

    def __post_init__(self) -> None:
        _require_positive_finite("OpenOrder.qty", self.qty)
        _require_nonnegative_finite("OpenOrder.filled_qty", self.filled_qty)
        if self.filled_qty > self.qty:
            raise ValueError(
                f"OpenOrder.filled_qty ({self.filled_qty}) cannot exceed qty ({self.qty})"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderBook:
    """A point-in-time L2 order-book snapshot.

    ``bids`` are ``(price, size)`` levels in **descending** price order (best
    bid first); ``asks`` in **ascending** price order (best ask first). ``size``
    is unsigned base-asset quantity available at that price level. ``ts`` is the
    snapshot timestamp (:data:`Ms`). Frozen and validated: ladder ordering,
    crossed-book detection, and positivity are checked at construction so a
    malformed snapshot fails loud at the source rather than poisoning a fill.
    """

    instrument_id: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    ts: Ms

    def __post_init__(self) -> None:
        self._validate_ladder("bids", self.bids, descending=True)
        self._validate_ladder("asks", self.asks, descending=False)
        if self.bids and self.asks and self.bids[0][0] >= self.asks[0][0]:
            raise ValueError(
                f"OrderBook {self.instrument_id!r}: crossed book, best bid "
                f"{self.bids[0][0]!r} >= best ask {self.asks[0][0]!r}"
            )

    @staticmethod
    def _validate_ladder(
        name: str, levels: tuple[tuple[float, float], ...], *, descending: bool
    ) -> None:
        """Validate one side: positive finite (price, size) and monotone price order."""
        prev: float | None = None
        for price, size in levels:
            _require_positive_finite(f"OrderBook.{name} price", price)
            _require_positive_finite(f"OrderBook.{name} size", size)
            if prev is not None:
                out_of_order = price >= prev if descending else price <= prev
                if out_of_order:
                    direction = "descending" if descending else "ascending"
                    raise ValueError(
                        f"OrderBook.{name} prices must be strictly {direction}, "
                        f"got {prev!r} then {price!r}"
                    )
            prev = price

    def side_for(self, side: Side) -> tuple[tuple[float, float], ...]:
        """Return the ladder a taker on ``side`` consumes: BUY lifts asks, SELL hits bids."""
        return self.asks if side is Side.BUY else self.bids


class Broker(ABC):
    """Synchronous broker interface — the contract the live loop programs against.

    Implementations: :class:`~alphaforge.execution.paper.PaperBroker` (simulated
    fills by walking a real book) and
    :class:`~alphaforge.execution.ccxt_broker.CCXTBroker` (real money, a NotArmed
    stub in v1). Read-only queries (:meth:`open_orders`, :meth:`positions`,
    :meth:`account`, :meth:`order_book`) are always safe to call; only
    :meth:`submit`/:meth:`cancel` mutate.
    """

    @abstractmethod
    def submit(self, order: OrderRequest) -> BrokerAck:
        """Submit ``order``; idempotent on ``order.client_order_id``.

        Re-submitting a known ``client_order_id`` returns the prior
        :class:`BrokerAck` verbatim and creates NO additional fill. A fresh id
        is acted on (paper: filled synchronously by walking the book; live:
        sent to the venue). Returns an ack with ``accepted=False`` on rejection
        rather than raising for ordinary business rejections; programming
        errors (unknown instrument, malformed request) still raise.
        """

    @abstractmethod
    def cancel(self, client_order_id: str) -> bool:
        """Cancel the working order with ``client_order_id``.

        Returns True if a working order was found and canceled, False if there
        was nothing to cancel (unknown id, or already terminal — both are
        no-ops, never errors, so cancel is safe to call defensively).
        """

    @abstractmethod
    def fetch_order(self, client_order_id: str) -> Fill | None:
        """Query the broker for executed quantity of ``client_order_id``.

        MUST be queryable by ``client_order_id`` (execDesign.md §8.1): the
        crash-recovery path (Phase-8 gate C5) calls this for every intent that
        the store recorded as SUBMITTED but never confirmed FILLED. If the venue
        actually executed all or part of the order during the submit→persist
        crash window, this returns the realized aggregate :class:`Fill` so recovery can ingest it
        idempotently; ``None`` means the broker has no execution for that id (the
        submit never landed, or the order is still working). For
        :class:`~alphaforge.execution.paper.PaperBroker` every fill is already in
        its serialized state, so this returns ``None`` (nothing to re-discover);
        :class:`~alphaforge.execution.ccxt_broker.CCXTBroker` raises
        ``NotArmedError`` until a venue adapter lands.
        """

    @abstractmethod
    def open_orders(self) -> list[OpenOrder]:
        """Return all currently working (non-terminal) orders."""

    @abstractmethod
    def positions(self) -> list[Position]:
        """Return the broker's view of open positions (signed qty). Broker is truth."""

    @abstractmethod
    def account(self) -> AccountState:
        """Return the broker's account snapshot (equity, cash, positions, ts)."""

    @abstractmethod
    def order_book(self, instrument_id: str, *, depth: int = 50) -> OrderBook:
        """Return an L2 order-book snapshot for ``instrument_id`` up to ``depth`` levels."""
