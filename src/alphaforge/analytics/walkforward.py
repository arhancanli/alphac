"""Walk-forward orchestrator (execDesign.md §10.4) — the number that matters.

Per leg of the :class:`~alphaforge.validation.splits.PurgedWalkForward`
layout (THE one splitter library, leakage finding 16)::

    strategy = BlendStrategy(precomputed, leg-0 signal_frame)              # ONCE
    # leg 0 uses it as built; every later leg swaps its frame in:
    strategy.load_leg(signal_frame)                                       # PER LEG
    result_k = EventDrivenBacktester.run(
                   strategy, start=test_start, end=test_end,
                   initial_cash=prior leg's final equity)                 # COMPOUNDS

then the per-leg OOS equity curves are stitched into one out-of-sample
equity curve + a combined :class:`~alphaforge.analytics.PerfSummary` and the
standard tearsheet.

ONE strategy is reused across all legs (F-A): equity compounds with no resets,
so the RISK STATE must be continuous too. A fresh BlendStrategy per leg reseeds
the drawdown ladder's high-water mark to leg-open equity, so a drawdown
straddling a leg boundary never trips ``dd_flat_halt`` and a halt silently
resurrects the next leg — an OPTIMISTIC, dishonest curve. Reusing one strategy
keeps the ladder (state + HWM) and the realized-vol equity history running on
the true continuous OOS equity; only the per-leg signal frame is swapped (and
the rebalance schedule reset) via ``load_leg``.

Why computing the signal frame over ``[train_start, test_end)`` does NOT
leak: the blend weights inside ``compute_research`` are ROLLING — the weight
row in force at any decision ``t`` is estimated from Rank-ICs whose labels
were fully realized by ``t`` (``t' + h·Δ <= t``, enforced mechanically inside
``estimate_blend_weights``), and there is no full-sample weight vector
anywhere. The train window therefore only WARMS UP the EWMA-IC state so the
test span starts with informed weights; no statistic computed over the test
span ever influences a decision inside it. The splitter's purge matters for
*fitted* models (Phase 9/10 ML CV — same splitter, real purging); here it is
consumed for leg layout and for asserting ``purge >= h`` once, from settings.

Leg boundary semantics (deliberate, documented): each leg starts FLAT with
``initial_cash = prior leg's final equity`` — equity AND risk state compound
across legs with no resets (one persistent strategy, F-A), but POSITIONS do not
persist across the boundary (each test span is an independent engine run; the
flat restart costs one extra rebalance's worth of entry trading per leg and
keeps every leg independently reproducible from its artifacts). The risk state
is continuous; positions flat-restart — the entry cost is the documented
pessimistic F-N charge, unchanged. The §10.4 "model swaps inside one continuous
run" refinement arrives with the ML layer, which actually has models to swap.

NOT exported from ``alphaforge.analytics``'s ``__init__``: this module
imports the backtest engine, which itself imports analytics — re-exporting
here would cycle. Import as ``from alphaforge.analytics.walkforward import
WalkForwardRunner``.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.analytics import PerfSummary, build_tearsheet, render_text, summarize
from alphaforge.backtest import EventDrivenBacktester
from alphaforge.core.time import Timeframe, expected_bar_opens
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.validation.splits import PurgedWalkForward

if TYPE_CHECKING:
    from pathlib import Path

    from alphaforge.backtest import BacktestResult, CostInputProvider
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import Ms
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore

__all__ = ["LegResult", "SignalSource", "WalkForwardResult", "WalkForwardRunner"]

_EQUITY_FILE: Final[str] = "equity.parquet"
_META_FILE: Final[str] = "walkforward.json"
_SUMMARY_FILE: Final[str] = "summary.txt"
_LEGS_DIR: Final[str] = "legs"


class SignalSource(Protocol):
    """The slice of ``SignalService`` this runner needs (test seams stub it)."""

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        """Batch signal history over ``[start, end)`` with a ``mu_ann`` column."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class LegResult:
    """One out-of-sample leg: its span, the full engine result, and the
    per-leg risk/observability counters.

    ``risk_counters`` is the per-leg DELTA of
    :attr:`~alphaforge.portfolio.strategy.BlendStrategy.counters` (the cumulative
    strategy counters span legs because the risk state persists across the leg
    boundary, F-A; subtracting the pre-leg snapshot gives this leg's own
    rebalances / fallbacks / holds / halts — the operator's per-leg confession).
    """

    leg: int
    train_start: Ms
    test_start: Ms
    test_end: Ms
    result: BacktestResult
    risk_counters: dict[str, int]


@dataclass(frozen=True, kw_only=True)
class WalkForwardResult:
    """Stitched OOS equity + per-leg results + the combined summary.

    Structurally satisfies :class:`alphaforge.analytics.ResultLike` (equity /
    fills / funding / positions concatenated across legs), so the standard
    tearsheet renders the full OOS path. ``summary`` is recomputed over the
    stitched artifacts — the same convention as :class:`BacktestResult`.
    """

    equity: pd.Series
    legs: tuple[LegResult, ...]
    summary: PerfSummary
    config: dict[str, object]

    # --------------------------------------------------------- ResultLike

    @property
    def fills(self) -> pd.DataFrame:
        """All OOS fills, concatenated in leg order."""
        return _concat_frames([leg.result.fills for leg in self.legs])

    @property
    def positions(self) -> pd.DataFrame:
        """All OOS position snapshots, concatenated in leg order."""
        return _concat_frames([leg.result.positions for leg in self.legs])

    @property
    def funding(self) -> pd.Series:
        """All OOS settled funding cashflows, concatenated in leg order."""
        parts = [leg.result.funding for leg in self.legs]
        non_empty = [s for s in parts if not s.empty]
        if not non_empty:
            return parts[0] if parts else pd.Series(dtype="float64", name="payment_quote")
        return cast(pd.Series, pd.concat(non_empty))

    # -------------------------------------------------------- persistence

    def save(self, out_dir: Path) -> Path:
        """Write all artifacts; return ``out_dir``.

        Layout::

            equity.parquet     stitched OOS curve (ts, equity)
            walkforward.json   config echo + per-leg summary table
            summary.txt        rendered combined PerfSummary
            tearsheet.png/.txt standard 6-panel tearsheet over the OOS path
            legs/leg_00/ ...   full BacktestResult artifacts per leg
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "ts": self.equity.index.to_numpy(dtype="int64"),
                "equity": self.equity.to_numpy(dtype="float64"),
            }
        ).to_parquet(out_dir / _EQUITY_FILE, index=False)

        leg_rows = [
            {
                "leg": leg.leg,
                "train_start": leg.train_start,
                "test_start": leg.test_start,
                "test_end": leg.test_end,
                "summary": _summary_dict(leg.result.summary),
                "risk_counters": dict(leg.risk_counters),
            }
            for leg in self.legs
        ]
        meta = {
            "config": self.config,
            "summary": _summary_dict(self.summary),
            "legs": leg_rows,
        }
        (out_dir / _META_FILE).write_text(
            json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (out_dir / _SUMMARY_FILE).write_text(render_text(self.summary), encoding="utf-8")
        build_tearsheet(self, out_dir)
        for leg in self.legs:
            leg.result.save(out_dir / _LEGS_DIR / f"leg_{leg.leg:02d}")
        return out_dir


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Row-concat preserving schema when every frame is empty."""
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return frames[0].copy()
    return pd.concat(non_empty, ignore_index=True)


def _counter_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Per-leg counter delta ``after - before`` (cumulative strategy counters
    span legs because the risk state persists across the boundary, F-A)."""
    return {key: after[key] - before.get(key, 0) for key in after}


def _summary_dict(summary: PerfSummary) -> dict[str, object]:
    """PerfSummary -> JSON-safe dict (non-finite floats become None)."""
    out: dict[str, object] = {}
    for key, value in dataclasses.asdict(summary).items():
        out[key] = None if isinstance(value, float) and not math.isfinite(value) else value
    return out


class WalkForwardRunner:
    """Drive purged walk-forward legs through the truth engine (module docstring).

    Args:
        reader: PIT lake reader (the engine's and the strategy's only data path).
        instruments: SCD2 instrument store for the engine.
        universe: PIT membership store; the run universe is every instrument
            whose membership interval overlaps ``[start, end)``.
        cost_model: THE shared cost authority.
        signal_service: anything satisfying :class:`SignalSource` — in
            production the Phase-6 ``SignalService``.
        settings: limits/knobs for the strategy + the splitter's ``purge_bars
            = signals.horizon_bars`` assertion (the ONE horizon constant).
        cost_inputs: optional engine ADV/sigma provider override (tests inject
            ``StaticCostInputs``; default None = per-leg ``LakeCostInputs``).
    """

    def __init__(
        self,
        reader: PITDataReader,
        instruments: InstrumentStore,
        universe: UniverseStore,
        cost_model: TransactionCostModel,
        signal_service: SignalSource,
        settings: Settings,
        *,
        cost_inputs: CostInputProvider | None = None,
    ) -> None:
        self._reader = reader
        self._instruments = instruments
        self._universe = universe
        self._cost_model = cost_model
        self._signals = signal_service
        self._settings = settings
        self._cost_inputs = cost_inputs

    def run(
        self,
        start: Ms,
        end: Ms,
        *,
        train_bars: int,
        test_bars: int,
        allocator: Literal["rank", "mvo"] = "rank",
        embargo_bars: int = 168,
        initial_cash: float = 100_000.0,
        instrument_ids: list[str] | None = None,
        rebalance_bars: int = 24,
        cov_window_bars: int = 720,
        cov_halflife_bars: int = 720,
        cov_min_periods: int = 240,
        out_dir: Path | None = None,
    ) -> WalkForwardResult:
        """Run every leg over ``[start, end)``; return (and optionally save) the result.

        ``start``/``end`` must be 1h-aligned epoch-ms UTC. ``train_bars`` /
        ``test_bars`` are grid points (1h bars); legs roll by ``test_bars``
        and the test spans tile ``[start + train_bars·Δ, end)``. The first
        ``train_bars`` bars are warm-up only (signal-frame IC history + Σ
        window) and never traded. Leg k's ``initial_cash`` is leg k-1's final
        marked equity — the OOS curve compounds with no resets. Strategy
        knobs (``rebalance_bars`` etc.) pass through to
        :class:`~alphaforge.portfolio.strategy.BlendStrategy`.

        Raises ``ValueError`` on malformed bounds, an empty universe window,
        or a grid too short for one leg (via the splitter).
        """
        tf = Timeframe.H1
        if end <= start:
            raise ValueError(f"end ({end}) must be > start ({start})")
        if start % tf.ms or end % tf.ms:
            raise ValueError(f"start/end must be {tf.value}-aligned epoch-ms, got {start}/{end}")

        ids = (
            sorted(dict.fromkeys(instrument_ids))
            if instrument_ids is not None
            else self._window_ids(start, end)
        )
        if not ids:
            raise ValueError(f"no instruments overlap the window [{start}, {end})")

        splitter = PurgedWalkForward.from_settings(
            self._settings, train_bars=train_bars, test_bars=test_bars, embargo_bars=embargo_bars
        )
        grid = np.asarray(expected_bar_opens(start, end, tf), dtype=np.int64)

        # ONE strategy reused across all legs (F-A): the OOS equity stream is
        # CONTINUOUS (leg k+1's initial_cash is leg k's final equity), so the
        # risk state — the DrawdownLadder (state + HWM) and the realized-vol
        # equity history — MUST persist across leg boundaries or the curve goes
        # optimistic: a drawdown straddling a boundary would never trip
        # dd_flat_halt and a halt would silently resurrect next leg. Built once
        # below with the first leg's frame; every later leg swaps in its frame
        # via strategy.load_leg (preserving risk state, resetting only the
        # rebalance schedule). Positions still flat-restart each leg (the
        # documented pessimistic one-extra-rebalance entry cost, F-N) — only the
        # RISK STATE is continuous.
        strategy: BlendStrategy | None = None
        legs: list[LegResult] = []
        cash = initial_cash
        for k, (_train_ts, test_ts) in enumerate(splitter.split(grid)):
            test_start = int(test_ts[0])
            test_end = int(test_ts[-1]) + tf.ms
            train_start = max(start, test_start - train_bars * tf.ms)
            # ONE research pass per leg over [train_start, test_end): the train
            # span warms the rolling blend weights; PIT by construction (module
            # docstring — weights at t use ICs realized by t only).
            signal_frame = self._signals.compute_research(train_start, test_end)
            if strategy is None:
                strategy = BlendStrategy(
                    self._settings,
                    signal_frame=signal_frame,
                    allocator=allocator,
                    rebalance_bars=rebalance_bars,
                    cov_window_bars=cov_window_bars,
                    cov_halflife_bars=cov_halflife_bars,
                    cov_min_periods=cov_min_periods,
                )
            else:
                strategy.load_leg(signal_frame)
            counters_before = strategy.counters
            engine = EventDrivenBacktester(
                self._reader,
                self._instruments,
                self._cost_model,
                cost_inputs=self._cost_inputs,
                no_trade_band_frac=self._settings.portfolio.no_trade_band,
                config_echo={
                    "walkforward_leg": k,
                    "train_start": train_start,
                    "allocator": allocator,
                },
            )
            result = engine.run(strategy, ids, start=test_start, end=test_end, initial_cash=cash)
            cash = float(result.equity.iloc[-1])
            legs.append(
                LegResult(
                    leg=k,
                    train_start=train_start,
                    test_start=test_start,
                    test_end=test_end,
                    result=result,
                    risk_counters=_counter_delta(counters_before, strategy.counters),
                )
            )

        # Aggregate risk counters across legs = the final cumulative strategy
        # snapshot (load_leg never resets, so the last leg's counters ARE the
        # run total). Equal to the sum of per-leg deltas by construction.
        risk_counters_total = strategy.counters if strategy is not None else {}

        # Legs tile, so per-leg close grids are disjoint and already ordered.
        equity = pd.concat([leg.result.equity for leg in legs])
        equity.name = "equity"
        wf = WalkForwardResult(
            equity=equity,
            legs=tuple(legs),
            summary=summarize(
                equity,
                fills=_concat_frames([leg.result.fills for leg in legs]),
                funding=_concat_funding(legs),
                positions=_concat_frames([leg.result.positions for leg in legs]),
            ),
            config={
                "start": start,
                "end": end,
                "train_bars": train_bars,
                "test_bars": test_bars,
                "purge_bars": splitter.purge_bars,
                "embargo_bars": splitter.embargo_bars,
                "allocator": allocator,
                "rebalance_bars": rebalance_bars,
                "initial_cash": initial_cash,
                "instrument_ids": list(ids),
                "n_legs": len(legs),
                # Aggregate observability counters (F-D / F-E): a run labelled
                # allocator="mvo" whose n_fallback_used is near n_rebalances was
                # mostly rank-fallback; a frozen book from a dead feed shows up
                # as hold_stale_signal, distinct from hold_between_rebalance.
                "risk_counters": risk_counters_total,
            },
        )
        if out_dir is not None:
            wf.save(out_dir)
        return wf

    def _window_ids(self, start: Ms, end: Ms) -> list[str]:
        """Sorted instruments whose membership interval overlaps ``[start, end)``."""
        tbl = self._universe.read_intervals()
        ids = tbl.column("instrument_id").to_pylist()
        froms = tbl.column("effective_from").cast(pa.int64()).to_pylist()
        tos = tbl.column("effective_to").cast(pa.int64()).to_pylist()
        return sorted(
            {
                str(iid)
                for iid, eff_from, eff_to in zip(ids, froms, tos, strict=True)
                if int(eff_from) < end and (eff_to is None or int(eff_to) > start)
            }
        )


def _concat_funding(legs: list[LegResult]) -> pd.Series:
    """Concatenate per-leg funding series (empty-safe)."""
    parts = [leg.result.funding for leg in legs]
    non_empty = [s for s in parts if not s.empty]
    if not non_empty:
        return parts[0]
    return cast(pd.Series, pd.concat(non_empty))
