"""Raw-alpha blend — EWMA Rank-IC weighting (alphaDesign.md §9.1).

The blend turns K processed directional alpha z-scores ``z_{k,i,t}`` (each already
multiplied by ``FeatureSpec.direction`` upstream, so a healthy alpha has POSITIVE
IC) into one cross-sectionally re-standardized signal::

    On the NON-OVERLAPPING h-bar grid (h = SignalsCfg.horizon_bars, THE one
    holding-period constant — buildabilityCritique.md §3.10):

        RIC_{k,t} = SpearmanCorr_i( z_{k,i,t}, y_{i,t,h} )
        ÎC_{k,t}  = EWMA( RIC_{k,·} ; halflife = 20 grid points ),  LAGGED:
                    uses ONLY observations with  t' + h·Δ <= t      (label realized)
        w_{k,t}   = max(ÎC_{k,t}, 0) + κ_t
        κ_t       = max( κ_shrink · mean_k max(ÎC_{k,t}, 0), κ_floor )
        w_{k,t}  := w_{k,t} / Σ_j w_{j,t}

    A_{i,t} = Σ_k w_{k,t} · z_{k,i,t}
    Ã_{i,t} = cs_zscore( A_{·,t} )        # over the SAME PIT universe mask

Lag enforcement is THE point (leakage critique): the label ``y_{i,t',h}`` exits at
the open of bar ``t' + (1+h)·Δ``, so RIC_{k,t'} is fully realized at decision
instant ``t + Δ`` iff ``t' + h·Δ <= t``. On a uniform h-spaced grid that is
*exactly* "all grid points strictly before t", i.e. a one-grid-step shift —
:func:`estimate_blend_weights` asserts the uniform spacing so the shift IS the
rule, mechanically. An IC printed inside the last ``h`` bars can never move the
weights used at ``t``.

Degenerate-case floor (leakage finding 19): when every smoothed IC is <= 0 the
design formula ``κ = 0.2·mean_k max(ÎC,0)`` collapses to 0 and normalization is
0/0. The absolute floor ``κ_floor = 0.01`` guarantees strictly positive weights;
with all ÎC <= 0 every alpha gets exactly ``κ_floor`` and the blend degrades to
EQUAL weights — never NaN, never a sign flip.

Cold start: before any realized RIC exists, ÎC is NaN for every alpha; NaN ÎC is
treated as "no evidence" (contributes 0 to ``max(ÎC,0)``), so the κ floor again
yields equal weights. Equal weights are therefore not a special code path but the
fixed point the estimator shrinks toward.

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
    "KAPPA_FLOOR",
    "KAPPA_SHRINK",
    "BlendWeights",
    "blend",
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


@dataclass(frozen=True, slots=True, kw_only=True)
class BlendWeights:
    """Walk-forward blend weights on the non-overlapping h-grid.

    Attributes:
        alpha_names: Alpha ordering shared by both frames' columns.
        weights: Float frame indexed by grid ``ts_open`` (epoch-ms int64,
            strictly increasing), one column per alpha; every row is strictly
            positive and sums to 1. Row at grid point ``t`` was estimated from
            RIC observations with ``t' + h·Δ <= t`` ONLY (realized labels).
        smoothed_ic: The lagged EWMA ``ÎC_{k,t}`` behind each weight row (NaN
            where no realized RIC existed yet) — kept for diagnostics/reports.

    Treat the frames as read-only (shared, not defensively copied).
    """

    alpha_names: tuple[str, ...]
    weights: pd.DataFrame
    smoothed_ic: pd.DataFrame

    def __post_init__(self) -> None:
        if not self.alpha_names:
            raise ValueError("BlendWeights requires at least one alpha")
        for frame_name in ("weights", "smoothed_ic"):
            frame: pd.DataFrame = getattr(self, frame_name)
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
        return cls(alpha_names=alpha_names, weights=empty, smoothed_ic=empty.copy())

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


def estimate_blend_weights(
    grid_ics: Mapping[str, pd.Series],
    *,
    horizon_bars: int,
    timeframe: Timeframe = Timeframe.H1,
    halflife_grid: float = BLEND_EWMA_HALFLIFE_GRID,
    kappa_shrink: float = KAPPA_SHRINK,
    kappa_floor: float = KAPPA_FLOOR,
) -> BlendWeights:
    """Estimate walk-forward blend weights from non-overlapping-grid Rank-ICs.

    ``grid_ics`` maps alpha name -> RIC series indexed by ``ts_open`` (epoch-ms
    int64) on the non-overlapping h-grid (e.g. the output of
    :func:`alphaforge.validation.metrics.rank_ic` subsampled by
    :func:`~alphaforge.validation.metrics.non_overlapping`). All series must share
    one index with UNIFORM spacing of exactly ``horizon_bars · Δ`` — asserted,
    because the realized-label rule ``t' + h·Δ <= t`` is implemented as a
    one-grid-step shift and is only equivalent under that spacing.

    Per alpha: shift the RIC series one grid step (lag enforcement), smooth with
    ``EWMA(halflife = halflife_grid grid points)`` — ``adjust=True`` (finite-sample
    weighted mean, exact from the first observation) with ``ignore_na=True`` so a
    thin-cross-section NaN RIC is skipped, not zero-imputed. Then apply the §9.1
    weight formula with the finding-19 floor (module docstring).

    Returns :class:`BlendWeights` with one row per grid point (including the
    cold-start rows, where the floor yields equal weights).
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
    names = tuple(grid_ics)
    if not names:
        raise ValueError("grid_ics must contain at least one alpha")

    first = grid_ics[names[0]].index
    grid = first.to_numpy(dtype=np.int64)
    if grid.size == 0:
        return BlendWeights.equal(names)
    if grid.size > 1:
        spacing = np.diff(grid)
        expected = horizon_bars * timeframe.ms
        if not bool(np.all(spacing == expected)):
            raise ValueError(
                "grid_ics index must be uniformly spaced by horizon_bars*Δ = "
                f"{expected} ms (the realized-label lag rule t' + h·Δ <= t is a "
                f"one-grid-step shift ONLY under that spacing); got spacings "
                f"{sorted(set(spacing.tolist()))}"
            )
    smoothed: dict[str, pd.Series] = {}
    for name in names:
        ic = grid_ics[name]
        if not ic.index.equals(first):
            raise ValueError(f"grid_ics[{name!r}] index differs from grid_ics[{names[0]!r}]")
        lagged = ic.astype(float).shift(1)  # realized-label rule: t' + h·Δ <= t
        smoothed[name] = lagged.ewm(
            halflife=halflife_grid, adjust=True, ignore_na=True, min_periods=1
        ).mean()

    index = pd.Index(grid, name="ts_open")
    ic_hat = pd.DataFrame(smoothed, index=index).reindex(columns=list(names))
    positive = np.where(np.isfinite(ic_hat.to_numpy()) & (ic_hat.to_numpy() > 0.0), ic_hat, 0.0)
    kappa = np.maximum(kappa_shrink * positive.mean(axis=1), kappa_floor)  # finding 19
    raw = positive + kappa[:, None]
    weights = raw / raw.sum(axis=1, keepdims=True)  # denominator >= K·kappa_floor > 0
    return BlendWeights(
        alpha_names=names,
        weights=pd.DataFrame(weights, index=index, columns=list(names)),
        smoothed_ic=ic_hat,
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
