"""The tested analysis core of the self-driving grand-backtest harness.

Pure, deterministic, offline analysis the thin ``scripts/grand_backtest.py``
driver calls. NOT exported from :mod:`alphaforge.analytics` (it imports
:mod:`alphaforge.analytics.walkforward`, which imports the engine -> cycle; same
rule as ``walkforward.py``). Import as
``from alphaforge.analytics.grand_matrix import ...``.

This module pins the bounded ~16-run robustness matrix
(``GRAND_BACKTEST.md`` section 1), the cross-config DSR / PBO instruments, the
capacity-curve builder, the deflated-winner selector, and the ``matrix.json`` /
``verdict.md`` writers. Every function is unit-tested on synthetic per-config
fixtures (never the live lake).

Honest-deflation discipline (the whole point)
---------------------------------------------
The blocking finding of both ``GB_CRITIQUE_*.md`` (B1 / GB1): the runner's own
``validation.dsr`` is deflated against ``N`` AS IT STOOD WHEN THAT CONFIG RAN
(``compute_validation`` records the trial, *then* reads ``log.n_trials()``), so a
config that ran early on the shared ledger is judged against a SMALLER, flattering
``SR*`` than one that ran late. That is run-order-dependent and tilts toward
passing a non-edge. This module therefore NEVER uses the per-config
``validation.dsr`` for any gate or winner decision: every distinct-trial config
(and the baseline) is RE-DEFLATED against the SHARED final
``(cross.n_trials, cross.sr_trials_variance)`` context via
:func:`alphaforge.validation.dsr.dsr_from_returns` over that config's own OOS
DAILY returns. ``sr_ann`` is annualization-only (run-order invariant) and read off
the runner. The raw per-config ``validation.dsr`` is preserved in ``matrix.json``
as an audit field only (``runtime_dsr``); the verdict and winner use the
re-deflated, run-order-invariant DSR.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Final, Literal

from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import pandas as pd

    from alphaforge.analytics.walkforward import ValidationReport, WalkForwardResult
    from alphaforge.core.time import Ms
    from alphaforge.validation.experiments import ExperimentLog

__all__ = [
    "DSR_GATE",
    "PBO_GATE",
    "SCHEMA_VERSION",
    "CapacityPoint",
    "CrossConfigDSR",
    "GrandConfig",
    "MatrixRow",
    "PBOSummary",
    "build_matrix_rows",
    "capacity_curve",
    "cpcv_path_sharpes",
    "cross_config_dsr",
    "matrix_pbo",
    "oos_returns_matrix",
    "reference_matrix",
    "select_deflated_winner",
    "write_matrix_json",
    "write_verdict",
]

# Deployment gates (alphaDesign.md sections 7.3 / 7.4) -- the same constants the engine uses.
DSR_GATE: Final[float] = 0.95
PBO_GATE: Final[float] = 0.20

SCHEMA_VERSION: Final[int] = 1

# The bounded capacity sweep (GRAND_BACKTEST.md section 1, Block B) -- ascending.
_CAPACITY_CASH: Final[tuple[float, ...]] = (100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0)
_CAPACITY_IDS: Final[tuple[str, ...]] = ("B_cap_100k", "B_cap_1M", "B_cap_10M", "B_cap_100M")

# The carry-tilt alpha subset for C_carry (GRAND_BACKTEST.md section 1, Block C).
_CARRY_ALPHAS: Final[tuple[str, ...]] = ("carry_fund_21", "carry_fund_90", "mr_res_72")

# A_blend is the blend-only reference whose curve IS the must-beat baseline every gated
# A-variant is judged against (all three gated baselines hash identically to A_blend's
# own trial, GRAND_BACKTEST.md section 1). Its re-deflated DSR is the shared baseline DSR.
_BASELINE_ID: Final[str] = "A_blend"


def _json_float(value: float) -> float | None:
    """Non-finite float -> ``None`` (strict JSON has no NaN/Inf); the convention
    used across ``walkforward.py`` / ``dsr.py`` / ``experiments.py``."""
    return None if not math.isfinite(value) else float(value)


# ----- the bounded config spec (one row of the matrix) -------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class GrandConfig:
    """One row of the bounded matrix -- a stable config_id + the knobs run(...) takes.

    ``block`` is "A" | "B" | "C". ``shares_trial_with`` is set ONLY for Block B
    capacity runs (the config_id of the gate variant whose trial hash they share);
    it documents -- and the verdict writer enforces -- that a capacity run never
    counts as a new trial. ``initial_cash`` is the only knob that differs across a
    capacity sweep and is intentionally NOT part of the trial identity (it is
    excluded from the runner's ``trial_config`` by design).
    """

    config_id: str
    block: Literal["A", "B", "C"]
    # run(...) knobs -- defaults match the reference config R.
    initial_cash: float = 1_000_000.0
    rebalance_bars: int = 72
    no_trade_band: float = 0.0030
    allocator: Literal["rank", "mvo"] = "rank"
    alpha_names: tuple[str, ...] | None = None
    ml: bool = False
    regime: bool = False
    shares_trial_with: str | None = None

    def out_dirname(self) -> str:
        """The checkpoint dir name (== config_id; stable, filesystem-safe)."""
        return self.config_id

    @property
    def is_distinct_trial(self) -> bool:
        """``True`` unless this is a Block-B capacity run sharing another's trial hash."""
        return self.shares_trial_with is None

    def knobs(self) -> dict[str, object]:
        """The defining knobs as a JSON-safe dict (the ``knobs`` block of matrix.json)."""
        return {
            "initial_cash": float(self.initial_cash),
            "rebalance_bars": int(self.rebalance_bars),
            "no_trade_band": float(self.no_trade_band),
            "allocator": str(self.allocator),
            "alpha_names": None if self.alpha_names is None else list(self.alpha_names),
            "ml": bool(self.ml),
            "regime": bool(self.regime),
        }


def reference_matrix(*, best_variant: GrandConfig | None = None) -> tuple[GrandConfig, ...]:
    """The bounded ~16-run matrix (Blocks A, B, C) as ordered GrandConfigs.

    Block A (4 distinct gate trials) + Block C (4 distinct robustness trials) are
    always present. Block B (4 capacity runs) is materialized off ``best_variant``
    -- the gate variant chosen by DEFLATED metrics from Block A (see
    :func:`select_deflated_winner`). When ``best_variant`` is None (first pass,
    before A has run), only Blocks A+C are returned; the driver calls again with the
    chosen variant to append Block B. Every Block-B config carries
    ``shares_trial_with = best_variant.config_id`` and varies only ``initial_cash``
    in {100k, 1M, 10M, 100M}, inheriting every search knob from ``best_variant``.
    config_ids are stable strings (``A_blend`` ... ``C_carry``).
    """
    block_a: tuple[GrandConfig, ...] = (
        GrandConfig(config_id="A_blend", block="A", ml=False, regime=False),
        GrandConfig(config_id="A_ml", block="A", ml=True, regime=False),
        GrandConfig(config_id="A_regime", block="A", ml=False, regime=True),
        GrandConfig(config_id="A_ml_regime", block="A", ml=True, regime=True),
    )
    block_c: tuple[GrandConfig, ...] = (
        GrandConfig(config_id="C_rebal24", block="C", rebalance_bars=24),
        GrandConfig(config_id="C_band10", block="C", no_trade_band=0.0010),
        GrandConfig(config_id="C_mvo", block="C", allocator="mvo"),
        GrandConfig(config_id="C_carry", block="C", alpha_names=_CARRY_ALPHAS),
    )
    if best_variant is None:
        return (*block_a, *block_c)

    block_b: tuple[GrandConfig, ...] = tuple(
        GrandConfig(
            config_id=cid,
            block="B",
            initial_cash=cash,
            rebalance_bars=best_variant.rebalance_bars,
            no_trade_band=best_variant.no_trade_band,
            allocator=best_variant.allocator,
            alpha_names=best_variant.alpha_names,
            ml=best_variant.ml,
            regime=best_variant.regime,
            shares_trial_with=best_variant.config_id,
        )
        for cid, cash in zip(_CAPACITY_IDS, _CAPACITY_CASH, strict=True)
    )
    return (*block_a, *block_b, *block_c)


# ----- (a) cross-config DSR over the SHARED ExperimentLog ----------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CrossConfigDSR:
    """The matrix-level deflation context read off the shared ledger AFTER all
    distinct trials are recorded (so every config sees the SAME final N / V[SR])."""

    n_trials: int  # log.n_trials() -- HONEST distinct-trial count
    sr_trials_variance: float  # log.trial_sharpe_variance() -- V[SR] (per-period)
    expected_max_sr: float  # expected_max_sharpe(max(2, N), V[SR]) -- SR* (per period)

    @property
    def n_trials_used(self) -> int:
        """``max(2, n_trials)`` -- what the expected-max-Sharpe form requires."""
        return max(2, self.n_trials)


def cpcv_path_sharpes(result: WalkForwardResult) -> list[float] | None:
    """The per-CPCV-path Sharpes for a walk-forward result, or ``None`` if absent.

    This is the bridge between a runner result and the ledger's honester
    within-path ``V[SR]`` (experiments.py ``ExperimentLog.record(path_sharpes=...)``
    / ``trial_sharpe_variance``). A :class:`CombinatorialPurgedCV` run resamples one
    config's own history into ``phi = k*C(N, k)/N`` complete OOS backtest paths
    (cpcv.py ``n_backtest_paths``); the per-path Sharpes are the spread the design's
    deflation benchmark ``SR*`` is meant to be built on (alphaDesign.md section 7.4).

    REMAINING-WIRING NOTE (honest): the deployment-faithful
    :class:`~alphaforge.analytics.walkforward.WalkForwardResult` is produced by the
    forward-chaining :class:`~alphaforge.validation.splits.PurgedWalkForward`, which
    yields ONE OOS path, not the CPCV path distribution. ``WalkForwardResult`` does
    not yet carry a per-CPCV-path Sharpe vector, so this helper returns ``None``
    today and the ledger correctly FALLS BACK to the between-config ``V[SR]``. The
    field + fallback + variance maths are in place end-to-end; the single remaining
    step is for the grand-backtest runner to additionally evaluate each distinct
    config under :class:`CombinatorialPurgedCV`, collect the
    ``n_backtest_paths`` per-path Sharpes, and pass them to
    ``ExperimentLog.record(path_sharpes=...)``. This is intentionally NOT faked:
    until that wiring lands, ``V[SR]`` stays the legacy between-config spread rather
    than a fabricated within-path number.
    """
    paths = getattr(result, "cpcv_path_sharpes", None)
    if paths is None:
        return None
    return [float(s) for s in paths]


def cross_config_dsr(log: ExperimentLog) -> CrossConfigDSR:
    """Read the final deflation context off the shared ledger.

    Calls ``log.n_trials()`` and ``log.trial_sharpe_variance()`` (the blessed
    ExperimentLog API) and ``expected_max_sharpe(max(2, N), V[SR])`` from
    validation.dsr. This is the SHARED ``SR*`` every config's deflated verdict is
    judged against -- the matrix-level honest deflation. Pure read; never records.

    ``V[SR]`` here is whatever ``trial_sharpe_variance`` resolves to: the honester
    WITHIN-CPCV-PATH variance once any trial on the ledger carries ``sharpe_per_path``
    (a wider spread -> a higher ``SR*`` -> a strictly MORE conservative DSR), or the
    legacy between-config variance otherwise. No branch is needed here -- the upgrade
    is transparent through the ExperimentLog API (experiments.py
    ``trial_sharpe_variance``).
    """
    from alphaforge.validation.dsr import expected_max_sharpe

    n_trials = log.n_trials()
    var_sr = log.trial_sharpe_variance()
    sr_star = expected_max_sharpe(max(2, n_trials), var_sr)
    return CrossConfigDSR(n_trials=n_trials, sr_trials_variance=var_sr, expected_max_sr=sr_star)


def _oos_daily(result: WalkForwardResult) -> pd.Series:
    """The OOS UTC-daily simple-return series for a result (possibly empty)."""
    return daily_returns(result.equity)


def _redeflated_dsr(rets: pd.Series, cross: CrossConfigDSR) -> float:
    """DSR of an OOS daily-return series against the SHARED final ``cross`` context.

    The run-order-invariant deflation (B1 / GB1 fix): EVERY config is judged against
    the same ``(n_trials_used, V[SR])``, never the per-config run-time ``N``.
    Returns ``nan`` for a series too short / degenerate to deflate (the writers map
    that to JSON ``null``).
    """
    from alphaforge.validation.dsr import dsr_from_returns

    if len(rets) < 2:
        return math.nan
    try:
        report = dsr_from_returns(
            rets, cross.n_trials_used, cross.sr_trials_variance, DAYS_PER_YEAR
        )
    except ValueError:
        # A zero-variance / degenerate OOS curve has no defined Sharpe; not deployable.
        return math.nan
    return report.dsr


def _validation_sr_ann(validation: ValidationReport | None) -> float:
    """The annualized OOS daily Sharpe off the runner (``nan`` when no validation)."""
    if validation is None:
        return math.nan
    return validation.sr_ann


# ----- (b) PBO via CSCV over the VARIANT set's OOS daily-returns matrix ---------


def oos_returns_matrix(
    results: Mapping[str, WalkForwardResult],
    variant_ids: Sequence[str],
) -> pd.DataFrame:
    """Build the T x N per-config OOS DAILY-returns matrix ``pbo_cscv`` consumes.

    Columns are exactly ``variant_ids`` (the DISTINCT-trial configs -- Blocks A+C,
    NOT the capacity sweep, which would be N duplicate columns of one config and
    bias the rank). Each column is ``analytics.metrics.daily_returns(result.equity)``
    for that config. Rows are the UTC-daily grid INNER-JOINED across all columns
    (the legs tile identically across variants, so the daily index is shared; an
    inner join drops the at-most-one boundary day a variant might miss). Rows are
    chronological -- ``pbo_cscv`` partitions rows in time order. Raises ValueError if
    fewer than 2 variant columns are requested, any requested id is missing/empty,
    or no aligned rows survive the inner join.
    """
    import pandas as pd

    if len(variant_ids) < 2:
        raise ValueError(
            f"oos_returns_matrix needs >= 2 variant columns to rank cross-sectionally; "
            f"got {len(variant_ids)}"
        )
    columns: dict[str, pd.Series] = {}
    for cid in variant_ids:
        if cid not in results:
            raise ValueError(f"oos_returns_matrix: config '{cid}' missing from results")
        rets = _oos_daily(results[cid])
        if len(rets) < 2:
            raise ValueError(
                f"oos_returns_matrix: config '{cid}' has < 2 OOS daily returns "
                f"(an OOS span shorter than 2 UTC days cannot enter the PBO matrix)"
            )
        columns[cid] = rets

    # Inner-join on the shared UTC-daily grid (chronological by construction -- each
    # column's index is the sorted epoch-ms daily grid; concat aligns on the index).
    matrix = pd.concat(columns, axis="columns", join="inner").sort_index()
    matrix.columns = list(variant_ids)
    if len(matrix) == 0:
        # Diagnose WHICH config truncated the join (GB correctness N5) so a detached
        # failure is readable from harness.log.
        spans = {cid: (int(s.index.min()), int(s.index.max())) for cid, s in columns.items()}
        raise ValueError(
            "oos_returns_matrix: inner join over variant OOS daily grids left 0 rows; "
            f"per-config [first_ms, last_ms] spans were {spans}"
        )
    return matrix


@dataclass(frozen=True, slots=True, kw_only=True)
class PBOSummary:
    pbo: float
    n_combinations: int
    n_configs: int
    n_obs: int
    clears_pbo_gate: bool  # pbo < PBO_GATE (0.20)


def matrix_pbo(
    results: Mapping[str, WalkForwardResult],
    variant_ids: Sequence[str],
    *,
    n_splits: int = 16,
    max_combinations: int = 5000,
    seed: int = 42,
) -> PBOSummary:
    """PBO via ``validation.pbo.pbo_cscv`` over :func:`oos_returns_matrix`.

    Wraps the SHIPPED ``pbo_cscv`` (BBLZ CSCV) on the variant OOS-returns matrix
    and applies the ``pbo < 0.20`` gate. Deterministic for fixed
    (matrix, n_splits, max_combinations, seed). With ~17 daily*legs the row count
    is ample for the default n_splits=16; the driver may pass a smaller even
    n_splits if a short window leaves < 16 aligned rows. Re-raises ``pbo_cscv``'s
    ValueError with the aligned-row count so a too-short matrix is diagnosable.
    """
    from alphaforge.validation.pbo import pbo_cscv

    matrix = oos_returns_matrix(results, variant_ids)
    n_obs, n_configs = matrix.shape
    if n_obs < n_splits:
        raise ValueError(
            f"matrix_pbo: variant OOS matrix has {n_obs} aligned daily rows < "
            f"n_splits={n_splits}; pass a smaller even n_splits or widen the window"
        )
    result = pbo_cscv(matrix, n_splits=n_splits, max_combinations=max_combinations, seed=seed)
    return PBOSummary(
        pbo=result.pbo,
        n_combinations=result.n_combinations,
        n_configs=int(n_configs),
        n_obs=int(n_obs),
        clears_pbo_gate=math.isfinite(result.pbo) and result.pbo < PBO_GATE,
    )


# ----- (c) the capacity-curve builder -----------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityPoint:
    initial_cash: float
    sr_ann: float
    max_dd: float  # non-negative depth fraction (summary.max_dd convention)
    turnover: float  # annualized one-way, from summary.turnover_ann
    dsr: float  # re-deflated against the SHARED SR* (capacity != a new trial)
    final_equity: float


def capacity_curve(
    results: Mapping[str, WalkForwardResult],
    capacity_ids: Sequence[str],
    cross: CrossConfigDSR,
) -> tuple[CapacityPoint, ...]:
    """The capacity curve from the Block-B runs, ascending by ``initial_cash``.

    For each capacity config_id pulls ``sr_ann`` from ``result.validation`` (NOT
    ``summary`` -- ``PerfSummary`` has no ``sr_ann``; GB correctness B2/GB4) and
    ``max_dd`` / ``turnover_ann`` / ``final_equity`` from ``result.summary``, and
    RE-DEFLATES its OOS daily Sharpe against the SHARED ``cross`` context (NOT a
    fresh per-capital N -- a capacity sweep is not a search). The curve shows where
    MARKET IMPACT (the engine's notional/ADV cost scaling) erodes ``sr_ann`` and
    lifts ``turnover``-adjusted cost as capital grows. Ascending by initial_cash;
    a missing/degenerate config emits ``nan`` fields rather than crashing.
    """
    points: list[CapacityPoint] = []
    for cid in capacity_ids:
        result = results.get(cid)
        if result is None:
            continue
        summary = result.summary
        rets = _oos_daily(result)
        points.append(
            CapacityPoint(
                initial_cash=float(summary.initial_equity),
                sr_ann=_validation_sr_ann(result.validation),
                max_dd=float(summary.max_dd),
                turnover=float(summary.turnover_ann),
                dsr=_redeflated_dsr(rets, cross),
                final_equity=float(summary.final_equity),
            )
        )
    points.sort(key=lambda p: p.initial_cash)
    return tuple(points)


# ----- (d) the winner selector + verdict.md / matrix.json writers --------------


def _redeflated_clears_baseline(
    variant_dsr: float,
    variant_sr_ann: float,
    baseline_dsr: float,
    baseline_sr_ann: float,
) -> bool:
    """The must-beat-baseline predicate on SHARED-SR* DSRs (mirrors
    ``walkforward.compare_to_baseline`` but on re-deflated, run-order-invariant
    numbers): dsr>=0.95 AND dsr>baseline.dsr AND sr_ann>baseline.sr_ann, all strict,
    non-finite -> ``False``."""
    return bool(
        math.isfinite(variant_dsr)
        and variant_dsr >= DSR_GATE
        and math.isfinite(baseline_dsr)
        and variant_dsr > baseline_dsr
        and math.isfinite(variant_sr_ann)
        and math.isfinite(baseline_sr_ann)
        and variant_sr_ann > baseline_sr_ann
    )


def select_deflated_winner(
    results: Mapping[str, WalkForwardResult],
    cross: CrossConfigDSR,
) -> str | None:
    """The DEPLOYABLE winner among Block-A gate variants -- by DEFLATED metrics, never
    raw Sharpe, judged against the SHARED final ``cross`` SR* (B1 / GB1 fix).

    Every gated A-variant and the blend-only baseline (``A_blend``'s curve, which IS
    the must-beat baseline -- all three gated baselines hash to A_blend's trial) are
    RE-DEFLATED against the same ``(cross.n_trials_used, cross.sr_trials_variance)``
    from their OOS daily returns. A variant is eligible iff, on the SAME purged legs
    net of costs: re-deflated dsr>=0.95 AND dsr>baseline_dsr AND sr_ann>baseline.sr_ann.
    Among the eligible, the winner is the highest re-deflated dsr (ties broken by
    higher sr_ann). Returns None when NO gate variant is live-eligible -- the HONEST
    null (the expected outcome given Phase 10). ``A_blend`` is never eligible (it is
    the baseline; the gate is meaningful only for a gated variant). The PBO gate is
    applied at the MATRIX level by :func:`write_verdict`, not here.
    """
    baseline = results.get(_BASELINE_ID)
    if baseline is None:
        return None
    baseline_dsr = _redeflated_dsr(_oos_daily(baseline), cross)
    baseline_sr_ann = _validation_sr_ann(baseline.validation)

    best_id: str | None = None
    best_key: tuple[float, float] = (-math.inf, -math.inf)
    for cid in ("A_ml", "A_regime", "A_ml_regime"):
        result = results.get(cid)
        if result is None:
            continue
        v_dsr = _redeflated_dsr(_oos_daily(result), cross)
        v_sr_ann = _validation_sr_ann(result.validation)
        if not _redeflated_clears_baseline(v_dsr, v_sr_ann, baseline_dsr, baseline_sr_ann):
            continue
        key = (v_dsr, v_sr_ann)
        if key > best_key:
            best_key = key
            best_id = cid
    return best_id


@dataclass(frozen=True, slots=True, kw_only=True)
class MatrixRow:
    """One config's row in matrix.json (per-config block of the schema)."""

    config_id: str
    block: str
    knobs: dict[str, object]  # the GrandConfig knobs that define this run
    psr: float
    dsr: float  # the SHARED-SR* re-deflated DSR (the judged quantity)
    runtime_dsr: float  # the runner's per-config validation.dsr (audit only)
    sr_ann: float
    max_dd: float  # non-negative depth fraction
    turnover: float
    clears_dsr_gate: bool  # re-deflated dsr >= 0.95
    clears_baseline_gate: bool  # re-deflated must-beat-baseline (gated variants only)
    is_distinct_trial: bool  # False for Block-B capacity rows
    baseline_dsr: float | None  # the must-beat reference, re-deflated (gated runs only)

    def to_json_obj(self) -> dict[str, object]:
        """JSON-safe dict (non-finite floats -> ``None``); keys sorted on dump."""
        return {
            "config_id": self.config_id,
            "block": self.block,
            "knobs": self.knobs,
            "psr": _json_float(self.psr),
            "dsr": _json_float(self.dsr),
            "runtime_dsr": _json_float(self.runtime_dsr),
            "sr_ann": _json_float(self.sr_ann),
            "max_dd": _json_float(self.max_dd),
            "turnover": _json_float(self.turnover),
            "clears_dsr_gate": bool(self.clears_dsr_gate),
            "clears_baseline_gate": bool(self.clears_baseline_gate),
            "is_distinct_trial": bool(self.is_distinct_trial),
            "baseline_dsr": None if self.baseline_dsr is None else _json_float(self.baseline_dsr),
        }


def build_matrix_rows(
    configs: Sequence[GrandConfig],
    results: Mapping[str, WalkForwardResult],
    cross: CrossConfigDSR,
) -> tuple[MatrixRow, ...]:
    """Assemble one MatrixRow per config from its WalkForwardResult, with EVERY
    judged DSR re-deflated against the SHARED ``cross`` SR* (B1 / GB1).

    ``dsr`` / ``clears_dsr_gate`` / ``clears_baseline_gate`` / ``baseline_dsr`` are
    computed from the config's OOS daily returns against ``cross`` (run-order
    invariant); the runner's per-config ``validation.dsr`` is preserved as
    ``runtime_dsr`` for audit. ``psr`` is the (N-independent) per-config PSR off the
    runner. ``sr_ann`` from ``validation``; ``max_dd`` / ``turnover`` from
    ``summary`` (B2/GB4: ``summary`` has no ``sr_ann``). Configs absent from
    ``results`` are skipped. ``baseline_dsr`` is the re-deflated ``A_blend`` curve
    for every gated A-variant (the must-beat reference).
    """
    baseline = results.get(_BASELINE_ID)
    baseline_dsr = (
        _redeflated_dsr(_oos_daily(baseline), cross) if baseline is not None else math.nan
    )
    baseline_sr_ann = _validation_sr_ann(baseline.validation) if baseline is not None else math.nan

    rows: list[MatrixRow] = []
    for cfg in configs:
        result = results.get(cfg.config_id)
        if result is None:
            continue
        validation = result.validation
        summary = result.summary
        rets = _oos_daily(result)
        re_dsr = _redeflated_dsr(rets, cross)
        sr_ann = _validation_sr_ann(validation)
        clears_dsr = math.isfinite(re_dsr) and re_dsr >= DSR_GATE

        # A gated A-variant carries the must-beat-baseline reference (A_blend, re-deflated).
        is_gated_a = cfg.block == "A" and (cfg.ml or cfg.regime)
        if is_gated_a:
            row_baseline_dsr: float | None = baseline_dsr
            clears_baseline = _redeflated_clears_baseline(
                re_dsr, sr_ann, baseline_dsr, baseline_sr_ann
            )
        else:
            row_baseline_dsr = None
            clears_baseline = False

        rows.append(
            MatrixRow(
                config_id=cfg.config_id,
                block=cfg.block,
                knobs=cfg.knobs(),
                psr=validation.psr if validation is not None else math.nan,
                dsr=re_dsr,
                runtime_dsr=validation.dsr if validation is not None else math.nan,
                sr_ann=sr_ann,
                max_dd=float(summary.max_dd),
                turnover=float(summary.turnover_ann),
                clears_dsr_gate=clears_dsr,
                clears_baseline_gate=clears_baseline,
                is_distinct_trial=cfg.is_distinct_trial,
                baseline_dsr=row_baseline_dsr,
            )
        )
    return tuple(rows)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp in the same dir + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _window_obj(window: tuple[Ms, Ms]) -> dict[str, object]:
    """The matrix.json window block (epoch-ms + UTC-midnight ISO date)."""
    from datetime import datetime

    start_ms, end_ms = int(window[0]), int(window[1])
    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "start_iso": datetime.fromtimestamp(start_ms / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
        "end_iso": datetime.fromtimestamp(end_ms / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
    }


def write_matrix_json(
    path: Path,
    *,
    rows: Sequence[MatrixRow],
    cross: CrossConfigDSR,
    pbo: PBOSummary,
    capacity: Sequence[CapacityPoint],
    winner: str | None,
    window: tuple[Ms, Ms],
    run_ts: str,
    git_sha: str = "",
) -> None:
    """Write the machine-readable matrix.json (schema in GRAND_BACKTEST.md section 3).

    Atomic write (tmp + os.replace), sorted keys, the ``_json_float`` non-finite
    convention. ``deployment_verdict`` is the conjunction the design forbids
    weakening: ``winner is not None AND pbo.clears_pbo_gate``.
    """
    deployment_verdict = winner is not None and pbo.clears_pbo_gate
    obj: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_ts": run_ts,
        "git_sha": git_sha,
        "window": _window_obj(window),
        "matrix": {
            "n_trials": int(cross.n_trials),
            "sr_trials_variance": _json_float(cross.sr_trials_variance),
            "expected_max_sr": _json_float(cross.expected_max_sr),
            "pbo": _json_float(pbo.pbo),
            "pbo_n_combinations": int(pbo.n_combinations),
            "pbo_n_configs": int(pbo.n_configs),
            "pbo_n_obs": int(pbo.n_obs),
            "clears_pbo_gate": bool(pbo.clears_pbo_gate),
            "deflated_winner": winner,
            "deployment_verdict": bool(deployment_verdict),
        },
        "configs": [row.to_json_obj() for row in rows],
        "capacity_curve": [
            {
                "initial_cash": _json_float(p.initial_cash),
                "sr_ann": _json_float(p.sr_ann),
                "max_dd": _json_float(p.max_dd),
                "turnover": _json_float(p.turnover),
                "dsr": _json_float(p.dsr),
                "final_equity": _json_float(p.final_equity),
            }
            for p in capacity
        ],
    }
    _atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _fmt(value: float, *, places: int = 4) -> str:
    """Human float for the verdict tables; non-finite -> ``n/a``."""
    return f"{value:.{places}f}" if math.isfinite(value) else "n/a"


def _fmt_cash(value: float) -> str:
    """Compact cash label (100k / 1M / 10M / 100M style); falls back to a raw int."""
    if not math.isfinite(value):
        return "n/a"
    if value >= 1_000_000.0:
        return f"{value / 1_000_000.0:g}M"
    if value >= 1_000.0:
        return f"{value / 1_000.0:g}k"
    return f"{value:g}"


def write_verdict(
    path: Path,
    *,
    rows: Sequence[MatrixRow],
    cross: CrossConfigDSR,
    pbo: PBOSummary,
    capacity: Sequence[CapacityPoint],
    winner: str | None,
    window: tuple[Ms, Ms],
) -> None:
    """Write verdict.md -- the human-readable, plainly-stated true result.

    States: (1) the resolved clean window + N distinct trials + V[SR] + SR*; (2) the
    full Block-A gate table (psr/dsr/sr_ann/max_dd/turnover/gates, baseline deltas) --
    NO cherry-picking, every variant shown; (3) the DEPLOYMENT VERDICT = (winner is
    not None) AND pbo<0.20, stated plainly (and the honest null when no variant
    qualifies); (4) the CAPACITY CURVE table showing where impact kills the thin edge;
    (5) whether the REGIME gate (the real lever) changed the verdict vs blend-only.
    The winner is judged by DEFLATED (shared-SR*) metrics only; raw Sharpe is reported
    but never decisive.
    """
    win = _window_obj(window)
    by_id = {row.config_id: row for row in rows}
    deployment_verdict = winner is not None and pbo.clears_pbo_gate

    lines: list[str] = []
    lines.append("# Grand Backtest — Deflated Verdict")
    lines.append("")
    lines.append(
        "Honest robustness matrix over the full crypto-perp history. Every DSR below "
        "is RE-DEFLATED against the SHARED final trial count so the verdict is "
        "run-order invariant (the runner's per-config DSR is order-dependent and is "
        "NOT used here). The winner is judged by DEFLATED metrics, never raw Sharpe."
    )
    lines.append("")

    # (1) Window + matrix-level deflation context.
    lines.append("## 1. Window and deflation context")
    lines.append("")
    lines.append(
        f"- Clean window: `{win['start_iso']}` -> `{win['end_iso']}` (UTC, exclusive end)."
    )
    lines.append(f"- Distinct trials on the dedicated ledger (honest N): **{cross.n_trials}**.")
    lines.append(
        f"- Cross-trial Sharpe variance V[SR] (per period): "
        f"{_fmt(cross.sr_trials_variance, places=6)}."
    )
    lines.append(
        f"- Shared expected-max Sharpe SR* (per period, the deflation benchmark, "
        f"computed at N_used={cross.n_trials_used}): {_fmt(cross.expected_max_sr, places=6)}."
    )
    lines.append("")

    # (2) The full Block-A gate table (no cherry-picking).
    lines.append("## 2. Block A — gate comparison (the core must-beat-baseline test)")
    lines.append("")
    lines.append(
        "| config | psr | dsr (shared-SR*) | sr_ann | max_dd | turnover | dsr>=0.95 | "
        "beats baseline | baseline_dsr |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for cid in ("A_blend", "A_ml", "A_regime", "A_ml_regime"):
        row = by_id.get(cid)
        if row is None:
            lines.append(f"| {cid} | _(not run)_ | | | | | | | |")
            continue
        baseline_cell = "—" if row.baseline_dsr is None else _fmt(row.baseline_dsr)
        lines.append(
            f"| {row.config_id} | {_fmt(row.psr)} | {_fmt(row.dsr)} | {_fmt(row.sr_ann)} | "
            f"{_fmt(row.max_dd)} | {_fmt(row.turnover)} | "
            f"{'yes' if row.clears_dsr_gate else 'no'} | "
            f"{'yes' if row.clears_baseline_gate else 'no'} | {baseline_cell} |"
        )
    lines.append("")
    lines.append(
        "Raw annualized Sharpe (`sr_ann`) is reported for context only; deployment is "
        "decided on the shared-SR* `dsr` column and the must-beat-baseline gate, never "
        "on raw Sharpe."
    )
    lines.append("")

    # (2b) Block C robustness, also shown in full.
    c_rows = [r for r in rows if r.block == "C"]
    if c_rows:
        lines.append("## 2b. Block C — one-knob robustness (each a distinct trial)")
        lines.append("")
        lines.append("| config | dsr (shared-SR*) | sr_ann | max_dd | turnover | dsr>=0.95 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in c_rows:
            lines.append(
                f"| {row.config_id} | {_fmt(row.dsr)} | {_fmt(row.sr_ann)} | "
                f"{_fmt(row.max_dd)} | {_fmt(row.turnover)} | "
                f"{'yes' if row.clears_dsr_gate else 'no'} |"
            )
        lines.append("")

    # (3) The deployment verdict — stated plainly.
    lines.append("## 3. Deployment verdict")
    lines.append("")
    lines.append(
        f"- Matrix PBO (CSCV over the Blocks A+C variant OOS-returns matrix, "
        f"{pbo.n_configs} configs x {pbo.n_obs} daily rows, {pbo.n_combinations} "
        f"combinations): {_fmt(pbo.pbo)} (gate `< {PBO_GATE}` -> "
        f"{'CLEARS' if pbo.clears_pbo_gate else 'FAILS'})."
    )
    if winner is None:
        lines.append("- Deflated winner: **none**.")
        lines.append("")
        lines.append(
            "**VERDICT: NO-DEPLOY (honest null).** No gate variant clears the "
            "must-beat-baseline gate AND dsr>=0.95 on the shared SR*. This confirms "
            "the Phase-10 finding: crypto-perps alone is noise — the thin cross-"
            "sectional signal does not survive honest deflation net of costs."
        )
    else:
        lines.append(f"- Deflated winner (highest shared-SR* dsr, ties by sr_ann): **{winner}**.")
        lines.append("")
        if deployment_verdict:
            lines.append(
                f"**VERDICT: DEPLOYABLE.** `{winner}` clears the must-beat-baseline gate "
                f"AND dsr>=0.95 on the same purged legs net of costs, AND the matrix PBO "
                f"is below {PBO_GATE}. All three conditions hold on the same legs."
            )
        else:
            lines.append(
                f"**VERDICT: NO-DEPLOY.** `{winner}` clears the must-beat-baseline gate, "
                f"but the matrix PBO ({_fmt(pbo.pbo)}) does NOT clear the `< {PBO_GATE}` "
                f"gate — the in-sample-best of this config family does not generalize OOS. "
                f"The conjunction (winner AND pbo<0.20) is not met."
            )
    lines.append("")

    # (4) The capacity curve — where impact kills the edge.
    lines.append("## 4. Capacity curve — where market impact kills the thin edge")
    lines.append("")
    if capacity:
        lines.append(
            "| initial_cash | sr_ann | dsr (shared-SR*) | max_dd | turnover | final_equity |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for p in capacity:
            lines.append(
                f"| {_fmt_cash(p.initial_cash)} | {_fmt(p.sr_ann)} | {_fmt(p.dsr)} | "
                f"{_fmt(p.max_dd)} | {_fmt(p.turnover)} | {_fmt(p.final_equity, places=2)} |"
            )
        lines.append("")
        lines.append(
            "`sr_ann` should DECAY as `initial_cash` grows: the engine's notional/ADV "
            "cost scaling lifts realized transaction cost until the (already thin) edge "
            "is consumed. The capacity sweep shares the winning gate variant's trial "
            "hash (it varies only `initial_cash`), so it adds ZERO to N and is shown for "
            "capacity context only — never as a separate deployable config."
        )
    else:
        lines.append("_(no capacity runs available)_")
    lines.append("")

    # (5) Did the regime gate (the real lever) change the verdict?
    lines.append("## 5. Did the regime gate (the real lever) change the verdict?")
    lines.append("")
    blend = by_id.get("A_blend")
    regime = by_id.get("A_regime")
    if blend is not None and regime is not None:
        regime_beats_blend = (
            math.isfinite(regime.dsr) and math.isfinite(blend.dsr) and regime.dsr > blend.dsr
        )
        lines.append(
            f"- Blend-only (`A_blend`) shared-SR* dsr = {_fmt(blend.dsr)}; "
            f"regime-gated (`A_regime`) shared-SR* dsr = {_fmt(regime.dsr)}; "
            f"regime beats blend on dsr: {'yes' if regime_beats_blend else 'no'}."
        )
        regime_is_winner = winner == "A_regime" or winner == "A_ml_regime"
        lines.append(
            "- The regime gate is the documented real lever, but it is INERT for the "
            "early OOS legs whose expanding HMM-fit window holds fewer than the "
            "required 730 daily-BTC days (those legs run blend-only by the documented "
            "IdentityRegime cold-start fallback). Read each regime variant's "
            "`gate_inactive_frac` in its `walkforward.json` before concluding the lever "
            "changed nothing — a high inactive fraction means the gate barely fired."
        )
        if winner is None:
            lines.append(
                "- Net: the regime gate did NOT flip the verdict — no variant (gated or "
                "not) is deployable."
            )
        elif regime_is_winner:
            lines.append(
                f"- Net: the regime gate IS the lever that produced the winner (`{winner}`)."
            )
        else:
            lines.append(
                f"- Net: the winner (`{winner}`) does not use the regime gate; the regime "
                f"lever did not change the deployable outcome."
            )
    else:
        lines.append("_(blend and/or regime variant not available for the comparison)_")
    lines.append("")

    _atomic_write_text(path, "\n".join(lines) + "\n")
