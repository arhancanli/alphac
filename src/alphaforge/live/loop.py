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

Per-cycle clock sanity (buildabilityCritique.md section 4, last bullet)
----------------------------------------------------------------------
An optional :class:`ClockSanityCheck` (Phase-8 ``ops/clock.py``) is consulted
once per cycle: it compares the LOCAL wall clock against the exchange server
time and reports the skew. The loop never HALTS on skew in v1 -- the staleness
breaker plus the ingest grace already protect the DATA path -- but a large skew
means the local clock has drifted versus the exchange, so the bar-close decision
TIMING (when the loop believes a bar closed, and thus when it reads/decides) is
unreliable even when the data is fresh. The loop therefore ALERTS (WARN) and
COUNTS the breach (:attr:`clock_skew_alerts`, surfaced on the
:class:`CycleReport`) so a 30-day unattended soak SURFACES clock drift rather
than silently deciding on a mistimed bar. When no clock sanity is injected
(backtests/tests) the check is skipped cleanly.

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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

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
    OrderStatus,
    Side,
)
from alphaforge.execution.broker import BrokerAck
from alphaforge.execution.paper import (
    PaperBroker,
    PaperFillAudit,
    PaperPosition,
    PaperState,
)
from alphaforge.execution.reconcile import EquityStatus, Reconciler
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
    from alphaforge.execution.reconcile import InstrumentRecon
    from alphaforge.live.alerts import Alerter
    from alphaforge.risk import DrawdownLadder, KillSwitch, PreTradeChecker, StalenessBreaker

__all__ = [
    "ClockSanityCheck",
    "ClockSanityResult",
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

    def newest_rebalance_ms(self) -> Ms | None:
        """Epoch-ms of the newest rebalance ON RECORD, or None if it cannot be determined.

        OPTIONAL — the loop duck-types this and treats its absence as "cannot tell, do nothing",
        so an adapter that does not implement it keeps exactly the old boundary-only behaviour.
        It exists so the loop can notice that a monthly rebalance was MISSED and repair it on the
        next healthy cycle, instead of silently waiting for the next 1st. Returning None must mean
        "unknown", never "stale": guessing stale would trigger a rebuild on every cycle.
        """
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
class ClockSanityResult(Protocol):
    """The per-cycle clock-check outcome the loop reads (structural seam).

    Satisfied by ``alphaforge.ops.clock.ClockCheck`` without importing it: the
    loop only needs the two fields it acts on. ``ok`` is True iff the local clock
    is within the configured skew of the exchange (``|skew_ms| <= max_skew_ms``);
    ``skew_ms`` is the SIGNED local-minus-exchange skew in milliseconds, surfaced
    in the alert/log so the operator can see the magnitude and direction of drift.
    """

    @property
    def ok(self) -> bool:
        """True iff ``|skew_ms| <= max_skew_ms`` (the local clock is trustworthy)."""
        ...

    @property
    def skew_ms(self) -> int:
        """Signed local-minus-exchange skew in milliseconds (positive = local ahead)."""
        ...


@runtime_checkable
class ClockSanityCheck(Protocol):
    """The per-cycle clock-sanity probe the loop OPTIONALLY consults (Phase-8 seam).

    Satisfied structurally by ``alphaforge.ops.clock.ClockSanity`` (built in
    ``ops/clock.py`` against the documented contract: ``ClockSanity(source, *,
    max_skew_ms=2000)`` with ``check(*, now: Ms) -> ClockCheck``). The loop never
    imports that concrete class -- it depends only on this shape so the two files
    compose without a build-time coupling. ``check`` MUST NOT raise on a network
    or exchange-time failure (the source owns that defence): a clock probe must
    never be able to kill the 24/7 loop.
    """

    def check(self, *, now: Ms) -> ClockSanityResult:
        """Compare the local clock ``now`` (epoch-ms UTC) against exchange time."""
        ...


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

    ``clock_skew`` is True when the per-cycle clock-sanity check FAILED this cycle
    (the local clock drifted beyond ``max_skew_ms`` versus the exchange). The loop
    did NOT halt -- it alerted and counted the breach -- but the operator must SEE
    that the bar-close decision timing for this cycle was made on a clock the
    system itself does not trust (a 30-day-soak surfacing signal, not a silent
    log). False both when the clock was in-skew and when no clock sanity was
    injected (backtests/tests).
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
    clock_skew: bool = False


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
        clock_sanity: optional per-cycle :class:`ClockSanityCheck` (Phase-8
            ``ops/clock.py``). When supplied, every cycle compares the local clock
            against the exchange and a breach (``|skew| > max_skew_ms``) fires a
            WARN alert + increments :attr:`clock_skew_alerts` (it never halts in
            v1). ``None`` (the default; backtests/tests) skips the check cleanly.
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
        clock_sanity: ClockSanityCheck | None = None,
        updater: DataUpdater,
        watermark: WatermarkSource,
        cost_inputs_factory: _CostInputsFactory,
        ctx_factory: _ContextFactory,
        instruments_factory: _InstrumentsFactory,
        universe_refresher: UniverseRefresher | None = None,
        # Funding settlements for the window just closed. Optional and defaulted so every
        # existing caller and test is unaffected: a loop without one books no funding, which
        # is exactly what shipped before 2026-08-06. Wired for the crypto profile in
        # cli/paper_cmds.py, where the PIT reader already exists.
        funding_source: _FundingSource | None = None,
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
        self._clock_sanity = clock_sanity
        self._updater = updater
        self._watermark = watermark
        self._cost_inputs_factory = cost_inputs_factory
        self._ctx_factory = ctx_factory
        self._instruments_factory = instruments_factory
        self._universe_refresher = universe_refresher
        self._funding_source = funding_source
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
        #: Cycles whose per-cycle clock-sanity check FAILED (local clock drifted vs
        #: the exchange beyond max_skew_ms). Counted + WARN-alerted, never halted.
        self._clock_skew_alerts = 0
        #: Last bar open observed by run_forever, to count bars slept through (C8).
        self._last_seen_bar: Ms | None = None
        #: Consecutive cycles that held PERP legs and yet booked NO funding. A perpetuals
        #: book settles at worst every 8h, so on an hourly loop this can legitimately reach
        #: ~8; it can never legitimately reach a full day. Escalates to CRITICAL at
        #: _FUNDING_DRY_LIMIT because the alternative is what actually happened: the read
        #: raised TypeError on every single call for 44 days, each one a lone WARN that read
        #: exactly like a transient venue hiccup, while a funding-CARRY sleeve published a
        #: track record containing no funding at all.
        self._funding_dry_cycles = 0

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

    @property
    def clock_skew_alerts(self) -> int:
        """Cycles whose clock-sanity check FAILED since boot (local-vs-exchange drift).

        Each such cycle found ``|local - exchange| > max_skew_ms`` and fired a WARN
        alert; the loop did NOT halt (v1: the staleness breaker + ingest grace
        already protect the DATA path, so a skew is a TIMING warning, not a stop).
        A non-zero, climbing count over a soak means the local clock is drifting
        versus the exchange and the bar-close decision timing is becoming
        unreliable -- the operator should fix NTP/chrony before it widens. Always
        0 when no :class:`ClockSanityCheck` was injected (the check is skipped).
        """
        return self._clock_skew_alerts

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
        3b. Replay the recorded equity curve through the :class:`DrawdownLadder`
           (:meth:`_restore_ladder`) so the risk brake carries the account's real
           high-water mark and state into this process, not a fresh one.
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
        fetched = self._recover_submitted_via_fetch_order(now=now)
        failed = self._fail_running_cycles(now=now)
        # 2b. Rebuild the drawdown ladder from the recorded equity curve BEFORE any
        # decision (it is a no-op on a truly fresh boot, whose curve is empty).
        self._restore_ladder()
        # 2c. Same durable record, second consumer: hand the strategy its equity history and
        # the overlay scale in force at each cycle, so the realized-vol leg is not 0.0 by
        # construction in a fresh process (duck-typed; a strategy without the seam is left alone).
        self._restore_strategy_history()
        # A TRULY fresh boot (no persisted state of any kind, broker untouched at
        # initial_cash) has nothing to recover or reconcile: there is no prior book
        # to diverge from. Short-circuit BEFORE seeding a synthetic opening-equity
        # row -- that seed (keyed at floor_bar(now)) would otherwise persist as a
        # phantom point on the canonical equity curve whenever the first traded
        # cycle runs at a DIFFERENT cycle_ts than now (e.g. replaying historical
        # bars), polluting the per-cycle N/M accounting. In production the seed and
        # the first cycle coincide and the upsert overwrites it; this guard makes
        # the invariant hold unconditionally instead of by coincidence.
        if self._is_fresh_boot(restored=restored, replayed=replayed, fetched=fetched):
            _log.info("boot.fresh", equity_broker=self._broker.account().equity_quote)
            return
        self._sync_book_snapshot_after_recovery(replayed=replayed, fetched=fetched, now=now)
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
            fetched_fills=fetched,
            failed_cycles=len(failed),
            n_inflight=len(report.inflight),
            n_adoptions=len(report.adoptions),
            equity_broker=report.equity_broker,
        )
        if replayed or fetched or failed or report.inflight or report.adoptions:
            self._alerter.alert(
                AlertLevel.WARN,
                f"boot recovery: restored={restored} replayed_fills={replayed} "
                f"fetched_fills={fetched} failed_cycles={len(failed)} "
                f"inflight={len(report.inflight)} adoptions={len(report.adoptions)}",
            )
        # C10c: a WARN-tier equity drift (0.5%-2%) did NOT halt the reconcile, but
        # the operator must see it building before it escalates to the 2% HALT.
        if report.equity_status is EquityStatus.WARN:
            self._alerter.alert(
                AlertLevel.WARN,
                f"reconcile equity WARN: book={report.equity_book:.2f} "
                f"broker={report.equity_broker:.2f} (>0.5%, <2%) -- trading continues",
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

    def _recover_submitted_via_fetch_order(self, *, now: Ms) -> int:
        """Re-discover venue fills lost in the submit->persist crash window (gate C5).

        :meth:`_replay_recorded_fills` recovers fills the STORE durably recorded
        but the broker blob missed. The opposite gap is a crash AFTER the order
        was sent to the venue but BEFORE the loop persisted the fill: the store
        holds a SUBMITTED intent with ``filled_qty == 0`` and has NO fill row, yet
        the order may actually have executed. The reconciler cannot heal this
        alone -- with no store fill it would mark the intent REJECTED, an audit lie
        about a real position. So for every such intent we ASK the broker by
        ``client_order_id`` (execDesign.md s8.3 idempotency backbone): if
        :meth:`~alphaforge.execution.broker.Broker.fetch_order` returns a
        :class:`Fill`, the venue executed it -- ingest it idempotently (book it
        into the broker, then persist it to the store only if not already on
        file) so the reconcile that follows sees agreement.

        Idempotent and safe to re-run: ``apply_recorded_fill`` is a no-op for an
        already-acked id, and the store is only written when ``fills_for`` shows
        the fill is genuinely missing. For :class:`PaperBroker` ``fetch_order``
        always returns ``None`` (paper fills are never lost behind the broker), so
        this is a quiet no-op in v1; it is the recovery path the live broker needs.
        Returns the count of fills newly recovered.
        """
        recovered = 0
        for intent in self._store.open_intents():
            if intent.status != OrderStatus.SUBMITTED.value or intent.filled_qty > 0.0:
                continue
            coid = intent.client_order_id
            if self._store.fills_for(coid):
                continue  # already has a fill row -> not a lost-fill case
            fill = self._broker.fetch_order(coid)
            if fill is None:
                continue  # venue never executed it -> reconcile marks it REJECTED
            # Book the recovered fill into the broker (idempotent on coid), then
            # persist it to the store so the order advances to FILLED/PARTIAL.
            self._broker.apply_recorded_fill(fill)
            self._store.mark_filled(fill, now=now)
            recovered += 1
            _log.warning(
                "boot.fetch_order_recovered",
                client_order_id=coid,
                instrument_id=intent.instrument_id,
                qty=fill.qty,
                price=fill.price,
            )
        return recovered

    def _sync_book_snapshot_after_recovery(
        self, *, replayed: int, fetched: int, now: Ms
    ) -> None:
        """Adopt recovered broker truth into the book ONLY when reconcile says to (C7).

        After :meth:`_replay_recorded_fills` / :meth:`_recover_submitted_via_fetch_order`
        the broker book is correct (rebuilt from the store's own durable fills),
        but the persisted equity/positions snapshot can lag it -- a mid-batch
        crash records fills but dies before its end-of-cycle snapshot, and a fresh
        boot has the broker at ``initial_cash`` while the book is empty. Left
        as-is the following reconcile would SPURIOUSLY halt on that lag.

        The OLD fix wrote the broker book into the store UNCONDITIONALLY and then
        let reconcile read it back -- a tautological write-then-compare that
        defeated reconcile (it could never see a real divergence, because we had
        already overwritten the book with broker truth). The C7 fix reverses the
        order: RECONCILE FIRST (a read-only
        :meth:`~alphaforge.execution.reconcile.Reconciler.classify` probe against
        broker truth), and adopt -- snapshot the broker account into the book --
        ONLY when that probe is not already ``ok`` (positions AND equity agree).
        On a clean restart the probe is ``ok``, so NOTHING is
        written and the gate reconcile that follows is a genuine, not
        rubber-stamped, comparison. A pure-equity lag with no position drift (the
        fresh-boot opening seed: a flat broker at ``initial_cash`` vs an empty
        book) has no position adoptions but still fails ``ok`` on equity, so it is
        seeded here -- preserving the old opening-seed behavior.

        Before adopting, every position adoption is checked to be BACKED BY DURABLE
        STORE FILLS: the broker book was rebuilt from the store's own fills (the
        restored blob plus :meth:`_replay_recorded_fills` /
        :meth:`_recover_submitted_via_fetch_order`), so each broker position must
        be reproduced by summing the store's recorded signed fill quantities for
        that instrument. A broker position the store CANNOT explain (no backing
        fill -- impossible for PaperBroker, the real-money hazard later) is NOT
        adopted, so it survives to the real :meth:`reconcile` gate and halts as it
        must. This keeps the 'never masks a genuine divergence' guarantee true by
        construction rather than by assuming the paper broker can never diverge.

        The adopted snapshot is keyed at ``as_of`` (``now``, the reconcile
        instant) -- not ``floor_bar(now)`` -- so its key matches the timestamp its
        equity is marked at (``account_at(now)``) and it becomes the latest book
        row the gate reconcile reads, marked at the same instant as the broker
        equity it is compared against (C3 alignment).
        """
        probe = self._reconciler.classify(as_of=now)
        if probe.ok:
            return  # book already agrees with broker (positions + equity) -> no-op
        if not self._adoptions_backed_by_store_fills(probe.adoptions):
            # A broker position the store's durable fills cannot explain: do NOT
            # silently adopt it. Leave the lagging book so the gate reconcile that
            # follows halts on the unexplained divergence.
            _log.warning(
                "boot.sync_skipped_unbacked_divergence",
                n_adoptions=len(probe.adoptions),
                n_divergent=probe.n_divergent,
            )
            return
        account = self._broker.account_at(now)
        self._store.snapshot_equity(now, account)
        self._store.snapshot_positions(now, account.positions)
        _log.info(
            "boot.sync_adopted",
            as_of=now,
            replayed=replayed,
            fetched=fetched,
            n_adoptions=len(probe.adoptions),
        )

    def _adoptions_backed_by_store_fills(
        self, adoptions: Sequence[InstrumentRecon]
    ) -> bool:
        """True iff every adoption's broker qty is reproduced by the store's fills.

        The broker book is rebuilt from the store's durable fills on recovery, so a
        legitimate adoption (broker position the persisted snapshot just lagged) is
        exactly the net of the store's recorded signed fill quantities for that
        instrument. We recompute that net per instrument and require it to match
        the broker qty within the reconciler's quantity tolerance. Any adoption the
        store's fills cannot account for is an UNBACKED divergence -- we refuse to
        adopt it (the gate reconcile then halts on it). Defensive against the
        future live broker; for PaperBroker every position is backed, so this
        passes whenever a real lag is being recovered.
        """
        store_qty: dict[str, float] = {}
        for record in self._store.fills_since(0):
            fill = record.fill
            store_qty[fill.instrument_id] = (
                store_qty.get(fill.instrument_id, 0.0) + fill.side.sign * fill.qty
            )
        tol = self._reconciler.tolerance
        for adoption in adoptions:
            implied = store_qty.get(adoption.instrument_id, 0.0)
            if not tol.qty_within(implied, adoption.broker_qty):
                return False
        return True

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

    def _restore_ladder(self) -> None:
        """Rebuild the live :class:`~alphaforge.risk.DrawdownLadder` from the equity curve.

        THE DEFECT THIS REPAIRS (found 2026-09-05). Production runs ``af paper run
        --once``: a fresh process per hourly cycle. The ladder is constructed in that
        process and lived only in its memory, so every cycle started it pristine --
        the first ``update(equity)`` set HWM to the CURRENT equity, drawdown read 0.0,
        state NORMAL -- and the 10% halve / 15% flatten brakes could never fire, on any
        drawdown of any depth. :meth:`_restore_paper_state` restored cash, positions,
        acks and fills, and never the ladder. On the crypto sleeve the persisted
        snapshot read ``hwm=90,504 drawdown=0.0`` while the recorded curve had peaked at
        101,294 -- a 10.6% drawdown the brake never saw.

        The ``equity_curve`` table is the one durable record of what the account did
        (one row per completed cycle, in order). Replaying it bar by bar through
        :meth:`DrawdownLadder.update` is exactly what a long-lived process would have
        done -- the same HWM, the same hysteresis, the same absorbing FLAT_HALTED
        state and cooldown clock -- so the restored ladder is the ladder, not an
        approximation of it. The persisted ``ladder_state`` row is NOT used as the
        source: it was written by the same fresh-per-cycle ladders and carries the
        defect.

        No-op when the ladder already has a mark (a long-lived ``--forever`` process
        booting once carries its own history) or when the curve is empty (a truly
        fresh boot). Non-finite / non-positive rows are skipped and counted, never
        fed to the ladder (which would raise). Deliberately does NOT seed the
        strategy's realized-vol equity history: that leg also needs the per-bar
        overlay scale, which is not persisted, and a partial seed would be a
        different book. Tracked separately.
        """
        if not math.isnan(self._ladder.hwm):
            return
        rows = self._store.equity_curve()
        if not rows:
            return
        replayed = 0
        skipped = 0
        for row in rows:
            equity = float(row[1])
            if not math.isfinite(equity) or equity <= 0.0:
                skipped += 1
                continue
            self._ladder.update(equity)
            replayed += 1
        state = self._ladder.state
        mult = self._ladder.gross_multiplier()
        _log.info(
            "boot.ladder_restored",
            replayed=replayed,
            skipped=skipped,
            hwm=self._ladder.hwm,
            drawdown=self._ladder.drawdown,
            state=state.value,
            gross_mult=mult,
        )
        if mult < 1.0:
            self._alerter.alert(
                AlertLevel.WARN,
                f"boot: drawdown ladder restored in {state.value} "
                f"(drawdown {self._ladder.drawdown:.2%} from hwm {self._ladder.hwm:.2f}); "
                f"gross multiplier {mult}",
            )

    def _restore_strategy_history(self) -> None:
        """Seed the strategy's realized-vol history from ``equity_curve`` (+ overlay scale).

        Companion to :meth:`_restore_ladder`, same defect: ``BlendStrategy`` keeps the equity
        history and the per-bar overlay scale in memory, so under ``--once`` the realized leg
        of ``max(ex_ante, realized)`` was 0.0 every cycle. The loop now persists the scale in
        force with each equity row, and on boot hands the strategy the whole recorded curve
        through its optional ``seed_history`` seam. Rows older than the column carry NaN, which
        the de-lever masks rather than misreads. The strategy refuses the seed when it already
        has history, so a long-lived process is never overwritten.
        """
        seed = getattr(self._strategy, "seed_history", None)
        if seed is None:
            return
        points = self._store.equity_curve_points()
        if not points:
            return
        try:
            accepted = bool(seed([(p.equity_quote, p.overlay_scale) for p in points]))
        except ValueError as exc:
            self._alerter.alert(AlertLevel.WARN, f"boot: strategy history not restored: {exc}")
            _log.warning("boot.strategy_history_rejected", error=str(exc))
            return
        with_scale = sum(1 for p in points if math.isfinite(p.overlay_scale))
        _log.info(
            "boot.strategy_history_restored",
            accepted=accepted,
            points=len(points),
            with_scale=with_scale,
        )

    def _fail_running_cycles(self, *, now: Ms) -> list[Ms]:
        """Mark every interrupted ``'running'`` cycle ``'failed'``; return their ids."""
        failed: list[Ms] = []
        for cycle in self._store.running_cycles():
            self._store.finish_cycle(
                cycle.cycle_ts, "failed", "interrupted: resolved on restart", now=now
            )
            failed.append(cycle.cycle_ts)
        return failed

    def _is_fresh_boot(self, *, restored: bool, replayed: int, fetched: int) -> bool:
        """True iff this boot has NO prior state to recover or reconcile.

        Fresh means: no ``paper_state`` blob was restored, no store fills were
        replayed onto the broker, no fill was re-discovered via ``fetch_order``,
        the store holds no equity history and no orders of any status, and the
        broker book is untouched (flat, cash == ``initial_cash``). Under those
        conditions there is nothing a reconcile could compare -- the (empty) book
        trivially equals the (initial) broker -- so the loop skips both the
        synthetic opening-equity seed and the reconcile. ANY trace of prior
        activity (a blob, a replayed fill, a fetched fill, a recorded order, an
        equity row, or a non-flat / non-initial broker) makes this False and the
        full recover+reconcile path runs.

        Deliberately conservative: it must never short-circuit a boot that has real
        state to reconcile, because that would let the loop trade on an
        un-reconciled book. Every clause is necessary; a False from any one is safe.
        """
        if restored or replayed > 0 or fetched > 0:
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

        # Per-cycle clock sanity (buildabilityCritique.md section 4): compare the
        # local clock against the exchange ONCE per cycle. A breach is ALERTED +
        # COUNTED and stamped onto the report, but the loop does NOT halt in v1 --
        # a clock skew makes the bar-close decision TIMING unreliable, yet the
        # staleness breaker + ingest grace already guard the DATA path.
        clock_skew = self._check_clock_sanity(cycle_ts, now=now)

        # The clock verdict is stamped onto WHICHEVER report this cycle produces
        # (success, skip, halt, or fail) without touching the body/finishers --
        # one place, additive, behavior-preserving.
        try:
            report = self._run_cycle_body(cycle_ts, now=now)
        except (RiskLimitError, ReconciliationError) as exc:
            # A risk/reconciliation breach is recorded distinctly as 'halted'.
            report = self._finish_failed(cycle_ts, f"risk halt: {exc}", now=now, halt=True)
        except Exception as exc:
            # Catch-all over NORMAL exceptions ONLY (TransientBrokerError,
            # sqlite3.OperationalError, OSError, ccxt NetworkError, ...). NOT
            # BaseException: SystemExit/KeyboardInterrupt must still propagate so
            # recover_on_boot runs on the next process start.
            report = self._finish_failed(cycle_ts, f"{type(exc).__name__}: {exc}", now=now)
        return replace(report, clock_skew=clock_skew) if clock_skew else report

    def _check_clock_sanity(self, cycle_ts: Ms, *, now: Ms) -> bool:
        """Probe local-vs-exchange clock skew this cycle; alert+count a breach.

        No-op (returns False) when no :class:`ClockSanityCheck` was injected. When
        one is present it is called with the loop's wall-clock ``now`` (the same
        instant the cycle reads). On an in-skew result this is a quiet success. On
        a breach (``not result.ok``) the loop fires a WARN alert naming the signed
        skew, increments :attr:`clock_skew_alerts`, logs it, and returns True so
        the caller can stamp the :class:`CycleReport`. It NEVER raises and NEVER
        halts: a clock skew is a TIMING warning (the bar-close decision instant is
        suspect), not a data-integrity stop -- the staleness breaker owns the data
        path. A probe that itself raised would be caught by ``run_cycle``'s
        catch-all and merely fail the cycle, so the contract asks the probe to be
        total; here we additionally swallow any escape into a no-skew result so a
        flaky clock source can never even fail a cycle.
        """
        if self._clock_sanity is None:
            return False
        try:
            result = self._clock_sanity.check(now=now)
        except Exception as exc:  # a clock probe must never disturb the cycle
            _log.warning("cycle.clock_probe_failed", cycle_ts=cycle_ts, error=str(exc))
            return False
        if result.ok:
            return False
        self._clock_skew_alerts += 1
        self._alerter.alert(
            AlertLevel.WARN,
            f"cycle {cycle_ts}: CLOCK SKEW {result.skew_ms:+d} ms vs exchange "
            f"(local clock drifted; bar-close decision timing is unreliable -- "
            f"check NTP/chrony). Trading continues (data path is guarded).",
        )
        _log.warning("cycle.clock_skew", cycle_ts=cycle_ts, skew_ms=result.skew_ms)
        return True

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

        # (1b) SETTLE FUNDING for the window just closed, BEFORE the book is marked or
        # re-decided. Added 2026-08-06. `Ledger.apply_funding` existed and was reachable from
        # exactly one place, the BACKTEST engine, so the live account moved cash only on fills
        # and a funding-CARRY sleeve never received the cashflow that is its entire mechanism
        # (~51% of its lifetime backtest PnL). Ordering matters: funding settles against the
        # position that was actually held through the settlement, so it must land before the
        # strategy re-decides and changes that position.
        self._settle_funding(cycle_ts, instruments)

        # (2) monthly boundary: refresh the universe BEFORE signals (finding 21).
        #
        # SELF-HEALING, added 2026-08-11 after the rebalance was silently lost TWICE.
        # `_is_month_boundary` is true for exactly ONE bar a month — 00:00 UTC on the 1st — so the
        # old condition gave the rebalance a single attempt with no retry. Miss that one cycle for
        # any reason and the universe does not move for a month. That is not hypothetical: the
        # crypto sleeve was dark across both 2026-07-01 and 2026-08-01, so it spent ten weeks
        # trading a cross-section chosen on 2026-06-01, and nobody noticed until it was looked for.
        #
        # A once-a-month trigger with no catch-up is the defect, not the venue outage. So the loop
        # now ALSO refreshes when the stored membership is older than the current month — the same
        # monthly cadence, but it repairs itself on the next healthy cycle instead of waiting for
        # the next 1st. `refresh` is idempotent (the builder is deterministic and rerun-safe), so a
        # boundary cycle and a catch-up cycle produce the same membership.
        #
        # NOTE this refreshes FORWARD only. It does not reconstruct rebalances that were missed in
        # the past: those decisions were never made, and a PIT rebuild of them would use data that
        # did not exist at the time (verified — a PIT rebuild at 2026-07-01 sees only the ~20 names
        # the lake actually held then, not the 627 since backfilled). Inventing a decision the book
        # never took would be fabricating history, which is worse than a stale universe.
        if self._universe_refresher is not None and (
            _is_month_boundary(cycle_ts) or self._universe_is_stale(cycle_ts)
        ):
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

        # (7) persist the post-trade book + equity + paper_state; finish 'ok'. The overlay
        # scale in force after this decision rides along on the equity row so a fresh --once
        # process can rebuild the realized-vol leg's de-lever history
        # (see _restore_strategy_history).
        marked = self._broker.account_at(cycle_ts)
        scale = getattr(self._strategy, "last_scale", math.nan)
        overlay_scale = float(scale) if isinstance(scale, (int, float)) else math.nan
        self._persist_book(cycle_ts, marked, now=now, overlay_scale=overlay_scale)
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
            # Persist WHY the strategy held (its per-cycle hold counters), so a dead signal can
            # never masquerade as a quiet hold again — 173 signal-dead cycles once read as
            # "hold: no target change" and were misdiagnosed as compressed carry (2026-07-05
            # correction). Under --once the counters are this-cycle-only, exactly what we want.
            detail = "hold: no target change"
            counters = getattr(self._strategy, "counters", None)
            if isinstance(counters, Mapping):
                active = {k: v for k, v in counters.items() if v and k.startswith("hold_")}
                if active:
                    detail += " (" + ", ".join(f"{k}={v}" for k, v in sorted(active.items())) + ")"
            return CycleReport(
                cycle_ts=cycle_ts,
                status="ok",
                traded=False,
                n_orders=0,
                n_filled=0,
                n_rejected=0,
                equity=account.equity_quote,
                detail=detail,
                degraded=degraded,
                dropped_book_instruments=0,
            )

        closes, dropped = self._closes_for(cycle_ts, account, instruments)
        if dropped:
            # C9: instruments silently dropped from sizing for want of a book mid.
            self._dropped_book_instruments += dropped
            _log.warning("cycle.dropped_book", cycle_ts=cycle_ts, n_dropped=dropped)
        # Per-instrument tradability: a TARGET with no valid close at the decision bar is
        # untradeable THIS bar (a mid-month member whose data went stale/delisted, e.g. TONUSDT
        # 2026-07-05: funding stopped 06-23 so it still carries a mu, but there is no price).
        # Drop it from the target book — conservative: its weight simply is not deployed, gross
        # runs slightly under target — instead of failing the whole cycle. weights_to_orders
        # keeps its hard raise as the backstop for anything that slips past this filter, and
        # HELD positions are unaffected (marking those is the systemic-breach guard's domain).
        stale = [
            iid for iid in targets
            if not isinstance((c := closes.get(iid)), int | float)
            or not math.isfinite(c) or c <= 0.0
        ]
        if stale:
            self._dropped_book_instruments += len(stale)
            _log.warning(
                "cycle.stale_targets_dropped", cycle_ts=cycle_ts,
                n=len(stale), instruments=sorted(stale)[:8],
            )
            targets = {iid: w for iid, w in targets.items() if iid not in set(stale)}
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
            # Fresh once the JUST-CLOSED bar (cycle_ts - one bar) has landed: its
            # close IS the cycle_ts-instant mark, and it is the data the decision for
            # cycle_ts consumes (signal at the prior close -> act at the cycle_ts open).
            # Requiring the cycle_ts bar ITSELF is impossible (it is still forming) and
            # would spuriously flag EVERY live cycle "degraded".
            if latest is not None and latest >= cycle_ts - self._bar_ms:
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

    def _settle_funding(self, cycle_ts: Ms, instruments: Mapping[str, object]) -> None:
        """Book every funding settlement in (prev_cycle, cycle_ts] against the live position.

        The stored events ARE the schedule, so applying them one by one is automatically
        interval-aware (8h / 4h / 1h per instrument) and never assumes a clock -- the same
        property the backtest engine relies on (leakageCritique.md finding 6).

        Deliberately forgiving: no funding source, no perps, or a source that raises all mean
        "book nothing this cycle" rather than "halt the sleeve". A funding read is an accounting
        improvement, and it must never be able to stop the book from trading -- a missed cycle
        is a permanent hole in the forward record, which is the most valuable asset here.

        FORGIVING PER CYCLE, NOT FORGIVING FOREVER. Being forgiving is right; being forgiving
        without ever counting is how this sleeve ran 44 days on a funding read that raised on
        every call. Each failure was a single WARN indistinguishable from a venue blip, so a
        PERMANENT breakage wore the costume of a TRANSIENT one. `_funding_dry_cycles` is what
        makes the difference observable, and it must be allowed to reach CRITICAL.
        """
        if self._funding_source is None:
            return
        prev = cycle_ts - self._bar_ms
        try:
            events = self._funding_source(sorted(instruments), start=prev, end=cycle_ts)
        except Exception as exc:
            self._alerter.alert(
                AlertLevel.WARN, f"cycle {cycle_ts}: funding read failed, booked none ({exc})"
            )
            self._note_funding_dry(cycle_ts, instruments, reason=f"read failed ({exc})")
            return
        total, applied = 0.0, 0
        for iid, ts_funding, rate in events:
            mark = self._book_mid(iid, cycle_ts)
            if mark is None or not (mark > 0.0):
                continue  # no observed mark -> we do not invent one (see paper_trading_state)
            try:
                paid = self._broker.apply_funding(iid, ts_funding, rate, mark)
            except ValueError as exc:  # a single bad rate must not poison the cycle
                self._alerter.alert(
                    AlertLevel.WARN, f"cycle {cycle_ts}: funding skipped for {iid}: {exc}"
                )
                continue
            if paid != 0.0:
                total += paid
                applied += 1
        if applied:
            _log.info("funding_settled", cycle_ts=cycle_ts, events=applied, quote=round(total, 6))
            self._funding_dry_cycles = 0
        else:
            self._note_funding_dry(cycle_ts, instruments, reason="no events booked")

    #: Consecutive perp-holding cycles with zero funding booked before this stops being
    #: treated as normal. 8h is the longest funding interval any venue we trade uses, so on
    #: an hourly loop ~8 dry cycles is ordinary and 24 is not physically possible.
    _FUNDING_DRY_LIMIT: Final[int] = 24

    def _note_funding_dry(
        self, cycle_ts: Ms, instruments: Mapping[str, object], *, reason: str
    ) -> None:
        """Count a cycle that booked no funding, and escalate once it stops being plausible.

        Only counts while PERP legs are actually held: a book holding no perps owes and earns
        no funding, so counting those cycles would build a warning that fires for a healthy
        system -- and a check that cries wolf gets muted, which is how you end up with no
        check at all.
        """
        holds_perp = any(
            getattr(getattr(i, "market_type", None), "name", "") == "PERP"
            for i in instruments.values()
        )
        if not holds_perp:
            self._funding_dry_cycles = 0
            return
        self._funding_dry_cycles += 1
        if self._funding_dry_cycles == self._FUNDING_DRY_LIMIT:
            self._alerter.alert(
                AlertLevel.CRITICAL,
                f"cycle {cycle_ts}: {self._funding_dry_cycles} consecutive cycles holding PERP "
                f"legs have booked ZERO funding ({reason}). A perpetuals book settles at worst "
                f"every 8h, so this is not a venue hiccup -- the funding path is broken and the "
                f"sleeve is accruing a track record that omits its own carry.",
            )

    def _persist_book(
        self, cycle_ts: Ms, account: AccountState, *, now: Ms, overlay_scale: float = math.nan
    ) -> None:
        """Snapshot positions + equity (+ the overlay scale in force) + the paper_state blob."""
        self._store.snapshot_positions(
            cycle_ts,
            account.positions,
            marks=self._broker.position_marks_at(cycle_ts),
        )
        self._store.snapshot_equity(cycle_ts, account, overlay_scale=overlay_scale)
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

    def _universe_is_stale(self, cycle_ts: Ms) -> bool:
        """True when the newest rebalance on record predates ``cycle_ts``'s calendar month.

        THE FAILURE THIS REPAIRS. The universe rebalances on the first bar of each UTC month, and
        that was its ONLY trigger — one cycle per month, no retry. The crypto sleeve was dark
        across both 2026-07-01 and 2026-08-01, so it traded a 2026-06-01 cross-section for ten
        weeks. The outage was the occasion; the single-attempt trigger was the defect.

        Deliberately conservative in three ways, because a rebuild that fires when it should not is
        worse than one that fires late:
          * an adapter that cannot answer (no method, or None) yields False — unknown is not stale;
          * any error yields False, so a broken read can never spin the loop into rebuilding every
            cycle;
          * it compares CALENDAR MONTHS, not elapsed days, so it matches the declared monthly
            cadence exactly and cannot drift into rebalancing more often than the policy says.
        """
        getter = getattr(self._universe_refresher, "newest_rebalance_ms", None)
        if getter is None:
            return False
        try:
            newest = getter()
        except Exception:
            return False
        if newest is None:
            return False
        from alphaforge.core.time import from_ms

        a, b = from_ms(int(newest)), from_ms(cycle_ts)
        return (a.year, a.month) < (b.year, b.month)

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
    # (instrument_ids, start, end) -> [(instrument_id, ts_funding, rate), ...] for the window.
    # The events ARE the schedule, so per-instrument 8h/4h/1h intervals need no clock here.
    type _FundingSource = Callable[..., Sequence[tuple[str, Ms, float]]]
