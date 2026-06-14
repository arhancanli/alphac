"""Durable, idempotent order submission layer (execDesign.md section 8.3).

:class:`OrderManager` is the only component that submits orders to the broker. It
sits between the live loop and the :class:`~alphaforge.execution.broker.Broker`
(``PaperBroker`` in v1) and provides the three guarantees that make the 24/7
paper loop crash-safe (execDesign.md sections 8.3, 9.3):

1. **Persist-before-submit.** Every order's intent is written to the
   :class:`OrderStore` with status NEW *before* the broker is contacted. A crash
   between persist and submit therefore leaves a recoverable NEW row, never a
   silent gap; the next reconcile (reconcile.py) resolves it against broker
   truth. A crash between submit and the ack-persist is recovered the same way:
   the deterministic ``client_order_id`` lets the broker be re-queried.

2. **Idempotent replay.** ``client_order_id`` is supplied by the loop and is a
   stable function of ``(cycle_ts, instrument)`` (execDesign.md section 8.3). If a
   replay (post-crash) calls :meth:`OrderManager.place` for a cycle whose intent
   is already TERMINAL (FILLED / REJECTED / CANCELED) in the store, the
   resubmission is SKIPPED. This is the crash-recovery guarantee: replaying a
   cycle never double-submits. The broker is itself idempotent on
   ``client_order_id`` (a re-submit returns the prior ack and books no second
   fill), so even the narrow window where the store says non-terminal but the
   broker already filled cannot double-order.

3. **Transport-only retry.** ``broker.submit`` is wrapped in transient retry
   (network blips, 5xx, rate limits) reusing the SAME ``client_order_id`` on
   every attempt -- broker idempotency keyed on that id makes a retry safe even
   if the original landed (execDesign.md section 8.3: "always fetch the order
   first ... it may have landed"). A *definitive* reject is signalled by the
   broker returning a :class:`~alphaforge.execution.broker.BrokerAck` with
   ``accepted=False`` (NOT by raising); it is recorded REJECTED and never
   retried, then the next order is attempted.

Fills (the real surface, leakageCritique.md finding 8)
------------------------------------------------------
The :class:`~alphaforge.execution.broker.Broker` ABC's ``submit`` returns only a
:class:`~alphaforge.execution.broker.BrokerAck` (accepted / rejected); it does
NOT itemize fills. ``PaperBroker`` books the fill *inside* ``submit`` by WALKING a
real order-book snapshot and exposes the executions on its ``fills`` property
(and the walked-vs-modeled slippage cross-check on ``audits``). OrderManager
reads the fills (and audits) booked by *this* submit -- the tail appended since
the call began -- and persists each via ``store.mark_filled`` with the walked-book
provenance attached. That keeps modeled-vs-realized slippage a genuine signal
rather than a tautology (finding 8).

Partial fills: the filled quantity is recorded; an unfilled remainder is *not*
chased in v1. The mid-frequency design lets the next hourly cycle re-evaluate the
residual as a fresh delta (execDesign.md section 8.3).

This module owns only the submission contract. The :class:`SubmitBroker` and
:class:`OrderStore` Protocols below are the minimal slices :class:`OrderManager`
needs; ``alphaforge.execution.paper.PaperBroker`` and
``alphaforge.live.store.TradingStore`` satisfy them structurally (no edits to
those modules). The Protocols are synchronous: the live loop owns the single
scheduler (leakageCritique.md finding 15) and has a full hour of budget, so the
broker/store seams here are plain blocking calls -- simpler to reason about and
to test offline with injected fakes. All timestamps are epoch-ms UTC.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from alphaforge.core.logging import get_logger
from alphaforge.core.time import Ms, now_ms
from alphaforge.core.types import (
    Fill,
    OrderRequest,
    OrderStatus,
)
from alphaforge.execution.broker import BrokerAck
from alphaforge.live.store import FillAudit, OrderRecord

__all__ = [
    "FillAuditLike",
    "OrderManager",
    "OrderStore",
    "PlacementReport",
    "SubmitBroker",
    "TransientBrokerError",
]

_log = get_logger("alphaforge.execution.order_manager")

type Sleeper = Callable[[float], None]
"""A blocking sleep of a non-negative number of seconds (``time.sleep`` in prod)."""

type _Submit = Callable[[], BrokerAck]
"""A zero-arg call that performs one broker submit and returns its ack."""

#: Order statuses from which no further submission is meaningful. Reaching any of
#: these for a ``client_order_id`` makes a replayed :meth:`OrderManager.place`
#: skip resubmission (the crash-recovery idempotency guarantee).
_TERMINAL: frozenset[str] = frozenset(
    {OrderStatus.FILLED.value, OrderStatus.REJECTED.value, OrderStatus.CANCELED.value}
)

# Default transport-retry schedule (execDesign.md section 8.3: 1s/2s/4s, max 3).
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE_S = 1.0


class TransientBrokerError(Exception):
    """A retryable transport failure from the broker (network blip, 5xx, 429).

    Distinct from a definitive reject, which a broker signals by returning a
    :class:`~alphaforge.execution.broker.BrokerAck` with ``accepted=False`` (NOT
    by raising). Only this exception type is retried; any other raised exception
    propagates immediately -- retrying a permanent failure only hides it (mirrors
    the ``transient_retry`` policy in ``alphaforge.data.ingest.retry``).
    """


@runtime_checkable
class FillAuditLike(Protocol):
    """The walked-book slippage provenance a fill may carry (leakageCritique #8).

    Structurally satisfied by
    :class:`~alphaforge.execution.paper.PaperFillAudit` (what ``PaperBroker``
    produces) and by :class:`~alphaforge.live.store.FillAudit` (what the store
    persists). OrderManager reads these four fields off the broker's audit and
    forwards them so the modeled-vs-realized comparison survives into the lake.
    """

    @property
    def walked_price(self) -> float:
        """The realized order-book-walk fill price."""
        ...

    @property
    def modeled_price(self) -> float:
        """What the cost model would have charged for the same notional."""
        ...

    @property
    def slippage_bps(self) -> float:
        """Signed adverse difference walked-vs-modeled, in basis points."""
        ...

    @property
    def book_exhausted(self) -> bool:
        """True iff the book ran out of depth before the order filled."""
        ...


@runtime_checkable
class SubmitBroker(Protocol):
    """The minimal broker slice :class:`OrderManager` submits against.

    Mirrors :class:`~alphaforge.execution.broker.Broker` (execDesign.md section
    8.1; ``PaperBroker`` in v1). ``submit`` MUST honour idempotency on
    ``client_order_id``: re-submitting the same id returns the prior
    :class:`~alphaforge.execution.broker.BrokerAck` and books NO second fill --
    that is what makes transport retry safe. Transport failures are raised as
    :class:`TransientBrokerError`; definitive rejects are returned as a
    ``BrokerAck`` with ``accepted=False``.

    ``fills`` / ``audits`` expose the executions the broker has booked so far in
    chronological order (``PaperBroker`` appends one per accepted ``submit``);
    OrderManager reads the tail appended by the submit it just issued.
    """

    def submit(self, order: OrderRequest) -> BrokerAck:
        """Submit ``order``; idempotent on ``order.client_order_id``."""
        ...

    @property
    def fills(self) -> Sequence[Fill]:
        """All fills booked so far (chronological)."""
        ...

    @property
    def audits(self) -> Sequence[FillAuditLike]:
        """All walked-book slippage audits, parallel to :attr:`fills`."""
        ...


@runtime_checkable
class OrderStore(Protocol):
    """The persistence slice :class:`OrderManager` needs (execDesign.md section 9.1).

    Satisfied by :class:`alphaforge.live.store.TradingStore` against
    ``trading.sqlite`` (WAL); the store is the source of truth for order intent
    and lifecycle. Each method is a single typed accessor that raises on storage
    failure (the loop treats that as a cycle FAILED). The slice is deliberately
    minimal: OrderManager records intent, submission, fills (with walked-book
    audit), and rejection, and reads back the resolved status.
    """

    def record_intent(self, req: OrderRequest, cycle_ts: Ms, *, now: Ms) -> None:
        """Persist ``req`` with status NEW BEFORE it is submitted; idempotent on the id."""
        ...

    def mark_submitted(self, client_order_id: str, *, now: Ms) -> None:
        """Transition an intent NEW -> SUBMITTED after the broker accepts it."""
        ...

    def mark_filled(self, fill: Fill, *, now: Ms, audit: FillAudit | None = None) -> None:
        """Persist one ``fill`` (with optional walked-book ``audit``) and advance status."""
        ...

    def mark_rejected(self, client_order_id: str, *, now: Ms) -> None:
        """Transition an intent to terminal REJECTED."""
        ...

    def get(self, client_order_id: str) -> OrderRecord | None:
        """Return the stored view of an order, or ``None`` if never recorded."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class PlacementReport:
    """Outcome of one :meth:`OrderManager.place` batch (execDesign.md section 8.3).

    ``cycle_ts`` keys the batch. ``filled`` / ``partial`` / ``submitted`` /
    ``rejected`` count orders by their resolved status after this call
    (``submitted`` is accepted-but-zero-fill -- e.g. an empty-book reject would be
    ``rejected``, an accepted order with no fill at all is rare in paper mode but
    counted ``submitted``). ``skipped_replay`` counts intents already terminal in
    the store and so NOT resubmitted (the crash-recovery idempotency path).
    ``acks`` carries each fresh broker response in input order (a skipped-replay
    order has no fresh ack). ``states`` is the final store view of every order
    touched, keyed by ``client_order_id`` -- the loop persists positions/equity
    from the broker, but inspects these for the per-cycle trade summary.
    """

    cycle_ts: Ms
    filled: int
    partial: int
    submitted: int
    rejected: int
    skipped_replay: int
    acks: tuple[BrokerAck, ...] = ()
    states: dict[str, OrderRecord] = field(default_factory=dict)

    @property
    def n_attempted(self) -> int:
        """Number of orders for which the broker was actually contacted."""
        return self.filled + self.partial + self.submitted + self.rejected


class OrderManager:
    """Durable, idempotent submission layer (execDesign.md section 8.3).

    Construct with a :class:`SubmitBroker` (the ``PaperBroker`` in v1) and an
    :class:`OrderStore` (the ``TradingStore``). The single public entry point is
    :meth:`place`. All timestamps are epoch-ms UTC; the wall clock is read once
    per call via :func:`~alphaforge.core.time.now_ms` (tests inject a frozen
    ``now`` for determinism).

    Transport retry reuses ``alphaforge.data.ingest.retry.transient_retry`` when
    importable (the codebase's single retry policy); otherwise a small local
    exponential backoff with the same semantics is used so this module has no
    hard dependency on the ingest package. Either way only
    :class:`TransientBrokerError` is retried and the ``client_order_id`` is held
    constant across attempts.
    """

    def __init__(
        self,
        broker: SubmitBroker,
        store: OrderStore,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S,
        sleeper: Sleeper | None = None,
    ) -> None:
        """Wire the manager to a broker and store.

        ``max_attempts`` (>= 1) bounds transport retries per order;
        ``backoff_base_s`` (> 0) is the exponential base used by the local
        fallback backoff. ``sleeper`` (default :func:`time.sleep`) is injected in
        tests so retry backoff is instant and deterministic.

        Raises ``ValueError`` for ``max_attempts < 1`` or ``backoff_base_s <= 0``.
        """
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
        if backoff_base_s <= 0.0:
            raise ValueError(f"backoff_base_s must be > 0, got {backoff_base_s}")
        self._broker = broker
        self._store = store
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._sleeper: Sleeper = time.sleep if sleeper is None else sleeper

    def place(
        self, orders: Sequence[OrderRequest], *, cycle_ts: Ms, now: Ms | None = None
    ) -> PlacementReport:
        """Persist, submit, and record every order in ``orders`` for ``cycle_ts``.

        For each order, in input order:

        1. If the store already holds a TERMINAL state for the order's
           ``client_order_id``, SKIP it (idempotent replay; counted in
           ``skipped_replay``) -- the post-crash double-submit guard.
        2. PERSIST the intent (status NEW) via ``store.record_intent`` BEFORE
           contacting the broker. If this raises, the exception propagates (the
           loop fails the cycle); nothing was submitted.
        3. SUBMIT to the broker with transport retry (transient errors only,
           same ``client_order_id`` each attempt). A definitive reject comes back
           as a ``BrokerAck`` with ``accepted=False`` and is NOT retried.
        4. PERSIST the result: ``mark_rejected`` for a reject; else
           ``mark_submitted`` then ``mark_filled`` for each fill the broker booked
           for this order (with its walked-book audit attached). Final status is
           read back from the store.

        Orders are independent: a reject or persisted fill on one does not abort
        the batch. A *raised* (non-transient, or retry-exhausted) exception from
        the broker DOES propagate, after the intent row for the failing order is
        already durable (step 2) so recovery can resolve it.

        ``now`` overrides the wall clock for deterministic tests. Idempotency
        requires the loop to supply a deterministic ``client_order_id`` per
        ``(cycle_ts, instrument)`` (execDesign.md section 8.3); this method trusts
        and dedups on it. Returns a :class:`PlacementReport`.
        """
        ts: Ms = now_ms() if now is None else now
        filled = 0
        partial = 0
        submitted = 0
        rejected = 0
        skipped = 0
        acks: list[BrokerAck] = []
        states: dict[str, OrderRecord] = {}

        for order in orders:
            coid = order.client_order_id
            existing = self._store.get(coid)
            if existing is not None and existing.status in _TERMINAL:
                skipped += 1
                states[coid] = existing
                _log.info(
                    "order_manager.skip_replay",
                    client_order_id=coid,
                    cycle_ts=cycle_ts,
                    status=existing.status,
                )
                continue

            # (2) Persist intent FIRST -- crash-safe: a NEW row always precedes any
            #     broker contact, so recovery can never miss an order we tried.
            self._store.record_intent(order, cycle_ts, now=ts)

            # (3) Submit with transport-only retry (same coid every attempt).
            #     Snapshot the broker's booked-fill count first so we attribute
            #     only the fills THIS submit produced.
            fills_before = len(self._broker.fills)
            ack = self._submit_with_retry(order)
            acks.append(ack)

            # (4) Persist the resolved state.
            if not ack.accepted:
                self._store.mark_rejected(coid, now=ts)
                rejected += 1
                _log.warning(
                    "order_manager.rejected",
                    client_order_id=coid,
                    cycle_ts=cycle_ts,
                    instrument_id=order.instrument_id,
                    reason=ack.reason,
                )
            else:
                self._store.mark_submitted(coid, now=ts)
                self._persist_fills(order, fills_before, now=ts)
                bucket = self._classify(coid, order)
                if bucket is OrderStatus.FILLED:
                    filled += 1
                elif bucket is OrderStatus.PARTIAL:
                    partial += 1
                    self._log_partial(order, coid, cycle_ts)
                else:
                    submitted += 1

            resolved = self._store.get(coid)
            if resolved is not None:
                states[coid] = resolved

        return PlacementReport(
            cycle_ts=cycle_ts,
            filled=filled,
            partial=partial,
            submitted=submitted,
            rejected=rejected,
            skipped_replay=skipped,
            acks=tuple(acks),
            states=states,
        )

    def _persist_fills(self, order: OrderRequest, fills_before: int, *, now: Ms) -> None:
        """Persist every fill the broker booked for ``order`` during this submit.

        The fills appended after ``fills_before`` belong to this submit (the
        broker appends in submit order). Only fills whose ``client_order_id``
        matches ``order`` are recorded (defensive against an interleaving the
        single-threaded loop never actually produces). The parallel walked-book
        audit (``broker.audits``) is attached per fill so the modeled-vs-realized
        slippage cross-check (leakageCritique.md finding 8) is persisted.
        """
        fills = self._broker.fills
        audits = self._broker.audits
        for idx in range(fills_before, len(fills)):
            fill = fills[idx]
            if fill.client_order_id != order.client_order_id:
                continue
            audit = self._audit_for(audits, idx)
            self._store.mark_filled(fill, now=now, audit=audit)

    @staticmethod
    def _audit_for(audits: Sequence[FillAuditLike], idx: int) -> FillAudit | None:
        """Adapt the broker's parallel walked-book audit at ``idx`` to a store ``FillAudit``.

        ``PaperBroker`` keeps ``audits`` index-aligned with ``fills``. If the
        broker carries no audit at that index (a non-paper or fill-only source),
        return ``None`` -- the fill is still persisted, just without provenance.
        """
        if idx >= len(audits):
            return None
        a = audits[idx]
        return FillAudit(
            walked_price=a.walked_price,
            modeled_price=a.modeled_price,
            slippage_bps=a.slippage_bps,
            book_exhausted=a.book_exhausted,
        )

    def _classify(self, coid: str, order: OrderRequest) -> OrderStatus:
        """Read the store-resolved lifecycle bucket for ``coid`` after persisting fills.

        Returns FILLED / PARTIAL when the store advanced the order on fills, else
        SUBMITTED (accepted but nothing filled -- rare in paper mode). The store
        is the authority on the fill-vs-partial boundary (it owns the lot
        epsilon), so we trust its status rather than re-deriving from qty.
        """
        record = self._store.get(coid)
        if record is None:  # pragma: no cover - store just wrote this row
            return OrderStatus.SUBMITTED
        try:
            status = OrderStatus(record.status)
        except ValueError:  # pragma: no cover - store only writes valid statuses
            return OrderStatus.SUBMITTED
        if status in (OrderStatus.FILLED, OrderStatus.PARTIAL):
            return status
        del order
        return OrderStatus.SUBMITTED

    def _log_partial(self, order: OrderRequest, coid: str, cycle_ts: Ms) -> None:
        """Log a partial fill (residual is NOT chased in v1; next cycle re-evaluates)."""
        record = self._store.get(coid)
        filled_qty = 0.0 if record is None else record.filled_qty
        _log.info(
            "order_manager.partial_fill",
            client_order_id=coid,
            cycle_ts=cycle_ts,
            requested_qty=order.qty,
            filled_qty=filled_qty,
            residual_qty=order.qty - filled_qty,
        )

    def _submit_with_retry(self, order: OrderRequest) -> BrokerAck:
        """Submit ``order`` retrying only :class:`TransientBrokerError`.

        Uses ``transient_retry`` (the codebase's single policy) when importable,
        else a local exponential backoff (base ``backoff_base_s``, ``max_attempts``
        tries). The ``client_order_id`` is fixed across attempts, so a retry after
        a transient error that nonetheless landed is deduped by broker
        idempotency. On exhaustion the original :class:`TransientBrokerError`
        propagates (the loop fails the cycle).
        """
        retryer = _build_retryer(self._max_attempts, self._backoff_base_s, self._sleeper)
        return retryer(lambda: self._broker.submit(order))


# ---------------------------------------------------------------------------
# Retry plumbing
# ---------------------------------------------------------------------------


def _build_retryer(
    max_attempts: int, backoff_base_s: float, sleeper: Sleeper
) -> Callable[[_Submit], BrokerAck]:
    """Return a callable that runs a zero-arg submit under transport retry.

    Prefers ``alphaforge.data.ingest.retry.transient_retry`` (tenacity-backed,
    full-jitter exponential, ``reraise=True``) so the whole codebase shares one
    retry policy. If that import fails (ingest package absent), falls back to a
    deterministic local exponential backoff with identical semantics: retry only
    on :class:`TransientBrokerError`, ``max_attempts`` total tries, re-raise the
    original exception on exhaustion. ``sleeper`` is used by the fallback only
    (tenacity sleeps internally); tests inject a no-op for instant retries.
    """
    try:
        from alphaforge.data.ingest.retry import transient_retry
    except ImportError:
        return _local_retryer(max_attempts, backoff_base_s, sleeper)

    retrying = transient_retry(
        (TransientBrokerError,),
        max_attempts=max_attempts,
        base_s=backoff_base_s,
        max_s=max(backoff_base_s, 60.0),
    )

    def _run(submit: _Submit) -> BrokerAck:
        # tenacity's Retrying is callable: it invokes the target and applies the
        # policy. The lambda captures the bound broker.submit(order).
        return retrying(submit)

    return _run


def _local_retryer(
    max_attempts: int, backoff_base_s: float, sleeper: Sleeper
) -> Callable[[_Submit], BrokerAck]:
    """Build the dependency-free fallback retry runner (see :func:`_build_retryer`)."""

    def _run(submit: _Submit) -> BrokerAck:
        last: TransientBrokerError | None = None
        for attempt in range(max_attempts):
            try:
                return submit()
            except TransientBrokerError as exc:
                last = exc
                if attempt + 1 >= max_attempts:
                    break
                sleep_s = backoff_base_s * (2.0**attempt)
                _log.warning(
                    "order_manager.retry_backoff",
                    attempt=attempt + 1,
                    sleep_s=round(sleep_s, 3),
                    error=repr(exc),
                )
                sleeper(sleep_s)
        assert last is not None  # loop ran >= 1 time and only breaks after a raise
        raise last

    return _run
