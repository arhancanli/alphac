"""PaperBroker: simulated fills by WALKING a real order-book snapshot (§8.2).

PAPER MONEY ONLY. This broker is the production execution path with *simulated*
fills: it flows through the exact :class:`~alphaforge.execution.broker.Broker`
interface the live loop uses, maintains its own cash/positions/equity (the paper
account), and persists that account to a serializable :class:`PaperState` so a
restart resumes the identical book.

The fill rule (leakageCritique.md finding 8 — non-negotiable)
-------------------------------------------------------------
A market order is filled by **walking the order-book ladder** supplied by an
:class:`OrderBookSource`: consume levels (best price first) until ``qty`` is
filled; the fill price is the size-weighted average of the consumed levels. If
the book is too thin to fill the requested qty, fill only what the book
supports, mark the fill **partial**, and flag ``book_exhausted`` -- never invent
liquidity. The taker commission is charged via the shared
:class:`~alphaforge.costs.TransactionCostModel`.

Crucially, the cost model is used here ONLY as a CROSS-CHECK: for every fill we
also compute ``cost_model.fill_price(...)`` and record ``walked_price``,
``modeled_price`` and ``slippage_bps`` on a :class:`PaperFillAudit` row. That
makes modeled-vs-realized slippage a *genuine* validation signal in paper mode
rather than a tautology (filling by the model and then comparing to the model
would show perfect agreement -- the exact circularity finding 8 calls out).

Idempotency (execDesign.md §8.3)
--------------------------------
``submit`` dedupes on ``client_order_id``: a re-submit returns the prior
:class:`~alphaforge.execution.broker.BrokerAck` and produces no second fill, so
crash-replay of a cycle never double-fills the paper account.

Accounting
----------
Linear quote-settled contracts, mirroring
:class:`~alphaforge.backtest.ledger.Ledger`: a buy spends ``qty*price`` cash plus
fee; a sell receives it; reducing fills realize ``qty_closed*(price-avg)*sign``;
flips realize the whole old side then reopen at the fill price.
``equity = cash + Sigma qty_i * mark_i`` where the mark is the book mid (no
position closes are needed to compute it). All money is float64 quote units; all
timestamps are :data:`~alphaforge.core.time.Ms` (epoch ms, UTC). Deterministic
and offline: inject a :class:`FakeOrderBookSource` in tests.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from alphaforge.core.time import Ms
from alphaforge.core.types import (
    AccountState,
    Fill,
    Liquidity,
    OrderRequest,
    OrderType,
    Position,
    Side,
)
from alphaforge.execution.broker import Broker, BrokerAck, OpenOrder, OrderBook

if TYPE_CHECKING:
    from alphaforge.core.instruments import Instrument
    from alphaforge.costs import TransactionCostModel

__all__ = [
    "CCXTOrderBookSource",
    "FakeOrderBookSource",
    "OrderBookSource",
    "PaperBroker",
    "PaperFillAudit",
    "PaperPosition",
    "PaperState",
    "WalkedFill",
]

_BPS_PER_UNIT: float = 1e4
_DEFAULT_BOOK_DEPTH: int = 50
#: live order-book fetch resilience: a transient timeout/blip on the fill's book
#: snapshot is retried this many times (the client also carries a hard per-request
#: timeout) before the error propagates, so one slow venue read never stalls a cycle.
_BOOK_FETCH_ATTEMPTS: int = 3
_BOOK_FETCH_BACKOFF_S: float = 0.5


def _require_positive_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` unless ``value`` is finite and strictly positive."""
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")


def _require_finite(name: str, value: float) -> None:
    """Raise ``ValueError`` unless ``value`` is a finite float (fail loud on NaN/inf)."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


# --------------------------------------------------------------------------- book


@runtime_checkable
class OrderBookSource(Protocol):
    """Supplies an L2 order-book snapshot for an instrument as of a timestamp.

    Implementations: :class:`CCXTOrderBookSource` (live, ``fetch_order_book``)
    and :class:`FakeOrderBookSource` (canned ladders for offline tests). The
    snapshot's ``bids`` must be price-descending and ``asks`` price-ascending
    (the :class:`OrderBook` constructor enforces this).
    """

    def snapshot(self, instrument_id: str, *, ts: Ms) -> OrderBook:
        """Return the order book for ``instrument_id`` as of ``ts``."""
        ...


@dataclass(slots=True)
class FakeOrderBookSource:
    """A canned :class:`OrderBookSource` for deterministic offline tests.

    Holds a per-instrument :class:`OrderBook`; :meth:`snapshot` returns it with
    its ``ts`` replaced by the requested ``ts`` (so callers may reuse one ladder
    across cycles). Unknown instruments raise ``KeyError`` -- a test that walks a
    book it never registered is a test bug, surfaced loudly.
    """

    books: dict[str, OrderBook] = field(default_factory=dict)

    def set_book(self, book: OrderBook) -> None:
        """Register (or replace) the canned book for ``book.instrument_id``."""
        self.books[book.instrument_id] = book

    def snapshot(self, instrument_id: str, *, ts: Ms) -> OrderBook:
        """Return the canned book for ``instrument_id`` stamped at ``ts``."""
        book = self.books.get(instrument_id)
        if book is None:
            raise KeyError(f"FakeOrderBookSource has no book for {instrument_id!r}")
        return replace(book, ts=ts)


class CCXTOrderBookSource:
    """Live :class:`OrderBookSource` backed by a ccxt client's ``fetch_order_book``.

    The ccxt client is injected (never constructed here, never imports network in
    tests). ``symbol_for`` maps a canonical ``instrument_id`` to the ccxt unified
    symbol; if omitted, the third colon-segment is used as a fallback. Levels
    arrive as ``[price, size]`` pairs which are coerced to floats and handed to
    :class:`OrderBook` (whose constructor validates ladder ordering). Truncated
    to ``depth`` levels per side. This class performs network I/O and is never
    exercised by the offline test suite (use :class:`FakeOrderBookSource`).
    """

    def __init__(
        self,
        client: object,
        *,
        symbol_for: Mapping[str, str] | None = None,
    ) -> None:
        self._client = client
        self._symbol_for: dict[str, str] = dict(symbol_for or {})

    def snapshot(self, instrument_id: str, *, ts: Ms) -> OrderBook:
        """Fetch and adapt a live order book, with a bounded retry. A transient
        timeout/network blip on the fill's book fetch is retried (the client also
        carries a hard per-request timeout) rather than stalling or failing the
        cycle; after the attempts the error propagates to the loop's backstop."""
        symbol = self._symbol_for.get(instrument_id, instrument_id.split(":")[-1])
        fetch = self._client.fetch_order_book  # type: ignore[attr-defined]
        last: Exception | None = None
        for attempt in range(_BOOK_FETCH_ATTEMPTS):
            try:
                raw = fetch(symbol, _DEFAULT_BOOK_DEPTH)
                bids = tuple((float(p), float(s)) for p, s in raw["bids"][:_DEFAULT_BOOK_DEPTH])
                asks = tuple((float(p), float(s)) for p, s in raw["asks"][:_DEFAULT_BOOK_DEPTH])
                return OrderBook(instrument_id=instrument_id, bids=bids, asks=asks, ts=ts)
            except Exception as exc:
                last = exc
                if attempt + 1 < _BOOK_FETCH_ATTEMPTS:
                    time.sleep(_BOOK_FETCH_BACKOFF_S * (attempt + 1))
        raise last if last is not None else RuntimeError("order-book fetch failed after retries")


# --------------------------------------------------------------------------- fills


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkedFill:
    """The result of walking an order book for one market order.

    ``filled_qty`` is unsigned base units actually consumed (0 .. requested);
    ``avg_price`` is the size-weighted average of the consumed levels (0.0 iff
    nothing filled); ``book_exhausted`` is True when the ladder ran out before
    the requested qty was reached (``filled_qty`` then < requested and the fill
    is a partial). ``levels_consumed`` is how many price levels were touched.
    """

    filled_qty: float
    avg_price: float
    requested_qty: float
    book_exhausted: bool
    levels_consumed: int

    @property
    def is_partial(self) -> bool:
        """True when fewer base units filled than requested (book ran dry)."""
        return self.filled_qty < self.requested_qty


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperFillAudit:
    """One slippage-validation audit row, the genuine signal in paper mode (finding 8).

    ``walked_price`` is the realized book-walk fill price; ``modeled_price`` is
    what :meth:`TransactionCostModel.fill_price` would have charged for the same
    notional at the book mid; ``slippage_bps`` is their signed difference in the
    *adverse* direction expressed in basis points of the modeled price -- positive
    means the realized walk was worse (more adverse) than the model predicted.
    Persisted by the live store so a weekly report compares realized vs modeled
    slippage per trade.
    """

    client_order_id: str
    instrument_id: str
    side: Side
    filled_qty: float
    walked_price: float
    modeled_price: float
    mid_price: float
    slippage_bps: float
    fee_quote: float
    book_exhausted: bool
    ts: Ms


def walk_book(book: OrderBook, side: Side, qty: float) -> WalkedFill:
    """Walk ``book`` on ``side`` for ``qty`` base units; return the size-weighted fill.

    A taker BUY lifts the asks (cheapest first); a taker SELL hits the bids
    (highest first). Levels are consumed in book order until ``qty`` is met or
    the ladder is exhausted. The fill price is
    ``Sigma(level_price * level_qty) / filled_qty``. No level price/size is
    invented: if the book is thinner than ``qty`` the fill is partial and
    ``book_exhausted`` is set.

    Raises:
        ValueError: if ``qty`` is not finite and > 0.
    """
    _require_positive_finite("walk_book: qty", qty)
    levels = book.side_for(side)
    remaining = qty
    notional = 0.0
    filled = 0.0
    consumed = 0
    for price, size in levels:
        if remaining <= 0.0:
            break
        take = size if size < remaining else remaining
        notional += take * price
        filled += take
        remaining -= take
        consumed += 1
    book_exhausted = remaining > 0.0
    avg_price = (notional / filled) if filled > 0.0 else 0.0
    return WalkedFill(
        filled_qty=filled,
        avg_price=avg_price,
        requested_qty=qty,
        book_exhausted=book_exhausted,
        levels_consumed=consumed,
    )


# --------------------------------------------------------------------------- state


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperPosition:
    """A serializable signed position in the paper account (mirrors :class:`Position`)."""

    instrument_id: str
    qty: float
    avg_entry_price: float
    opened_ts: Ms

    def to_position(self) -> Position:
        """Adapt to the shared :class:`~alphaforge.core.types.Position` value type."""
        return Position(
            instrument_id=self.instrument_id,
            qty=self.qty,
            avg_entry_price=self.avg_entry_price,
            opened_ts=self.opened_ts,
        )


@dataclass(slots=True, kw_only=True)
class PaperState:
    """The full serializable paper-account snapshot the live store persists.

    Restoring a :class:`PaperBroker` from a ``PaperState`` reproduces the exact
    book: cash, every open position, the realized-fill ledger keyed by
    ``client_order_id`` (for idempotent re-submit), and the slippage audit trail.
    It is a plain dataclass (no behaviour) so the live store can serialize it
    field-by-field to SQLite without this module knowing the schema.
    """

    initial_cash: float
    cash: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    acks: dict[str, BrokerAck] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    audits: list[PaperFillAudit] = field(default_factory=list)

    def copy(self) -> PaperState:
        """Return a deep-enough copy so a restored broker cannot alias the original.

        The contained value objects are all frozen (immutable), so copying the
        containers is sufficient for full isolation.
        """
        return PaperState(
            initial_cash=self.initial_cash,
            cash=self.cash,
            positions=dict(self.positions),
            acks=dict(self.acks),
            fills=list(self.fills),
            audits=list(self.audits),
        )


# --------------------------------------------------------------------------- broker


class PaperBroker(Broker):
    """A paper-money broker that fills by walking a real order-book snapshot.

    Args:
        instruments: ``instrument_id`` -> :class:`Instrument` for every tradable
            instrument; fee routing and (future) lot rules come from here. Orders
            for unknown ids are rejected programming-error style (``KeyError``).
        cost_model: the shared :class:`TransactionCostModel`, used ONLY as a
            slippage cross-check (never as the fill -- finding 8).
        book_source: supplies the L2 snapshot each fill walks.
        initial_cash: starting paper cash in quote units (> 0); ignored when
            ``state`` is given.
        state: an existing :class:`PaperState` to resume from (crash recovery);
            when ``None`` a fresh account is opened with ``initial_cash``.

    The broker is deterministic given the same book snapshots and order stream.
    """

    def __init__(
        self,
        instruments: Mapping[str, Instrument],
        cost_model: TransactionCostModel,
        *,
        book_source: OrderBookSource,
        initial_cash: float = 100_000.0,
        state: PaperState | None = None,
    ) -> None:
        self._instruments: dict[str, Instrument] = dict(instruments)
        self._cost_model = cost_model
        self._book_source = book_source
        if state is None:
            _require_positive_finite("PaperBroker.initial_cash", initial_cash)
            self._state = PaperState(initial_cash=initial_cash, cash=initial_cash)
        else:
            self._state = state.copy()

    # ------------------------------------------------------------------ accessors

    @property
    def state(self) -> PaperState:
        """The live :class:`PaperState` (mutated in place as orders fill).

        Returned by reference so the live store can serialize it after each
        cycle; call :meth:`snapshot_state` for an isolated copy.
        """
        return self._state

    def snapshot_state(self) -> PaperState:
        """Return an isolated copy of the paper account (safe to persist/inspect)."""
        return self._state.copy()

    @property
    def cash(self) -> float:
        """Free paper cash in quote units."""
        return self._state.cash

    @property
    def fills(self) -> list[Fill]:
        """All paper fills booked so far (chronological)."""
        return list(self._state.fills)

    @property
    def audits(self) -> list[PaperFillAudit]:
        """All slippage-validation audit rows (one per executed fill)."""
        return list(self._state.audits)

    def apply_recorded_fill(self, fill: Fill) -> bool:
        """Book a STORE-recorded ``fill`` into the paper account; idempotent.

        Crash recovery (execDesign.md section 9.3 step 4): the live store persists
        each fill durably the instant it is booked, but the broker's serialized
        :class:`PaperState` blob is only snapshotted at cycle END. A process that
        dies mid-batch -- after some fills are durable but before the end-of-cycle
        snapshot -- therefore leaves the store's recorded fills AHEAD of the
        restored book. On restart the loop replays those just-recorded fills here
        so the broker book catches up to the store's truth before any reconcile or
        new decision.

        Idempotent on ``client_order_id``: a fill whose order is already in
        :attr:`PaperState.acks` (it was part of the restored blob) is a no-op and
        returns ``False``; a genuinely missing fill is applied (cash/position
        moved exactly as in :meth:`submit`, a matching ack synthesized) and
        returns ``True``. Re-running recovery is therefore safe -- the second pass
        finds every fill already acked.

        The fill is NOT re-walked: the store's recorded price/qty/fee ARE the
        realized execution (the book that produced them is long gone), so we
        replay them verbatim. No audit row is synthesized (the original
        walked-vs-modeled audit lives in the store); the in-memory audit trail
        stays aligned with the live blob, not the recovered tail.

        Returns:
            True iff the fill was newly applied; False iff already booked.
        """
        if fill.client_order_id in self._state.acks:
            return False
        self._apply_fill(fill)
        self._state.fills.append(fill)
        self._state.acks[fill.client_order_id] = BrokerAck(
            accepted=True,
            client_order_id=fill.client_order_id,
            broker_order_id=f"paper-{fill.client_order_id}",
            reason="recovered: replayed from store-recorded fill",
        )
        return True

    # ------------------------------------------------------------------ Broker API

    def submit(self, order: OrderRequest) -> BrokerAck:
        """Fill a MARKET order by walking the book; idempotent on client_order_id.

        Re-submitting a known ``client_order_id`` returns the stored ack and
        books no second fill. A fresh order is: routed to its instrument (unknown
        -> ``KeyError``); rejected with ``accepted=False`` if the book is
        completely empty on the relevant side (no liquidity at all); otherwise
        filled (fully or partially) by :func:`walk_book`. The realized fill, the
        cost-model cross-check audit row, the position/cash update and the ack
        are all recorded before returning.

        Only ``OrderType.MARKET`` is supported in v1; a LIMIT order raises
        ``NotImplementedError`` (the live loop emits market orders only).

        Raises:
            KeyError: ``order.instrument_id`` is not in this broker's universe.
            NotImplementedError: a non-market order type.
        """
        prior = self._state.acks.get(order.client_order_id)
        if prior is not None:
            return prior

        inst = self._instruments.get(order.instrument_id)
        if inst is None:
            raise KeyError(
                f"PaperBroker has no instrument {order.instrument_id!r}; "
                "the tradable universe is fixed at construction"
            )
        if order.order_type is not OrderType.MARKET:
            raise NotImplementedError(
                f"PaperBroker fills MARKET orders only in v1, got {order.order_type!r}"
            )

        book = self._book_source.snapshot(order.instrument_id, ts=order.decision_ts)
        ladder = book.side_for(order.side)
        if not ladder:
            ack = BrokerAck(
                accepted=False,
                client_order_id=order.client_order_id,
                broker_order_id=None,
                reason="book_empty: no liquidity on the order side",
            )
            self._state.acks[order.client_order_id] = ack
            return ack

        walked = walk_book(book, order.side, order.qty)
        if walked.filled_qty <= 0.0:
            ack = BrokerAck(
                accepted=False,
                client_order_id=order.client_order_id,
                broker_order_id=None,
                reason="book_exhausted: zero fillable qty at top of book",
            )
            self._state.acks[order.client_order_id] = ack
            return ack

        # C10a: record the idempotency ACK BEFORE booking the fill. The ack is the
        # dedup key: a re-submit of a known coid returns this ack and books no
        # second fill. If the ack were written AFTER _book_fill, a crash in the
        # window between booking the fill and recording the ack would, on replay,
        # find the coid absent from acks, re-walk the book, and DOUBLE-FILL. The
        # ack carries no fill-dependent data beyond walked.is_partial (already
        # known here), so it is safe to mint first. The fill, the audit row, and
        # the cash/position update then follow; replaying after a crash in THAT
        # window is healed by _replay_recorded_fills (durable store fill) +
        # apply_recorded_fill, never by re-walking.
        broker_order_id = f"paper-{order.client_order_id}"
        ack = BrokerAck(
            accepted=True,
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            reason="partial: book exhausted" if walked.is_partial else "",
        )
        self._state.acks[order.client_order_id] = ack
        self._book_fill(order, inst, book, walked)
        return ack

    def cancel(self, client_order_id: str) -> bool:
        """No-op: paper market orders fill synchronously, so nothing is ever working.

        Always returns False (there is no working order to cancel). The method
        exists to satisfy the :class:`Broker` contract and stay call-compatible
        with the live broker.
        """
        del client_order_id
        return False

    def fetch_order(self, client_order_id: str) -> Fill | None:
        """Always ``None``: a paper fill is never lost behind the broker (C5).

        The crash-recovery ``fetch_order`` call (execDesign.md §8.1, gate C5)
        exists to re-discover a fill the VENUE executed during the submit→persist
        crash window. ``PaperBroker`` has no such window: every fill it books is
        already in its serialized :class:`PaperState` blob and is replayed by
        :meth:`apply_recorded_fill` on restore, so there is never an execution
        the store does not already know about. Returning ``None`` makes the
        recovery call a safe, idempotent no-op for paper while keeping the
        :class:`Broker` surface uniform with the live broker.
        """
        del client_order_id
        return None

    def open_orders(self) -> list[OpenOrder]:
        """Empty: every paper market order reaches a terminal state inside :meth:`submit`."""
        return []

    def positions(self) -> list[Position]:
        """Open paper positions (signed qty), sorted by instrument id."""
        return [self._state.positions[iid].to_position() for iid in sorted(self._state.positions)]

    def account(self) -> AccountState:
        """Account snapshot marked at the current book mids.

        ``equity = cash + Sigma qty_i * mid_i`` for each open position, where
        ``mid_i`` is the book mid from a fresh snapshot at ``ts``. ``ts`` defaults
        to the latest booked fill timestamp (0 when no fills yet). Use
        :meth:`account_at` to mark as of a specific time.
        """
        ts = self._state.fills[-1].ts if self._state.fills else 0
        return self.account_at(ts)

    def account_at(self, ts: Ms) -> AccountState:
        """Account snapshot marked at book mids as of ``ts`` (explicit mark time).

        Each open position is marked at the mid of a book snapshot pulled at
        ``ts``; missing-book instruments fall back to ``avg_entry_price`` (a
        flat, conservative mark when no live book exists -- never silently zero).
        """
        equity = self._state.cash
        positions: list[Position] = []
        for iid in sorted(self._state.positions):
            pos = self._state.positions[iid]
            mid = self._mid_or_entry(iid, pos, ts)
            equity += pos.qty * mid
            positions.append(pos.to_position())
        _require_finite("PaperBroker.account equity", equity)
        return AccountState(
            equity_quote=equity,
            cash_quote=self._state.cash,
            positions=tuple(positions),
            ts=ts,
        )

    def order_book(self, instrument_id: str, *, depth: int = _DEFAULT_BOOK_DEPTH) -> OrderBook:
        """Proxy the configured :class:`OrderBookSource` snapshot for ``instrument_id``.

        ``depth`` is advisory: the underlying source decides how many levels it
        returns. The snapshot is stamped at ``ts=0`` here (the caller supplies a
        real ``ts`` when it walks via :meth:`submit`); this accessor is for
        inspection/validation, not pricing.
        """
        del depth
        return self._book_source.snapshot(instrument_id, ts=0)

    # ------------------------------------------------------------------ internals

    def _mid_or_entry(self, instrument_id: str, pos: PaperPosition, ts: Ms) -> float:
        """Mid price from a fresh book at ``ts``; fall back to avg_entry on absence."""
        try:
            book = self._book_source.snapshot(instrument_id, ts=ts)
        except KeyError:
            return pos.avg_entry_price
        return _book_mid(book, fallback=pos.avg_entry_price)

    def _book_fill(
        self,
        order: OrderRequest,
        inst: Instrument,
        book: OrderBook,
        walked: WalkedFill,
    ) -> None:
        """Record the walked fill: cash/position update, fee, audit cross-check."""
        price = walked.avg_price
        qty = walked.filled_qty
        fee_quote = self._cost_model.fee_frac(inst, Liquidity.TAKER) * qty * price
        _require_finite("PaperBroker fee_quote", fee_quote)

        fill = Fill(
            client_order_id=order.client_order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            qty=qty,
            price=price,
            fee_quote=fee_quote,
            liquidity=Liquidity.TAKER,
            ts=order.decision_ts,
        )
        self._apply_fill(fill)
        self._state.fills.append(fill)
        self._state.audits.append(self._build_audit(order, inst, book, walked, fee_quote))

    def _build_audit(
        self,
        order: OrderRequest,
        inst: Instrument,
        book: OrderBook,
        walked: WalkedFill,
        fee_quote: float,
    ) -> PaperFillAudit:
        """Compute the modeled-vs-walked slippage cross-check (the genuine signal)."""
        mid = _book_mid(book, fallback=walked.avg_price)
        notional = walked.filled_qty * mid
        modeled_price = self._modeled_price(order, inst, mid, notional)
        slippage_bps = self._slippage_bps(order.side, walked.avg_price, modeled_price)
        return PaperFillAudit(
            client_order_id=order.client_order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            filled_qty=walked.filled_qty,
            walked_price=walked.avg_price,
            modeled_price=modeled_price,
            mid_price=mid,
            slippage_bps=slippage_bps,
            fee_quote=fee_quote,
            book_exhausted=walked.book_exhausted,
            ts=order.decision_ts,
        )

    def _modeled_price(
        self,
        order: OrderRequest,
        inst: Instrument,
        mid: float,
        notional: float,
    ) -> float:
        """Cost-model fill price at the book mid, for cross-check only (never the fill).

        The impact term needs ADV and daily sigma, which the broker does not
        carry; without them the model degrades to spread+latency around the mid.
        We therefore call the model with a zero-impact configuration by using the
        instrument's spread/latency only, evaluated at the mid -- the comparison
        is meaningful because the *book walk* captures the real impact, while the
        model's static half-spread is exactly the assumption under test.
        """
        del notional  # impact intentionally excluded from the cross-check baseline
        slip = self._cost_model.half_spread_frac(inst) + self._cost_model.latency_frac(inst)
        return mid * (1.0 + float(order.side.sign) * slip)

    @staticmethod
    def _slippage_bps(side: Side, walked_price: float, modeled_price: float) -> float:
        """Adverse slippage of the walked fill vs the modeled price, in bps.

        Positive => the realized walk was MORE adverse than the model predicted
        (a buy filled higher, or a sell filled lower). Reference is the modeled
        price; sign is normalized so "worse than model" is always positive
        regardless of side.
        """
        if modeled_price <= 0.0:
            return 0.0
        raw = (walked_price - modeled_price) / modeled_price
        return float(side.sign) * raw * _BPS_PER_UNIT

    def _apply_fill(self, fill: Fill) -> None:
        """Update cash and the position for ``fill`` (linear-contract accounting).

        Cash always moves by ``-side.sign*qty*price - fee``. Position update
        mirrors :class:`~alphaforge.backtest.ledger.Ledger`: VWAP on same-side
        adds, realize on reduce/close, realize-then-reopen on a flip.
        """
        signed_qty = fill.side.sign * fill.qty
        new_cash = self._state.cash - signed_qty * fill.price - fill.fee_quote
        _require_finite(f"paper cash after fill {fill.client_order_id!r}", new_cash)

        pos = self._state.positions.get(fill.instrument_id)
        if pos is None or pos.qty * signed_qty > 0.0:
            old_qty = 0.0 if pos is None else pos.qty
            old_avg = 0.0 if pos is None else pos.avg_entry_price
            new_qty = old_qty + signed_qty
            new_avg = (abs(old_qty) * old_avg + abs(signed_qty) * fill.price) / abs(new_qty)
            self._state.positions[fill.instrument_id] = PaperPosition(
                instrument_id=fill.instrument_id,
                qty=new_qty,
                avg_entry_price=new_avg,
                opened_ts=fill.ts if pos is None else pos.opened_ts,
            )
        else:
            residual = pos.qty + signed_qty
            if abs(signed_qty) < abs(pos.qty):
                self._state.positions[fill.instrument_id] = PaperPosition(
                    instrument_id=fill.instrument_id,
                    qty=residual,
                    avg_entry_price=pos.avg_entry_price,
                    opened_ts=pos.opened_ts,
                )
            elif abs(signed_qty) == abs(pos.qty):
                del self._state.positions[fill.instrument_id]
            else:
                self._state.positions[fill.instrument_id] = PaperPosition(
                    instrument_id=fill.instrument_id,
                    qty=residual,
                    avg_entry_price=fill.price,
                    opened_ts=fill.ts,
                )
        self._state.cash = new_cash

    # ------------------------------------------------------------------ funding
    def apply_funding(
        self, instrument_id: str, ts_funding: Ms, rate: float, mark_price: float
    ) -> float:
        """Settle one funding event against the live position; return the cashflow.

        Added 2026-08-06, and it closes the largest correctness gap this system had.
        ``Ledger.apply_funding`` existed and was called from exactly ONE place: the BACKTEST
        engine. Nothing on the live path ever booked funding, so cash moved only on fills.
        For a *funding-carry* sleeve that is not a rounding error, it is the entire mechanism:
        ``artifacts/walkforward/crypto_carry_wk/summary.txt`` reports funding_net $19,500 of a
        $38,236 total return, so roughly HALF of everything the strategy ever earned was the
        one cashflow the live account could not receive. Its live Sharpe was capped near half
        its validated value (0.653 -> ~0.30 ex-funding).

        Sign convention is the ledger's, verbatim, because two conventions would be worse than
        none::

            payment = -position_qty * mark_price * rate

        ``qty > 0, rate > 0`` => payment < 0, longs pay shorts (Binance USDT-M).

        No position, no event: returns 0.0 and moves nothing, which is what makes this safe to
        call for every settlement in a window without first checking what is held.

        FORWARD-ONLY. This does not and must not restate history: the published curve stays as
        it was observed, the shortfall stays visible in the signed chain, and the correction
        applies from the day it ships. Callers own idempotency (settle each ts_funding once).
        """
        pos = self._state.positions.get(instrument_id)
        if pos is None or pos.qty == 0.0:
            return 0.0
        if not math.isfinite(rate):
            raise ValueError(f"funding rate must be finite for {instrument_id!r}, got {rate!r}")
        if not (math.isfinite(mark_price) and mark_price > 0.0):
            raise ValueError(
                f"funding mark must be finite and > 0 for {instrument_id!r}, got {mark_price!r}"
            )
        payment = -pos.qty * mark_price * rate
        new_cash = self._state.cash + payment
        _require_finite(f"paper cash after funding {instrument_id!r}@{ts_funding}", new_cash)
        self._state.cash = new_cash
        return payment


def _book_mid(book: OrderBook, *, fallback: float) -> float:
    """Mid of the best bid/ask; ``fallback`` when one side is empty (one-sided book)."""
    if book.bids and book.asks:
        return 0.5 * (book.bids[0][0] + book.asks[0][0])
    if book.asks:
        return book.asks[0][0]
    if book.bids:
        return book.bids[0][0]
    return fallback
