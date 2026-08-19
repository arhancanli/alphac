"""BlendStrategy — the first full strategy: mu_ann -> Σ -> allocator -> overlay -> targets.

Implements the :class:`alphaforge.backtest.Strategy` protocol over the
Phase-6 portfolio brain. Per rebalance (every ``rebalance_bars`` bars)::

    mu_ann row (signals; THE mu_ann contract, leakageCritique finding 2)
      -> Σ: ewma_cov -> ledoit_wolf_cc -> nearest_psd -> annualize_cov   (§6.1)
      -> allocator: RankEqualVolFallback (v1 PRIMARY) or
         MeanVarianceOptimizer (drop-in upgrade with built-in fallback)  (§6.2)
      -> vol_target overlay (sigma_hat = max(ex-ante, realized))         (§6.3)
      -> DrawdownLadder gross multiplier                                 (§7.2)
      -> target weights (fractions of equity)

Two signal sources, ONE decision body (the anti-skew shape):

* **Precomputed** (walk-forward / research): construct with ``signal_frame``
  — the output of ``SignalService.compute_research`` — a float frame on a
  ``(ts_open, instrument_id)`` MultiIndex carrying the ``mu_ann`` column.
  The decision at bar close ``ctx.ts`` reads the row at
  ``ts_open = ctx.ts - Δ`` (the decision bar's open: the signal value at
  ``(t, i)`` is by the engine contract a function of data through the close
  ``t + Δ``). Exact-row lookup with a bounded grace window: if the exact row
  is missing, the newest available row within ``staleness_max_bars`` bars is
  used; older than that the strategy HOLDS (returns ``{}``) — trading a
  stale mu is how a dead signal feed quietly keeps a book levered
  (RiskCfg.staleness_max_bars; de-gross-on-staleness is a documented Phase-7
  live-loop option, v1 holds).
* **Live** (stub for Phase 7): construct with ``mu_provider`` — a callable
  ``(decision_ts) -> {instrument_id: mu_ann}``, e.g. an adapter over
  ``SignalService.on_bar_close(decision_ts)['mu_ann']``. The live loop
  (Phase 7) wires it; an empty/missing result at a rebalance holds.

THE risk/enforcement boundary (documented, deliberate):

* The strategy returns TARGET WEIGHTS; the **engine** discretizes them
  (no-trade band, lot rounding, min-qty/min-notional) — the strategy never
  emits orders. Portfolio caps (gross/net/w_max) are enforced inside the
  allocator; the vol overlay and ladder only ever scale DOWN.
* The full :class:`alphaforge.risk.PreTradeChecker` runs on discretized
  orders and is the LIVE loop's job (Phase 7) — in backtests the engine's
  discretization plus the allocator caps are the enforcement surface.
* What the strategy DOES enforce every bar: the
  :class:`~alphaforge.risk.DrawdownLadder` gross multiplier on targets, for
  BOTH active tiers (FLAT_HALTED -> all-zero targets immediately, absorbing
  until a human rearms; HALF_GROSS -> the last emitted book re-emitted at half
  gross on the very next bar, not deferred to the next rebalance), and the
  signal-staleness hold above. Because the multiplier acts every bar, a
  NORMAL -> HALF_GROSS transition de-grosses with at most one bar of lag.
* The vol-target overlay scales toward the vol target but the per-name hard cap
  ``w_max`` is INVIOLABLE: each weight is re-clipped to [-w_max, +w_max] after
  the overlay and before the ladder multiplier, so the decision-time book never
  holds a position the live ``PreTradeChecker`` (max_position_frac = w_max)
  would reject. The resulting small vol-target shortfall is accepted (no
  re-scale-up after clipping).

Σ estimation cost (documented): the trailing close panel is re-read through
``ctx.bars`` and the EWMA+LW pipeline re-run at every rebalance (every
``rebalance_bars`` = 24 bars by default — LW intensity drifts slowly, so
re-estimating it more often buys nothing). Between rebalances the strategy
does NO data access; an incremental EWMA cache is a measured-need
optimization, not a v1 requirement (cov_window_bars x N panel per rebalance,
~720x20 floats — microseconds).

mu_ann contract (leakageCritique finding 2): the signal layer emits
``mu_ann = mu_h * 8760/h`` with ``h = settings.signals.horizon_bars`` — the
ONE horizon constant — and the allocator's ``check_mu_ann_contract`` tripwire
refuses ``|mu_ann| >= 3.0`` (the strategy never weakens it).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa

from alphaforge.core.time import Ms, Timeframe
from alphaforge.portfolio.covariance import (
    annualize_cov,
    ewma_cov,
    ledoit_wolf_cc,
    nearest_psd,
)
from alphaforge.portfolio.optimizer import (
    MeanVarianceOptimizer,
    OptResult,
    PortfolioConstraints,
    RankEqualVolFallback,
    TrendVolTarget,
)
from alphaforge.portfolio.overlay import vol_target
from alphaforge.risk import DDState, DrawdownLadder
from alphaforge.signals.sizing import MU_ANN_COLUMN

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from alphaforge.backtest import StrategyContext
    from alphaforge.config.settings import Settings
    from alphaforge.core.calendar import TradingCalendar

__all__ = ["MU_ANN_COLUMN", "BlendStrategy"]

#: Default flat one-way cost fraction fed to the MVO turnover penalty: taker
#: fee 5 bps + half-spread 2.5 bps + small-order impact ~2.5 bps. A per-asset
#: TransactionCostModel.oneway_cost_frac wiring (needs ADV/sigma plumbing into
#: the strategy) is the Phase-7 refinement; the rank allocator ignores it.
_DEFAULT_COST_FRAC: Final[float] = 0.0010

_DAY_MS: Final[int] = 86_400_000
"""One UTC day in ms — the calendar over-reach unit for the gappy-grid covariance window."""


class BlendStrategy:
    """The Phase-6 product strategy (module docstring = the contract).

    Exactly one of ``signal_frame`` (precomputed mode) / ``mu_provider``
    (live mode) must be supplied.

    Args:
        settings: Source of ALL limits and knobs: ``portfolio`` (constraints,
            vol target/scale cap, risk aversion), ``risk`` (drawdown ladder
            thresholds, staleness), ``signals.horizon_bars`` (the ONE horizon
            constant, consumed by the MVO's cost amortization).
        signal_frame: ``SignalService.compute_research`` output — float frame
            on a ``(ts_open, instrument_id)`` MultiIndex with a ``mu_ann``
            column (extra columns ignored).
        mu_provider: live-mode callable ``(decision_ts) -> mapping`` of
            ``instrument_id -> mu_ann`` (Phase 7 wires it to
            ``SignalService.on_bar_close``).
        allocator: ``"rank"`` (v1 PRIMARY — RankEqualVolFallback, buildability
            ruling §1) or ``"mvo"`` (MeanVarianceOptimizer upgrade; it
            delegates to the same fallback on any solver trouble).
        rebalance_bars: bars between decisions (default 24 = daily on 1h).
        cov_window_bars: trailing return window for Σ (default 720 = 30d).
        cov_halflife_bars: EWMA covariance halflife (default 720).
        cov_min_periods: minimum return rows before Σ is trusted; fewer ->
            hold (cold start). Default 240 (10d).
        realized_vol_halflife_bars: EWMA halflife of realized portfolio-return
            vol for the overlay's ``sigma_realized`` (default 240, §6.3).
        cost_frac_oneway: flat per-asset one-way cost fraction for the MVO
            turnover penalty (see ``_DEFAULT_COST_FRAC``).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        signal_frame: pd.DataFrame | None = None,
        mu_provider: Callable[[Ms], Mapping[str, float]] | None = None,
        allocator: Literal["rank", "rank_long", "mvo", "trend"] = "rank",
        rebalance_bars: int = 24,
        rebalance_anchor: Literal["run", "epoch"] = "run",
        cov_window_bars: int = 720,
        cov_halflife_bars: int = 720,
        cov_min_periods: int = 240,
        realized_vol_halflife_bars: int = 240,
        cost_frac_oneway: float = _DEFAULT_COST_FRAC,
    ) -> None:
        if (signal_frame is None) == (mu_provider is None):
            raise ValueError(
                "exactly one of signal_frame (precomputed mode) / mu_provider "
                "(live mode) must be provided"
            )
        if rebalance_bars <= 0:
            raise ValueError(f"rebalance_bars must be > 0, got {rebalance_bars}")
        if cov_window_bars < cov_min_periods or cov_min_periods < 2:
            raise ValueError(
                f"need cov_window_bars ({cov_window_bars}) >= cov_min_periods "
                f"({cov_min_periods}) >= 2"
            )
        if cov_halflife_bars <= 0 or realized_vol_halflife_bars <= 0:
            raise ValueError("cov_halflife_bars/realized_vol_halflife_bars must be > 0")
        if not math.isfinite(cost_frac_oneway) or cost_frac_oneway < 0.0:
            raise ValueError(f"cost_frac_oneway must be finite and >= 0, got {cost_frac_oneway!r}")

        p = settings.portfolio
        r = settings.risk
        constraints = PortfolioConstraints.from_settings(settings)
        self._allocator_name: Literal["rank", "rank_long", "mvo", "trend"] = allocator
        if allocator == "rank":
            self._allocator: (
                RankEqualVolFallback | MeanVarianceOptimizer | TrendVolTarget
            ) = RankEqualVolFallback(constraints)
        elif allocator == "rank_long":
            # Long-only factor-tilt book (no short leg): top-K longs at full gross. Earns
            # market beta + the factor tilt, not market-neutral alpha (evaluate vs a
            # buy-and-hold benchmark). Byte-identical to 'rank' on crypto since it is an
            # explicit equity opt-in (the crypto path never selects it).
            self._allocator = RankEqualVolFallback(replace(constraints, long_only=True))
        elif allocator == "trend":
            # Directional time-series-momentum book (managed-futures sleeve): each asset long or
            # short on its OWN trend, inverse-vol weighted, NET exposure allowed. The net
            # directionality is the source of the positive skew + crash protection. Byte-identical
            # to 'rank' on crypto/equity — only the managed-futures profile selects it.
            self._allocator = TrendVolTarget(constraints)
        elif allocator == "mvo":
            self._allocator = MeanVarianceOptimizer.from_settings(settings)
        else:  # pragma: no cover - Literal narrows, guard for untyped callers
            raise ValueError(
                f"allocator must be 'rank', 'rank_long', 'mvo', or 'trend', got {allocator!r}"
            )

        self._vol_target_ann = p.vol_target_ann
        self._vol_scale_max = p.vol_scale_max
        self._gross_max = p.gross_max
        self._w_max = constraints.w_max
        # RiskCfg drawdowns are NEGATIVE fractions from HWM; the ladder takes
        # positive depths (same flip RiskLimits.from_cfg performs).
        self._ladder = DrawdownLadder(
            dd_half_frac=abs(r.dd_halve_gross),
            dd_flat_frac=abs(r.dd_flat_halt),
            flat_cooldown_bars=r.flat_cooldown_bars,
        )
        self._staleness_max_bars = r.staleness_max_bars
        self._rebalance_bars = rebalance_bars
        # "run" (default): the cadence anchor is in-memory (_next_rebalance_ts), set after each
        # completed rebalance — correct for a long-lived backtest/loop process, byte-identical to
        # the pre-anchor behavior. "epoch": STATELESS cadence for the fresh-process-per-cycle
        # (`af paper run --once`) deployment, where an in-memory anchor is None every cycle and
        # the run-mode gate can never hold: a rebalance is due iff the bar is epoch-aligned
        # (ts % (rebalance_bars * tf.ms) == 0) OR the book is flat (the boot entry).
        self._rebalance_anchor = rebalance_anchor
        self._cov_window_bars = cov_window_bars
        self._cov_halflife_bars = cov_halflife_bars
        self._cov_min_periods = cov_min_periods
        self._rv_halflife_bars = realized_vol_halflife_bars
        self._cost_frac = cost_frac_oneway

        self._mu_provider = mu_provider
        self._mu: pd.Series | None
        if signal_frame is not None:
            self._mu, self._signal_ts = _validate_signal_frame(signal_frame)
        else:
            self._mu = None
            self._signal_ts = np.array([], dtype=np.int64)

        # Mutable per-run state (the engine calls strictly forward in time).
        self._next_rebalance_ts: Ms | None = None
        self._equity_hist: list[float] = []
        # Overlay scale in force during each observed bar, index-aligned with
        # ``_equity_hist``. Needed because ``_equity_hist`` is the POST-overlay account
        # curve while the overlay's ex-ante leg is computed from PRE-overlay optimizer
        # weights: without this the two sides of ``max(ex_ante, realized)`` are on
        # different scales and the fast realized leg cannot win. See _realized_vol_ann.
        self._scale_hist: list[float] = []
        self._last_result: OptResult | None = None
        self._last_scale: float = math.nan
        # Most recent PRE-ladder-multiplier target book (the vol-targeted,
        # w_max-clipped weights BEFORE the gross multiplier). Re-emitted, rescaled
        # to the live gross_multiplier(), on HALF_GROSS non-rebalance bars so the
        # ladder de-gross takes effect EVERY bar, not only at the next rebalance
        # (F-B). None until the first completed rebalance.
        self._last_targets: dict[str, float] | None = None
        # Observability counters (the operator's "confession" — never reset by
        # load_leg so a walk-forward run aggregates them across legs):
        #   allocator status (F-D): a run labelled allocator="mvo" that is mostly
        #     rank-fallback is no longer silent.
        self._n_rebalances: int = 0
        self._n_fallback_used: int = 0
        # Did the FAST realized leg actually overrule the SLOW covariance leg? Simulation
        # said 0.02% of days as shipped vs 81.8% de-levered; a counter makes that
        # measurable in the REAL book instead of only in a study.
        self._n_realized_leg_bound: int = 0
        #   per hold/halt reason (F-E): a dead/stale feed (frozen book) is now
        #     distinguishable from healthy between-rebalance holding.
        self._n_hold_between_rebalance: int = 0
        self._n_hold_stale_signal: int = 0
        self._n_hold_cov_cold_start: int = 0
        self._n_hold_degenerate_xsection: int = 0
        self._n_bars_halted_flat: int = 0
        self._n_bars_half_gross: int = 0

    # ------------------------------------------------------- leg persistence

    def load_leg(self, signal_frame: pd.DataFrame) -> None:
        """Swap in a new leg's precomputed signal frame, PRESERVING risk state.

        Walk-forward reuses ONE strategy across all legs (the OOS equity stream
        is continuous: leg k+1's initial_cash is leg k's final equity), so the
        risk state must persist across leg boundaries or the curve goes
        optimistic (F-A). A drawdown straddling a leg boundary must trip
        ``dd_flat_halt`` on the TRUE running HWM; a fresh per-leg ladder reseeds
        the HWM to leg-open equity and a halt would silently resurrect next leg.

        Precomputed mode only (live mode never builds per-leg frames). REPLACES
        the precomputed signal frame (re-validating it identically) and PRESERVES
        the :class:`~alphaforge.risk.DrawdownLadder` (state + HWM), the
        realized-vol equity history (``_equity_hist``) and its index-aligned
        ``_scale_hist`` (these two MUST be preserved and dropped together -- the
        realized leg de-levers bar-by-bar using the pair, so clearing one alone
        silently mis-scales every subsequent vol estimate), ``_last_result`` /
        ``_last_scale`` / ``_last_targets``, and all observability counters.
        RESETS ``_next_rebalance_ts`` to None so the leg — which restarts FLAT
        (positions do not cross the boundary; this is the documented pessimistic
        F-N one-extra-rebalance entry cost, unchanged) — re-enters promptly on
        its first bar instead of inheriting a stale rebalance schedule.

        Raises:
            RuntimeError: in live mode (``mu_provider``) — no per-leg frame.
        """
        if self._mu_provider is not None:
            raise RuntimeError(
                "load_leg is precomputed-mode only; live mode has no per-leg signal frame"
            )
        self._mu, self._signal_ts = _validate_signal_frame(signal_frame)
        self._next_rebalance_ts = None

    # ------------------------------------------------------------ diagnostics

    @property
    def ladder(self) -> DrawdownLadder:
        """The drawdown ladder (read for state; ``rearm()`` is a human act)."""
        return self._ladder

    @property
    def last_result(self) -> OptResult | None:
        """Allocator result of the most recent completed rebalance (None before)."""
        return self._last_result

    @property
    def last_scale(self) -> float:
        """Vol-target scale ``s`` of the most recent rebalance (NaN before)."""
        return self._last_scale

    @property
    def counters(self) -> dict[str, int]:
        """The operator's confession: how every bar's decision was produced.

        A frozen book from a dead signal feed (``hold_stale_signal``) must not
        read like healthy between-rebalance holding (``hold_between_rebalance``),
        and an ``allocator="mvo"`` run that is mostly rank-fallback
        (``n_fallback_used`` near ``n_rebalances``) must be visible, not silent
        (F-D / F-E). Counts accumulate over the strategy's whole lifetime; in
        walk-forward they span legs (``load_leg`` never resets them), and the
        runner also snapshots per-leg deltas into ``walkforward.json``.

        Keys:
            n_rebalances: completed rebalances (allocator solved + book emitted).
            n_fallback_used: of those, how many returned the rank/inverse-vol
                fallback (``OptResult.status == "fallback_used"``).
            hold_between_rebalance: ``{}`` returned because it was not a
                rebalance bar (NORMAL hold; healthy).
            hold_stale_signal: ``{}`` because the signal was stale/missing.
            hold_cov_cold_start: ``{}`` because the covariance window was too
                short (``< cov_min_periods``).
            hold_degenerate_xsection: ``{}`` because < 2 tradable names survived
                the mu/finite-return/positive-variance cross-section filter.
            bars_halted_flat: bars the ladder forced an all-zero (FLAT_HALTED)
                target book.
            bars_half_gross: bars emitted at the HALF_GROSS de-grossed level
                (rebalance or every-bar re-emit, F-B).
            realized_leg_bound: rebalances where the FAST realized leg exceeded the
                SLOW ex-ante leg and therefore set the size. Near-zero against a
                large n_rebalances means the fast regime detector is inert -- the
                exact failure that hid the pre-overlay/post-overlay scale defect,
                which is why this is counted rather than assumed.
            n_auto_rearms: times the ladder auto-rearmed out of FLAT_HALTED
                after the cooldown elapsed (resumed trading from a reset HWM).
                Zero here means either no full halt occurred or the run ended
                inside a cooldown; a permanently-absorbed run is now impossible.
        """
        return {
            "n_rebalances": self._n_rebalances,
            "n_fallback_used": self._n_fallback_used,
            "realized_leg_bound": self._n_realized_leg_bound,
            "hold_between_rebalance": self._n_hold_between_rebalance,
            "hold_stale_signal": self._n_hold_stale_signal,
            "hold_cov_cold_start": self._n_hold_cov_cold_start,
            "hold_degenerate_xsection": self._n_hold_degenerate_xsection,
            "bars_halted_flat": self._n_bars_halted_flat,
            "bars_half_gross": self._n_bars_half_gross,
            "n_auto_rearms": self._ladder.n_auto_rearms,
        }

    # ----------------------------------------------------------- the protocol

    def on_bar_close(self, ctx: StrategyContext) -> Mapping[str, float]:
        """One decision at bar close ``ctx.ts`` (module docstring pipeline).

        Returns target weights; ``{}`` = hold (cold start / between rebalances
        in NORMAL / stale or missing signal), all-zeros = flatten (ladder
        FLAT_HALTED). The :class:`~alphaforge.risk.DrawdownLadder` is updated
        EVERY bar with the marked equity and its gross multiplier is enforced
        EVERY bar for BOTH active tiers (F-B): on a HALF_GROSS bar that is NOT a
        rebalance bar the last emitted (pre-multiplier) book is re-emitted at the
        live ``gross_multiplier()`` (i.e. halved) rather than held at full gross,
        so a NORMAL -> HALF_GROSS transition de-grosses on the NEXT bar, not up
        to a full rebalance period later. Every branch increments exactly one
        observability counter (see :attr:`counters`).
        """
        self._equity_hist.append(ctx.equity)
        # Appended here, BEFORE this bar's rebalance can overwrite ``_last_scale``, so
        # ``_scale_hist[t]`` is the scale that was in force while the return into
        # ``_equity_hist[t]`` was being earned (it was set at bar t-1). NaN until the
        # first completed rebalance; _realized_vol_ann masks those bars.
        self._scale_hist.append(self._last_scale)
        state = self._ladder.update(ctx.equity)
        if state is DDState.FLAT_HALTED:
            # Absorbing flatten: explicit zeros for the whole run universe,
            # re-emitted every bar (the engine's band suppresses no-op orders).
            self._n_bars_halted_flat += 1
            return dict.fromkeys(ctx.instruments, 0.0)

        if self._rebalance_anchor == "epoch":
            # Stateless cadence (fresh-process --once deployment): due on epoch-aligned
            # boundaries, or immediately when the book is flat (the boot entry).
            boundary = ctx.ts % (self._rebalance_bars * ctx.tf.ms) == 0
            flat_book = not any(abs(q) > 1e-12 for q in ctx.positions.values())
            between = not (boundary or flat_book)
        else:
            between = self._next_rebalance_ts is not None and ctx.ts < self._next_rebalance_ts
        if between:
            # Between rebalances: hold in NORMAL, but the ladder de-gross is
            # enforced every bar (F-B). In HALF_GROSS re-emit the last book
            # rescaled to the current multiplier (0.5); in NORMAL hold ({}).
            # (epoch mode note: under --once _last_targets is process-local and
            # None, so a HALF_GROSS de-gross waits for the next boundary; the
            # critical FLAT_HALTED all-zeros brake above still acts every bar.)
            if state is DDState.HALF_GROSS and self._last_targets is not None:
                self._n_bars_half_gross += 1
                mult = self._ladder.gross_multiplier()
                return {iid: w * mult for iid, w in self._last_targets.items()}
            self._n_hold_between_rebalance += 1
            return {}

        mu_map = self._mu_asof(ctx.ts, ctx.tf, ctx.calendar)
        if mu_map is None:
            self._n_hold_stale_signal += 1
            return {}  # stale/missing signal: hold, retry next bar (docstring)

        targets = self._rebalance(ctx, mu_map)
        if targets is None:
            return {}  # cold start / degenerate xsection: counted inside _rebalance
        # Advance the schedule by rebalance_bars BARS through the calendar (NOT calendar
        # time): on the 24/7 grid next_bar_open(o) == o + tf.ms, so looping is byte-
        # identical to ``ctx.ts + rebalance_bars * tf.ms``; on the XNYS session grid it
        # hops weekends/holidays, so a 21-bar cadence is 21 SESSIONS (a true trading
        # month), not 21 calendar days pinned to a weekday (EQUITIES: F-cadence).
        nxt = ctx.ts
        for _ in range(self._rebalance_bars):
            nxt = ctx.calendar.next_bar_open(nxt, ctx.tf)
        self._next_rebalance_ts = nxt
        if state is DDState.HALF_GROSS:
            self._n_bars_half_gross += 1
        return targets

    # ------------------------------------------------------------- mu lookup

    def _mu_asof(self, ts: Ms, tf: Timeframe, calendar: TradingCalendar) -> dict[str, float] | None:
        """Finite mu_ann per instrument for the decision at close ``ts``.

        Precomputed mode: the row at the decision bar's open — the bar that CLOSED at
        ``ts``, whose open is ``calendar.floor_bar(ts - 1, tf)`` — else the newest row
        within ``staleness_max_bars`` bars (grace), else None (stale -> hold). The open
        is resolved through the CALENDAR, not naive ``ts - tf.ms``: byte-identical on
        the 24/7 grid, but on the XNYS session grid a Monday/post-holiday decision's
        prior session is the preceding Friday, so the staleness gap is measured from the
        true prior session (a weekend is 0 bars stale, not 2 calendar days).
        Live mode: the provider's mapping, None when empty/all-NaN.
        """
        if self._mu_provider is not None:
            raw = self._mu_provider(ts)
            out = {str(iid): float(v) for iid, v in raw.items() if math.isfinite(float(v))}
            return out or None

        assert self._mu is not None  # constructor invariant; mypy aid
        want = calendar.floor_bar(ts - 1, tf)
        pos = int(np.searchsorted(self._signal_ts, want, side="right")) - 1
        if pos < 0:
            return None
        row_ts = int(self._signal_ts[pos])
        if want - row_ts > self._staleness_max_bars * tf.ms:
            return None
        row = self._mu.xs(row_ts, level="ts_open")
        finite = row[np.isfinite(row.to_numpy(dtype=np.float64))]
        if finite.empty:
            return None
        return {str(iid): float(v) for iid, v in finite.items()}

    # ------------------------------------------------------------- rebalance

    def _rebalance(
        self, ctx: StrategyContext, mu_map: Mapping[str, float]
    ) -> dict[str, float] | None:
        """Σ -> allocator -> overlay -> w_max clip -> ladder multiplier -> targets.

        Returns the target book, or None to HOLD on a cold start (covariance
        window shorter than ``cov_min_periods``) or a degenerate cross-section
        (< 2 names with a known mu, >= 2 finite returns, and positive variance);
        each None path increments its own observability counter (F-E) so the two
        are distinguishable in :attr:`counters`.
        """
        tf = ctx.tf
        closes = self._close_panel(ctx, sorted(ctx.instruments))
        rets = closes.pct_change().iloc[1:]
        if len(rets) < self._cov_min_periods:
            self._n_hold_cov_cold_start += 1
            return None

        # Tradable cross-section: a known mu AND >= 2 finite returns (the
        # covariance variance-only fallback needs that many; instruments
        # without it are simply not sized this cycle — never guessed).
        finite_counts = rets.notna().sum(axis=0)
        ids = [iid for iid in closes.columns if iid in mu_map and int(finite_counts[iid]) >= 2]
        if len(ids) < 2:
            self._n_hold_degenerate_xsection += 1
            return None

        cov_bar = ewma_cov(
            rets.loc[:, ids],
            halflife_bars=self._cov_halflife_bars,
            min_periods=self._cov_min_periods,
        )
        # Zero-variance columns (constant prints) make inverse-vol sizing
        # undefined — drop them from this cycle's cross-section.
        keep = np.flatnonzero(np.diag(cov_bar) > 0.0)
        if keep.size < 2:
            self._n_hold_degenerate_xsection += 1
            return None
        ids = [ids[int(i)] for i in keep]
        cov_bar = cov_bar[np.ix_(keep, keep)]

        # LW shrink on the jointly-complete columns (the asymptotic estimates
        # need a finite TxN window); young/gappy instruments keep their
        # documented diagonal-only EWMA fallback from ewma_cov.
        sub = rets.loc[:, ids]
        full = np.flatnonzero(sub.notna().all(axis=0).to_numpy())
        if full.size >= 2:
            block, _delta = ledoit_wolf_cc(
                sub.iloc[:, full].to_numpy(dtype=np.float64),
                cov_bar[np.ix_(full, full)],
            )
            cov_bar[np.ix_(full, full)] = block
        # Annualization basis from the sleeve calendar (the ONE source): 8760.0 for the
        # crypto H1 sleeve (Always24x7.periods_per_year(H1) == H1.bars_per_year, hence
        # byte-identical), 252.0 for equity D1 (XNYS) — never a bare tf.bars_per_year.
        periods_per_year = ctx.calendar.periods_per_year(tf)
        cov_ann = annualize_cov(nearest_psd(cov_bar), periods_per_year)

        mu = np.array([mu_map[iid] for iid in ids], dtype=np.float64)
        last_close = closes.iloc[-1]
        w_prev = np.array(
            [
                ctx.positions.get(iid, 0.0) * float(last_close[iid]) / ctx.equity
                if math.isfinite(float(last_close[iid]))
                else 0.0
                for iid in ids
            ],
            dtype=np.float64,
        )
        shortable = np.array(
            [1.0 if ctx.instruments[iid].can_short else 0.0 for iid in ids],
            dtype=np.float64,
        )
        cost = np.full(len(ids), self._cost_frac, dtype=np.float64)

        result = self._allocator.solve(mu, cov_ann, w_prev, cost, shortable)
        realized_ann = self._realized_vol_ann(periods_per_year)
        # Recomputed here rather than read back out of vol_target so the counter cannot
        # drift from the overlay's own definition of ex-ante without a test noticing.
        _w = np.asarray(result.weights, dtype=np.float64).ravel()
        if realized_ann > math.sqrt(max(float(_w @ cov_ann @ _w), 0.0)):
            self._n_realized_leg_bound += 1
        w_vt, scale = vol_target(
            result.weights,
            cov_ann,
            realized_ann,
            target=self._vol_target_ann,
            s_max=self._vol_scale_max,
            gross_max=self._gross_max,
        )
        # The vol overlay TARGETS vol and may scale a per-asset weight ABOVE
        # w_max (up to w_max * s_max). The per-name hard cap is INVIOLABLE: the
        # documented live PreTradeChecker (max_position_frac = w_max) would
        # reject such an order, so the backtest re-clips to [-w_max, +w_max]
        # here, before the ladder multiplier (F-H). The small vol-target
        # shortfall from clipping is ACCEPTED — we do NOT re-scale the book back
        # up after clipping (that would just push another name past the cap).
        w_clip = np.clip(w_vt, -self._w_max, self._w_max)
        mult = self._ladder.gross_multiplier()

        self._last_result = result
        self._last_scale = scale
        self._n_rebalances += 1
        if result.status == "fallback_used":
            self._n_fallback_used += 1

        # The PRE-multiplier (vol-targeted, w_max-clipped) book, kept so a
        # HALF_GROSS non-rebalance bar can re-emit it rescaled to the live gross
        # multiplier (F-B). Held-but-unsized ids flatten (a silently-orphaned
        # position is a risk hole; absent ids are left untouched by the engine).
        pre_mult = {iid: float(w) for iid, w in zip(ids, w_clip, strict=True)}
        for iid in ctx.positions:
            pre_mult.setdefault(iid, 0.0)
        self._last_targets = pre_mult

        return {iid: w * mult for iid, w in pre_mult.items()}

    def _close_panel(self, ctx: StrategyContext, ids: list[str]) -> pd.DataFrame:
        """Trailing close panel on the complete expected grid (PIT via ctx.bars).

        ``cov_window_bars + 1`` bars ending at ``ctx.ts``; missing grid slots
        are NaN (per-instrument gaps surface as NaN returns, handled by the
        covariance's documented drop/fallback path — never forward-filled).
        """
        window = self._cov_window_bars + 1
        tbl = ctx.bars(ids, window)
        # Grid = the last `window` BARS (sessions) ending at ctx.ts on the sleeve calendar.
        # CONTIGUOUS (24/7 crypto): ctx.ts - window*tf.ms gives exactly `window` opens —
        # byte-identical to before. GAPPY (XNYS): a `window`-CALENDAR-DAY start would yield
        # only ~0.69*window SESSIONS (weekends/holidays), silently shrinking the covariance
        # window; over-reach in calendar time then keep the last `window` expected opens.
        if ctx.calendar.contiguous:
            start = ctx.ts - window * ctx.tf.ms
        else:
            start = ctx.ts - (window * 2 + 32) * _DAY_MS  # >= 2x sessions + holiday slack
        grid = ctx.calendar.expected_bar_opens(start, ctx.ts, ctx.tf)[-window:]
        index = pd.Index(grid, dtype="int64", name="ts_open")
        if tbl.num_rows == 0:
            return pd.DataFrame(np.nan, index=index, columns=ids, dtype="float64")
        frame = pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": tbl.column("ts_open").cast(pa.int64()).to_pylist(),
                "close": tbl.column("close").to_pylist(),
            }
        )
        return (
            frame.pivot(index="ts_open", columns="instrument_id", values="close")
            .reindex(index=index, columns=ids)
            .astype("float64")
        )

    def _realized_vol_ann(self, periods_per_year: float) -> float:
        """Annualized zero-mean EWMA vol of realized per-bar equity returns.

        ``sqrt(EWMA_halflife(r²)) * sqrt(periods_per_year)`` over the equity
        history this strategy has observed (§6.3: realized leg of
        ``sigma_hat = max(ex-ante, realized)``). ``periods_per_year`` is the sleeve
        calendar's annualization basis for the anchor TF (``8760.0`` for the crypto H1
        sleeve, ``252.0`` for equity D1) — the ONE annualization source, never a bare
        ``tf.bars_per_year``. For crypto this is ``sqrt(8760)`` exactly as before.
        0.0 with < 2 equity points — the overlay then sizes off ex-ante vol alone.
        Recomputed from scratch each rebalance (O(run length), trivially cheap at daily
        cadence).
        """
        eq = np.asarray(self._equity_hist, dtype=np.float64)
        if eq.size < 2:
            return 0.0
        rets = eq[1:] / eq[:-1] - 1.0

        # DE-LEVER BEFORE MEASURING. ``_equity_hist`` is the account curve, i.e. the book
        # AFTER the overlay scaled it by ``s``; the ex-ante leg this value is compared
        # against is computed from the optimizer's PRE-overlay weights (see the
        # ``vol_target`` call site). Comparing them raw compares two different books:
        # while the book runs de-levered (s < 1) the realized side is shrunk by roughly s
        # and can never win ``max(ex_ante, realized)``, so the FAST regime detector
        # (halflife 240) is silently disabled and only the SLOW covariance leg (halflife
        # 720) runs. Measured in artifacts/analysis/frontier_14: the realized leg bound
        # 0.02% of days as shipped versus 81.8% once de-levered, worth +0.6 to +2.2pp of
        # expected maximum drawdown. Above 1x the same defect ran the other way, with the
        # overlay double-counting its own leverage.
        #
        # Dividing PER BAR (not the aggregate vol) is what makes this correct when the
        # scale varied across the window, and it is the same quantity the drawdown study
        # measured: `observed = r / max(scale, eps)`.
        #
        # WHAT THIS DOES NOT DE-LEVER, stated so the next reader does not assume more than
        # is true: the drawdown ladder's gross multiplier and the per-name w_max clip also
        # move the traded book relative to the optimizer's weights. Both are 1.0/no-op in
        # the NORMAL regime that dominates the sample, and neither was included in the arm
        # that produced the measured numbers above, so neither is included here.
        scales = np.asarray(self._scale_hist, dtype=np.float64)[1:]
        if scales.size == rets.size:
            usable = np.isfinite(scales) & (scales > 1e-9)
            # Bars before the first rebalance (scale NaN) and flat/halted bars carry no
            # information about the unlevered book's vol. Dropping them is right; dividing
            # a ~0 return by a ~0 scale would inject noise, and flooring the divisor would
            # inject a spurious 0 into the EWMA and understate vol.
            rets = np.where(usable, rets / np.where(usable, scales, 1.0), np.nan)

        ser = pd.Series(rets).pow(2)
        var = ser.ewm(halflife=self._rv_halflife_bars, adjust=True, min_periods=1).mean().iloc[-1]
        if not np.isfinite(var):
            return 0.0
        return float(np.sqrt(max(float(var), 0.0)) * np.sqrt(periods_per_year))


def _validate_signal_frame(frame: pd.DataFrame) -> tuple[pd.Series, npt.NDArray[np.int64]]:
    """Validate the precomputed signal frame; return (mu series, ts grid with signal).

    Requires the ``(ts_open, instrument_id)`` MultiIndex and the ``mu_ann``
    column. The returned grid holds the sorted unique ``ts_open`` values that
    carry at least one finite mu (all-NaN rows are non-signals: an empty
    universe slot must read as missing, not fresh).
    """
    if MU_ANN_COLUMN not in frame.columns:
        raise ValueError(
            f"signal_frame must carry the {MU_ANN_COLUMN!r} column "
            "(THE mu_ann contract, leakageCritique finding 2); got "
            f"{list(frame.columns)}"
        )
    if not isinstance(frame.index, pd.MultiIndex) or frame.index.names != [
        "ts_open",
        "instrument_id",
    ]:
        raise ValueError(
            "signal_frame index must be a (ts_open, instrument_id) MultiIndex "
            "(the SignalService.compute_research contract)"
        )
    mu = frame[MU_ANN_COLUMN].astype("float64").sort_index()
    by_ts = mu.groupby(level="ts_open").apply(lambda s: bool(np.isfinite(s.to_numpy()).any()))
    mask = np.asarray(by_ts.to_numpy(), dtype=bool)
    ts = by_ts.index.to_numpy(dtype=np.int64)[mask]
    return mu, ts
