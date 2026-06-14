"""Broker/book reconciliation and crash-recovery resolution (execDesign.md 8.4, 9.3).

The broker is the single source of truth for what positions and cash actually
exist; the :class:`~alphaforge.execution.order_manager.OrderStore` is our internal
book of intent and recorded fills. They can drift -- a fill that landed during a
crash, an order left in flight before the process died, fee-model error, or (in
real money later) a manual trade. :class:`Reconciler` detects and classifies that
drift and decides whether trading may continue.

Run order (execDesign.md 9.2 stage 0, 9.3 step 2): reconcile BEFORE the first
decision of every cycle and on boot. Two responsibilities, in this order:

1. **Resolve in-flight orders.** Any store intent left non-terminal (NEW /
   SUBMITTED / PARTIAL) before a crash is checked against broker truth:

   - It is still in ``broker.open_orders()`` -> genuinely working; leave it (the
     next cycle's polling handles it). For ``PaperBroker`` this never happens --
     paper market orders fill synchronously inside ``submit`` -- but the live
     broker can rest orders, so the path exists.
   - The broker has fills for its ``client_order_id`` that the store has not yet
     recorded -> ingest them (``store.mark_filled``) so the book reflects fills
     that completed while we were down.
   - The broker neither holds it open nor has any new fill for it, AND the stored
     intent already carries ``filled_qty > 0`` -> it is a settled PARTIAL whose
     residual is deliberately not chased. Leave its PARTIAL status and
     ``filled_qty`` intact; the residual re-enters as a fresh delta next cycle. An
     order with ``filled_qty > 0`` is NEVER rewritten to REJECTED -- the broker
     truly holds that quantity, so a REJECTED row would be an audit lie.
   - The broker neither holds it open nor has any fill for it, AND ``filled_qty``
     is zero -> the submit never landed (a crash before/during submit). Mark it
     REJECTED; the residual delta re-enters cleanly as a fresh intent at the next
     cycle's optimization.

   This MUST happen first so the position comparison sees the post-recovery book.

2. **Compare positions + equity.** Per instrument, classify the broker-vs-book
   relationship as AGREE / DIVERGENT / ORPHAN / MISSING (see
   :class:`InstrumentRecon`). Within tolerance the cycle proceeds; beyond
   tolerance :class:`~alphaforge.core.errors.ReconciliationError` is raised and
   the loop halts trading and alerts (execDesign.md 8.4: a large divergence means
   something is deeply wrong -- missed fills, fee drift, or an unrecorded trade).

This module classifies and reports; it does NOT mutate positions. Adopting broker
truth into the live book is the loop's job, driven off the returned
:class:`ReconReport` (the loop owns all position state, keeping the reconciler a
pure, testable comparator). It DOES drive in-flight intents to terminal in the
store (idempotent writes) -- that is order-lifecycle bookkeeping, not position
mutation.

Startup recovery algorithm (execDesign.md 9.3), exactly as :class:`Reconciler`
participates in it:

    1. The loop opens trading.sqlite (WAL) and reads the kill-switch sentinel,
       restoring the PaperBroker from its last persisted state blob (PAPER only).
    2. ``Reconciler.resolve_in_flight()``: every non-terminal stored intent is
       resolved against ``broker.open_orders()`` and ``broker.fills``; broker
       fills are written through to the store; a settled PARTIAL (filled_qty > 0)
       is left intact; only an UNFILLED intent the broker never saw is marked
       REJECTED (safe to re-decide next cycle).
    3. ``Reconciler.reconcile()``: positions + equity are compared. AGREE /
       within tolerance -> proceed. Beyond tolerance -> ReconciliationError ->
       the loop halts + alerts and does NOT trade until an operator acks.
    4. Only after a clean reconcile does the loop take its first decision.

Because intents carry a deterministic per-(cycle, instrument) ``client_order_id``
and the broker is idempotent on it, re-querying after a crash never double-submits
and step 2 is fully idempotent. All timestamps are epoch-ms UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from alphaforge.core.errors import ReconciliationError
from alphaforge.core.logging import get_logger
from alphaforge.core.time import Ms
from alphaforge.core.types import (
    AccountState,
    Fill,
    OrderStatus,
    Position,
)
from alphaforge.live.store import FillAudit, OrderRecord

__all__ = [
    "BrokerView",
    "InflightResolution",
    "InstrumentRecon",
    "OpenOrderView",
    "ReconReport",
    "ReconStatus",
    "ReconStore",
    "ReconTolerance",
    "Reconciler",
]

_log = get_logger("alphaforge.execution.reconcile")

#: Stored statuses that mean an order may still be live and so must be resolved on
#: reconcile (everything not already terminal).
_NON_TERMINAL: frozenset[str] = frozenset(
    {OrderStatus.NEW.value, OrderStatus.SUBMITTED.value, OrderStatus.PARTIAL.value}
)


@runtime_checkable
class OpenOrderView(Protocol):
    """A working order as the broker currently sees it (the slice reconcile needs).

    Structurally satisfied by :class:`~alphaforge.execution.broker.OpenOrder`.
    ``client_order_id`` correlates with the store intent; the rest is for
    logging/audit only.
    """

    @property
    def client_order_id(self) -> str:
        """The idempotency key correlating this working order to a stored intent."""
        ...


@runtime_checkable
class BrokerView(Protocol):
    """The broker slice :class:`Reconciler` reads (execDesign.md section 8.1).

    Satisfied by :class:`~alphaforge.execution.broker.Broker` /
    ``PaperBroker``. The broker is authoritative for ``positions()`` and
    ``account()``; ``open_orders()`` lists still-working orders (always empty for
    ``PaperBroker``); ``fills`` is the chronological execution log used to ingest
    fills that landed while the process was down.
    """

    def positions(self) -> list[Position]:
        """Authoritative open positions (signed qty)."""
        ...

    def account(self) -> AccountState:
        """Authoritative account snapshot (equity, cash, positions, ts)."""
        ...

    def open_orders(self) -> Sequence[OpenOrderView]:
        """Still-working (non-terminal) orders the broker holds."""
        ...

    @property
    def fills(self) -> Sequence[Fill]:
        """All fills the broker has booked (chronological)."""
        ...


@runtime_checkable
class ReconStore(Protocol):
    """The persistence slice :class:`Reconciler` needs.

    Satisfied by :class:`alphaforge.live.store.TradingStore`. ``open_intents``
    feeds in-flight resolution; ``mark_filled`` / ``mark_rejected`` drive intents
    terminal; ``fills_for`` dedups already-ingested broker fills; ``equity_curve``
    and ``positions_at`` materialize the internal book to compare against broker
    truth (the latest equity row's ``cycle_ts`` indexes the latest position
    snapshot).
    """

    def open_intents(self) -> list[OrderRecord]:
        """All orders in a non-terminal status (NEW / SUBMITTED / PARTIAL)."""
        ...

    def mark_filled(self, fill: Fill, *, now: Ms, audit: FillAudit | None = None) -> None:
        """Persist one ``fill`` and advance its order's status."""
        ...

    def mark_rejected(self, client_order_id: str, *, now: Ms) -> None:
        """Transition an order to terminal REJECTED."""
        ...

    def fills_for(self, client_order_id: str) -> Sequence[object]:
        """Fills already recorded for ``client_order_id`` (count only; each wraps a ``Fill``)."""
        ...

    def positions_at(self, cycle_ts: Ms) -> tuple[Position, ...]:
        """The book's position snapshot recorded at ``cycle_ts`` (empty if none)."""
        ...

    def equity_curve(self, start: Ms | None = None) -> list[tuple[Ms, float, float, int]]:
        """``(cycle_ts, equity, cash, n_pos)`` rows ascending; the book equity series."""
        ...


class ReconStatus(StrEnum):
    """Classification of one instrument's broker-vs-book relationship.

    ``AGREE`` -- both hold the same signed qty within tolerance (or both flat).
    ``DIVERGENT`` -- both hold a position but the signed quantities differ beyond
    tolerance. ``ORPHAN`` -- the broker holds a position the book does not (an
    unrecorded fill or manual trade). ``MISSING`` -- the book holds a position the
    broker does not (a fill we recorded but the venue lost, or a close we missed).
    Only ``AGREE`` is safe to trade on; the other three are surfaced and, if
    beyond tolerance, halt the loop.
    """

    AGREE = "agree"
    DIVERGENT = "divergent"
    ORPHAN = "orphan"
    MISSING = "missing"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconTolerance:
    """How far broker and book may drift before the loop must halt.

    ``qty_rel`` is the allowed signed-quantity mismatch as a fraction of the
    larger absolute position (execDesign.md section 8.4: 0.1% of ``|position|``).
    ``qty_abs_floor`` is an absolute floor in base-asset units so a tiny position
    is not flagged on rounding dust (one ``qty_step`` in the design). ``equity_rel``
    is the allowed equity mismatch as a fraction of the larger equity (execDesign.md
    section 8.4: 0.5% WARN escalating to 2% kill -- v1 treats breach of this single
    bound as halt-worthy). A divergence is *within* tolerance iff
    ``abs(diff) <= max(qty_abs_floor, qty_rel * max(|a|, |b|))``.
    """

    qty_rel: float = 1e-3
    qty_abs_floor: float = 1e-8
    equity_rel: float = 5e-3

    def __post_init__(self) -> None:
        for name, value in (
            ("qty_rel", self.qty_rel),
            ("qty_abs_floor", self.qty_abs_floor),
            ("equity_rel", self.equity_rel),
        ):
            if not (value >= 0.0):  # also rejects NaN
                raise ValueError(f"ReconTolerance.{name} must be >= 0, got {value!r}")

    def qty_within(self, book_qty: float, broker_qty: float) -> bool:
        """Whether signed ``book_qty`` and ``broker_qty`` agree within tolerance."""
        scale = max(abs(book_qty), abs(broker_qty))
        bound = max(self.qty_abs_floor, self.qty_rel * scale)
        return abs(broker_qty - book_qty) <= bound

    def equity_within(self, equity_book: float, equity_broker: float) -> bool:
        """Whether book and broker equity agree within ``equity_rel``.

        The relative bound uses ``max(|book|, |broker|, 1.0)`` as the scale so a
        near-zero equity (a fresh account) does not make the tolerance vanish.
        """
        scale = max(abs(equity_book), abs(equity_broker), 1.0)
        return abs(equity_broker - equity_book) <= self.equity_rel * scale


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentRecon:
    """The reconciliation outcome for one instrument.

    ``book_qty`` / ``broker_qty`` are signed base-asset quantities (0.0 when that
    side is flat). ``diff`` is ``broker_qty - book_qty`` (the adjustment the loop
    would apply to adopt broker truth). ``within_tolerance`` is whether the drift
    is acceptable for trading to continue.
    """

    instrument_id: str
    status: ReconStatus
    book_qty: float
    broker_qty: float
    diff: float
    within_tolerance: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InflightResolution:
    """The resolution of one previously non-terminal stored intent.

    ``prior_status`` is what the store held before reconcile; ``resolved_status``
    is what it was driven to (a terminal status, or unchanged when the broker
    still reports it working). ``broker_fills_ingested`` counts fills written
    through from the broker. ``found_open`` is whether the order is still working
    at the broker.
    """

    client_order_id: str
    instrument_id: str
    prior_status: str
    resolved_status: str
    broker_fills_ingested: int
    found_open: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconReport:
    """The full result of a :meth:`Reconciler.reconcile` pass.

    ``as_of`` is the reconcile timestamp. ``instruments`` is the per-instrument
    classification over the union of broker and book positions. ``inflight`` is
    the resolution of every non-terminal stored intent. ``equity_book`` /
    ``equity_broker`` are the compared equities and ``equity_within`` whether they
    agree within tolerance. ``ok`` is the single trade/no-trade gate: True iff
    every instrument and equity is within tolerance. ``adoptions`` lists the
    instruments whose broker truth differs from the book (the loop applies their
    ``diff`` after a clean -- within-tolerance -- reconcile).
    """

    as_of: Ms
    instruments: tuple[InstrumentRecon, ...]
    inflight: tuple[InflightResolution, ...]
    equity_book: float
    equity_broker: float
    equity_within: bool
    ok: bool

    @property
    def adoptions(self) -> tuple[InstrumentRecon, ...]:
        """Instruments whose status is not AGREE (broker truth differs)."""
        return tuple(r for r in self.instruments if r.status is not ReconStatus.AGREE)

    @property
    def n_divergent(self) -> int:
        """Count of instruments beyond tolerance (the halt drivers)."""
        return sum(1 for r in self.instruments if not r.within_tolerance)


class Reconciler:
    """Compares broker truth to the internal book and resolves in-flight orders.

    Construct with a :class:`BrokerView` (the ``PaperBroker`` in v1) and a
    :class:`ReconStore` (the ``TradingStore``). A pure comparator: it drives
    in-flight intents to terminal in the store (idempotent writes) but never
    mutates positions -- the loop adopts broker truth off the returned report.
    """

    def __init__(
        self,
        broker: BrokerView,
        store: ReconStore,
        *,
        tolerance: ReconTolerance | None = None,
    ) -> None:
        """Wire the reconciler. ``tolerance`` defaults to :class:`ReconTolerance`()."""
        self._broker = broker
        self._store = store
        self._tol = tolerance if tolerance is not None else ReconTolerance()

    def resolve_in_flight(self, *, as_of: Ms) -> tuple[InflightResolution, ...]:
        """Drive every non-terminal stored intent to its true terminal state.

        For each order in ``store.open_intents()`` whose status is NEW /
        SUBMITTED / PARTIAL:

        - It is in ``broker.open_orders()`` (still working) -> leave the store as
          is (genuinely in flight; the next cycle's fill polling handles it).
        - The broker has fills for its ``client_order_id`` the store has not yet
          recorded -> ingest them via ``store.mark_filled`` (the store advances
          the order to FILLED/PARTIAL itself). An order the broker DID fill more
          of is thereby updated to its true filled state.
        - It already carries ``filled_qty > 0`` and the broker reports no new
          fills and no working order -> it is a settled PARTIAL whose residual was
          deliberately not chased (execDesign.md section 8.3: the residual
          re-enters as a fresh delta at the next cycle, it is not retried). It is
          treated as terminal-for-resolution: the recorded PARTIAL status and
          ``filled_qty`` are preserved, NOT rewritten. This is the load-bearing
          invariant -- an order with ``filled_qty > 0`` is NEVER downgraded to
          REJECTED by recovery, because the broker really executed that quantity
          and rewriting the row to REJECTED would be an audit lie about a position
          that exists. ``resolve_in_flight`` runs on every non-fresh boot (not
          only post-crash), so a routine restart with a legitimate thin-book
          partial on file must leave it intact.
        - It carries ``filled_qty == 0`` (a NEW/SUBMITTED the broker never filled)
          and the broker neither holds it open nor has any fill for it -> the
          submit never landed; mark it REJECTED so it is re-decided cleanly next
          cycle. This is the only branch that writes REJECTED, and only for
          truly-unfilled intents.

        This MUST run before :meth:`reconcile` so position comparison sees the
        post-recovery book. Idempotent: ``fills_for`` dedups already-ingested
        broker fills, a settled PARTIAL is left untouched on every pass, and a
        re-run finds the now-terminal NEW/SUBMITTED intents gone from
        ``open_intents``. Returns one :class:`InflightResolution` per intent
        inspected, in store order.
        """
        open_coids = {o.client_order_id for o in self._broker.open_orders()}
        fills_by_coid = self._broker_fills_by_coid()
        resolutions: list[InflightResolution] = []

        for intent in self._store.open_intents():
            if intent.status not in _NON_TERMINAL:
                continue
            coid = intent.client_order_id
            iid = intent.instrument_id

            if coid in open_coids:
                resolutions.append(
                    self._inflight(intent, OrderStatus.SUBMITTED, 0, found_open=True)
                )
                _log.info("reconcile.inflight_working", client_order_id=coid, instrument_id=iid)
                continue

            ingested = self._ingest_missing_fills(coid, fills_by_coid.get(coid, ()), as_of=as_of)
            if ingested > 0:
                resolved = self._stored_status(coid, default=OrderStatus.FILLED)
                resolutions.append(self._inflight(intent, resolved, ingested, found_open=False))
                _log.info(
                    "reconcile.inflight_filled",
                    client_order_id=coid,
                    instrument_id=iid,
                    fills_ingested=ingested,
                    resolved=resolved.value,
                )
                continue

            # No working order and no new broker fills. An intent that already
            # holds filled_qty > 0 is a settled PARTIAL whose residual is
            # deliberately not chased (execDesign.md 8.3) -- the broker really
            # executed that quantity, so it is terminal-for-resolution: leave the
            # PARTIAL status and filled_qty intact. NEVER rewrite a filled order to
            # REJECTED -- that would be an audit lie about a real position, and it
            # would fire on the first thin-book partial on a routine restart.
            if intent.filled_qty > 0.0:
                resolutions.append(
                    self._inflight(intent, OrderStatus(intent.status), 0, found_open=False)
                )
                _log.info(
                    "reconcile.inflight_partial_settled",
                    client_order_id=coid,
                    instrument_id=iid,
                    status=intent.status,
                    filled_qty=intent.filled_qty,
                )
                continue

            # Truly unfilled (filled_qty == 0) and never seen by the broker -> the
            # submit never landed; mark REJECTED so it is re-decided next cycle.
            self._store.mark_rejected(coid, now=as_of)
            resolutions.append(self._inflight(intent, OrderStatus.REJECTED, 0, found_open=False))
            _log.warning(
                "reconcile.inflight_not_found",
                client_order_id=coid,
                instrument_id=iid,
                prior_status=intent.status,
            )

        return tuple(resolutions)

    def reconcile(self, *, as_of: Ms, resolve_inflight: bool = True) -> ReconReport:
        """Resolve in-flight orders, then classify positions + equity.

        When ``resolve_inflight`` is True (default, the production path),
        :meth:`resolve_in_flight` runs first so position comparison reflects the
        recovered book. The broker's ``positions()`` / ``account()`` are truth;
        the book's positions come from the latest ``positions_snapshots`` row-set
        and the book equity from the tail of ``equity_curve`` (the trading.sqlite
        materialization -- execDesign.md section 9.1). The reconciler never
        mutates positions.

        Per instrument in the union of broker and book positions, signed
        quantities are compared and classified (:class:`ReconStatus`): AGREE
        within tolerance; ORPHAN when only the broker holds it; MISSING when only
        the book holds it; DIVERGENT when both hold mismatched qty. Equity is
        compared against ``tolerance.equity_rel``. ``ReconReport.ok`` is True iff
        every instrument and equity is within tolerance.

        Raises :class:`~alphaforge.core.errors.ReconciliationError` when any
        classification is beyond tolerance -- the loop catches this, halts
        trading, and alerts (execDesign.md section 8.4). Within tolerance, returns
        a report whose ``adoptions`` the loop applies to its book.
        """
        inflight: tuple[InflightResolution, ...] = ()
        if resolve_inflight:
            inflight = self.resolve_in_flight(as_of=as_of)

        broker_positions = {p.instrument_id: p.qty for p in self._broker.positions()}
        book_positions = {p.instrument_id: p.qty for p in self._book_positions()}
        instruments = self._classify_positions(book_positions, broker_positions)

        equity_broker = self._broker.account().equity_quote
        equity_book = self._book_equity()
        equity_within = self._tol.equity_within(equity_book, equity_broker)

        ok = equity_within and all(r.within_tolerance for r in instruments)
        report = ReconReport(
            as_of=as_of,
            instruments=instruments,
            inflight=inflight,
            equity_book=equity_book,
            equity_broker=equity_broker,
            equity_within=equity_within,
            ok=ok,
        )

        if not ok:
            breaches = [
                f"{r.instrument_id}:{r.status.value}(book={r.book_qty},broker={r.broker_qty})"
                for r in instruments
                if not r.within_tolerance
            ]
            if not equity_within:
                breaches.append(f"equity(book={equity_book},broker={equity_broker})")
            msg = "reconcile beyond tolerance: " + "; ".join(breaches)
            _log.error("reconcile.halt", as_of=as_of, breaches=breaches)
            raise ReconciliationError(msg)

        _log.info(
            "reconcile.ok",
            as_of=as_of,
            n_instruments=len(instruments),
            n_adopt=len(report.adoptions),
        )
        return report

    # ------------------------------------------------------------------ internals

    def _broker_fills_by_coid(self) -> dict[str, list[Fill]]:
        """Group the broker's fill log by ``client_order_id`` (chronological within id)."""
        out: dict[str, list[Fill]] = {}
        for fill in self._broker.fills:
            out.setdefault(fill.client_order_id, []).append(fill)
        return out

    def _ingest_missing_fills(self, coid: str, broker_fills: Sequence[Fill], *, as_of: Ms) -> int:
        """Write through broker fills for ``coid`` not yet in the store; return the count.

        Dedups on the count already recorded: the store keeps fills in submit
        order per ``client_order_id`` (it has no broker fill-id), so the first
        ``len(already)`` broker fills are assumed present and only the tail is
        ingested. Re-running is therefore a no-op once every fill is recorded.
        """
        already = len(self._store.fills_for(coid))
        ingested = 0
        for fill in list(broker_fills)[already:]:
            self._store.mark_filled(fill, now=as_of)
            ingested += 1
        return ingested

    def _stored_status(self, coid: str, *, default: OrderStatus) -> OrderStatus:
        """Read back the store's status for ``coid`` (the store owns the fill/partial line).

        After ``mark_filled`` the store has decided FILLED vs PARTIAL via its lot
        epsilon; we surface that rather than re-deriving it. Falls back to
        ``default`` if the open-intents list and the live row disagree (it does
        not, on the single-threaded loop).
        """
        for record in self._store.open_intents():
            if record.client_order_id == coid:
                try:
                    return OrderStatus(record.status)
                except ValueError:  # pragma: no cover - store writes valid statuses
                    return default
        # Not in open_intents anymore -> terminal; mark_filled drove it to FILLED.
        return default

    @staticmethod
    def _inflight(
        intent: OrderRecord,
        resolved: OrderStatus,
        ingested: int,
        *,
        found_open: bool,
    ) -> InflightResolution:
        """Build one :class:`InflightResolution` row."""
        return InflightResolution(
            client_order_id=intent.client_order_id,
            instrument_id=intent.instrument_id,
            prior_status=intent.status,
            resolved_status=resolved.value,
            broker_fills_ingested=ingested,
            found_open=found_open,
        )

    def _book_positions(self) -> tuple[Position, ...]:
        """The book's current positions = the latest ``positions_snapshots`` row-set.

        Indexed by the ``cycle_ts`` of the latest ``equity_curve`` row (positions
        and equity are snapshotted together each cycle). Empty when the book has
        no equity history yet (a fresh account).
        """
        curve = self._store.equity_curve()
        if not curve:
            return ()
        latest_cycle_ts = curve[-1][0]
        return self._store.positions_at(latest_cycle_ts)

    def _book_equity(self) -> float:
        """The book's current equity = the tail of ``equity_curve`` (0.0 if empty)."""
        curve = self._store.equity_curve()
        return curve[-1][1] if curve else 0.0

    def _classify_positions(
        self,
        book: dict[str, float],
        broker: dict[str, float],
    ) -> tuple[InstrumentRecon, ...]:
        """Classify each instrument in the union of book and broker positions."""
        out: list[InstrumentRecon] = []
        for iid in sorted(set(book) | set(broker)):
            book_qty = book.get(iid, 0.0)
            broker_qty = broker.get(iid, 0.0)
            within = self._tol.qty_within(book_qty, broker_qty)
            status = self._status_for(book_qty, broker_qty, within=within)
            out.append(
                InstrumentRecon(
                    instrument_id=iid,
                    status=status,
                    book_qty=book_qty,
                    broker_qty=broker_qty,
                    diff=broker_qty - book_qty,
                    within_tolerance=within,
                )
            )
        return tuple(out)

    @staticmethod
    def _status_for(book_qty: float, broker_qty: float, *, within: bool) -> ReconStatus:
        """Map a (book, broker) signed-qty pair to a :class:`ReconStatus`."""
        if within:
            return ReconStatus.AGREE
        book_flat = book_qty == 0.0
        broker_flat = broker_qty == 0.0
        if book_flat and not broker_flat:
            return ReconStatus.ORPHAN
        if broker_flat and not book_flat:
            return ReconStatus.MISSING
        return ReconStatus.DIVERGENT
