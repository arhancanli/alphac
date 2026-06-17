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
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, cast

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa

from alphaforge.analytics import PerfSummary, build_tearsheet, daily_returns, render_text, summarize
from alphaforge.backtest import EventDrivenBacktester
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.time import Timeframe
from alphaforge.ml.model import HistGBMMetaModel, IdentityMeta, MetaModel
from alphaforge.ml.retrain import build_fit_windows
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.regime.hmm import (
    GATE_WEIGHTS,
    IdentityRegime,
    RegimeGate,
    RegimeHMM,
    build_observations,
)
from alphaforge.signals.gating import gate_signal_frame
from alphaforge.validation.experiments import ExperimentLog
from alphaforge.validation.splits import PurgedWalkForward

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from alphaforge.backtest import BacktestResult, CostInputProvider
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import Instrument, InstrumentStore
    from alphaforge.core.time import Ms
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.ml.registry import ModelRegistry
    from alphaforge.validation.dsr import DSRReport

__all__ = [
    "DailyBtcReader",
    "LegResult",
    "SignalSource",
    "ValidationReport",
    "WalkForwardResult",
    "WalkForwardRunner",
    "compare_to_baseline",
    "compute_validation",
]

_LOG = logging.getLogger(__name__)

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

# The gated-fit feature surface (Phase 12, D4): the per-leg meta-model gates the
# blend off ONE processed, direction-signed feature — the ungated blend magnitude
# ``alpha_blend`` itself. Training (the per-leg dataset builder) and serve (the
# per-leg ``gate_signal_frame`` call) BOTH assemble X through the same
# ``assemble_meta_features`` over this name, so the X at decision bar ``t`` is
# byte-identical on both paths (the train/serve parity invariant, CRITIQUE_leakage
# #15). Adding richer engine context features is a purely additive change to this
# tuple once the runner threads those columns through the signal frame.
_ALPHA_BLEND_COLUMN: Final[str] = "alpha_blend"
_GATE_FEATURE_NAMES: Final[tuple[str, ...]] = (_ALPHA_BLEND_COLUMN,)

# Per-leg meta-model training window (days) — the rolling span the HistGBM fits on
# inside ``[train_start, test_start)`` (D4). It feeds the honest trial hash (D6).
_ML_WINDOW_DAYS: Final[int] = 365

# Minimum tradable (finite, non-zero ``alpha_blend``) decisions a leg's purged train
# window must carry before the per-leg meta fit is even attempted. Below this we fall
# back to IdentityMeta (the documented cold-start fallback, mirrors D3's regime path) —
# a HistGBM + isotonic calibration on a handful of events would be noise, not an edge.
_MIN_LEG_EVENTS: Final[int] = 50

# Default HMM shape + lag for the per-leg regime gate (D3). These feed the honest trial
# hash (D6: regime_n_states / regime_gate_weights / regime_lag_days are hashed into
# trial_config when the regime gate is on, so a tuned variant is a DISTINCT DSR trial).
_REGIME_N_STATES: Final[int] = 3
_REGIME_LAG_DAYS: Final[int] = 1


class SignalSource(Protocol):
    """The slice of ``SignalService`` this runner needs (test seams stub it)."""

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        """Batch signal history over ``[start, end)`` with a ``mu_ann`` column."""
        ...


class DailyBtcReader(Protocol):
    """The daily-BTC OHLC source the HMM regime gate fits on (Phase 12, D3).

    The runner reads daily BTC bars ONCE over ``[global_start, end)`` at run start
    and slices the result to ``ts_open < test_start`` per leg (the expanding HMM fit
    window). The frame must be indexed by int64 epoch-ms ``ts_open`` (1d-aligned) with
    float ``open``/``high``/``low``/``close`` columns — exactly what
    :func:`alphaforge.regime.hmm.build_observations` consumes. In production this is a
    thin adapter over ``PITDataReader.ohlcv(..., tf=Timeframe.D1)`` for the BTC
    instrument; tests stub it with a synthetic daily frame.
    """

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        """Daily BTC OHLC over ``[start, end)`` indexed by int64 ``ts_open``."""
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

    Phase-12 gate fields (``12_FINAL.md`` 3b; all default to the blend-only values so
    the OFF path's report is byte-identical to today, D7):

    - ``variant``: ``"blend" | "ml" | "regime" | "ml+regime"`` — which gates were on.
    - ``gate_inactive_frac``: fraction of legs whose regime gate fell back to
      :class:`~alphaforge.regime.hmm.IdentityRegime` (the documented cold-start /
      insufficient-data fallback, CRITIQUE_leakage #19 observability). ``0.0`` on the
      blend-only path.
    - ``baseline``: the ungated blend-only companion :class:`ValidationReport` measured
      on the IDENTICAL purged legs (``None`` on the blend-only path itself).
    - ``clears_baseline_gate``: D5 / CRITIQUE_overfit #1 — the must-beat-baseline
      predicate (``dsr >= 0.95 AND dsr > baseline.dsr AND sr_ann > baseline.sr_ann``).
      ``False`` when there is no baseline (a blend-only run is not itself live-eligible
      under this gate; that gate is meaningful only for a gated variant).
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
    variant: str = "blend"
    gate_inactive_frac: float = 0.0
    baseline: ValidationReport | None = None
    clears_baseline_gate: bool = False

    def to_json_obj(self) -> dict[str, object]:
        """JSON-safe dict (non-finite floats -> ``None``) for the ``validation`` block.

        The Phase-12 gate keys (``variant`` / ``gate_inactive_frac`` / ``baseline`` /
        ``clears_baseline_gate``) are emitted ONLY for a GATED variant (one whose
        ``variant != "blend"`` or which carries a ``baseline`` companion). A blend-only
        run — and the nested blend-only baseline of a gated run — emits EXACTLY the nine
        pre-Phase-12 keys, so the OFF-path ``walkforward.json`` is byte-identical to
        today's HEAD (D7; the gate fields default to the blend-only values and are absent
        from the artifact, mirroring how ``config``/``trial_config`` gain gate keys only
        when a gate is on)."""
        obj: dict[str, object] = {
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
        if self.variant != "blend" or self.baseline is not None:
            obj["variant"] = str(self.variant)
            obj["gate_inactive_frac"] = _json_float(self.gate_inactive_frac)
            obj["baseline"] = None if self.baseline is None else self.baseline.to_json_obj()
            obj["clears_baseline_gate"] = bool(self.clears_baseline_gate)
        return obj


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


def compare_to_baseline(variant: ValidationReport, baseline: ValidationReport) -> bool:
    """The must-beat-baseline predicate (D5 / CRITIQUE_overfit #1).

    A gated variant is live-eligible ONLY IF, measured on the IDENTICAL purged legs
    net of fees + half-spread + funding::

        variant.clears_dsr_gate                 # dsr >= 0.95
        AND variant.dsr     > baseline.dsr      # strictly beats the blend on DSR
        AND variant.sr_ann  > baseline.sr_ann   # strictly beats the blend on Sharpe

    Strict inequalities by design: a gated variant that TIES the blend-only baseline on
    either DSR or annualized Sharpe is reported NOT live-eligible — even if its own DSR
    clears 0.95. The gate's whole purpose is to refuse a variant that does not earn the
    extra trial it costs (CRITIQUE_overfit #1/#2). Non-finite Sharpes/DSRs compare
    ``False`` (a degenerate curve never beats the baseline).
    """
    return bool(
        variant.clears_dsr_gate
        and math.isfinite(variant.dsr)
        and math.isfinite(baseline.dsr)
        and variant.dsr > baseline.dsr
        and math.isfinite(variant.sr_ann)
        and math.isfinite(baseline.sr_ann)
        and variant.sr_ann > baseline.sr_ann
    )


def _variant_label(*, ml: bool, regime: bool) -> str:
    """The ``ValidationReport.variant`` tag for the active gate combination (3b/3g).

    ``"blend"`` (neither), ``"ml"``, ``"regime"``, or ``"ml+regime"`` — the exact set
    the honest-trial test asserts and the operator reads off ``walkforward.json``.
    """
    if ml and regime:
        return "ml+regime"
    if ml:
        return "ml"
    if regime:
        return "regime"
    return "blend"


def _assemble_leg_features(
    signal_frame: pd.DataFrame, feature_names: tuple[str, ...]
) -> pd.DataFrame:
    """The serve-time X for the per-leg meta-gate (D4 / CRITIQUE_leakage #15).

    Routes through the ONE shared train/serve surface
    :func:`~alphaforge.signals.features_serve.assemble_meta_features` so the X handed to
    ``meta.bet_size`` at decision bar ``t`` is byte-identical to the X the per-leg
    dataset builder trained on (the parity invariant ``test_feature_serve_parity.py``
    pins). The Phase-12 v1 gate feature surface (:data:`_GATE_FEATURE_NAMES`) is the
    PROCESSED, direction-signed blend magnitude ``alpha_blend`` itself — already a
    column of ``signal_frame`` (the engine's processed decision-time surface), so it
    resolves through the helper's RAW-frame branch. Threading richer engine context
    columns is a purely additive change: extend ``_GATE_FEATURE_NAMES`` and ensure the
    signal frame carries the column (the same helper resolves directional names to the
    ``zs`` panel when one is supplied).

    Args:
        signal_frame: The leg's ``[alpha_blend, mu_ann]`` frame on the
            ``(ts_open, instrument_id)`` MultiIndex (the engine's processed surface).
        feature_names: The frozen meta-model's pinned column order
            (``meta.feature_names``); an empty tuple is never passed (the caller
            short-circuits to ``None``).

    Returns:
        A float frame on ``signal_frame.index`` with columns EXACTLY
        ``feature_names``, in order.
    """
    from alphaforge.signals.features_serve import assemble_meta_features

    # The v1 gate features are processed engine columns already present in the signal
    # frame (no directional zs panel needed at serve — alpha_blend IS the processed,
    # signed blend), so the shared helper's empty-zs path resolves every name from the
    # raw frame. This is the SAME call the per-leg trainer makes (train/serve parity).
    return assemble_meta_features(signal_frame, {}, feature_names)


def _maybe_register(registry: ModelRegistry, meta: MetaModel) -> None:
    """Best-effort registration of a per-leg challenger model (optional, never fatal).

    The runner discards the frozen per-leg meta after its leg by default; when a
    :class:`~alphaforge.ml.registry.ModelRegistry` is supplied the operator wants the
    per-leg challenger persisted for live-vs-backtest reconciliation. Registration is
    advisory observability, not part of the deployment gate (the binding gate is
    :func:`compare_to_baseline` on the gated WF, D5), so a registry collision /
    duplicate ``model_id`` across legs is swallowed (logged) rather than aborting an
    otherwise-valid walk-forward — the run's correctness does not depend on the side
    effect succeeding.
    """
    if not isinstance(meta, HistGBMMetaModel):
        return  # only a fitted HistGBM challenger is a registrable artifact
    try:
        from alphaforge.ml.registry import ModelCard

        card = ModelCard(
            model_id=meta.model_id,
            trained_at=int(meta.windows.fit_end),
            train_start=int(meta.windows.train_start),
            fit_end=int(meta.windows.fit_end),
            n_samples=meta.n_train,
            feature_names=meta.feature_names,
            params_json="{}",
            val_logloss=float("nan"),
            val_rank_ic=float("nan"),
            code_git_sha="walkforward-per-leg",
            data_sha256="",
            label_is_net=True,
            status="candidate",
        )
        registry.register(card, meta, importance=None)
    except (ValueError, RuntimeError) as exc:  # collision / not-fitted -> advisory only
        _LOG.warning("per-leg meta registration skipped: %s", exc)


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
        registry: optional per-leg model register/lookup (Phase 12). Kept ``None`` on
            the OFF path (and even on the ON path the per-leg frozen ``meta`` is simply
            discarded after its leg when no registry is supplied) — nothing changes.
        daily_btc_reader: optional source of the daily BTC OHLC the HMM regime gate
            fits on (Phase 12, D3 expanding window). Required only for ``regime=True``;
            ``None`` on the OFF path.
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
        registry: ModelRegistry | None = None,
        daily_btc_reader: DailyBtcReader | None = None,
        regime_n_states: int = _REGIME_N_STATES,
        regime_lag_days: int = _REGIME_LAG_DAYS,
    ) -> None:
        self._reader = reader
        self._instruments = instruments
        self._universe = universe
        self._cost_model = cost_model
        self._signals = signal_service
        self._settings = settings
        # Sleeve-resolved anchor TF + calendar (the ONE grid/annualization source,
        # SPINE_ARC §3.7). The default crypto sleeve (settings.data.asset_class ==
        # CRYPTO_PERP) anchors H1 on the 24/7 calendar, whose expected_bar_opens
        # delegates to the same core.time kernel the runner used before — byte-identical.
        self._sleeve = sleeve_for(settings.data.asset_class)
        self._calendar = self._sleeve.calendar
        self._cost_inputs = cost_inputs
        self._registry = registry
        self._daily_btc_reader = daily_btc_reader
        # Per-leg HMM shape/lag (D3); also the honest-trial-hash inputs (D6). The
        # gate-weight tuple is GATE_WEIGHTS[n_states] (the regime module's pinned vector).
        self._regime_n_states = regime_n_states
        self._regime_lag_days = regime_lag_days

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
        ml: bool = False,
        regime: bool = False,
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
        tf = self._sleeve.anchor_tf
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
        # Grid from the sleeve calendar (the ONE grid source): the 24/7 crypto calendar
        # delegates to the same core.time.expected_bar_opens (byte-identical), so the WF
        # leg layout is unchanged for crypto; the equity calendar session-filters the
        # grid, which is what makes the bar-count purge/embargo measure SESSIONS, not
        # calendar days, for free (SPINE_ARC §3.7). Equity WF is gated off this arc by the
        # FeatureEngine D1/EQUITY fail-closed guard (the compute_research call below would
        # raise), so only the crypto path is exercised here.
        grid = np.asarray(self._calendar.expected_bar_opens(start, end, tf), dtype=np.int64)

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

        # Phase 12 gates (D7: this whole block is dead on the OFF path). When ml or
        # regime is on, each leg trains a meta-model on its purged train window
        # [train_start, test_start) (D4) and refits the HMM on an EXPANDING daily-BTC
        # window ts_open < test_start (D3), then applies BOTH gates to the leg's
        # signal frame via gate_signal_frame (D1 then D2) BEFORE building/load_leg-ing
        # the strategy. The OFF path never touches gating, the daily-BTC reader, or the
        # registry, so its equity + validation are byte-identical to today.
        gated = ml or regime
        # The daily BTC OHLC is read ONCE over [start, end) and sliced per leg to
        # ts_open < test_start (the expanding HMM-fit window). Read-once is both the
        # perf win and the leak guard — the per-leg slice can only ever SHRINK it.
        daily_btc = self._read_daily_btc(start, end) if regime else None

        # The ACTIVE path: gated when ml or regime is on, blend-only otherwise. The OFF
        # path's slice-and-backtest loop is byte-identical to today (D7) because
        # _run_leg_set with ml=regime=False applies NO gate (the full_frame slice flows
        # straight into the strategy). gate_inactive counts cold-start IdentityRegime
        # fallbacks for the observability field (3b / leakage #19).
        legs, strategy, gate_inactive = self._run_leg_set(
            splitter,
            grid,
            ids,
            full_frame,
            full_ts,
            train_bars=train_bars,
            allocator=allocator,
            band=band,
            rebalance_bars=rebalance_bars,
            cov_window_bars=cov_window_bars,
            cov_halflife_bars=cov_halflife_bars,
            cov_min_periods=cov_min_periods,
            initial_cash=initial_cash,
            ml=ml,
            regime=regime,
            daily_btc=daily_btc,
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
        # D6/D7: the gate flags + their params enter the artifact echo ONLY when a gate
        # is on, so the OFF config dict (and walkforward.json) is byte-identical to today.
        config.update(self._gate_config(ml=ml, regime=regime))

        # Anti-overfit verdict (alphaDesign.md section 7.4): record THIS trial on
        # the experiment ledger and attach the PSR/DSR report. The trial config
        # hashed below is the run's DEFINING knobs (alphas / rebalance / band /
        # allocator / window) -- NOT the observability counters or initial_cash
        # (a re-run that produces different fallback counts or starts with more
        # cash is the SAME trial and must not inflate N).
        validation: ValidationReport | None = None
        if now_ms is not None:
            log = experiment_log if experiment_log is not None else self._default_log()
            base_trial_config = {
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
            # D6: when a gate is on, the trial identity hashes the ACTUAL gate params
            # (not two booleans), so a tuned gated variant is a DISTINCT DSR trial. With
            # both off these keys are ABSENT, so the config_hash is byte-identical to
            # today's HEAD ledger (D7) and OFF==identity holds on the ledger too.
            variant_trial_config = {
                **base_trial_config,
                **self._gate_trial_config(ml=ml, regime=regime),
            }
            validation = compute_validation(
                equity, variant_trial_config, log, now_ms, dsr_fn=dsr_fn
            )
            if validation is not None and gated:
                # D5 / 3g: the gated variant must BEAT the blend-only baseline measured on
                # the IDENTICAL purged legs. Re-run the legs blend-only (ungated full_frame
                # slices) once, record it as its OWN distinct trial (base_trial_config — no
                # gate keys), and attach it as the variant's baseline companion.
                base_legs, _base_strategy, _ = self._run_leg_set(
                    splitter,
                    grid,
                    ids,
                    full_frame,
                    full_ts,
                    train_bars=train_bars,
                    allocator=allocator,
                    band=band,
                    rebalance_bars=rebalance_bars,
                    cov_window_bars=cov_window_bars,
                    cov_halflife_bars=cov_halflife_bars,
                    cov_min_periods=cov_min_periods,
                    initial_cash=initial_cash,
                    ml=False,
                    regime=False,
                    daily_btc=None,
                )
                base_equity = pd.concat([leg.result.equity for leg in base_legs])
                base_equity.name = "equity"
                baseline = compute_validation(
                    base_equity, base_trial_config, log, now_ms, dsr_fn=dsr_fn
                )
                n_legs = len(legs)
                validation = dataclasses.replace(
                    validation,
                    variant=_variant_label(ml=ml, regime=regime),
                    gate_inactive_frac=(gate_inactive / n_legs) if n_legs else 0.0,
                    baseline=baseline,
                    clears_baseline_gate=(
                        baseline is not None and compare_to_baseline(validation, baseline)
                    ),
                )

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

    def _run_leg_set(
        self,
        splitter: PurgedWalkForward,
        grid: npt.NDArray[np.int64],
        ids: list[str],
        full_frame: pd.DataFrame,
        full_ts: npt.NDArray[np.int64],
        *,
        train_bars: int,
        allocator: Literal["rank", "mvo"],
        band: float,
        rebalance_bars: int,
        cov_window_bars: int,
        cov_halflife_bars: int,
        cov_min_periods: int,
        initial_cash: float,
        ml: bool,
        regime: bool,
        daily_btc: pd.DataFrame | None,
    ) -> tuple[list[LegResult], BlendStrategy | None, int]:
        """Run every leg through the engine on the (optionally gated) signal frame.

        ONE persistent :class:`~alphaforge.portfolio.strategy.BlendStrategy` reused
        across legs (continuous risk state, F-A); positions flat-restart; cash compounds.
        Per leg the global ``full_frame`` is sliced to ``[train_start, test_end)`` (the
        exact OFF-path slice). When ``ml or regime`` the slice is then run through the
        per-leg frozen gates (D1 then D2) BEFORE building/``load_leg``-ing the strategy:

        * ``ml``: :meth:`_train_leg_meta` fits a per-leg meta-model on the purged train
          window ``[train_start, test_start)`` (D4); else :class:`IdentityMeta`.
        * ``regime``: :meth:`_build_leg_regime` fits the HMM on the expanding daily window
          ``ts_open < test_start`` (D3); else / on cold start an all-1.0 ``G`` (identity).

        With ``ml=regime=False`` NO gate is applied (``gated`` is False below): the slice
        flows straight into the strategy, so this path is byte-identical to today (D7) and
        is reused verbatim to compute the blend-only baseline curve (3g). Returns
        ``(legs, strategy, gate_inactive)`` where ``gate_inactive`` counts cold-start
        IdentityRegime fallbacks (the 3b observability fraction's numerator).
        """
        gated = ml or regime
        # Anchor TF from the sleeve (crypto == H1, byte-identical). ``tf.ms`` here is the
        # bar DURATION (test_end = last test-bar open + one bar; warm-up window width),
        # not a next-session hop, so it is correct for both sleeves.
        tf = self._sleeve.anchor_tf
        strategy: BlendStrategy | None = None
        legs: list[LegResult] = []
        gate_inactive = 0
        cash = initial_cash
        for k, (_train_ts, test_ts) in enumerate(splitter.split(grid)):
            test_start = int(test_ts[0])
            test_end = int(test_ts[-1]) + tf.ms
            window_open = test_start - train_bars * tf.ms
            train_start = max(int(full_ts.min()), window_open) if full_ts.size else window_open
            # Half-open [train_start, test_end) slice via an explicit boolean mask so
            # duplicate-free semantics are exact regardless of index sort/collisions
            # (the same slice the OFF path uses; the train span only WARMS the strategy).
            in_leg = (full_ts >= train_start) & (full_ts < test_end)
            signal_frame = full_frame.iloc[in_leg]
            if gated:
                # Per-leg frozen gate artifacts (trained on < test_start data ONLY).
                meta = (
                    self._train_leg_meta(signal_frame, train_start, test_start)
                    if ml
                    else IdentityMeta()
                )
                regime_gate, leg_g_series, leg_inactive = self._build_leg_regime(
                    daily_btc, signal_frame, test_start, enabled=regime
                )
                gate_inactive += leg_inactive
                feature_frame = (
                    _assemble_leg_features(signal_frame, meta.feature_names)
                    if meta.feature_names
                    else None
                )
                # gate_signal_frame keeps the UNGATED Ã in alpha_blend and folds the
                # meta |size| and the regime G into mu_ann by linearity (D1 then D2).
                signal_frame = gate_signal_frame(
                    signal_frame,
                    feature_frame,
                    meta,
                    leg_g_series,
                    signal_frame[_ALPHA_BLEND_COLUMN],
                )
                if self._registry is not None and not isinstance(meta, IdentityMeta):
                    _maybe_register(self._registry, meta)
                del regime_gate  # frozen per-leg; discarded after the leg unless registered
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
        return legs, strategy, gate_inactive

    def _gate_config(self, *, ml: bool, regime: bool) -> dict[str, object]:
        """Gate keys for the ``config`` artifact echo — EMPTY when both off (D6/D7)."""
        out: dict[str, object] = {}
        if ml or regime:
            out["ml"] = ml
            out["regime"] = regime
        return out

    def _gate_trial_config(self, *, ml: bool, regime: bool) -> dict[str, object]:
        """The honest-trial gate identity (D6) — EMPTY when both off (D7 byte-identity).

        When a gate is on, its ACTUAL parameters are hashed (not just a boolean), so a
        tuned gated variant is a DISTINCT DSR trial and ``N`` cannot silently ratchet:

        * ``ml`` on → ``ml=True`` + ``ml_feature_set_sha`` (sha256 of the sorted resolved
          feature names, 16 hex) + ``ml_window_days``.
        * ``regime`` on → ``regime=True`` + ``regime_n_states`` + ``regime_gate_weights``
          (the pinned :data:`~alphaforge.regime.hmm.GATE_WEIGHTS` tuple for ``n_states``)
          + ``regime_lag_days``.
        """
        out: dict[str, object] = {}
        if ml:
            feature_sha = hashlib.sha256(
                json.dumps(sorted(_GATE_FEATURE_NAMES)).encode("ascii")
            ).hexdigest()[:16]
            out["ml"] = True
            out["ml_feature_set_sha"] = feature_sha
            out["ml_window_days"] = _ML_WINDOW_DAYS
        if regime:
            out["regime"] = True
            out["regime_n_states"] = self._regime_n_states
            out["regime_gate_weights"] = list(GATE_WEIGHTS[self._regime_n_states])
            out["regime_lag_days"] = self._regime_lag_days
        return out

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

    # ----------------------------------------------------- Phase 12 gate builders (D3/D4)

    def _read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame | None:
        """Daily BTC OHLC over ``[start, end)`` for the HMM fit (D3), or ``None``.

        Delegates to the injected :class:`DailyBtcReader` (production: a thin adapter
        over ``PITDataReader.ohlcv(..., tf=Timeframe.D1)`` for the BTC instrument; the
        sanctioned Phase-3 1d resampler lives BEHIND that reader — the runner never
        resamples ad hoc). Read ONCE over the whole span; the per-leg expanding-window
        slice (``ts_open < test_start``) can only SHRINK it (the leak guard, D3).
        Returns ``None`` when no reader is configured (the ``regime=False`` path never
        calls this; a ``regime=True`` run without a reader falls back leg-by-leg to
        :class:`~alphaforge.regime.hmm.IdentityRegime`).
        """
        if self._daily_btc_reader is None:
            return None
        frame = self._daily_btc_reader.read_daily_btc(start, end)
        if not pd.api.types.is_integer_dtype(frame.index):
            raise TypeError(
                "daily_btc_reader must return an int64 epoch-ms ts_open index; "
                f"got dtype {frame.index.dtype}"
            )
        return frame

    def _build_leg_regime(
        self,
        daily_btc: pd.DataFrame | None,
        signal_frame: pd.DataFrame,
        test_start: Ms,
        *,
        enabled: bool,
    ) -> tuple[RegimeGate, pd.Series, int]:
        """Fit the HMM on the EXPANDING daily window ``ts_open < test_start`` (D3).

        Returns ``(gate, g_series, inactive)`` where ``g_series`` is the daily gross
        multiplier ``G`` keyed by the day-``D`` ``ts_open`` it APPLIES TO (already lagged
        once by :meth:`~alphaforge.regime.hmm.RegimeHMM.gross_multiplier_series`), ready
        for the single backward ``merge_asof`` broadcast (D2). ``inactive`` is ``1`` when
        the leg fell back to :class:`~alphaforge.regime.hmm.IdentityRegime` (the
        documented cold-start / insufficient-data fallback), else ``0``.

        The leak guard (D3): the daily frame is sliced to ``ts_open < test_start`` BEFORE
        :func:`~alphaforge.regime.hmm.build_observations`, so no day-``D`` observation
        with ``ts_open >= test_start`` can enter the fit. ``build_observations`` raises
        ``ValueError`` when fewer than :data:`~alphaforge.regime.hmm.MIN_FIT_DAYS` finite
        daily rows remain; we catch it and fall back to ``IdentityRegime`` (G ≡ 1) rather
        than crash the run.
        """
        if not enabled or daily_btc is None:
            return IdentityRegime(), self._identity_g_series(signal_frame), 0

        # Expanding window: anchored at the global run start, ending strictly BEFORE
        # the test span. The slice is the ONLY place test-span days are excluded.
        daily_ts = daily_btc.index.to_numpy(dtype=np.int64)
        pre = daily_btc.iloc[daily_ts < test_start]
        if pre.empty:
            # An EMPTY expanding window is the extreme cold start (no daily-BTC day at
            # all precedes this leg's test span — e.g. BTC listed after the alt this leg
            # trades, or the global daily read is wholly inside the test span). The frozen
            # build_observations raises IndexError (not ValueError) on a 0-row frame
            # because it touches m[0] before its length check, so we short-circuit here
            # rather than rely on that edge — same documented IdentityRegime fallback (D3).
            _LOG.info("regime leg fell back to IdentityRegime (no pre-%d daily obs)", test_start)
            return IdentityRegime(), self._identity_g_series(signal_frame), 1
        try:
            obs = build_observations(pre)
        except (ValueError, TypeError, IndexError) as exc:
            # < MIN_FIT_DAYS finite obs (cold start) or a malformed/degenerate slice ->
            # identity. IndexError defends against the frozen build_observations touching
            # m[0] on a slice that survives the .empty guard but degenerates to 0 finite
            # rows after warm-up trimming (it raises ValueError there, but the catch stays
            # total so a frozen-seam edge never aborts an otherwise-valid walk-forward).
            _LOG.info("regime leg fell back to IdentityRegime (test_start=%d): %s", test_start, exc)
            return IdentityRegime(), self._identity_g_series(signal_frame), 1

        hmm = RegimeHMM(n_states=self._regime_n_states).fit(obs)
        # The gate's daily G is computed on the SAME (< test_start) obs and is already
        # lagged once (value at day D = filtered posterior through D-1). The hourly
        # broadcast (gate_signal_frame -> apply_regime_gate) is a single backward
        # merge_asof keyed on the day-D ts_open; cold-start hours get G=1.0 there (D2).
        g_series = hmm.gross_multiplier_series(obs, lag_days=self._regime_lag_days)
        return hmm, g_series, 0

    @staticmethod
    def _identity_g_series(signal_frame: pd.DataFrame) -> pd.Series:
        """An empty daily ``G`` series ⇒ every hour cold-starts to ``G = 1.0`` (D7).

        :func:`~alphaforge.signals.gating.apply_regime_gate` ``fillna(1.0)``s any hour
        with no day-``D`` gate at or before it, so an EMPTY right side makes the regime
        gate a byte-exact identity (multiply by 1.0) — the OFF / inactive path. Keyed by
        ``ts_open`` (int64) like a real gate so the broadcast's dtypes are uniform.
        """
        del signal_frame  # the identity series is independent of the panel rows
        empty_ts = pd.Index([], dtype="int64", name="ts_open")
        return pd.Series([], index=empty_ts, dtype="float64", name="regime_gate")

    def _train_leg_meta(
        self, signal_frame: pd.DataFrame, train_start: Ms, test_start: Ms
    ) -> MetaModel:
        """Train the per-leg meta-model on the PURGED train window (D4), or identity.

        Pipeline (D4 / 09_ml.md; all decision bars strictly ``< test_start``):

        1. Build ``events`` from the leg's blend over ``[train_start, test_start)``:
           every finite, non-zero ``alpha_blend`` row is a decision with
           ``side = sign(alpha_blend)`` (the blend side ``s``). Zero/NaN rows are not
           tradable decisions and are dropped.
        2. Read the long OHLC ``bars`` for those instruments over the train window
           (the labeler's price + funding source, PIT-clamped to ``test_start``).
        3. ``make_meta_label_dataset(bars, events, features, cfg, ...)`` with the
           cost-honest triple barrier (``ret`` net of fees + half-spread + funding,
           finding 11) and AFML sample weights; ``features`` is the shared
           :func:`_assemble_leg_features` surface (train/serve parity, finding 15).
        4. ``windows = build_fit_windows(asof=test_start, horizon_bars=h)`` —
           ``fit_end = test_start - h·Δ`` so NO ``ts_open >= test_start`` decision bar
           enters the fit (D4 OOS-honest invariant).
        5. ``HistGBMMetaModel(...).fit(X, y, w, t1, windows, label_is_net=True)``.

        A train window too short to carve :class:`~alphaforge.ml.model.FitWindows`, too
        few resolved events, or any fit-time ``ValueError`` falls back to
        :class:`~alphaforge.ml.model.IdentityMeta` (``|size| ≡ 1`` ⇒ the leg is blend-
        only) rather than crashing — the documented cold-start fallback mirrors D3.
        """
        h = self._settings.signals.horizon_bars
        try:
            windows = build_fit_windows(test_start, horizon_bars=h)
        except ValueError as exc:
            _LOG.info("ml leg fell back to IdentityMeta (test_start=%d): %s", test_start, exc)
            return IdentityMeta()

        # Decisions strictly inside the purged train window. The fit itself re-clamps
        # via fit_end = test_start - h*Δ (build_fit_windows), so this only needs to
        # exclude the test span; we trim to < test_start defensively.
        ts = signal_frame.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        a_blend = signal_frame[_ALPHA_BLEND_COLUMN].to_numpy(dtype=float)
        sign = np.sign(a_blend)
        keep = (ts >= train_start) & (ts < test_start) & np.isfinite(a_blend) & (sign != 0.0)
        if int(keep.sum()) < _MIN_LEG_EVENTS:
            _LOG.info("ml leg fell back to IdentityMeta: only %d tradable events", int(keep.sum()))
            return IdentityMeta()

        train_idx = signal_frame.index[keep]
        events = pd.DataFrame(
            {
                "ts": train_idx.get_level_values("ts_open").to_numpy(dtype=np.int64),
                "instrument_id": train_idx.get_level_values("instrument_id").to_numpy(dtype=object),
                "side": sign[keep].astype(np.int8),
            }
        )
        leg_ids = sorted({str(i) for i in events["instrument_id"].tolist()})
        bars = self._read_long_bars(leg_ids, train_start, test_start)
        if bars.empty:
            return IdentityMeta()
        instruments = self._instruments_map(leg_ids, test_start)
        funding = self._read_funding(leg_ids, train_start, test_start)
        features = _assemble_leg_features(signal_frame.loc[train_idx], _GATE_FEATURE_NAMES)

        from alphaforge.labeling import TripleBarrierConfig, make_meta_label_dataset

        # cost_honest=True ⇒ the triple-barrier `ret` is NET of fees + half-spread +
        # expected funding (finding 11), so the meta-label is P(net win) and the fit is
        # cost-honest: label_is_net is True by construction of this cfg.
        cfg = TripleBarrierConfig(horizon_bars=h, timeframe=Timeframe.H1, cost_honest=True)
        try:
            dataset = make_meta_label_dataset(
                bars,
                events,
                features,
                cfg,
                cost_model=self._cost_model,
                instruments=instruments,
                funding=funding,
                feature_names=_GATE_FEATURE_NAMES,
            )
            X, y, w, t1, _side = dataset.matrices()
            model = HistGBMMetaModel(model_id=f"histgbm_leg_{test_start}").fit(
                X, y, w, t1, windows, label_is_net=cfg.cost_honest
            )
        except (ValueError, KeyError) as exc:
            _LOG.info(
                "ml leg fell back to IdentityMeta (fit failed, test_start=%d): %s",
                test_start,
                exc,
            )
            return IdentityMeta()
        return model

    def _read_long_bars(self, ids: list[str], start: Ms, end: Ms) -> pd.DataFrame:
        """Long OHLC panel over ``[start, end)`` PIT-clamped at ``end`` (labeler input)."""
        tbl = self._reader.ohlcv(ids, start=start, end=end, as_of=end, tf=Timeframe.H1)
        return pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": tbl.column("ts_open").cast(pa.int64()).to_numpy(),
                "open": tbl.column("open").to_numpy(),
                "high": tbl.column("high").to_numpy(),
                "low": tbl.column("low").to_numpy(),
                "close": tbl.column("close").to_numpy(),
            }
        )

    def _read_funding(self, ids: list[str], start: Ms, end: Ms) -> pd.DataFrame:
        """Funding settlements over ``[start, end)`` PIT-clamped at ``end`` (cost-honest)."""
        tbl = self._reader.funding(ids, start=start, end=end, as_of=end)
        return pd.DataFrame(
            {
                "ts_funding": tbl.column("ts_funding").cast(pa.int64()).to_numpy(),
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "rate": tbl.column("rate").to_numpy(),
                "available_at": tbl.column("available_at").cast(pa.int64()).to_numpy(),
            }
        )

    def _instruments_map(self, ids: list[str], as_of: Ms) -> dict[str, Instrument]:
        """``instrument_id -> Instrument`` as of ``as_of`` (labeler metadata, mandatory)."""
        out: dict[str, Instrument] = {}
        for iid in ids:
            inst = self._instruments.get(iid, as_of)
            if inst is not None:
                out[iid] = inst
        return out


def _concat_funding(legs: list[LegResult]) -> pd.Series:
    """Concatenate per-leg funding series (empty-safe)."""
    parts = [leg.result.funding for leg in legs]
    non_empty = [s for s in parts if not s.empty]
    if not non_empty:
        return parts[0]
    return cast(pd.Series, pd.concat(non_empty))
