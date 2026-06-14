"""LiveLoop -- the single-timer 24/7 PAPER trading cycle (execDesign.md section 9.2).

The loop OWNS the one scheduler (leakageCritique.md finding 15): each cycle it
FIRST invokes the data updater (drives ingestion), THEN reads the just-closed
bar, THEN runs the exact Phase-6 decision stack against PAPER money. There is no
second clock anywhere -- the loop computes its next deadline from
:func:`~alphaforge.core.time.now_ms` and sleeps in short wall-clock ticks.

The wall-clock tick rule (buildabilityCritique.md section 4, rule 12)
--------------------------------------------------------------------
macOS monotonic timers FREEZE while the laptop sleeps, so one long
``sleep(3600)`` would wake an hour-plus late and silently skip cycles. Instead
:meth:`run_forever` sleeps in ``tick_sleep_s`` (~45s) ticks and RECOMPUTES the
next-cycle deadline from ``now_ms()`` on every wake. A laptop that slept through
several bar boundaries wakes, sees the deadline long past, and runs the CURRENT
bar's cycle once -- the bars it slept through are SKIPPED (idempotently, keyed on
``cycle_ts``) and COUNTED, never back-filled by trading.

The hourly cycle (:meth:`run_cycle`)
-------------------------------------
Every step is persisted to ``trading.sqlite`` (the source of truth) and is
crash-recoverable. Numbered to match the spec:

  0. ``store.start_cycle(cycle_ts)`` -- the idempotency gate (already-terminal ->
     SKIP). KILL-sentinel check.
  1. INVOKE the data updater for the just-closed bar, then BLOCK until the ingest
     watermark covers ``cycle_ts`` (or a staleness timeout -> finish 'skipped').
  2. (monthly boundary) refresh the universe BEFORE signals (finding 21 order).
  3. ``SignalService.on_bar_close`` -> mu_ann (the live ``mu_provider``).
  4. ``BlendStrategy.on_bar_close(ctx)`` -> target weights (ladder/overlay/caps
     applied inside, the SAME instances as the backtest).
  5. ``weights_to_orders`` -> ``PreTradeChecker.check`` -> rejected dropped +
     alerted; client_order_ids are deterministic per ``(cycle_ts, instrument)``.
  6. ``OrderManager.place`` -> PaperBroker (walks the real book).
  7. persist fills/positions/equity + paper_state; ``store.finish_cycle('ok')``.

Any exception inside a cycle -> ``finish_cycle('failed', detail)`` + a CRITICAL
alert; the loop CONTINUES to the next cycle (one bad bar never kills the loop).
On boot, :meth:`recover_on_boot` restores the paper account and reconciles the
book BEFORE the first cycle.

Crash safety
------------
Every external effect (an order submit) flows through
:class:`~alphaforge.execution.order_manager.OrderManager`'s persist-before-submit
plus deterministic, idempotent ``client_order_id``. A SIGKILL at ANY step,
followed by a restart, re-derives the same intent and the broker recognizes it
-- no double order. ``trading.sqlite`` (WAL) is authoritative.

PAPER ONLY in v1. All timestamps are epoch-ms UTC; ASCII-only throughout.
"""

from __future__ import annotations

import json
import math
import time as _time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from alphaforge.core.errors import (
    ReconciliationError,
    RiskLimitError,
)
from alphaforge.core.logging import get_logger
from alphaforge.core.time import (
    Ms,
    Timeframe,
    floor_bar,
    next_bar_open,
    now_ms,
)
from alphaforge.core.types import (
    AccountState,
    Fill,
    Liquidity,
    Side,
)
from alphaforge.execution.broker import BrokerAck
from alphaforge.execution.paper import (
    PaperBroker,
    PaperFillAudit,
    PaperPosition,
    PaperState,
)
from alphaforge.execution.reconcile import Reconciler
from alphaforge.live.alerts import AlertLevel
from alphaforge.live.store import CycleStatus, TradingStore
from alphaforge.portfolio.discretize import weights_to_orders

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from alphaforge.backtest.engine import StrategyContext
    from alphaforge.backtest.ledger import Ledger
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import Instrument
    from alphaforge.execution.order_manager import OrderManager, PlacementReport
    from alphaforge.live.alerts import Alerter
    from alphaforge.risk import DrawdownLadder, KillSwitch, PreTradeChecker, StalenessBreaker

__all__ = [
    "CostInputSource",
    "CycleReport",
    "DataUpdater",
    "DecisionStrategy",
    "LiveLoop",
    "MuProvider",
    "UniverseRefresher",
    "WatermarkSource",
    "decode_paper_state",
    "encode_paper_state",
]

_log = get_logger("alphaforge.live.loop")

#: A paper-state blob format version, stamped into the JSON so a future schema
#: change is detectable on restore rather than silently mis-decoded.
_PAPER_STATE_VERSION = 1


# --------------------------------------------------------------------------- seams


@runtime_checkable
class DataUpdater(Protocol):
    """The incremental ingest the loop DRIVES each cycle (finding 15: one clock).

    Satisfied structurally by ``alphaforge.data.ingest.BackfillJob`` (its
    ``update`` fetches the just-closed bar). The loop calls this FIRST, before
    reading -- it never relies on a separate ingest scheduler.
    """

    def update(self, *, as_of: Ms) -> object:
        """Fetch bars up to ``as_of`` (epoch-ms UTC); the return value is ignored."""
        ...


@runtime_checkable
class WatermarkSource(Protocol):
    """Reports how fresh the lake is for the loop's freshness/staleness gate.

    The loop reads the freshest fully-available bar open for the universe and
    compares against ``cycle_ts``. Satisfied by a thin adapter over
    :class:`~alphaforge.data.store.reader.PITDataReader.latest_bar_open`.
    """

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        """Open of the freshest bar closed at or before ``as_of``, across the ids."""
        ...


@runtime_checkable
class UniverseRefresher(Protocol):
    """Recomputes PIT universe membership at a monthly boundary (finding 21 order).

    Satisfied by a thin adapter over
    :class:`~alphaforge.data.universe.builder.UniverseBuilder.rebuild`. Called
    BEFORE signals so the just-rebalanced membership feeds the decision.
    """

    def refresh(self, *, cycle_ts: Ms) -> None:
        """Rebuild membership so it is current as of ``cycle_ts``."""
        ...


class MuProvider(Protocol):
    """``(decision_ts) -> {instrument_id: mu_ann}`` -- the live BlendStrategy seam.

    The loop wires an adapter that calls
    ``SignalService.on_bar_close(as_of, weights)['mu_ann']`` and returns the
    finite rows. An empty mapping at a rebalance makes the strategy HOLD.
    """

    def __call__(self, decision_ts: Ms) -> Mapping[str, float]: ...


@runtime_checkable
class DecisionStrategy(Protocol):
    """The target-weight strategy the loop drives (the backtest ``Strategy`` shape).

    Satisfied by :class:`~alphaforge.portfolio.strategy.BlendStrategy` in live
    mode (and structurally by the backtest ``Strategy`` protocol). ``on_bar_close``
    takes a :class:`~alphaforge.backtest.engine.StrategyContext` exposing
    ``ts``/``equity``/``positions``/``instruments``/``tf`` and a PIT ``bars``
    reader -- the loop builds that context from the broker's book and the lake
    reader via its ``ctx_factory``.
    """

    def on_bar_close(self, ctx: StrategyContext) -> Mapping[str, float]: ...


@runtime_checkable
class CostInputSource(Protocol):
    """Supplies ``(adv_quote, sigma_daily)`` per instrument for the pre-trade gate.

    Satisfied by :class:`~alphaforge.backtest.engine.LakeCostInputs`. The loop
    builds one per cycle over the trailing window and reads it positionally; a
    ``(nan, nan)`` pair makes the pre-trade checker reject the order (it never
    guesses a cost), exactly as in the backtest.
    """

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        """``(adv_quote, sigma_daily)`` as of ``decision_ts``; ``(nan, nan)`` if unknown."""
        ...


# --------------------------------------------------------------------------- report


@dataclass(frozen=True, slots=True, kw_only=True)
class CycleReport:
    """The outcome of one :meth:`LiveLoop.run_cycle` (for logging + ``af status``).

    ``status`` is the terminal cycle status persisted to the store
    (``'ok'``/``'skipped'``/``'failed'``/``'halted'``). ``traded`` is True iff at
    least one order filled. ``n_orders``/``n_filled``/``n_rejected`` count the
    pre-trade-accepted orders, the broker fills, and the pre-trade rejections.
    ``equity`` is the marked paper equity at cycle end (NaN when the cycle
    skipped/failed before marking). ``detail`` is free-form operator text.

    ``degraded`` is True when the cycle traded on a partially-stale lake (latest
    bar older than ``cycle_ts`` but still inside the staleness window) -- it fired
    a WARN alert and still decided, so the operator must SEE the degradation rather
    than infer it from logs. ``dropped_book_instruments`` counts instruments
    silently dropped from sizing this cycle because no book mid could be marked
    (a missing/empty order book); a non-zero count means the universe the loop
    sized over was narrower than the PIT universe, which is otherwise invisible.
    """

    cycle_ts: Ms
    status: str
    traded: bool
    n_orders: int
    n_filled: int
    n_rejected: int
    equity: float
    detail: str
    degraded: bool = False
    dropped_book_instruments: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class _FreshnessResult:
    """Outcome of the per-cycle freshness gate (:meth:`LiveLoop._ingest_and_wait`).

    ``tradeable`` is whether the cycle may decide this bar at all; ``degraded`` is
    True when it may, but only on a partially-stale lake (the just-closed bar did
    not land within grace yet the staleness breaker still allowed trading) -- a
    WARN-worthy condition the caller surfaces (C9).
    """

    tradeable: bool
    degraded: bool


# --------------------------------------------------------------------------- codec


def encode_paper_state(state: PaperState) -> str:
    """Serialize a :class:`PaperState` to a JSON blob the store persists verbatim.

    Captures cash, every open position, the idempotency acks (so a re-submit
    after restore is deduped), the realized-fill ledger, and the slippage audit
    trail -- enough for :func:`decode_paper_state` to rebuild the identical book.
    The store treats the blob as opaque; this codec is the loop's persistence
    concern (the broker stays free of any storage format).
    """
    return json.dumps(
        {
            "version": _PAPER_STATE_VERSION,
            "initial_cash": state.initial_cash,
            "cash": state.cash,
            "positions": [
                {
                    "instrument_id": p.instrument_id,
                    "qty": p.qty,
                    "avg_entry_price": p.avg_entry_price,
                    "opened_ts": p.opened_ts,
                }
                for p in state.positions.values()
            ],
            "acks": [
                {
                    "accepted": a.accepted,
                    "client_order_id": a.client_order_id,
                    "broker_order_id": a.broker_order_id,
                    "reason": a.reason,
                }
                for a in state.acks.values()
            ],
            "fills": [
                {
                    "client_order_id": f.client_order_id,
                    "instrument_id": f.instrument_id,
                    "side": f.side.value,
                    "qty": f.qty,
                    "price": f.price,
                    "fee_quote": f.fee_quote,
                    "liquidity": f.liquidity.value,
                    "ts": f.ts,
                }
                for f in state.fills
            ],
            "audits": [
                {
                    "client_order_id": au.client_order_id,
                    "instrument_id": au.instrument_id,
                    "side": au.side.value,
                    "filled_qty": au.filled_qty,
                    "walked_price": au.walked_price,
                    "modeled_price": au.modeled_price,
                    "mid_price": au.mid_price,
                    "slippage_bps": au.slippage_bps,
                    "fee_quote": au.fee_quote,
                    "book_exhausted": au.book_exhausted,
                    "ts": au.ts,
                }
                for au in state.audits
            ],
        }
    )


def decode_paper_state(blob: str) -> PaperState:
    """Rebuild a :class:`PaperState` from a :func:`encode_paper_state` blob.

    Raises ``ValueError`` on a missing/unknown version or malformed payload --
    a corrupt blob must fail loud at boot, not silently resume an empty book.
    """
    raw = json.loads(blob)
    if not isinstance(raw, dict) or raw.get("version") != _PAPER_STATE_VERSION:
        raise ValueError(
            f"unrecognized paper_state blob (want version {_PAPER_STATE_VERSION}, "
            f"got {raw.get('version') if isinstance(raw, dict) else type(raw).__name__})"
        )
    positions = {
        str(p["instrument_id"]): PaperPosition(
            instrument_id=str(p["instrument_id"]),
            qty=float(p["qty"]),
            avg_entry_price=float(p["avg_entry_price"]),
            opened_ts=int(p["opened_ts"]),
        )
        for p in raw["positions"]
    }
    acks = {
        str(a["client_order_id"]): BrokerAck(
            accepted=bool(a["accepted"]),
            client_order_id=str(a["client_order_id"]),
            broker_order_id=None if a["broker_order_id"] is None else str(a["broker_order_id"]),
            reason=str(a["reason"]),
        )
        for a in raw["acks"]
    }
    fills = [
        Fill(
            client_order_id=str(f["client_order_id"]),
            instrument_id=str(f["instrument_id"]),
            side=Side(str(f["side"])),
            qty=float(f["qty"]),
            price=float(f["price"]),
            fee_quote=float(f["fee_quote"]),
            liquidity=Liquidity(str(f["liquidity"])),
            ts=int(f["ts"]),
        )
        for f in raw["fills"]
    ]
    audits = [
        PaperFillAudit(
            client_order_id=str(au["client_order_id"]),
            instrument_id=str(au["instrument_id"]),
            side=Side(str(au["side"])),
            filled_qty=float(au["filled_qty"]),
            walked_price=float(au["walked_price"]),
            modeled_price=float(au["modeled_price"]),
            mid_price=float(au["mid_price"]),
            slippage_bps=float(au["slippage_bps"]),
            fee_quote=float(au["fee_quote"]),
            book_exhausted=bool(au["book_exhausted"]),
            ts=int(au["ts"]),
        )
        for au in raw["audits"]
    ]
    return PaperState(
        initial_cash=float(raw["initial_cash"]),
        cash=float(raw["cash"]),
        positions=positions,
        acks=acks,
        fills=fills,
        audits=audits,
    )


# --------------------------------------------------------------------------- loop


class LiveLoop:
    """The single-timer hourly PAPER trading loop (module docstring = the contract).

    Construct from settings plus the composed Phase-6 decision stack and the
    Phase-7 persistence/execution spine. The loop is deterministic given the same
    seams; everything time-dependent enters through ``now_ms`` (injectable via
    ``clock``) and the injected updater/reader, so the whole cycle is testable
    offline with fakes.

    Args:
        settings: the validated :class:`~alphaforge.config.settings.Settings`
            (``live`` timing, ``risk``, ``portfolio``, ``signals``).
        store: the :class:`~alphaforge.live.store.TradingStore` source of truth.
        broker: the :class:`~alphaforge.execution.paper.PaperBroker` (PAPER only).
        order_manager: durable, idempotent submission layer over ``broker`` + ``store``.
        reconciler: broker-vs-book reconciliation (boot + post-trade).
        strategy: the live :class:`~alphaforge.portfolio.strategy.BlendStrategy`
            (its ``mu_provider`` is the loop's signal seam).
        pretrade: the :class:`~alphaforge.risk.PreTradeChecker` (same code as backtest).
        ladder: the SAME :class:`~alphaforge.risk.DrawdownLadder` the strategy uses
            (the loop never double-updates it -- the strategy owns the marks).
        staleness: the :class:`~alphaforge.risk.StalenessBreaker` freshness gate.
        kill: the file-sentinel :class:`~alphaforge.risk.KillSwitch`.
        alerter: the outbound :class:`~alphaforge.live.alerts.Alerter`.
        updater: the :class:`DataUpdater` the loop drives each cycle.
        watermark: the :class:`WatermarkSource` freshness probe.
        cost_inputs_factory: builds a per-cycle :class:`CostInputSource` over the
            trailing window for the pre-trade gate.
        ctx_factory: builds the decision context for ``strategy.on_bar_close``
            from ``(cycle_ts, equity, positions, instruments)``.
        instruments_factory: returns the tradable ``{id: Instrument}`` as of a
            ``cycle_ts`` (the PIT universe x instrument record).
        universe_refresher: optional monthly :class:`UniverseRefresher`.
        ledger_factory: builds a fresh :class:`Ledger` seeded with the broker's
            current book (for ``weights_to_orders`` sizing).
        clock: wall-clock read (defaults to :func:`~alphaforge.core.time.now_ms`).
        sleeper: blocking sleep (defaults to :func:`time.sleep`); injected so the
            tick loop is instant in tests.
        initial_cash: paper starting cash, recorded into the first equity point.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        store: TradingStore,
        broker: PaperBroker,
        order_manager: OrderManager,
        reconciler: Reconciler,
        strategy: DecisionStrategy,
        pretrade: PreTradeChecker,
        ladder: DrawdownLadder,
        staleness: StalenessBreaker,
        kill: KillSwitch,
        alerter: Alerter,
        updater: DataUpdater,
        watermark: WatermarkSource,
        cost_inputs_factory: _CostInputsFactory,
        ctx_factory: _ContextFactory,
        instruments_factory: _InstrumentsFactory,
        universe_refresher: UniverseRefresher | None = None,
        ledger_factory: _LedgerFactory | None = None,
        clock: _Clock | None = None,
        sleeper: _Sleeper | None = None,
        initial_cash: float = 100_000.0,
    ) -> None:
        self._settings = settings
        self._store = store
        self._broker = broker
        self._om = order_manager
        self._reconciler = reconciler
        self._strategy = strategy
        self._pretrade = pretrade
        self._ladder = ladder
        self._staleness = staleness
        self._kill = kill
        self._alerter = alerter
        self._updater = updater
        self._watermark = watermark
        self._cost_inputs_factory = cost_inputs_factory
        self._ctx_factory = ctx_factory
        self._instruments_factory = instruments_factory
        self._universe_refresher = universe_refresher
        self._ledger_factory = ledger_factory if ledger_factory is not None else _default_ledger
        self._clock: _Clock = now_ms if clock is None else clock
        self._sleeper: _Sleeper = _time.sleep if sleeper is None else sleeper
        self._initial_cash = initial_cash
        self._tf: Timeframe = settings.data.timeframe
        self._bar_ms: int = self._tf.ms
        self._grace_ms: int = settings.live.cycle_grace_s * 1000
        self._tick_s: float = float(settings.live.tick_sleep_s)
        #: Bar opens whose deadline passed while we were asleep/elsewhere (and any
        #: bar that reached a terminal SKIP); counted, never trade-backfilled.
        self._missed_cycles = 0
        #: Cycles that traded on a partially-stale-but-tradeable lake (WARN-alerted).
        self._degraded_cycles = 0
        #: Total instruments dropped from sizing across cycles for want of a book mid.
        self._dropped_book_instruments = 0
        #: Last bar open observed by run_forever, to count bars slept through (C8).
        self._last_seen_bar: Ms | None = None

    # ------------------------------------------------------------------ scheduling

    @property
    def missed_cycles(self) -> int:
        """Count of bar opens not traded since boot: laptop slept through them, a
        duplicate wake re-hit an already-terminal bar, or a cycle finished SKIP.

        Includes bar opens the loop slept clean past: when :meth:`run_forever`
        wakes and discovers the wall clock jumped over several bar boundaries, the
        intervening bars never ran, and each is counted here (not only the one
        current bar). The property therefore reflects EVERY un-traded scheduled
        bar, matching :meth:`~alphaforge.live.store.TradingStore.expected_vs_run`.
        """
        return self._missed_cycles

    @property
    def degraded_cycles(self) -> int:
        """Cycles that traded on a partially-stale-but-tradeable lake since boot.

        Each such cycle fired a WARN alert (the lake's freshest bar was older than
        ``cycle_ts`` yet still inside the staleness window, so the loop decided on
        slightly stale marks). A non-zero, climbing count is an early feed-health
        signal the operator must see before the breaker finally forces a SKIP.
        """
        return self._degraded_cycles

    @property
    def dropped_book_instruments(self) -> int:
        """Instruments dropped from sizing (no book mid) summed across cycles.

        Each is an instrument in the PIT universe that could not be marked from
        the broker book this cycle and so was excluded from ``weights_to_orders``
        sizing. Counted (and surfaced per cycle on the report) so a feed that
        silently shrinks the tradable set is visible, not inferred from logs.
        """
        return self._dropped_book_instruments

    def next_deadline(self, now: Ms) -> Ms:
        """Wall-clock instant the next cycle is due: next bar close + the grace.

        The grace (``cycle_grace_s``) lets the venue finalize the just-closed
        kline before the loop reads it. Recomputed from ``now`` on every tick so
        a laptop that slept past several boundaries lands on the CURRENT bar.
        """
        return next_bar_open(now, self._tf) + self._grace_ms

    def run_forever(self, *, max_cycles: int | None = None) -> None:
        """The single-timer tick loop (module docstring: rule 12).

        Boots via :meth:`recover_on_boot`, then repeatedly: compute the next
        deadline from ``now_ms()``; sleep in ``tick_sleep_s`` ticks (checking the
        KILL sentinel each tick) until ``now >= deadline``; run the cycle for the
        just-closed bar (``cycle_ts = floor_bar(now)``). A missed deadline (we
        woke well past it) still runs only the CURRENT bar -- the bars slept
        through are COUNTED into :attr:`missed_cycles` (C8: every intervening bar
        open between the last bar we ran and this one is a miss) and never
        trade-backfilled. When the KILL sentinel is engaged the loop stops TRADING
        but keeps the heartbeat tick alive (a halted system is still observable).

        ``max_cycles`` bounds the number of cycles run (tests/soak); ``None`` runs
        until the process is signalled. The loop NEVER exits because of a cycle: a
        normal exception escaping :meth:`run_cycle` (already best-effort caught
        inside it, but defended again here) is logged, CRITICAL-alerted, and the
        loop CONTINUES to the next tick. Only ``SystemExit``/``KeyboardInterrupt``
        (and any other ``BaseException``) break out, for a clean graceful
        shutdown -- preserving the crash-recovery contract (a hard crash must
        propagate so :meth:`recover_on_boot` runs on restart).
        """
        self.recover_on_boot()
        cycles_run = 0
        halted_announced = False
        while max_cycles is None or cycles_run < max_cycles:
            deadline = self.next_deadline(self._clock())
            while self._clock() < deadline:
                if self._kill.engaged():
                    if not halted_announced:
                        self._alerter.alert(
                            AlertLevel.CRITICAL, "TRADING HALTED: KILL sentinel engaged"
                        )
                        halted_announced = True
                    # Heartbeat only: keep observing, never trade.
                    self._sleeper(self._tick_s)
                    deadline = self.next_deadline(self._clock())
                    continue
                halted_announced = False
                self._sleeper(self._tick_s)
            if self._kill.engaged():
                # Deadline reached but the brake is on: skip trading this bar.
                self._sleeper(self._tick_s)
                continue
            cycle_ts = floor_bar(self._clock(), self._tf)
            self._count_slept_through_bars(cycle_ts)
            self._last_seen_bar = cycle_ts
            try:
                self.run_cycle(cycle_ts)
            except Exception as exc:
                # run_cycle already backstops normal exceptions; this is a second
                # firewall so even an error raised by run_cycle's OWN persistence
                # (e.g. a store write that fails AFTER the body's except clause)
                # cannot kill the 24/7 loop. SystemExit/KeyboardInterrupt are NOT
                # caught (they are BaseException, not Exception): they break the
                # loop cleanly so the crash-recovery contract holds on restart.
                self._alerter.alert(
                    AlertLevel.CRITICAL, f"cycle {cycle_ts} escaped run_cycle: {exc}"
                )
                _log.error("run_forever.cycle_escaped", cycle_ts=cycle_ts, error=str(exc))
            cycles_run += 1

    def _count_slept_through_bars(self, cycle_ts: Ms) -> None:
        """Add bar opens strictly between the last bar we ran and ``cycle_ts`` (C8).

        macOS sleep freezes the timer, so a wake can land several bars past the
        last one we traded. Each aligned bar open in ``(prev, cycle_ts)`` -- the
        bars we slept clean through, which the per-wake ``floor_bar(now)`` would
        otherwise never count -- is a missed cycle. The current bar (``cycle_ts``)
        is NOT counted here: it is about to run (and if it is a no-trade SKIP,
        :meth:`_finish_skip` / the terminal-replay gate counts it instead, so we
        never double-count). A first bar after boot (no prior seen bar) adds
        nothing; a non-advancing wake (same bar) adds nothing.
        """
        prev = self._last_seen_bar
        if prev is None or cycle_ts <= prev:
            return
        # Count aligned opens prev+bar_ms, ..., cycle_ts-bar_ms (the slept-through
        # bars). Integer arithmetic, allocation-free; never negative given the
        # guard above.
        self._missed_cycles += (cycle_ts - prev) // self._bar_ms - 1

    # ------------------------------------------------------------------ boot recovery

    def recover_on_boot(self) -> None:
        """Restore the paper book and reconcile BEFORE the first new decision.

        Section 9.3 ordering, composed against the real surfaces:

        1. Restore the :class:`PaperBroker` from the latest persisted
           ``paper_state`` blob (PAPER: the broker IS our serialized book).
        2. REPLAY store-recorded fills newer than that blob onto the broker
           (section 9.3 step 4). The store persists each fill the instant it is
           booked, but the broker blob is snapshotted only at cycle END; a crash
           mid-batch therefore leaves durable fills the restored book has not yet
           seen. Replaying them (idempotent on ``client_order_id``) rebuilds the
           book to the store's truth BEFORE any reconcile -- without this the
           broker silently under-counts a position the store recorded.
        3. Fail any interrupted ``'running'`` cycle so it is never counted as a
           run and the loop SKIPs that bar (missed cycles are not back-filled).
        4. Seed the opening equity snapshot on a TRULY fresh boot (no equity
           history yet): the broker holds ``initial_cash`` while the store's book
           is empty, which the reconciler would (correctly) read as a divergence.
           Recording the opening account first makes book == broker at the
           opening so the reconcile is a clean no-op rather than a spurious halt.
        5. ``Reconciler.reconcile`` -- resolve in-flight intents against broker
           truth (deterministic ids make this idempotent) and compare
           positions/equity. A divergence beyond tolerance raises
           :class:`~alphaforge.core.errors.ReconciliationError`; the loop alerts
           and re-raises (it must NOT trade on a divergent book).

        Idempotent: a second boot with a clean store is a quiet no-op.
        """
        now = self._clock()
        restored, blob_cycle_ts = self._restore_paper_state()
        replayed = self._replay_recorded_fills(blob_cycle_ts)
        failed = self._fail_running_cycles(now=now)
        # A TRULY fresh boot (no persisted state of any kind, broker untouched at
        # initial_cash) has nothing to recover or reconcile: there is no prior book
        # to diverge from. Short-circuit BEFORE seeding a synthetic opening-equity
        # row -- that seed (keyed at floor_bar(now)) would otherwise persist as a
        # phantom point on the canonical equity curve whenever the first traded
        # cycle runs at a DIFFERENT cycle_ts than now (e.g. replaying historical
        # bars), polluting the per-cycle N/M accounting. In production the seed and
        # the first cycle coincide and the upsert overwrites it; this guard makes
        # the invariant hold unconditionally instead of by coincidence.
        if self._is_fresh_boot(restored=restored, replayed=replayed):
            _log.info("boot.fresh", equity_broker=self._broker.account().equity_quote)
            return
        self._sync_book_snapshot_after_recovery(replayed=replayed, now=now)
        try:
            report = self._reconciler.reconcile(as_of=now)
        except ReconciliationError as exc:
            self._alerter.alert(AlertLevel.CRITICAL, f"boot reconcile beyond tolerance: {exc}")
            _log.error("boot.reconcile_halt", error=str(exc))
            raise
        _log.info(
            "boot.recovered",
            paper_state_restored=restored,
            replayed_fills=replayed,
            failed_cycles=len(failed),
            n_inflight=len(report.inflight),
            n_adoptions=len(report.adoptions),
            equity_broker=report.equity_broker,
        )
        if replayed or failed or report.inflight or report.adoptions:
            self._alerter.alert(
                AlertLevel.WARN,
                f"boot recovery: restored={restored} replayed_fills={replayed} "
                f"failed_cycles={len(failed)} inflight={len(report.inflight)} "
                f"adoptions={len(report.adoptions)}",
            )

    def _replay_recorded_fills(self, blob_cycle_ts: Ms | None) -> int:
        """Re-book store-recorded fills the restored broker blob has not yet seen.

        The broker's :class:`PaperState` blob is snapshotted only at cycle end, so
        any fill the store persisted AFTER that snapshot (a mid-batch crash) is
        durable in the store but absent from the restored book. This replays every
        such fill onto the broker via
        :meth:`~alphaforge.execution.paper.PaperBroker.apply_recorded_fill` --
        idempotent on ``client_order_id``, so fills already in the blob are
        no-ops. ``blob_cycle_ts`` is the watermark: when a blob was restored, only
        fills with ``ts > blob_cycle_ts`` can be new (each fill's ``ts`` is its
        cycle's bar-open); on a fresh boot (no blob) every recorded fill is
        replayed. Returns the count newly applied.
        """
        since = -1 if blob_cycle_ts is None else blob_cycle_ts
        applied = 0
        for record in self._store.fills_since(since + 1):
            if self._broker.apply_recorded_fill(record.fill):
                applied += 1
        return applied

    def _sync_book_snapshot_after_recovery(self, *, replayed: int, now: Ms) -> None:
        """Make the persisted book snapshot equal the recovered broker, pre-reconcile.

        Two recoverable cases where the persisted equity/positions snapshot lags
        the (now-correct) broker book and would otherwise trip a SPURIOUS
        reconcile halt:

        1. **Fresh boot** (no equity history): the broker holds ``initial_cash``
           while the book reads 0.0 -- a phantom divergence on a healthy first
           boot. We record the opening account under a sentinel cycle keyed at
           ``floor_bar(now)``.
        2. **Mid-batch crash** (``replayed > 0``): :meth:`_replay_recorded_fills`
           just re-booked durable store fills onto the broker, but the cycle that
           recorded them died before its end-of-cycle snapshot, so the book's last
           positions/equity snapshot predates them. We re-snapshot the broker (the
           book authority -- those fills ARE ours) so reconcile sees agreement
           rather than an ORPHAN it cannot explain.

        This NEVER masks a genuine divergence: it only writes the book to match a
        broker state we ourselves reconstructed from the store's own durable fills.
        A broker position with NO backing store fill (impossible for PaperBroker,
        the real-money posture later) still has no snapshot written for it and so
        still halts reconcile. A no-op when neither case applies (a clean restart
        with an up-to-date snapshot).
        """
        fresh = not self._store.equity_curve()
        if not fresh and replayed == 0:
            return
        snap_ts = floor_bar(now, self._tf)
        account = self._broker.account_at(snap_ts)
        self._store.snapshot_equity(snap_ts, account)
        self._store.snapshot_positions(snap_ts, account.positions)

    def _restore_paper_state(self) -> tuple[bool, Ms | None]:
        """Load the latest persisted paper_state blob into a fresh broker book.

        Returns ``(restored, blob_cycle_ts)``: ``restored`` is True iff a blob
        existed and was applied; ``blob_cycle_ts`` is the ``cycle_ts`` the blob
        was snapshotted at (``None`` when no blob existed), the watermark
        :meth:`_replay_recorded_fills` uses to find fills booked after it. The
        broker is mutated in place via its live :attr:`PaperBroker.state` so the
        loop and reconciler share one book.
        """
        latest = self._store.latest_paper_state()
        if latest is None:
            return False, None
        blob_cycle_ts, blob = latest
        state = decode_paper_state(blob)
        # Replace the broker's book wholesale (a fresh restored copy).
        self._broker.state.cash = state.cash
        self._broker.state.initial_cash = state.initial_cash
        self._broker.state.positions.clear()
        self._broker.state.positions.update(state.positions)
        self._broker.state.acks.clear()
        self._broker.state.acks.update(state.acks)
        self._broker.state.fills.clear()
        self._broker.state.fills.extend(state.fills)
        self._broker.state.audits.clear()
        self._broker.state.audits.extend(state.audits)
        return True, blob_cycle_ts

    def _fail_running_cycles(self, *, now: Ms) -> list[Ms]:
        """Mark every interrupted ``'running'`` cycle ``'failed'``; return their ids."""
        failed: list[Ms] = []
        for cycle in self._store.running_cycles():
            self._store.finish_cycle(
                cycle.cycle_ts, "failed", "interrupted: resolved on restart", now=now
            )
            failed.append(cycle.cycle_ts)
        return failed

    def _is_fresh_boot(self, *, restored: bool, replayed: int) -> bool:
        """True iff this boot has NO prior state to recover or reconcile.

        Fresh means: no ``paper_state`` blob was restored, no store fills were
        replayed onto the broker, the store holds no equity history and no orders
        of any status, and the broker book is untouched (flat, cash ==
        ``initial_cash``). Under those conditions there is nothing a reconcile
        could compare -- the (empty) book trivially equals the (initial) broker --
        so the loop skips both the synthetic opening-equity seed and the
        reconcile. ANY trace of prior activity (a blob, a replayed fill, a recorded
        order, an equity row, or a non-flat / non-initial broker) makes this False
        and the full recover+reconcile path runs.

        Deliberately conservative: it must never short-circuit a boot that has real
        state to reconcile, because that would let the loop trade on an
        un-reconciled book. Every clause is necessary; a False from any one is safe.
        """
        if restored or replayed > 0:
            return False
        if self._store.equity_curve() or self._store.open_intents():
            return False
        # Broker untouched: no booked fills and no open positions. Value-independent
        # (does not float-compare cash), so a fresh broker is recognized regardless
        # of the configured starting cash.
        return not self._broker.fills and not self._broker.positions()

    # ------------------------------------------------------------------ the cycle

    def run_cycle(self, cycle_ts: Ms) -> CycleReport:
        """Run the one-bar pipeline for ``cycle_ts`` (module docstring steps 0-7).

        Every step persists its transition and is crash-recoverable. The cycle
        NEVER raises on a NORMAL exception: ANY ``Exception`` is caught, the cycle
        is finished ``'failed'`` (or ``'halted'`` for a risk/reconciliation
        breach), a CRITICAL alert fires, and the report carries the failure so the
        caller can continue to the next bar. The catch-all backstops everything --
        a retry-exhausted :class:`~alphaforge.execution.order_manager.TransientBrokerError`,
        a ``sqlite3.OperationalError`` (db lock), an ``OSError``, or a live ccxt
        ``NetworkError`` -- so 'one bad bar never kills the loop' is literally true,
        not just for the curated allowlist.

        CRITICAL contract: ``SystemExit``/``KeyboardInterrupt`` (and any other
        ``BaseException``) are deliberately NOT caught -- they propagate so a hard
        crash still terminates the process and :meth:`recover_on_boot` runs on
        restart (the crash-recovery test injects ``SystemExit`` to simulate this).
        """
        now = self._clock()
        # (0) idempotency gate -- a missed/replayed bar that already reached a
        #     terminal status is SKIPPED (counted), never re-traded.
        if not self._store.start_cycle(cycle_ts, now=now):
            self._missed_cycles += 1
            _log.info("cycle.skip_terminal", cycle_ts=cycle_ts)
            return _skip_report(cycle_ts, "already terminal (missed/replayed bar)")

        if self._kill.engaged():
            return self._finish_skip(cycle_ts, "kill sentinel engaged", now=now)

        try:
            return self._run_cycle_body(cycle_ts, now=now)
        except (RiskLimitError, ReconciliationError) as exc:
            # A risk/reconciliation breach is recorded distinctly as 'halted'.
            return self._finish_failed(cycle_ts, f"risk halt: {exc}", now=now, halt=True)
        except Exception as exc:
            # Catch-all over NORMAL exceptions ONLY (TransientBrokerError,
            # sqlite3.OperationalError, OSError, ccxt NetworkError, ...). NOT
            # BaseException: SystemExit/KeyboardInterrupt must still propagate so
            # recover_on_boot runs on the next process start.
            return self._finish_failed(cycle_ts, f"{type(exc).__name__}: {exc}", now=now)

    def _run_cycle_body(self, cycle_ts: Ms, *, now: Ms) -> CycleReport:
        """Steps 1-7 of :meth:`run_cycle` (exceptions handled by the caller)."""
        # (1) DRIVE ingestion for the just-closed bar, then block on freshness.
        freshness = self._ingest_and_wait(cycle_ts)
        if not freshness.tradeable:
            return self._finish_skip(cycle_ts, "stale: ingest did not cover the bar", now=now)
        if freshness.degraded:
            # C9: a tradeable-but-partially-stale cycle is no longer a silent log;
            # WARN-alert it and count it so feed degradation is visible in status.
            self._degraded_cycles += 1
            self._alerter.alert(
                AlertLevel.WARN,
                f"cycle {cycle_ts}: trading on a PARTIALLY STALE lake "
                f"(just-closed bar did not land within grace)",
            )

        instruments = dict(self._instruments_factory(cycle_ts))
        if not instruments:
            return self._finish_skip(cycle_ts, "empty universe at cycle", now=now)

        # (2) monthly boundary: refresh the universe BEFORE signals (finding 21).
        if self._universe_refresher is not None and _is_month_boundary(cycle_ts):
            self._universe_refresher.refresh(cycle_ts=cycle_ts)
            instruments = dict(self._instruments_factory(cycle_ts))

        # (3)+(4) the decision: BlendStrategy (live mu_provider) -> target weights.
        #         The ladder/overlay/caps and the SAME mu seam run INSIDE the
        #         strategy, mirroring the backtest exactly.
        account = self._broker.account_at(cycle_ts)
        positions = {p.instrument_id: p.qty for p in account.positions}
        ctx = self._ctx_factory(
            cycle_ts=cycle_ts,
            equity=account.equity_quote,
            positions=positions,
            instruments=instruments,
        )
        targets = dict(self._strategy.on_bar_close(ctx))

        # (C4-persist) record the LIVE ladder snapshot AFTER the decision so
        # ``af paper status`` renders the TRUE ladder (state/hwm/drawdown/mult) the
        # strategy just sized off -- not a replay through a fresh ladder. The
        # strategy and the loop share the SAME ladder instance, so this reads its
        # current (post-mark) state.
        self._record_ladder_state(cycle_ts)

        # (5) discretize -> pre-trade -> accepted orders (deterministic ids).
        report = self._decide_and_place(
            cycle_ts, targets, account, instruments, now=now, degraded=freshness.degraded
        )

        # (7) persist the post-trade book + equity + paper_state; finish 'ok'.
        marked = self._broker.account_at(cycle_ts)
        self._persist_book(cycle_ts, marked, now=now)
        self._store.finish_cycle(cycle_ts, "ok", report.detail, now=now)
        if report.traded:
            self._alerter.alert(
                AlertLevel.INFO,
                f"cycle {cycle_ts}: filled {report.n_filled}/{report.n_orders} "
                f"equity={marked.equity_quote:.2f}",
            )
        return report

    def _record_ladder_state(self, cycle_ts: Ms) -> None:
        """Persist the live :class:`~alphaforge.risk.DrawdownLadder` snapshot (C4-persist).

        Reads the loop's ladder -- the SAME instance the strategy sizes off -- and
        upserts ``(state, hwm, drawdown, gross_mult)`` under ``cycle_ts`` so the
        status command renders the true current ladder. The ladder's ``state`` is a
        :class:`~alphaforge.risk.monitors.DDState` whose ``.value`` is the persisted
        label (``'normal'``/``'half_gross'``/``'flat_halted'``).
        """
        self._store.record_ladder_state(
            cycle_ts=cycle_ts,
            state=self._ladder.state.value,
            hwm=self._ladder.hwm,
            drawdown=self._ladder.drawdown,
            gross_mult=self._ladder.gross_multiplier(),
        )

    def _decide_and_place(
        self,
        cycle_ts: Ms,
        targets: Mapping[str, float],
        account: AccountState,
        instruments: Mapping[str, Instrument],
        *,
        now: Ms,
        degraded: bool = False,
    ) -> CycleReport:
        """Steps 5-6: discretize targets, pre-trade gate, submit accepted orders.

        Empty targets (a HOLD) short-circuit: no orders, no broker contact. The
        ladder having flattened to all-zeros flows through naturally -- the orders
        it produces are reduce-only closes, which the pre-trade checker passes.

        ``degraded`` is propagated onto the returned report (C9). Instruments the
        book could not mark are counted (C9) and surfaced on the report as
        ``dropped_book_instruments``; they are excluded from sizing exactly as
        before -- the count makes that exclusion visible rather than silent.
        """
        if not targets:
            return CycleReport(
                cycle_ts=cycle_ts,
                status="ok",
                traded=False,
                n_orders=0,
                n_filled=0,
                n_rejected=0,
                equity=account.equity_quote,
                detail="hold: no target change",
                degraded=degraded,
                dropped_book_instruments=0,
            )

        closes, dropped = self._closes_for(cycle_ts, account, instruments)
        if dropped:
            # C9: instruments silently dropped from sizing for want of a book mid.
            self._dropped_book_instruments += dropped
            _log.warning("cycle.dropped_book", cycle_ts=cycle_ts, n_dropped=dropped)
        ledger = self._ledger_factory(self._initial_cash, instruments, account, closes)
        orders = weights_to_orders(
            targets,
            ledger,
            closes,
            instruments,
            no_trade_band=self._settings.portfolio.no_trade_band,
            cycle_ts=cycle_ts,
        )
        if not orders:
            return CycleReport(
                cycle_ts=cycle_ts,
                status="ok",
                traded=False,
                n_orders=0,
                n_filled=0,
                n_rejected=0,
                equity=account.equity_quote,
                detail="hold: orders below no-trade band / min-size",
                degraded=degraded,
                dropped_book_instruments=dropped,
            )

        cost_src = self._cost_inputs_factory(cycle_ts, sorted(instruments))
        adv = {iid: cost_src.cost_inputs(iid, cycle_ts)[0] for iid in instruments}
        sigma = {iid: cost_src.cost_inputs(iid, cycle_ts)[1] for iid in instruments}
        check = self._pretrade.check(
            orders,
            equity=account.equity_quote,
            positions={p.instrument_id: p.qty for p in account.positions},
            closes=closes,
            adv_quote=adv,
            sigma_daily=sigma,
            instruments=instruments,
        )
        for verdict in check.rejected:
            self._alerter.alert(
                AlertLevel.WARN,
                f"pre-trade reject {verdict.order.client_order_id}: {'; '.join(verdict.reasons)}",
            )
        accepted = list(check.accepted)
        if not accepted:
            return CycleReport(
                cycle_ts=cycle_ts,
                status="ok",
                traded=False,
                n_orders=0,
                n_filled=0,
                n_rejected=check.n_rejected,
                equity=account.equity_quote,
                detail=f"all {check.n_rejected} order(s) rejected pre-trade",
                degraded=degraded,
                dropped_book_instruments=dropped,
            )

        # (6) durable, idempotent submission to the PaperBroker (walks the book).
        placement: PlacementReport = self._om.place(accepted, cycle_ts=cycle_ts, now=now)
        n_filled = placement.filled + placement.partial
        return CycleReport(
            cycle_ts=cycle_ts,
            status="ok",
            traded=n_filled > 0,
            n_orders=len(accepted),
            n_filled=n_filled,
            n_rejected=check.n_rejected + placement.rejected,
            equity=account.equity_quote,
            detail=(
                f"orders={len(accepted)} filled={placement.filled} "
                f"partial={placement.partial} rejected={check.n_rejected + placement.rejected} "
                f"skipped_replay={placement.skipped_replay}"
            ),
            degraded=degraded,
            dropped_book_instruments=dropped,
        )

    # ------------------------------------------------------------------ step 1 helper

    def _ingest_and_wait(self, cycle_ts: Ms) -> _FreshnessResult:
        """DRIVE the updater, then block until the lake covers ``cycle_ts`` (finding 15).

        The loop is the single scheduler: it calls ``updater.update`` then probes
        the watermark. It re-invokes + re-probes in ``tick_sleep_s`` ticks until
        either the freshest universe bar open reaches ``cycle_ts`` (the just-closed
        bar landed) or ``cycle_grace_s`` of wall time elapses, in which case the
        :class:`~alphaforge.risk.StalenessBreaker` decides: stale -> no-trade
        (the caller finishes ``'skipped'``).

        Returns a :class:`_FreshnessResult`. ``tradeable`` is True iff fresh enough
        to decide this bar. ``degraded`` is True (C9) when the bar IS tradeable but
        the lake's freshest bar open is OLDER than ``cycle_ts`` -- i.e. the grace
        elapsed, the just-closed bar never landed, yet the staleness breaker still
        allows trading on a slightly-stale mark. That partial staleness was
        previously only a WARNING log; the caller now also fires a WARN
        :class:`~alphaforge.live.alerts.Alerter` so the operator SEES it.
        """
        instruments = sorted(self._instruments_factory(cycle_ts))
        deadline = self._clock() + self._grace_ms
        while True:
            now = self._clock()
            self._updater.update(as_of=now)
            latest = (
                self._watermark.latest_bar_open(instruments, as_of=now) if instruments else None
            )
            if latest is not None and latest >= cycle_ts:
                return _FreshnessResult(tradeable=True, degraded=False)
            if now >= deadline:
                # Out of grace: let the staleness breaker make the final call so
                # the same gate that protects the backtest protects live.
                latest_close = (latest + self._bar_ms) if latest is not None else 0
                allowed = self._staleness.trading_allowed(
                    now=now, latest_bar_close=latest_close, bar_ms=self._bar_ms
                )
                if not allowed:
                    _log.warning(
                        "cycle.stale",
                        cycle_ts=cycle_ts,
                        latest_bar_open=latest,
                        grace_ms=self._grace_ms,
                    )
                    return _FreshnessResult(tradeable=False, degraded=False)
                # Tradeable but the just-closed bar never landed: degraded.
                _log.warning(
                    "cycle.degraded_stale",
                    cycle_ts=cycle_ts,
                    latest_bar_open=latest,
                    grace_ms=self._grace_ms,
                )
                return _FreshnessResult(tradeable=True, degraded=True)
            self._sleeper(self._tick_s)

    # ------------------------------------------------------------------ step 7 helper

    def _persist_book(self, cycle_ts: Ms, account: AccountState, *, now: Ms) -> None:
        """Snapshot positions + equity + the paper_state blob for ``cycle_ts``."""
        self._store.snapshot_positions(cycle_ts, account.positions)
        self._store.snapshot_equity(cycle_ts, account)
        self._store.save_paper_state(
            cycle_ts, encode_paper_state(self._broker.snapshot_state()), now=now
        )

    def _closes_for(
        self,
        cycle_ts: Ms,
        account: AccountState,
        instruments: Mapping[str, Instrument],
    ) -> tuple[dict[str, float], int]:
        """Decision-bar close (book mid) per instrument with a position or a target.

        Uses the broker's order-book mid as the single mark for sizing and the
        pre-trade collar -- the same book the fill walks, so sizing and execution
        cannot drift apart. Falls back to a held position's avg-entry when no book
        exists (never a silent zero). Instruments without any mark are dropped from
        ``closes``; ``weights_to_orders`` / the pre-trade checker handle the gap.

        Returns ``(closes, dropped)``. ``dropped`` (C9) is the number of universe
        instruments that ended with NO mark (no book mid and no held-position
        avg-entry fallback) and so are silently absent from sizing this cycle --
        previously invisible; the caller now counts and surfaces it.
        """
        closes: dict[str, float] = {}
        for iid in instruments:
            mid = self._book_mid(iid, cycle_ts)
            if mid is not None:
                closes[iid] = mid
        for pos in account.positions:
            if pos.instrument_id not in closes:
                closes[pos.instrument_id] = pos.avg_entry_price
        dropped = sum(1 for iid in instruments if iid not in closes)
        return closes, dropped

    def _book_mid(self, instrument_id: str, ts: Ms) -> float | None:
        """Best-bid/ask mid from a fresh book snapshot; None when unavailable."""
        try:
            book = self._broker.order_book(instrument_id)
        except (KeyError, ValueError):
            return None
        if book.bids and book.asks:
            return 0.5 * (book.bids[0][0] + book.asks[0][0])
        if book.asks:
            return book.asks[0][0]
        if book.bids:
            return book.bids[0][0]
        return None

    # ------------------------------------------------------------------ finishers

    def _finish_skip(self, cycle_ts: Ms, detail: str, *, now: Ms) -> CycleReport:
        """Persist a ``'skipped'`` terminal status and count the miss."""
        self._store.finish_cycle(cycle_ts, "skipped", detail, now=now)
        self._missed_cycles += 1
        _log.info("cycle.skipped", cycle_ts=cycle_ts, detail=detail)
        return _skip_report(cycle_ts, detail)

    def _finish_failed(
        self, cycle_ts: Ms, detail: str, *, now: Ms, halt: bool = False
    ) -> CycleReport:
        """Persist ``'failed'`` (or ``'halted'``), alert CRITICAL, never raise.

        A risk/reconciliation breach is recorded ``'halted'`` (and the KILL
        sentinel is NOT engaged here -- the ladder/kill-switch own that); an
        ordinary cycle error is ``'failed'``. Either way the loop survives and the
        next bar proceeds (one bad cycle never kills the loop).
        """
        status: CycleStatus = "halted" if halt else "failed"
        self._store.finish_cycle(cycle_ts, status, detail, now=now)
        self._alerter.alert(AlertLevel.CRITICAL, f"cycle {cycle_ts} {status}: {detail}")
        _log.error("cycle.failed", cycle_ts=cycle_ts, status=status, detail=detail)
        return CycleReport(
            cycle_ts=cycle_ts,
            status=status,
            traded=False,
            n_orders=0,
            n_filled=0,
            n_rejected=0,
            equity=math.nan,
            detail=detail,
        )


# --------------------------------------------------------------------------- helpers

_DAY_MS = 86_400_000


def _is_month_boundary(cycle_ts: Ms) -> bool:
    """True iff ``cycle_ts`` is the first bar open of a UTC calendar month.

    The universe rebalances monthly at 00:00 UTC on the 1st; the loop refreshes
    membership on the cycle whose bar opens exactly there. Pure epoch arithmetic
    (no datetime) keeps it allocation-free and deterministic.
    """
    from alphaforge.core.time import from_ms

    dt = from_ms(cycle_ts)
    return dt.day == 1 and dt.hour == 0 and dt.minute == 0 and (cycle_ts % _DAY_MS == 0)


def _skip_report(cycle_ts: Ms, detail: str) -> CycleReport:
    """A no-trade :class:`CycleReport` for a skipped bar."""
    return CycleReport(
        cycle_ts=cycle_ts,
        status="skipped",
        traded=False,
        n_orders=0,
        n_filled=0,
        n_rejected=0,
        equity=math.nan,
        detail=detail,
    )


def _default_ledger(
    initial_cash: float,
    instruments: Mapping[str, Instrument],
    account: AccountState,
    closes: Mapping[str, float],
) -> Ledger:
    """Build a :class:`Ledger` whose positions+cash equal the broker's book.

    ``weights_to_orders`` sizes off a ledger's positions and cash; the loop seeds
    a fresh ledger from the broker so the discretizer sees the true paper book.
    Each open position is re-opened with a synthetic fill at its avg-entry (cost
    accounting is irrelevant here -- only the resulting position/cash matter), then
    cash is set to the broker's cash so marked equity matches.
    """
    from alphaforge.backtest.ledger import Ledger

    ledger = Ledger(initial_cash, instruments)
    for pos in account.positions:
        if pos.qty == 0.0:
            continue
        side = Side.BUY if pos.qty > 0.0 else Side.SELL
        ledger.apply_fill(
            Fill(
                client_order_id=f"seed-{pos.instrument_id}",
                instrument_id=pos.instrument_id,
                side=side,
                qty=abs(pos.qty),
                price=pos.avg_entry_price,
                fee_quote=0.0,
                liquidity=Liquidity.TAKER,
                ts=pos.opened_ts,
            )
        )
    # Override cash so the ledger's marked equity equals the broker's account.
    _force_cash(ledger, account.cash_quote)
    return ledger


def _force_cash(ledger: Ledger, cash: float) -> None:
    """Set the ledger's free cash to ``cash`` (post-seed reconciliation).

    The seed fills above moved cash by their notionals; the broker's true free
    cash is authoritative, so we set it directly. The ledger exposes ``cash`` as a
    read-only property; this writes the private slot once, at construction, which
    is the single sanctioned place the loop owns the seeded ledger.
    """
    object.__setattr__(ledger, "_cash", cash)


# --------------------------------------------------------------------------- seam types

if TYPE_CHECKING:
    from collections.abc import Callable

    type _Clock = Callable[[], Ms]
    type _Sleeper = Callable[[float], None]
    type _CostInputsFactory = Callable[[Ms, Sequence[str]], CostInputSource]
    type _ContextFactory = Callable[..., StrategyContext]
    type _InstrumentsFactory = Callable[[Ms], Mapping[str, Instrument]]
    type _LedgerFactory = Callable[
        [float, Mapping[str, Instrument], AccountState, Mapping[str, float]], Ledger
    ]
