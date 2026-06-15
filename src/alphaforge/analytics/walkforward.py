"""Walk-forward orchestrator (execDesign.md §10.4) — the number that matters.

Per leg of the :class:`~alphaforge.validation.splits.PurgedWalkForward`
layout (THE one splitter library, leakage finding 16)::

    full_frame = signal_service.compute_research(start, end)              # ONCE
    strategy   = BlendStrategy(precomputed, full_frame[leg-0 slice])      # ONCE
    # leg 0 uses it as built; every later leg swaps its frame slice in:
    strategy.load_leg(full_frame[leg-k slice])                            # PER LEG
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

The signal frame is computed ONCE over the whole ``[start, end)`` span and
SLICED per leg (perf: the legacy per-leg ``compute_research`` calls overlapped
~80%; one global pass over ~43k bar-rows replaces ~176k re-derived ones across
16 legs). This is numerically EQUIVALENT, not a divergent speedup: every
per-``(t, i)`` statistic is window-local -- the directional z-scores and the
Grinold ``sigma_hat`` at bar ``t`` are functions of data through ``t`` only
(each warmed with its declared lookback), and the rolling blend weight
``w_k(t)`` is SLICE-INVARIANT because the rank-IC is subsampled on an ABSOLUTE
bar grid (``non_overlapping(..., delta_ms=delta)``). The global pass carries
MORE realized-IC history before each leg than a per-leg pass would, so it is the
MORE-correct reference (it never under-warms a later leg's EWMA-IC); the
residual vs the per-leg path is exactly that warm-up truncation, pinned below
the blend-weight tolerance in ``tests/integration/test_walkforward_equivalence``.

Why slicing the global frame to ``[train_start, test_end)`` does NOT leak: the
blend weights inside ``compute_research`` are ROLLING — the weight row in force
at any decision ``t`` is estimated from Rank-ICs whose labels were fully
realized by ``t`` (``t' + h·Δ <= t``, enforced mechanically inside
``estimate_blend_weights``), and there is no full-sample weight vector
anywhere. The train slice therefore only WARMS the strategy's mu lookup so the
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

from alphaforge.analytics import PerfSummary, build_tearsheet, daily_returns, render_text, summarize
from alphaforge.backtest import EventDrivenBacktester
from alphaforge.core.time import Timeframe, expected_bar_opens
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.validation.experiments import ExperimentLog
from alphaforge.validation.splits import PurgedWalkForward

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from alphaforge.backtest import BacktestResult, CostInputProvider
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import Ms
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.validation.dsr import DSRReport

__all__ = [
    "LegResult",
    "SignalSource",
    "ValidationReport",
    "WalkForwardResult",
    "WalkForwardRunner",
    "compute_validation",
]

# Minimum n_trials the DSR expected-max-Sharpe form is defined for (alphaDesign.md
# section 7.4 / dsr.expected_max_sharpe raises for n_trials < 2): with a single
# trial there is no selection bias to deflate against. We report the HONEST
# measured trial count in the block but feed max(2, n_trials) to the maths so a
# first-ever run still produces a (provisional) DSR rather than crashing.
_MIN_DSR_TRIALS: Final[int] = 2

# Deployment gate (alphaDesign.md section 7.4): a configuration family is
# live-eligible only when its Deflated Sharpe Ratio clears this threshold.
_DSR_GATE: Final[float] = 0.95

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


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationReport:
    """The anti-overfit verdict attached to a walk-forward run (alphaDesign.md section 7.4).

    Built by :func:`compute_validation` from the stitched OOS daily returns and
    the experiment ledger. All Sharpe quantities in ``psr``/``dsr``/
    ``expected_max_sr`` are PER-PERIOD probabilities/Sharpes (the maths is
    per-period; ``sr_ann`` is the human-facing annualized Sharpe).

    - ``psr``: PSR against a zero benchmark -- P(true Sharpe > 0 | sample).
    - ``dsr``: Deflated Sharpe Ratio -- PSR against the expected-max-Sharpe of
      ``n_trials`` searched configs. THE deployment gate quantity (>= 0.95).
    - ``sr_ann``: annualized Sharpe of the OOS daily returns (reporting only).
    - ``n_trials``: HONEST measured number of distinct trials on the ledger.
    - ``n_trials_used``: ``max(2, n_trials)`` -- what the deflation maths used
      (the expected-max form needs >= 2 trials; equals ``n_trials`` once a
      second config is logged).
    - ``expected_max_sr``: the deflation benchmark ``SR*`` (per period).
    - ``sr_trials_variance``: ``V[SR]`` used (ledger variance, or the documented
      :data:`~alphaforge.validation.experiments.DEFAULT_SR_TRIALS_VARIANCE`
      fallback when fewer than 2 finite trial Sharpes exist).
    - ``n_obs``: number of daily return observations behind the statistics.
    - ``clears_dsr_gate``: ``dsr >= 0.95`` (the design's live-eligibility gate).
    """

    psr: float
    dsr: float
    sr_ann: float
    n_trials: int
    n_trials_used: int
    expected_max_sr: float
    sr_trials_variance: float
    n_obs: int
    clears_dsr_gate: bool

    def to_json_obj(self) -> dict[str, object]:
        """JSON-safe dict (non-finite floats -> ``None``) for the ``validation`` block."""
        return {
            "psr": _json_float(self.psr),
            "dsr": _json_float(self.dsr),
            "sr_ann": _json_float(self.sr_ann),
            "n_trials": int(self.n_trials),
            "n_trials_used": int(self.n_trials_used),
            "expected_max_sr": _json_float(self.expected_max_sr),
            "sr_trials_variance": _json_float(self.sr_trials_variance),
            "n_obs": int(self.n_obs),
            "clears_dsr_gate": bool(self.clears_dsr_gate),
        }


@dataclass(frozen=True, kw_only=True)
class WalkForwardResult:
    """Stitched OOS equity + per-leg results + the combined summary.

    Structurally satisfies :class:`alphaforge.analytics.ResultLike` (equity /
    fills / funding / positions concatenated across legs), so the standard
    tearsheet renders the full OOS path. ``summary`` is recomputed over the
    stitched artifacts — the same convention as :class:`BacktestResult`.

    ``validation`` is the anti-overfit (PSR/DSR) verdict, attached by
    :meth:`WalkForwardRunner.run` after the run is stitched (alphaDesign.md
    section 7.4); it is ``None`` only when no daily returns could be computed
    (an OOS span shorter than two UTC days).
    """

    equity: pd.Series
    legs: tuple[LegResult, ...]
    summary: PerfSummary
    config: dict[str, object]
    validation: ValidationReport | None = None

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
            "validation": None if self.validation is None else self.validation.to_json_obj(),
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


def _json_float(value: float) -> float | None:
    """Non-finite float -> ``None`` (strict JSON has no NaN/Inf)."""
    return None if not math.isfinite(value) else float(value)


def compute_validation(
    equity: pd.Series,
    config: Mapping[str, object],
    log: ExperimentLog,
    now_ms: Ms,
    *,
    dsr_fn: Callable[..., DSRReport] | None = None,
) -> ValidationReport | None:
    """Record this trial on ``log`` and build its :class:`ValidationReport`.

    Pipeline (alphaDesign.md section 7.4), leak-free and deterministic:

    1. Compute UTC-DAILY returns from the stitched OOS ``equity`` (the headline
       basis, leakageCritique finding 29). If the run spans fewer than two UTC
       days there is no daily-return sample and this returns ``None``.
    2. Derive the per-period (daily) and annualized Sharpe plus the daily-return
       skewness and non-excess kurtosis, and ``record`` the trial on ``log``
       keyed by ``config`` (idempotent on the config hash -- a re-run of an
       identical configuration does not inflate ``N``). ``now_ms`` is the
       caller-supplied timestamp; the clock is never read here.
    3. Read ``N = log.n_trials()`` and ``V[SR] = log.trial_sharpe_variance()``
       *after* recording (so this trial is counted), and compute the DSR via the
       blessed :func:`~alphaforge.validation.dsr.dsr_from_returns` API. The
       expected-max-Sharpe form requires ``N >= 2``; with a single trial we feed
       ``max(2, N)`` to the maths and report the honest ``N`` in the block.

    ``dsr_fn`` overrides the DSR implementation (tests inject a deterministic
    stub); it defaults to ``dsr_from_returns`` (deferred import -- the DSR module
    pulls scipy). ``config`` should be the trial's defining knobs (alphas /
    rebalance / band / allocator / window); it is hashed verbatim.
    """
    rets = daily_returns(equity)
    if len(rets) < 2:
        return None

    # Per-period (daily) and annualized Sharpe + the daily-return moments. These
    # are the SAME estimators dsr_from_returns derives internally (recomputed
    # here only to populate the ledger -- the DSR maths recomputes from the
    # series so the trial Sharpe stored and the Sharpe judged never drift).
    from scipy.stats import kurtosis as _kurtosis
    from scipy.stats import skew as _skew

    from alphaforge.analytics.metrics import DAYS_PER_YEAR, sharpe

    vals = rets.to_numpy(dtype="float64")
    sr_per_period = sharpe(rets, 1.0)  # per-period (A = 1)
    sr_ann = sharpe(rets, DAYS_PER_YEAR)
    skew = float(_skew(vals, bias=True))
    kurt = float(_kurtosis(vals, fisher=False, bias=True))

    log.record(
        config,
        sharpe_ann=sr_ann,
        sharpe_per_period=sr_per_period,
        n_obs=len(rets),
        skew=skew,
        kurtosis=kurt,
        now_ms=now_ms,
    )

    n_trials = log.n_trials()
    var_sr = log.trial_sharpe_variance()  # DEFAULT_SR_TRIALS_VARIANCE when < 2 trials
    n_trials_used = max(_MIN_DSR_TRIALS, n_trials)

    fn = dsr_fn
    if fn is None:
        from alphaforge.validation.dsr import dsr_from_returns

        fn = dsr_from_returns
    report = fn(rets, n_trials_used, var_sr, DAYS_PER_YEAR)

    return ValidationReport(
        psr=report.psr,
        dsr=report.dsr,
        sr_ann=report.sr_ann,
        n_trials=n_trials,
        n_trials_used=n_trials_used,
        expected_max_sr=report.expected_max_sr,
        sr_trials_variance=var_sr,
        n_obs=report.n_obs,
        clears_dsr_gate=math.isfinite(report.dsr) and report.dsr >= _DSR_GATE,
    )


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
        no_trade_band: float | None = None,
        cov_window_bars: int = 720,
        cov_halflife_bars: int = 720,
        cov_min_periods: int = 240,
        out_dir: Path | None = None,
        now_ms: Ms | None = None,
        alpha_names: list[str] | None = None,
        experiment_log: ExperimentLog | None = None,
        dsr_fn: Callable[..., DSRReport] | None = None,
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

        ``now_ms`` is the caller's wall-clock epoch-ms (never read from the clock
        here — determinism): it stamps the experiment-ledger trial. When it is
        ``None`` the anti-overfit step is skipped entirely (``validation`` stays
        ``None``, nothing is recorded) so callers that do not opt in pay no
        clock/ledger cost. ``alpha_names`` (the blended factor names) feeds the
        trial's config hash; ``experiment_log`` is the ledger the trial is
        recorded on (default: ``settings.paths.var_dir / "experiments.jsonl"``).
        After the OOS curve is stitched, the run records its trial and attaches a
        :class:`ValidationReport` (PSR/DSR, alphaDesign.md section 7.4) to the
        result and the saved ``walkforward.json`` ``validation`` block. ``dsr_fn``
        overrides the DSR implementation (tests inject a deterministic stub).

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

        # Turnover knob: the no-trade band suppresses |Delta| < band*equity orders.
        # Default reads settings.portfolio.no_trade_band; an explicit override lets
        # a turnover/cost sweep widen it (the base over-trades a weak edge -- the
        # 10bps default lets through trades that can't clear their own cost hurdle).
        band = self._settings.portfolio.no_trade_band if no_trade_band is None else no_trade_band

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
        # COMPUTE THE SIGNAL FRAME ONCE over the whole [start, end) span, then
        # SLICE per leg (perf: the per-leg compute_research calls overlapped ~80%
        # -- 16 legs over ~11k bars re-derived ~176k bar-rows where one global pass
        # derives ~43k). This is numerically EQUIVALENT, not a divergent speedup,
        # because every per-(t,i) statistic is window-local: the directional
        # z-scores and the Grinold sigma_hat at bar t are functions of data through
        # t only (the engine warms each up with its declared lookback), and the
        # rolling blend weight w_k(t) is now SLICE-INVARIANT -- the rank-IC is
        # subsampled on an ABSOLUTE bar grid (service.py delta_ms anchoring), so a
        # leg's kept IC timestamps are a subset of the global pass's, and the
        # lagged-EWMA blend weight at t over those identical kept ICs differs only
        # by the warm-up truncation a per-leg pass would suffer at its own
        # train_start. The global pass, carrying MORE realized-IC history before
        # each leg, is therefore the MORE-correct reference (it never UNDER-warms a
        # later leg). PIT is preserved by construction (module docstring): the
        # weight in force at decision t still uses only ICs whose labels realized
        # by t -- slicing the frame to [train_start, test_end) changes nothing
        # about which row the strategy reads at each t, only how warm that row's
        # weight estimate is. The equivalence is pinned by tests/integration/
        # test_walkforward_equivalence.py.
        full_frame = self._signals.compute_research(start, end)
        full_ts = full_frame.index.get_level_values("ts_open").to_numpy(dtype=np.int64)

        strategy: BlendStrategy | None = None
        legs: list[LegResult] = []
        cash = initial_cash
        for k, (_train_ts, test_ts) in enumerate(splitter.split(grid)):
            test_start = int(test_ts[0])
            test_end = int(test_ts[-1]) + tf.ms
            train_start = max(start, test_start - train_bars * tf.ms)
            # Slice the global frame to this leg's [train_start, test_end) span
            # (half-open, the same bounds the per-leg compute_research used). The
            # train span only WARMS the strategy's mu lookup (BlendStrategy reads
            # the row at ts_open = ctx.ts - delta and never trades the warm-up
            # bars); PIT by construction (module docstring -- weights at t use ICs
            # realized by t only). .loc on the ts_open level is avoided in favour
            # of an explicit boolean mask so duplicate-free half-open semantics are
            # exact regardless of index sort/label collisions.
            in_leg = (full_ts >= train_start) & (full_ts < test_end)
            signal_frame = full_frame.iloc[in_leg]
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
                no_trade_band_frac=band,
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
        config: dict[str, object] = {
            "start": start,
            "end": end,
            "train_bars": train_bars,
            "test_bars": test_bars,
            "purge_bars": splitter.purge_bars,
            "embargo_bars": splitter.embargo_bars,
            "allocator": allocator,
            "rebalance_bars": rebalance_bars,
            "no_trade_band": band,
            "initial_cash": initial_cash,
            "instrument_ids": list(ids),
            "n_legs": len(legs),
            # Aggregate observability counters (F-D / F-E): a run labelled
            # allocator="mvo" whose n_fallback_used is near n_rebalances was
            # mostly rank-fallback; a frozen book from a dead feed shows up
            # as hold_stale_signal, distinct from hold_between_rebalance.
            "risk_counters": risk_counters_total,
        }
        if alpha_names is not None:
            config["alpha_names"] = list(alpha_names)

        # Anti-overfit verdict (alphaDesign.md section 7.4): record THIS trial on
        # the experiment ledger and attach the PSR/DSR report. The trial config
        # hashed below is the run's DEFINING knobs (alphas / rebalance / band /
        # allocator / window) -- NOT the observability counters or initial_cash
        # (a re-run that produces different fallback counts or starts with more
        # cash is the SAME trial and must not inflate N).
        validation: ValidationReport | None = None
        if now_ms is not None:
            log = experiment_log if experiment_log is not None else self._default_log()
            trial_config = {
                "start": start,
                "end": end,
                "train_bars": train_bars,
                "test_bars": test_bars,
                "allocator": allocator,
                "rebalance_bars": rebalance_bars,
                "no_trade_band": band,
                "instrument_ids": list(ids),
                "alpha_names": list(alpha_names) if alpha_names is not None else None,
            }
            validation = compute_validation(equity, trial_config, log, now_ms, dsr_fn=dsr_fn)

        wf = WalkForwardResult(
            equity=equity,
            legs=tuple(legs),
            summary=summarize(
                equity,
                fills=_concat_frames([leg.result.fills for leg in legs]),
                funding=_concat_funding(legs),
                positions=_concat_frames([leg.result.positions for leg in legs]),
            ),
            config=config,
            validation=validation,
        )
        if out_dir is not None:
            wf.save(out_dir)
        return wf

    def _default_log(self) -> ExperimentLog:
        """The default experiment ledger: ``settings.paths.var_dir / experiments.jsonl``."""
        return ExperimentLog(self._settings.paths.var_dir / "experiments.jsonl")

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
