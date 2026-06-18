"""Raw-alpha blend — EWMA NET-of-cost Rank-IC weighting (alphaDesign.md §9.1).

The blend turns K processed directional alpha z-scores ``z_{k,i,t}`` (each already
multiplied by ``FeatureSpec.direction`` upstream, so a healthy alpha has POSITIVE
IC) into one cross-sectionally re-standardized signal::

    On the NON-OVERLAPPING h-bar grid (h = SignalsCfg.horizon_bars, THE one
    holding-period constant — buildabilityCritique.md §3.10):

        RIC_{k,t}    = SpearmanCorr_i( z_{k,i,t}, y_{i,t,h} )
        ÎC_{k,t}     = EWMA( RIC_{k,·} ; halflife = 20 grid points ),  LAGGED:
                       uses ONLY observations with  t' + h·Δ <= t   (label realized)
        T̂O_{k,t}     = EWMA( TO_{k,·} ; same halflife ),  LAGGED the SAME way
        netIC_{k,t}  = ÎC_{k,t}  -  λ_cost · c · T̂O_{k,t}        (Grinold cost haircut)
        w_{k,t}      = max(netIC_{k,t}, 0) + κ_t
        κ_t          = max( κ_shrink · mean_k max(netIC_{k,t}, 0), κ_floor )
        w_{k,t}     := w_{k,t} / Σ_j w_{j,t}

    A_{i,t} = Σ_k w_{k,t} · z_{k,i,t}
    Ã_{i,t} = cs_zscore( A_{·,t} )        # over the SAME PIT universe mask

WHY NET-OF-COST (the single highest-leverage change — head-of-research slate §2):
the original weighting used GROSS Rank-IC, so a factor that churns its ranking
every grid point and one that holds it for weeks got equal weight at equal IC —
systematically over-weighting the costly factors at the desk's 63x turnover (the
1-day reversal that eats the real +0.67 gross edge). The cost haircut charges each
factor its expected per-rebalance cost drag in IC-equivalent units (Grinold's
relation: a return drag of ``c·TO`` is worth ``c·TO / (IC_target·sigma_h)`` of IC),
so a slow factor (TO≈0.15) loses ~0.09 IC while a fast 1-day reversal (TO≈0.7)
loses ~0.41 IC — which dwarfs any realistic gross IC and correctly drives it to
the κ-floor. The deliberately SLOW new alpha slate is rewarded automatically.

The cost haircut is OPT-IN and back-compatible: ``grid_turnover=None`` (the
default) reproduces the gross-IC behaviour bit-for-bit. When supplied, each
factor's turnover series is lagged + EWMA-smoothed with the IDENTICAL lagged EWMA
as the IC — so it carries no future information (realized-history turnover only).

Lag enforcement is THE point (leakage critique): the label ``y_{i,t',h}`` exits at
the open of bar ``t' + (1+h)·Δ``, so RIC_{k,t'} is fully realized at decision
instant ``t + Δ`` iff ``t' + h·Δ <= t``. On a uniform h-spaced grid that is
*exactly* "all grid points strictly before t", i.e. a one-grid-step shift —
:func:`estimate_blend_weights` asserts the uniform spacing so the shift IS the
rule, mechanically. An IC printed inside the last ``h`` bars can never move the
weights used at ``t``. Turnover ``TO_{k,t} = 0.5·Σ_i|g_{i,t}-g_{i,t-1}|`` is
already observable AT ``t`` (both rankings are known at the decision instant), but
it is lagged the SAME one grid step as the IC so the cost penalty is symmetric
with the edge estimate and uses strictly realized history — no future-turnover.

Degenerate-case floor (leakage finding 19): when every (net) smoothed IC is <= 0
the design formula ``κ = 0.2·mean_k max(netIC,0)`` collapses to 0 and normalization
is 0/0. The absolute floor ``κ_floor = 0.01`` guarantees strictly positive weights;
with all netIC <= 0 every alpha gets exactly ``κ_floor`` and the blend degrades to
EQUAL weights — never NaN, never a sign flip. (The cost haircut only LOWERS netIC,
so it can drive a profitable-but-costly factor to the floor, never below zero
weight, and never NaN.)

Cold start: before any realized RIC exists, ÎC is NaN for every alpha; NaN ÎC is
treated as "no evidence" (contributes 0 to ``max(netIC,0)``), so the κ floor again
yields equal weights. NaN turnover is likewise "no cost evidence" → 0 haircut.
Equal weights are therefore not a special code path but the fixed point the
estimator shrinks toward.

All functions are pure and deterministic; inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from alphaforge.core.time import Ms, Timeframe
from alphaforge.features.cross_section import cs_zscore

__all__ = [
    "ALPHA_BLEND_COLUMN",
    "BLEND_EWMA_HALFLIFE_GRID",
    "DEFAULT_COST_FRAC",
    "DEFAULT_IC_TARGET",
    "DEFAULT_SIGMA_H_TYP",
    "KAPPA_FLOOR",
    "KAPPA_SHRINK",
    "BlendWeights",
    "blend",
    "default_lambda_cost",
    "estimate_blend_weights",
]

ALPHA_BLEND_COLUMN: Final[str] = "alpha_blend"
"""Output column name of the blended, re-standardized signal Ã."""

BLEND_EWMA_HALFLIFE_GRID: Final[int] = 20
"""EWMA halflife of the Rank-IC smoother, in NON-OVERLAPPING grid points.

With h = 72 (1h bars) one grid point is 3 days, so 20 grid points ≈ 60 days —
alphaDesign.md §9.1."""

KAPPA_SHRINK: Final[float] = 0.2
"""κ = KAPPA_SHRINK · mean_k max(ÎC_k, 0) — shrinkage toward equal weights."""

KAPPA_FLOOR: Final[float] = 0.01
"""Absolute κ floor (leakage finding 19): keeps weights strictly positive when
every smoothed IC is <= 0, degrading to equal weights instead of 0/0."""

DEFAULT_COST_FRAC: Final[float] = 0.0010
"""One-way cost scalar ``c`` for the net-IC haircut, default 10 bps — the same
value as ``portfolio.strategy._DEFAULT_COST_FRAC`` (the flat per-asset one-way
cost the MVO turnover penalty already uses). Mirrored here as a module constant
rather than imported across the B→C layer boundary; per-factor ``c_k`` is a
later phase. Override via ``estimate_blend_weights(..., cost_frac=...)``."""

DEFAULT_IC_TARGET: Final[float] = 0.02
"""``IC_target`` used in the Grinold cost→IC conversion, matching
``SignalsCfg.ic_target``. Only the value of ``λ_cost = 1/(IC_target·sigma_h_typ)``
matters, and a common constant cancels in the RELATIVE weighting the blend uses;
this is the documented default behind :func:`default_lambda_cost`."""

DEFAULT_SIGMA_H_TYP: Final[float] = 0.085
"""Typical h-bar return volatility ``sigma_h_typ`` (median sigma_hat·sqrt(h) over the PIT
panel, ≈0.085 at h=72) used in the default ``λ_cost``. The caller (``service.py``)
may pass a panel-derived ``lambda_cost`` to use the realized value; this constant
exists so :func:`estimate_blend_weights` has a sensible standalone default."""


def default_lambda_cost(
    *, ic_target: float = DEFAULT_IC_TARGET, sigma_h_typ: float = DEFAULT_SIGMA_H_TYP
) -> float:
    """The Grinold cost→IC conversion factor ``λ_cost = 1/(IC_target·sigma_h_typ)``.

    Converts a per-rebalance return drag ``c·TO`` into IC-equivalent units so it
    can be subtracted directly from the (gross) smoothed Rank-IC. With the
    defaults (``IC_target=0.02``, ``sigma_h_typ=0.085``) this is ≈588 — a slow factor
    (TO=0.15) then loses ``λ·c·TO ≈ 588·0.0010·0.15 ≈ 0.088`` IC, a 1-day reversal
    (TO=0.7) loses ≈0.41 IC. A common positive constant in ``λ_cost`` cancels in
    the relative ``w_k`` normalisation, so only ``λ·c`` (the cost-to-IC slope) is
    economically identified; the defaults pin a principled scale.
    """
    if ic_target <= 0.0:
        raise ValueError(f"ic_target must be > 0; got {ic_target}")
    if sigma_h_typ <= 0.0:
        raise ValueError(f"sigma_h_typ must be > 0; got {sigma_h_typ}")
    return 1.0 / (ic_target * sigma_h_typ)


@dataclass(frozen=True, slots=True, kw_only=True)
class BlendWeights:
    """Walk-forward blend weights on the non-overlapping h-grid.

    Attributes:
        alpha_names: Alpha ordering shared by every frame's columns.
        weights: Float frame indexed by grid ``ts_open`` (epoch-ms int64,
            strictly increasing), one column per alpha; every row is strictly
            positive and sums to 1. Row at grid point ``t`` was estimated from
            RIC (and turnover) observations with ``t' + h·Δ <= t`` ONLY
            (realized labels).
        smoothed_ic: The lagged EWMA NET IC ``netIC_{k,t}`` actually behind each
            weight row (= gross when no cost haircut was applied; NaN where no
            realized RIC existed yet) — kept for diagnostics/reports.
        gross_smoothed_ic: Optional auditability frame — the lagged EWMA GROSS
            ``ÎC_{k,t}`` before any cost haircut. ``None`` when not recorded.
        net_smoothed_ic: Optional auditability frame — ``netIC_{k,t} = ÎC - λ·c·T̂O``,
            i.e. the same numbers as ``smoothed_ic`` (a named, explicit alias for
            reports that print gross vs net side-by-side). ``None`` when not
            recorded; equals ``gross_smoothed_ic`` when no turnover was supplied.

    Treat the frames as read-only (shared, not defensively copied).
    """

    alpha_names: tuple[str, ...]
    weights: pd.DataFrame
    smoothed_ic: pd.DataFrame
    gross_smoothed_ic: pd.DataFrame | None = None
    net_smoothed_ic: pd.DataFrame | None = None

    def __post_init__(self) -> None:
        if not self.alpha_names:
            raise ValueError("BlendWeights requires at least one alpha")
        for frame_name in ("weights", "smoothed_ic", "gross_smoothed_ic", "net_smoothed_ic"):
            frame: pd.DataFrame | None = getattr(self, frame_name)
            if frame is None:  # optional auditability frames
                continue
            if tuple(frame.columns) != self.alpha_names:
                raise ValueError(
                    f"BlendWeights.{frame_name} columns {tuple(frame.columns)!r} must equal "
                    f"alpha_names {self.alpha_names!r}"
                )

    @classmethod
    def equal(cls, alpha_names: tuple[str, ...]) -> BlendWeights:
        """Empty-grid weights: :meth:`asof` returns equal weights for every ts.

        The documented cold-start object — used live before the first research
        estimation run has produced any realized-IC history.
        """
        empty = pd.DataFrame(
            np.empty((0, len(alpha_names))),
            index=pd.Index(np.array([], dtype=np.int64), name="ts_open"),
            columns=list(alpha_names),
            dtype=float,
        )
        return cls(
            alpha_names=alpha_names,
            weights=empty,
            smoothed_ic=empty.copy(),
            gross_smoothed_ic=empty.copy(),
            net_smoothed_ic=empty.copy(),
        )

    def asof(self, ts: Ms) -> pd.Series:
        """Weights in force at decision bar ``ts``: the row at the greatest grid
        point ``<= ts`` (a step function — between grid points the realized-IC
        set cannot change, so neither can the walk-forward-correct weights).
        Before the first grid point (or on an empty grid): equal weights
        (cold start; see module docstring).
        """
        grid = self.weights.index.to_numpy(dtype=np.int64)
        pos = int(np.searchsorted(grid, ts, side="right")) - 1
        if pos < 0:
            k = len(self.alpha_names)
            return pd.Series(np.full(k, 1.0 / k), index=list(self.alpha_names), dtype=float)
        return self.weights.iloc[pos]


def _lagged_ewma(series: pd.Series, halflife_grid: float) -> pd.Series:
    """The blend's ONE smoother: shift one grid step (lag enforcement — the
    realized-label rule ``t' + h·Δ <= t``) then EWMA with ``adjust=True``
    (finite-sample weighted mean, exact from the first observation) and
    ``ignore_na=True`` so a thin-cross-section NaN is skipped, not zero-imputed.

    Both the Rank-IC and the per-factor turnover are run through this IDENTICAL
    operation, so the cost haircut is lag-symmetric with the edge estimate and
    carries no future information (module docstring)."""
    return (
        series.astype(float)
        .shift(1)
        .ewm(halflife=halflife_grid, adjust=True, ignore_na=True, min_periods=1)
        .mean()
    )


def estimate_blend_weights(
    grid_ics: Mapping[str, pd.Series],
    *,
    horizon_bars: int,
    timeframe: Timeframe = Timeframe.H1,
    halflife_grid: float = BLEND_EWMA_HALFLIFE_GRID,
    kappa_shrink: float = KAPPA_SHRINK,
    kappa_floor: float = KAPPA_FLOOR,
    grid_turnover: Mapping[str, pd.Series] | None = None,
    cost_frac: float = DEFAULT_COST_FRAC,
    lambda_cost: float | None = None,
) -> BlendWeights:
    """Estimate walk-forward NET-of-cost blend weights from non-overlapping-grid Rank-ICs.

    ``grid_ics`` maps alpha name -> RIC series indexed by ``ts_open`` (epoch-ms
    int64) on the non-overlapping h-grid (e.g. the output of
    :func:`alphaforge.validation.metrics.rank_ic` subsampled by
    :func:`~alphaforge.validation.metrics.non_overlapping`). All series must share
    one index with UNIFORM spacing of exactly ``horizon_bars · Δ`` — asserted,
    because the realized-label rule ``t' + h·Δ <= t`` is implemented as a
    one-grid-step shift and is only equivalent under that spacing.

    Per alpha: shift the RIC series one grid step (lag enforcement), smooth with
    the shared lagged EWMA (:func:`_lagged_ewma`). When ``grid_turnover`` is
    supplied, the SAME smoother is applied to each factor's per-rebalance turnover
    series (e.g. :func:`alphaforge.validation.metrics.factor_turnover`, on the same
    grid) and the smoothed edge is haircut by its cost drag in IC-equivalent
    units::

        netIC_{k,t} = ÎC_{k,t}  -  λ_cost · cost_frac · T̂O_{k,t}

    then the §9.1 weight formula with the finding-19 floor (module docstring) is
    applied to ``netIC`` instead of the gross ``ÎC``. ``grid_turnover=None`` (the
    default) reproduces the gross-IC behaviour BIT-FOR-BIT — the only difference is
    that the optional audit frames are populated.

    Args:
        grid_turnover: optional alpha name -> per-rebalance one-way turnover series
            on the IDENTICAL grid/index as ``grid_ics``. Missing names default to
            zero turnover (no haircut). NaN turnover at a grid point = no cost
            evidence yet → zero haircut there.
        cost_frac: one-way cost scalar ``c`` (default :data:`DEFAULT_COST_FRAC`,
            10 bps). Must be finite and >= 0.
        lambda_cost: the Grinold cost→IC conversion ``λ_cost``. ``None`` uses
            :func:`default_lambda_cost` (≈588). Must be finite and >= 0.

    Returns :class:`BlendWeights` with one row per grid point (including the
    cold-start rows, where the floor yields equal weights). ``smoothed_ic`` and
    ``net_smoothed_ic`` carry the NET IC that drives the weights;
    ``gross_smoothed_ic`` carries the pre-haircut ÎC for auditability.
    """
    if horizon_bars <= 0:
        raise ValueError(f"horizon_bars must be > 0; got {horizon_bars}")
    if halflife_grid <= 0:
        raise ValueError(f"halflife_grid must be > 0; got {halflife_grid}")
    if kappa_shrink < 0 or kappa_floor <= 0:
        raise ValueError(
            f"kappa_shrink must be >= 0 and kappa_floor > 0 (finding 19); "
            f"got {kappa_shrink}, {kappa_floor}"
        )
    if not np.isfinite(cost_frac) or cost_frac < 0.0:
        raise ValueError(f"cost_frac must be finite and >= 0; got {cost_frac}")
    lam = default_lambda_cost() if lambda_cost is None else float(lambda_cost)
    if not np.isfinite(lam) or lam < 0.0:
        raise ValueError(f"lambda_cost must be finite and >= 0; got {lambda_cost}")
    names = tuple(grid_ics)
    if not names:
        raise ValueError("grid_ics must contain at least one alpha")
    if grid_turnover is not None:
        unknown = set(grid_turnover) - set(names)
        if unknown:
            raise ValueError(
                f"grid_turnover has alphas {sorted(unknown)} absent from grid_ics {sorted(names)}"
            )

    first = grid_ics[names[0]].index
    grid = first.to_numpy(dtype=np.int64)
    if grid.size == 0:
        return BlendWeights.equal(names)
    # The uniform-spacing requirement enforces the realized-label one-grid-step lag rule,
    # which only governs the RELATIVE weighting of MULTIPLE alphas. A single alpha is
    # definitionally weight 1 (max(IC,0)+κ normalized over one term == 1) regardless of the
    # lag/spacing, so the assertion does not apply — and a session (XNYS) grid is uniform in
    # SESSIONS but not wall-clock, so this would otherwise reject every equity single-alpha
    # book. (Multi-alpha EQUITY blends need session-aware non_overlapping; deferred.)
    if grid.size > 1 and len(names) > 1:
        spacing = np.diff(grid)
        expected = horizon_bars * timeframe.ms
        if not bool(np.all(spacing == expected)):
            raise ValueError(
                "grid_ics index must be uniformly spaced by horizon_bars*Δ = "
                f"{expected} ms (the realized-label lag rule t' + h·Δ <= t is a "
                f"one-grid-step shift ONLY under that spacing); got spacings "
                f"{sorted(set(spacing.tolist()))}"
            )
    smoothed_ic: dict[str, pd.Series] = {}
    smoothed_to: dict[str, pd.Series] = {}
    for name in names:
        ic = grid_ics[name]
        if not ic.index.equals(first):
            raise ValueError(f"grid_ics[{name!r}] index differs from grid_ics[{names[0]!r}]")
        smoothed_ic[name] = _lagged_ewma(ic, halflife_grid)
        if grid_turnover is not None and name in grid_turnover:
            to = grid_turnover[name]
            if not to.index.equals(first):
                raise ValueError(
                    f"grid_turnover[{name!r}] index differs from grid_ics[{names[0]!r}]"
                )
            smoothed_to[name] = _lagged_ewma(to, halflife_grid)

    index = pd.Index(grid, name="ts_open")
    gross_hat = pd.DataFrame(smoothed_ic, index=index).reindex(columns=list(names))

    if grid_turnover is None:
        net_hat = gross_hat
    else:
        # Smoothed turnover, missing/NaN -> 0 (no cost evidence -> no haircut).
        to_hat = (
            pd.DataFrame(smoothed_to, index=index).reindex(columns=list(names))
            if smoothed_to
            else pd.DataFrame(0.0, index=index, columns=list(names))
        )
        haircut = (lam * cost_frac) * to_hat.to_numpy(dtype=float)
        haircut = np.where(np.isfinite(haircut), haircut, 0.0)
        net_hat = pd.DataFrame(
            gross_hat.to_numpy(dtype=float) - haircut, index=index, columns=list(names)
        )

    net_values = net_hat.to_numpy(dtype=float)
    positive = np.where(np.isfinite(net_values) & (net_values > 0.0), net_values, 0.0)
    kappa = np.maximum(kappa_shrink * positive.mean(axis=1), kappa_floor)  # finding 19
    raw = positive + kappa[:, None]
    weights = raw / raw.sum(axis=1, keepdims=True)  # denominator >= K·kappa_floor > 0
    return BlendWeights(
        alpha_names=names,
        weights=pd.DataFrame(weights, index=index, columns=list(names)),
        smoothed_ic=net_hat,
        gross_smoothed_ic=gross_hat,
        net_smoothed_ic=net_hat,
    )


def blend(
    factor_zs: Mapping[str, pd.Series],
    weights: BlendWeights,
    universe_mask: pd.Series,
    *,
    min_members: int = 5,
) -> pd.Series:
    """Blend processed directional alpha z-scores into Ã (alphaDesign.md §9.1).

    ``A_{i,t} = Σ_k w_k(t) · z_{k,i,t}`` with ``w(t) = weights.asof(t)`` (the step
    function over the h-grid), then ``Ã = cs_zscore(A)`` over the SAME point-in-time
    universe mask (non-members are NaN'd BEFORE the cross-sectional moments —
    reusing :func:`alphaforge.features.cross_section.cs_zscore`).

    ``factor_zs`` maps alpha name -> z-score Series on a shared
    ``(ts_open, instrument_id)`` MultiIndex; its key set must equal
    ``weights.alpha_names``. NaN discipline is strict: an instrument missing ANY
    alpha at ``t`` has ``A_{i,t} = NaN`` (it drops out of that cross-section) — a
    partially-informed blend would silently re-weight alphas per instrument.

    Returns a float Series named ``"alpha_blend"`` aligned to the input index.
    """
    if set(factor_zs) != set(weights.alpha_names):
        raise ValueError(
            f"factor_zs alphas {sorted(factor_zs)} must equal weights.alpha_names "
            f"{sorted(weights.alpha_names)}"
        )
    zs = pd.DataFrame({name: factor_zs[name] for name in weights.alpha_names})
    if not isinstance(zs.index, pd.MultiIndex) or zs.index.nlevels != 2:
        raise ValueError("factor_zs must share a 2-level (ts_open, instrument_id) MultiIndex")
    ts_values = zs.index.get_level_values(0).to_numpy(dtype=np.int64)
    grid = weights.weights.index.to_numpy(dtype=np.int64)
    k = len(weights.alpha_names)
    if grid.size == 0:
        w_rows = np.full((len(zs), k), 1.0 / k)
    else:
        pos = np.searchsorted(grid, ts_values, side="right") - 1
        w_matrix = weights.weights.to_numpy(dtype=float)
        equal_row = np.full(k, 1.0 / k)
        w_rows = np.where((pos >= 0)[:, None], w_matrix[np.clip(pos, 0, None)], equal_row[None, :])
    a_values = (zs.to_numpy(dtype=float) * w_rows).sum(axis=1)  # NaN z propagates
    a = pd.Series(a_values, index=zs.index)
    mask = universe_mask.reindex(zs.index, fill_value=False).astype(bool)
    a_tilde = cs_zscore(a.where(mask), min_members=min_members)
    return a_tilde.rename(ALPHA_BLEND_COLUMN)
