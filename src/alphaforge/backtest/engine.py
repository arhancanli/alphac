"""EventDrivenBacktester — the truth engine (execDesign.md §4.1/§4.4).

THE no-lookahead contract (leakageCritique.md findings 4/5), enforced in code,
never by convention:

* A strategy decides at the **close** of bar ``t`` and its orders fill at the
  **open** of bar ``t+1`` — never the same bar. The fill model receives only
  the ``t+1`` bar and raises :class:`~alphaforge.core.errors.LookaheadError`
  if that bar opened before the decision; the engine re-checks every returned
  fill as defense in depth.
* The strategy sees history through :class:`StrategyContext`, whose ``bars``
  accessor is a true PIT read (``as_of = decision close``) — the engine
  slices, the strategy *cannot* ask for more.
* Funding cashflows are applied by iterating the **stored funding-events
  table** per instrument (leakageCritique.md finding 6): each event carries
  its own ``ts_funding``, so 8h/4h/1h funding intervals are honoured
  automatically — there is no funding clock anywhere in this engine.
* All pricing/fee arithmetic is delegated to the ONE shared
  :class:`~alphaforge.costs.TransactionCostModel` (buildabilityCritique.md
  §3.7) via the fill model — the engine itself never computes a cost.

Event loop per bar close ``t_k`` over the union grid of all instruments'
closes (execDesign.md §4.1)::

    0. fill orders queued at t_{k-1} against each instrument's bar opening at
       t_{k-1} (missing bar => order DROPPED and counted, never filled at a
       synthetic price)
    1. apply stored funding events with ts_funding in (t_{k-1}, t_k], mark
       price proxied by the instrument's close at t_k (documented
       approximation, execDesign.md §4.3)
    2. mark the ledger at close[t_k]; record the equity point
    3. force-flat delisted instruments (last lake bar closes at t_k while a
       position is open): closed at the last available close with taker fee —
       conservative and loud (counted + logged), never a silent hold
    4. strategy.on_bar_close(ctx at t_k) -> target weights (fraction of
       equity, signed; ids absent from the mapping are LEFT UNTOUCHED — return
       an explicit 0.0 to flatten)
    5. discretize targets to orders (no-trade band, lot rounding, min-qty /
       min-notional filters) and queue them for t_{k+1}

Orders decided on the final bar have no ``t+1``: they are counted as
``unfilled_final_bar`` and produce **zero fills and no exception**.

Phase 6's SignalService + optimizer will implement the :class:`Strategy`
protocol; Phase 5 ships :class:`ScriptedStrategy` (predefined ts -> weights)
for tests and :class:`RankStrategy` as a CLI demo (NOT the product).

Money is float64 in quote units at full internal precision (rounding only at
report rendering); all timestamps are epoch-ms UTC (:data:`Ms`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Final, Protocol, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.analytics import summarize
from alphaforge.backtest.fills import BarView, FillModel, NextOpenFill
from alphaforge.backtest.ledger import Ledger
from alphaforge.backtest.result import (
    FILLS_COLUMNS,
    ORDERS_COLUMNS,
    POSITIONS_COLUMNS,
    BacktestResult,
)
from alphaforge.core.errors import LookaheadError
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms, Timeframe, expected_bar_opens
from alphaforge.core.types import (
    Fill,
    Liquidity,
    MarketType,
    OrderRequest,
    OrderType,
    Side,
)
from alphaforge.costs import TransactionCostModel
from alphaforge.data.store.reader import PITDataReader
from alphaforge.features.library.vol import ewma_vol_halflife, log_returns

__all__ = [
    "CostInputProvider",
    "EventDrivenBacktester",
    "LakeCostInputs",
    "RankStrategy",
    "ScriptedStrategy",
    "StaticCostInputs",
    "Strategy",
    "StrategyContext",
]

_DAY_MS: Final[int] = 86_400_000

#: Engine bookkeeping counter names (all always present in the result, 0 if unused).
COUNTER_NAMES: Final[tuple[str, ...]] = (
    "bars_processed",
    "orders_decided",
    "fills_applied",
    "skipped_no_trade_band",
    "skipped_below_min",
    "dropped_no_decision_bar",
    "dropped_missing_next_bar",
    "dropped_no_cost_inputs",
    "unfilled_final_bar",
    "forced_flat",
    "funding_events_applied",
)


# ---------------------------------------------------------------------------
# strategy surface
# ---------------------------------------------------------------------------


class StrategyContext:
    """The strategy's window onto the world at one bar close — PIT by construction.

    ``ts`` is the decision timestamp (a bar close, epoch-ms UTC). ``equity``
    is the marked equity at ``ts``; ``positions`` the open book; and
    ``instruments`` the full run universe (its keys are the tradable ids).
    History access goes through :meth:`bars`, which reads the lake with
    ``as_of = ts`` — bars closing after ``ts`` are structurally invisible, so
    a strategy cannot look ahead even by bug.
    """

    __slots__ = ("_equity", "_instruments", "_positions", "_reader", "_tf", "_ts")

    def __init__(
        self,
        *,
        reader: PITDataReader,
        tf: Timeframe,
        ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> None:
        self._reader = reader
        self._tf = tf
        self._ts = ts
        self._equity = equity
        self._positions = dict(positions)
        self._instruments = dict(instruments)

    @property
    def ts(self) -> Ms:
        """Decision timestamp — the bar close this callback is for (epoch-ms UTC)."""
        return self._ts

    @property
    def tf(self) -> Timeframe:
        """The engine's bar timeframe."""
        return self._tf

    @property
    def equity(self) -> float:
        """Account equity marked at :attr:`ts` (quote units, full precision)."""
        return self._equity

    @property
    def positions(self) -> Mapping[str, float]:
        """Open positions as signed base-unit quantities keyed by instrument id."""
        return dict(self._positions)

    @property
    def instruments(self) -> Mapping[str, Instrument]:
        """The run universe; keys are the ids a strategy may emit targets for."""
        return dict(self._instruments)

    def bars(self, instrument_ids: Sequence[str], lookback_bars: int) -> pa.Table:
        """PIT-read the trailing ``lookback_bars`` bars ending at :attr:`ts`.

        Returns lake rows with ``ts_open in [ts - lookback_bars*Δ, ts)`` and
        ``as_of = ts`` — exactly the bars whose close is at or before the
        decision. The newest visible bar is the one closing at ``ts`` itself.
        """
        if lookback_bars <= 0:
            raise ValueError(f"lookback_bars must be > 0, got {lookback_bars}")
        start = self._ts - lookback_bars * self._tf.ms
        return self._reader.ohlcv(
            instrument_ids, start=start, end=self._ts, as_of=self._ts, tf=self._tf
        )


class Strategy(Protocol):
    """A target-weight strategy driven by the engine, one callback per bar close.

    Returns target weights as a mapping ``instrument_id -> w`` (fraction of
    current equity, signed; -0.10 = 10% short). **Ids absent from the mapping
    are left untouched** — return an explicit ``0.0`` to flatten. Returning
    ``{}`` means "hold everything". Implementations may be stateful; the
    engine calls strictly in increasing time order within one run.

    Phase 6's SignalService + portfolio optimizer implement this protocol;
    the engine does not change when they arrive.
    """

    def on_bar_close(self, ctx: StrategyContext) -> Mapping[str, float]:
        """Decide target weights at ``ctx.ts`` using only PIT data from ``ctx``."""
        ...


class ScriptedStrategy:
    """Replays a predefined ``decision_ts -> {instrument_id: weight}`` script.

    The test/bench workhorse: deterministic, no data access. Timestamps absent
    from the script return ``{}`` (hold). The script is copied at construction.
    """

    __slots__ = ("_script",)

    def __init__(self, script: Mapping[Ms, Mapping[str, float]]) -> None:
        self._script: dict[Ms, dict[str, float]] = {
            int(ts): dict(targets) for ts, targets in script.items()
        }

    def on_bar_close(self, ctx: StrategyContext) -> Mapping[str, float]:
        """Return the scripted targets for ``ctx.ts`` (empty mapping = hold)."""
        return self._script.get(ctx.ts, {})


class RankStrategy:
    """DEMO: equal-weight long the top-K by trailing return, periodic rebalance.

    THIS IS NOT THE PRODUCT — it exists so ``af backtest run`` exercises the
    full engine on real lake data before Phase 6 lands the real signal stack.
    Every ``rebalance_bars`` bars it ranks the run universe by the trailing
    ``lookback_bars``-bar close-to-close return (PIT via ``ctx.bars``), goes
    long the top ``top_k`` at ``1/top_k`` each, and explicitly zeroes every
    other ranked instrument. Instruments without a full lookback window are
    unranked (and untouched). Stateful: tracks its next rebalance time.
    """

    __slots__ = ("_lookback_bars", "_next_rebalance_ts", "_rebalance_bars", "_top_k")

    def __init__(
        self, *, top_k: int = 10, lookback_bars: int = 168, rebalance_bars: int = 168
    ) -> None:
        if top_k <= 0 or lookback_bars <= 0 or rebalance_bars <= 0:
            raise ValueError(
                f"top_k/lookback_bars/rebalance_bars must be > 0, got "
                f"{top_k}/{lookback_bars}/{rebalance_bars}"
            )
        self._top_k = top_k
        self._lookback_bars = lookback_bars
        self._rebalance_bars = rebalance_bars
        self._next_rebalance_ts: Ms | None = None

    def on_bar_close(self, ctx: StrategyContext) -> Mapping[str, float]:
        """Rebalance when due: long top-K trailing-return names, zero the rest."""
        if self._next_rebalance_ts is not None and ctx.ts < self._next_rebalance_ts:
            return {}
        self._next_rebalance_ts = ctx.ts + self._rebalance_bars * ctx.tf.ms

        ids = sorted(ctx.instruments)
        window = self._lookback_bars + 1  # need close at t and close 168 bars earlier
        tbl = ctx.bars(ids, window)
        if tbl.num_rows == 0:
            return {}
        frame = pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": tbl.column("ts_open").cast(pa.int64()).to_pylist(),
                "close": tbl.column("close").to_pylist(),
            }
        )
        newest_open = ctx.ts - ctx.tf.ms
        oldest_open = ctx.ts - window * ctx.tf.ms
        returns: dict[str, float] = {}
        for iid, grp in frame.groupby("instrument_id", sort=True):
            by_open = dict(zip(grp["ts_open"], grp["close"], strict=True))
            c_now = by_open.get(newest_open)
            c_then = by_open.get(oldest_open)
            if c_now is None or c_then is None or c_then <= 0.0:
                continue  # incomplete window: unranked, position untouched
            returns[str(iid)] = float(c_now) / float(c_then) - 1.0
        if not returns:
            return {}
        ranked = sorted(returns, key=lambda i: (-returns[i], i))
        top = ranked[: self._top_k]
        w = 1.0 / len(top)
        return {iid: (w if iid in top else 0.0) for iid in ranked}


# ---------------------------------------------------------------------------
# cost inputs (ADV / sigma_daily as of the decision bar)
# ---------------------------------------------------------------------------


class CostInputProvider(Protocol):
    """Supplies the cost model's per-order inputs as of a decision timestamp."""

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        """Return ``(adv_quote, sigma_daily)`` as of ``decision_ts`` (NaN = unknown)."""
        ...


class StaticCostInputs:
    """Fixed ``(adv_quote, sigma_daily)`` for every instrument and timestamp.

    For tests and quick what-ifs where hand-computable fills matter more than
    realism. Production runs use :class:`LakeCostInputs`.
    """

    __slots__ = ("_adv_quote", "_sigma_daily")

    def __init__(self, *, adv_quote: float, sigma_daily: float) -> None:
        if not math.isfinite(adv_quote) or adv_quote <= 0.0:
            raise ValueError(f"adv_quote must be finite and > 0, got {adv_quote!r}")
        if not math.isfinite(sigma_daily) or sigma_daily <= 0.0:
            raise ValueError(f"sigma_daily must be finite and > 0, got {sigma_daily!r}")
        self._adv_quote = adv_quote
        self._sigma_daily = sigma_daily

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        """Return the fixed pair regardless of instrument/timestamp."""
        return (self._adv_quote, self._sigma_daily)


class LakeCostInputs:
    """ADV / sigma_daily computed from the lake with THE library formulas.

    Same definitions as the registered features in
    :mod:`alphaforge.features.library.market` (which need a full
    ``FeatureContext``/registry pipeline — deliberately not dragged into the
    backtester; the formulas are shared via the sanctioned primitive bodies
    :func:`~alphaforge.features.library.vol.ewma_vol_halflife` /
    :func:`~alphaforge.features.library.vol.log_returns`, and the ADV
    mechanics below mirror ``market._adv_quote_fn`` line for line):

    * ``adv_quote`` — 30-day rolling MEDIAN of daily quote volume (USDT/day);
      daily = 1h ``quote_volume`` summed per complete UTC day; the value at
      decision time ``t`` covers the last 30 UTC days fully completed by ``t``.
    * ``sigma_daily`` — zero-mean EWMA vol of 1h log returns (halflife 240
      bars = 10 days) scaled by ``sqrt(24)``.

    Everything is computed ONCE over ``[start - warmup, end)`` at
    construction; per-decision lookups are then positional. The bulk read uses
    ``as_of = end`` — PIT-safe for OHLCV because bar *contents* are immutable
    (only quality-flag visibility evolves, and flags are not consumed here);
    the per-decision truncation is positional (only rows with
    ``ts_open <= decision_ts - Δ`` ever feed a lookup at ``decision_ts``).

    1h-only: the formulas' constants (sqrt(24), halflife 240 bars, day
    bucketing) are defined on the 1h grid; for any other engine timeframe a
    custom :class:`CostInputProvider` must be injected.
    """

    ADV_DAYS: Final[int] = 30
    SIGMA_HALFLIFE_BARS: Final[float] = 240.0
    BARS_PER_DAY: Final[int] = 24
    #: 30 complete UTC days + the partial decision day + sigma warmup headroom.
    WARMUP_MS: Final[int] = 33 * _DAY_MS

    __slots__ = ("_adv", "_sigma", "_tf")

    def __init__(
        self,
        reader: PITDataReader,
        instrument_ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
    ) -> None:
        self._tf = Timeframe.H1
        read_start = start - self.WARMUP_MS
        tbl = reader.ohlcv(instrument_ids, start=read_start, end=end, as_of=end, tf=self._tf)
        grid = expected_bar_opens(read_start, end, self._tf)
        index = pd.Index(grid, dtype="int64", name="ts_open")
        ids = sorted(dict.fromkeys(instrument_ids))
        if tbl.num_rows == 0:
            nan = pd.DataFrame(np.nan, index=index, columns=ids, dtype="float64")
            self._sigma = nan
            self._adv = nan.copy()
            return
        frame = pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": tbl.column("ts_open").cast(pa.int64()).to_pylist(),
                "close": tbl.column("close").to_pylist(),
                "quote_volume": tbl.column("quote_volume").to_pylist(),
            }
        )
        closes = (
            frame.pivot(index="ts_open", columns="instrument_id", values="close")
            .reindex(index=index, columns=ids)
            .astype("float64")
        )
        qv = (
            frame.pivot(index="ts_open", columns="instrument_id", values="quote_volume")
            .reindex(index=index, columns=ids)
            .astype("float64")
        )

        # sigma_daily = EWMA_halflife240(1h log returns) * sqrt(24)  (market.py formula)
        self._sigma = ewma_vol_halflife(log_returns(closes), self.SIGMA_HALFLIFE_BARS) * math.sqrt(
            float(self.BARS_PER_DAY)
        )

        # adv_quote = rolling 30-day MEDIAN of complete-UTC-day quote volume,
        # mapped to each bar's last fully-completed day (market.py mechanics).
        grid_arr = np.asarray(grid, dtype="int64")
        day_key = (grid_arr // _DAY_MS) * _DAY_MS
        daily = qv.groupby(day_key).sum(min_count=1)
        first_full_day = -(-read_start // _DAY_MS) * _DAY_MS  # ceil to next UTC day
        day_index = np.asarray(daily.index, dtype="int64")
        complete = (day_index >= first_full_day) & (day_index + _DAY_MS <= end)
        daily = daily.loc[complete]
        med = daily.rolling(self.ADV_DAYS, min_periods=self.ADV_DAYS).median()
        last_day = ((grid_arr + self._tf.ms) // _DAY_MS) * _DAY_MS - _DAY_MS
        adv = med.reindex(last_day)
        adv.index = index
        self._adv = adv.astype("float64")

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        """``(adv_quote, sigma_daily)`` from the decision bar (``ts_open = ts - Δ``).

        Returns ``(nan, nan)`` for unknown instruments, off-grid timestamps,
        or insufficient history — the engine drops such orders loudly rather
        than guessing a cost.
        """
        ts_open = decision_ts - self._tf.ms
        if instrument_id not in self._sigma.columns or ts_open not in self._sigma.index:
            return (math.nan, math.nan)
        adv = cast(float, self._adv.at[ts_open, instrument_id])
        sigma = cast(float, self._sigma.at[ts_open, instrument_id])
        return (float(adv), float(sigma))


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


def _finite_positive(value: float) -> bool:
    """True iff ``value`` is a finite float > 0."""
    return math.isfinite(value) and value > 0.0


class EventDrivenBacktester:
    """Bar-close event loop over PIT lake data (module docstring = the contract).

    Args:
        reader: PIT lake reader; the only data access path (strategy included).
        instruments: SCD2 instrument store. Static trading attributes
            (lot/min filters, funding interval, market type) are resolved
            ``as_of = end`` of each run — a documented v1 simplification
            (per-bar SCD2 resolution arrives with the execution layer).
        cost_model: THE shared cost authority; consumed only through the fill
            model, never reimplemented (buildabilityCritique.md §3.7).
        tf: Bar timeframe (default 1h).
        fill_model: Defaults to :class:`NextOpenFill` over ``cost_model``.
        cost_inputs: ADV/sigma provider; defaults to a per-run
            :class:`LakeCostInputs` (1h-only — other timeframes must inject).
        no_trade_band_frac: Suppress orders with ``|Δnotional| <
            band * equity`` (default 0.001 = 10 bps of equity; mirrors
            ``portfolio.no_trade_band``). Full exchange-filter discretization
            is Phase 6; v1 applies lot-size rounding toward zero plus
            ``min_qty``/``min_notional`` filters from the instrument record.
        config_echo: Extra key/values copied verbatim into the result config
            (callers pass cost parameters etc. for full reproducibility — the
            engine cannot introspect the cost model's internals and will not
            guess).
    """

    __slots__ = (
        "_config_echo",
        "_cost_inputs",
        "_cost_model",
        "_fill_model",
        "_instruments",
        "_no_trade_band_frac",
        "_reader",
        "_tf",
    )

    def __init__(
        self,
        reader: PITDataReader,
        instruments: InstrumentStore,
        cost_model: TransactionCostModel,
        *,
        tf: Timeframe = Timeframe.H1,
        fill_model: FillModel | None = None,
        cost_inputs: CostInputProvider | None = None,
        no_trade_band_frac: float = 0.001,
        config_echo: Mapping[str, object] | None = None,
    ) -> None:
        if not math.isfinite(no_trade_band_frac) or no_trade_band_frac < 0.0:
            raise ValueError(
                f"no_trade_band_frac must be finite and >= 0, got {no_trade_band_frac!r}"
            )
        if cost_inputs is None and tf is not Timeframe.H1:
            raise ValueError(
                "the default LakeCostInputs provider is 1h-only; inject cost_inputs "
                f"for tf={tf.value}"
            )
        self._reader = reader
        self._instruments = instruments
        self._cost_model = cost_model
        self._tf = tf
        self._fill_model: FillModel = NextOpenFill(cost_model) if fill_model is None else fill_model
        self._cost_inputs = cost_inputs
        self._no_trade_band_frac = no_trade_band_frac
        self._config_echo: dict[str, object] = dict(config_echo or {})

    # ------------------------------------------------------------------- run

    def run(
        self,
        strategy: Strategy,
        instrument_ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
        initial_cash: float = 100_000.0,
    ) -> BacktestResult:
        """Run ``strategy`` over ``[start, end)`` and return the full result.

        ``start``/``end`` must be ``tf``-aligned epoch-ms UTC; bars with
        ``ts_open in [start, end)`` define the run. Raises ``ValueError`` on
        unknown instruments, an empty/too-short bar set (< 2 bar closes), or
        malformed bounds. Propagates :class:`LookaheadError` (contract breach
        — a bug, never a data condition) and
        :class:`~alphaforge.core.errors.CostModelMisuse` (an order escaped
        the sizing guards) — both must halt the run, not be smoothed over.
        """
        ids = list(dict.fromkeys(instrument_ids))
        if not ids:
            raise ValueError("instrument_ids must be non-empty")
        if end <= start:
            raise ValueError(f"end ({end}) must be > start ({start})")
        if start % self._tf.ms or end % self._tf.ms:
            raise ValueError(
                f"start/end must be {self._tf.value}-aligned epoch-ms, got {start}/{end}"
            )
        if not _finite_positive(initial_cash):
            raise ValueError(f"initial_cash must be finite and > 0, got {initial_cash!r}")

        insts: dict[str, Instrument] = {}
        for iid in ids:
            inst = self._instruments.get(iid, as_of=end)
            if inst is None:
                # SCD2 validity starts at first INGESTION time, so a run that
                # ends before the store's first record resolves no version at
                # as_of=end. Fall back to the EARLIEST recorded version (the
                # nearest-in-time record for a historical run) — a documented
                # v1 simplification consistent with the static as_of=end
                # attribute resolution above; truly unknown ids still raise.
                history = self._instruments.history(iid)
                if not history:
                    raise ValueError(f"unknown instrument {iid!r} (no SCD2 record)")
                inst = history[0][2]
            insts[iid] = inst

        bars = self._load_bars(ids, start=start, end=end)
        grid = sorted({ts_open + self._tf.ms for rows in bars.values() for ts_open in rows})
        if len(grid) < 2:
            raise ValueError(
                f"need at least 2 bar closes in [{start}, {end}) for {ids}, got {len(grid)}"
            )
        last_close_of: dict[str, Ms] = {
            iid: max(rows) + self._tf.ms for iid, rows in bars.items() if rows
        }
        funding_events = self._load_funding(insts, start=start, end=end)
        funding_ptr: dict[str, int] = dict.fromkeys(funding_events, 0)
        provider: CostInputProvider = (
            LakeCostInputs(self._reader, ids, start=start, end=end)
            if self._cost_inputs is None
            else self._cost_inputs
        )

        ledger = Ledger(initial_cash, insts)
        counters: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
        order_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []
        reason_by_order: dict[str, str] = {}
        record_by_order: dict[str, dict[str, object]] = {}
        last_close: dict[str, float] = {}
        pending: list[OrderRequest] = []
        final_close = grid[-1]

        for t in grid:
            counters["bars_processed"] += 1

            # (0) fill orders queued at the previous close against the bar
            #     opening at that close (ts_open == decision_ts).
            for order in pending:
                self._execute(order, insts, bars, provider, ledger, counters, record_by_order)
            pending = []

            # (1) stored funding events with ts_funding in (prev_close, t];
            #     pointer per instrument is monotone, so "<= t" is exact.
            for iid, events in funding_events.items():
                ptr = funding_ptr[iid]
                while ptr < len(events) and events[ptr][0] <= t:
                    ts_funding, rate = events[ptr]
                    ptr += 1
                    bar = bars[iid].get(t - self._tf.ms)
                    mark = bar.close if bar is not None else last_close.get(iid)
                    if mark is not None:  # no close ever seen => provably flat: no-op
                        ledger.apply_funding(iid, ts_funding, rate, mark)
                funding_ptr[iid] = ptr

            # (2) mark at close[t] (last-known closes carry across per-
            #     instrument gaps so open positions always mark — documented).
            for iid, rows in bars.items():
                bar = rows.get(t - self._tf.ms)
                if bar is not None:
                    last_close[iid] = bar.close
            state = ledger.mark(
                {iid: last_close[iid] for iid in ledger.positions()},
                t,
            )

            # (3) force-flat delisted instruments (bars end before the run does).
            if t < final_close:
                for pos in list(ledger.positions().values()):
                    if last_close_of.get(pos.instrument_id) != t:
                        continue
                    self._force_flat(
                        pos.instrument_id,
                        insts[pos.instrument_id],
                        ledger,
                        last_close[pos.instrument_id],
                        t,
                        counters,
                        order_records,
                        reason_by_order,
                    )
                state = ledger.mark(
                    {iid: last_close[iid] for iid in ledger.positions()},
                    t,
                )
            equity = state.equity_quote

            # snapshot positions at this close (post administrative actions)
            for pos in state.positions:
                mark = last_close[pos.instrument_id]
                position_records.append(
                    {
                        "ts": t,
                        "instrument_id": pos.instrument_id,
                        "qty": pos.qty,
                        "mark": mark,
                        "weight": pos.qty * mark / equity,
                        "unreal_pnl": pos.qty * (mark - pos.avg_entry_price),
                    }
                )

            # (4) strategy decision at close t
            ctx = StrategyContext(
                reader=self._reader,
                tf=self._tf,
                ts=t,
                equity=equity,
                positions={p.instrument_id: p.qty for p in state.positions},
                instruments=insts,
            )
            targets = strategy.on_bar_close(ctx)

            # (5) discretize targets -> orders queued for the next close
            pending = self._discretize(
                targets,
                insts,
                bars,
                ledger,
                equity,
                t,
                counters,
                order_records,
                reason_by_order,
                record_by_order,
            )

        # Orders decided on the final bar have no t+1: zero fills, loud counter.
        for order in pending:
            counters["unfilled_final_bar"] += 1
            record_by_order[order.client_order_id]["status"] = "unfilled_final_bar"

        return self._build_result(
            ledger,
            insts,
            ids,
            start=start,
            end=end,
            initial_cash=initial_cash,
            counters=counters,
            order_records=order_records,
            position_records=position_records,
            reason_by_order=reason_by_order,
        )

    # ----------------------------------------------------------- loop pieces

    def _execute(
        self,
        order: OrderRequest,
        insts: Mapping[str, Instrument],
        bars: Mapping[str, dict[Ms, BarView]],
        provider: CostInputProvider,
        ledger: Ledger,
        counters: dict[str, int],
        record_by_order: dict[str, dict[str, object]],
    ) -> None:
        """Fill one queued order against the bar opening at its decision close.

        Missing next bar (per-instrument gap or delisting): the order is
        DROPPED and counted — never filled at a synthetic price. Missing
        ADV/sigma: dropped and counted — never a guessed cost.
        """
        record = record_by_order[order.client_order_id]
        next_bar = bars[order.instrument_id].get(order.decision_ts)
        if next_bar is None:
            counters["dropped_missing_next_bar"] += 1
            record["status"] = "dropped_missing_next_bar"
            return
        adv_quote, sigma_daily = provider.cost_inputs(order.instrument_id, order.decision_ts)
        if not _finite_positive(adv_quote) or not _finite_positive(sigma_daily):
            counters["dropped_no_cost_inputs"] += 1
            record["status"] = "dropped_no_cost_inputs"
            return
        fill = self._fill_model.fill(
            order,
            insts[order.instrument_id],
            next_bar,
            adv_quote=adv_quote,
            sigma_daily=sigma_daily,
        )
        if fill.ts < order.decision_ts:  # defense in depth against custom fill models
            raise LookaheadError(
                f"fill model returned ts {fill.ts} before decision {order.decision_ts} "
                f"for {order.instrument_id!r}"
            )
        ledger.apply_fill(fill)
        counters["fills_applied"] += 1
        record["status"] = "filled"

    def _force_flat(
        self,
        iid: str,
        inst: Instrument,
        ledger: Ledger,
        close: float,
        t: Ms,
        counters: dict[str, int],
        order_records: list[dict[str, object]],
        reason_by_order: dict[str, str],
    ) -> None:
        """Administratively close a delisted instrument at its last close.

        Price = last available close (the same print used for the final mark,
        so the position value is unchanged) with the taker fee from the shared
        cost model — strictly conservative versus holding an unmarkable
        position, and loud (counted + logged with status ``forced_flat``).
        This is NOT a strategy decision, so the same-bar timing is exempt from
        the t+1 fill rule by design (documented).
        """
        pos = ledger.positions()[iid]
        side = Side.SELL if pos.qty > 0.0 else Side.BUY
        qty = abs(pos.qty)
        fee = self._cost_model.fee_frac(inst, Liquidity.TAKER) * qty * close
        client_order_id = f"bt-{t}-{iid}-forceflat"
        ledger.apply_fill(
            Fill(
                client_order_id=client_order_id,
                instrument_id=iid,
                side=side,
                qty=qty,
                price=close,
                fee_quote=fee,
                liquidity=Liquidity.TAKER,
                ts=t,
            )
        )
        counters["forced_flat"] += 1
        reason_by_order[client_order_id] = "forced_flat"
        order_records.append(
            {
                "decision_ts": t,
                "instrument_id": iid,
                "side": side.value,
                "qty": qty,
                "decision_price": close,
                "status": "forced_flat",
                "client_order_id": client_order_id,
            }
        )

    def _discretize(
        self,
        targets: Mapping[str, float],
        insts: Mapping[str, Instrument],
        bars: Mapping[str, dict[Ms, BarView]],
        ledger: Ledger,
        equity: float,
        t: Ms,
        counters: dict[str, int],
        order_records: list[dict[str, object]],
        reason_by_order: dict[str, str],
        record_by_order: dict[str, dict[str, object]],
    ) -> list[OrderRequest]:
        """Turn target weights into queued orders (band, lot, min filters).

        Per instrument: ``Δnotional = w*equity - qty*close_t``; suppressed when
        ``|Δnotional| < no_trade_band_frac * equity``; quantity rounded toward
        zero to ``lot_size`` steps and filtered by ``min_qty``/``min_notional``
        (a too-small flattening residual therefore stays open — documented v1
        simplification, full exchange-filter discretization is Phase 6).
        """
        positions = ledger.positions()
        orders: list[OrderRequest] = []
        for iid in sorted(targets):
            weight = float(targets[iid])
            if iid not in insts:
                raise ValueError(f"strategy emitted target for unknown instrument {iid!r}")
            if not math.isfinite(weight):
                raise ValueError(f"strategy emitted non-finite weight for {iid!r}: {weight!r}")
            counters["orders_decided"] += 1
            inst = insts[iid]
            bar = bars[iid].get(t - self._tf.ms)

            def _skip(status: str, *, price: float, side: str, qty: float, _iid: str = iid) -> None:
                order_records.append(
                    {
                        "decision_ts": t,
                        "instrument_id": _iid,
                        "side": side,
                        "qty": qty,
                        "decision_price": price,
                        "status": status,
                        "client_order_id": "",
                    }
                )

            if bar is None:
                counters["dropped_no_decision_bar"] += 1
                _skip("dropped_no_decision_bar", price=math.nan, side="", qty=0.0)
                continue
            price = bar.close
            pos = positions.get(iid)
            held_qty = 0.0 if pos is None else pos.qty
            delta_notional = weight * equity - held_qty * price
            side = Side.BUY if delta_notional > 0.0 else Side.SELL
            if abs(delta_notional) < self._no_trade_band_frac * equity:
                counters["skipped_no_trade_band"] += 1
                _skip(
                    "skipped_no_trade_band",
                    price=price,
                    side=side.value,
                    qty=abs(delta_notional) / price,
                )
                continue
            steps = math.floor(abs(delta_notional) / price / inst.lot_size + 1e-9)
            qty = steps * inst.lot_size
            if qty <= 0.0 or qty < inst.min_qty or qty * price < inst.min_notional:
                counters["skipped_below_min"] += 1
                _skip("skipped_below_min", price=price, side=side.value, qty=qty)
                continue
            client_order_id = f"bt-{t}-{iid}"
            order = OrderRequest(
                client_order_id=client_order_id,
                instrument_id=iid,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                decision_ts=t,
                decision_price=price,
                reason="target_weight",
            )
            reason_by_order[client_order_id] = "target_weight"
            record: dict[str, object] = {
                "decision_ts": t,
                "instrument_id": iid,
                "side": side.value,
                "qty": qty,
                "decision_price": price,
                "status": "queued",
                "client_order_id": client_order_id,
            }
            order_records.append(record)
            record_by_order[client_order_id] = record
            orders.append(order)
        return orders

    # -------------------------------------------------------------- plumbing

    def _load_bars(self, ids: Sequence[str], *, start: Ms, end: Ms) -> dict[str, dict[Ms, BarView]]:
        """One bulk PIT read -> per-instrument ``ts_open -> BarView`` maps.

        ``as_of = end`` is PIT-safe here: bar contents are immutable (only
        quality-flag *visibility* evolves with as_of, and the engine does not
        consume flags); the per-decision truncation is enforced positionally
        by the event loop and, for strategies, by ``StrategyContext.bars``.
        """
        tbl = self._reader.ohlcv(ids, start=start, end=end, as_of=end, tf=self._tf)
        out: dict[str, dict[Ms, BarView]] = {iid: {} for iid in ids}
        if tbl.num_rows == 0:
            return out
        iid_col = tbl.column("instrument_id").to_pylist()
        ts_col = tbl.column("ts_open").cast(pa.int64()).to_pylist()
        cols = {
            name: tbl.column(name).to_pylist()
            for name in ("open", "high", "low", "close", "volume", "quote_volume")
        }
        for i, iid in enumerate(iid_col):
            qv = cols["quote_volume"][i]
            out[str(iid)][int(ts_col[i])] = BarView(
                ts_open=int(ts_col[i]),
                open=float(cols["open"][i]),
                high=float(cols["high"][i]),
                low=float(cols["low"][i]),
                close=float(cols["close"][i]),
                volume=float(cols["volume"][i]),
                quote_volume=math.nan if qv is None else float(qv),
            )
        return out

    def _load_funding(
        self, insts: Mapping[str, Instrument], *, start: Ms, end: Ms
    ) -> dict[str, list[tuple[Ms, float]]]:
        """Stored funding events per perp instrument, ``start < ts_funding <= end``.

        Read once up front (funding history is immutable; ``as_of = end``
        bounds visibility — an event published within its lag of the run end
        is conservatively excluded). The events ARE the schedule: applying
        them one by one is automatically 8h/4h/1h interval-aware
        (leakageCritique.md finding 6).
        """
        perp_ids = sorted(iid for iid, inst in insts.items() if inst.market_type is MarketType.PERP)
        out: dict[str, list[tuple[Ms, float]]] = {iid: [] for iid in perp_ids}
        if not perp_ids:
            return out
        tbl = self._reader.funding(perp_ids, start=start + 1, end=end + 1, as_of=end)
        iid_col = tbl.column("instrument_id").to_pylist()
        ts_col = tbl.column("ts_funding").cast(pa.int64()).to_pylist()
        rate_col = tbl.column("rate").to_pylist()
        for i, iid in enumerate(iid_col):
            out[str(iid)].append((int(ts_col[i]), float(rate_col[i])))
        return out  # reader returns sorted (instrument_id, ts_funding)

    def _build_result(
        self,
        ledger: Ledger,
        insts: Mapping[str, Instrument],
        ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
        initial_cash: float,
        counters: dict[str, int],
        order_records: list[dict[str, object]],
        position_records: list[dict[str, object]],
        reason_by_order: dict[str, str],
    ) -> BacktestResult:
        """Assemble frames + :func:`summarize` into a :class:`BacktestResult`."""
        equity = ledger.equity_curve()
        raw_fills = ledger.fills_log()
        fills = pd.DataFrame(
            {
                "ts": raw_fills["ts"],
                "instrument_id": raw_fills["instrument_id"],
                "side": raw_fills["side"],
                "qty": raw_fills["qty"],
                "price": raw_fills["price"],
                "notional": raw_fills["qty"] * raw_fills["price"],
                "fee": raw_fills["fee_quote"],
                "liquidity": raw_fills["liquidity"],
                "realized_pnl_quote": raw_fills["realized_pnl_quote"],
                "client_order_id": raw_fills["client_order_id"],
                "reason": raw_fills["client_order_id"].map(
                    lambda coid: reason_by_order.get(str(coid), "")
                ),
            },
            columns=list(FILLS_COLUMNS),
        )
        funding_frame = ledger.funding_log()
        counters["funding_events_applied"] = len(funding_frame)
        orders = pd.DataFrame(order_records, columns=list(ORDERS_COLUMNS))
        positions = pd.DataFrame(position_records, columns=list(POSITIONS_COLUMNS))
        funding_series = pd.Series(
            funding_frame["payment_quote"].to_numpy(dtype="float64"),
            index=pd.Index(funding_frame["ts_funding"].to_numpy(dtype="int64"), name="ts_funding"),
            name="payment_quote",
        )
        summary = summarize(equity, fills=fills, funding=funding_series, positions=positions)
        config: dict[str, object] = {
            "start": start,
            "end": end,
            "tf": self._tf.value,
            "instrument_ids": list(ids),
            "initial_cash": initial_cash,
            "no_trade_band_frac": self._no_trade_band_frac,
            "fill_model": type(self._fill_model).__name__,
            "perp_instruments": sorted(
                iid for iid, inst in insts.items() if inst.market_type is MarketType.PERP
            ),
            **self._config_echo,
        }
        return BacktestResult(
            equity=equity,
            fills=fills,
            funding_events=funding_frame,
            orders=orders,
            positions=positions,
            summary=summary,
            config=config,
            counters=counters,
        )
