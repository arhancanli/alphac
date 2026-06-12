"""Cross-sectional processing for factor panels (alphaDesign.md §3).

Every transform here operates *per timestamp* on a long panel: a
:class:`pandas.Series` indexed by a two-level MultiIndex ``(ts_open, instrument_id)``
with ``ts_open`` as epoch-ms UTC ``int64``. Statistics are computed independently
within each ``ts_open`` group over the non-NaN members, so a value at time ``T`` is a
pure function of the cross-section at ``T`` — no time-series state, no lookahead.

Universe masking (leakage-critical). :class:`CSPipeline.apply` masks non-members to
NaN **before** any statistic is computed. Computing cross-sectional statistics over
instruments that were not point-in-time universe members is lookahead-adjacent
*selection bias*: the historical cross-section gets contaminated by names that were
only selected (listed, liquid, surviving) later, which shifts means/stds/ranks in a
way no live system could have reproduced. The mask must come from
``UniverseStore.membership_asof`` / ``UniverseBuilder.members_asof``, never from
today's listing set applied historically.

No function in this module mutates its inputs; each returns a freshly allocated
Series/DataFrame aligned to the input index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

__all__ = [
    "CSPipeline",
    "cs_rank",
    "cs_zscore",
    "neutralize",
    "winsorize_mad",
]

MAD_CONSISTENCY: Final[float] = 1.4826
"""Scale factor making the MAD a consistent estimator of sigma under normality
(1 / Φ⁻¹(3/4))."""

_FALLBACK_QUANTILES: Final[tuple[float, float]] = (0.01, 0.99)
"""Quantile clip bounds used when MAD == 0 (degenerate cross-section;
alphaDesign.md §3)."""


def _require_panel_index(s: pd.Series, name: str) -> None:
    """Fail loud if ``s`` is not indexed by a 2-level (ts_open, instrument_id) MultiIndex."""
    if not isinstance(s.index, pd.MultiIndex) or s.index.nlevels != 2:
        raise ValueError(
            f"{name} must be indexed by a 2-level (ts_open, instrument_id) MultiIndex; "
            f"got {type(s.index).__name__} with nlevels="
            f"{s.index.nlevels if isinstance(s.index, pd.MultiIndex) else 1}"
        )


def winsorize_mad(s: pd.Series, k: float = 5.0) -> pd.Series:
    """MAD-winsorize a factor cross-section per timestamp.

    Per ``ts_open`` group, over the non-NaN members::

        med  = median_i(x_i)
        MAD  = median_i(|x_i - med|)
        x̃_i = clip(x_i, med - k·1.4826·MAD, med + k·1.4826·MAD)

    ``1.4826·MAD`` is a consistent sigma estimate under normality, so ``k`` is a robust
    sigma-unit clip. When ``MAD == 0`` (more than half the members share one value — a
    degenerate cross-section) the MAD bound would crush everything to the median, so
    the clip falls back to the (1%, 99%) member quantiles (alphaDesign.md §3).

    NaNs pass through unchanged. Returns a new Series aligned to ``s.index``.
    """
    _require_panel_index(s, "s")
    if not np.isfinite(k) or k <= 0.0:
        raise ValueError(f"k must be a positive finite float; got {k}")

    def _winsorize_group(g: pd.Series) -> pd.Series:
        valid = g.dropna()
        if valid.empty:
            return g.astype(float)
        med = float(valid.median())
        mad = float((valid - med).abs().median())
        if mad > 0.0:
            half_width = k * MAD_CONSISTENCY * mad
            lo, hi = med - half_width, med + half_width
        else:
            lo = float(valid.quantile(_FALLBACK_QUANTILES[0]))
            hi = float(valid.quantile(_FALLBACK_QUANTILES[1]))
        return g.clip(lower=lo, upper=hi)

    out = s.groupby(level=0, sort=False, group_keys=False).transform(_winsorize_group)
    out.name = s.name
    return out


def cs_zscore(s: pd.Series, *, min_members: int = 5) -> pd.Series:
    """Cross-sectional z-score per timestamp.

    Per ``ts_open`` group, over the ``n`` non-NaN members::

        z_i = (x_i - mean(x)) / std(x)        # std with ddof=1

    The entire timestamp is emitted as NaN when ``std == 0`` (no cross-sectional
    dispersion — a z-score is meaningless) or ``n < min_members`` (too few names for
    the cross-sectional moments to mean anything; alphaDesign.md §3, default 5).

    NaN inputs stay NaN. Returns a new Series aligned to ``s.index``.
    """
    _require_panel_index(s, "s")
    if min_members < 2:
        raise ValueError(f"min_members must be >= 2; got {min_members}")

    def _zscore_group(g: pd.Series) -> pd.Series:
        valid = g.dropna()
        if len(valid) < min_members:
            return g * np.nan
        mu = float(valid.mean())
        sd = float(valid.std(ddof=1))
        if not np.isfinite(sd) or sd == 0.0:
            return g * np.nan
        return (g - mu) / sd

    out = s.groupby(level=0, sort=False, group_keys=False).transform(_zscore_group)
    out.name = s.name
    return out


def cs_rank(s: pd.Series) -> pd.Series:
    """Cross-sectional rank transform to ``[-1, 1]`` per timestamp.

    Per ``ts_open`` group, over the ``n`` non-NaN members, with average ranks for
    ties (``rank_i ∈ [1, n]``)::

        u_i = 2·(rank_i - 1)/(n - 1) - 1      # min rank → -1, max rank → +1

    Bounded and outlier-proof — the preferred input form for tree models
    (alphaDesign.md §3). A single-member cross-section (``n == 1``) maps to ``0.0``
    (centre of the range; the rank carries no information). NaNs pass through.

    Returns a new Series aligned to ``s.index``.
    """
    _require_panel_index(s, "s")

    def _rank_group(g: pd.Series) -> pd.Series:
        n = int(g.count())
        if n == 0:
            return g.astype(float)
        ranks = g.rank(method="average")
        if n == 1:
            return ranks * 0.0  # 0.0 at the lone member; NaN elsewhere preserved
        return 2.0 * (ranks - 1.0) / (n - 1.0) - 1.0

    out = s.groupby(level=0, sort=False, group_keys=False).transform(_rank_group)
    out.name = s.name
    return out


def neutralize(s: pd.Series, beta: pd.Series) -> pd.Series:
    """Per-timestamp OLS residualization of ``s`` against ``beta`` (plus intercept).

    Per ``ts_open`` group, with exposure matrix ``X = [1, β]`` over the members where
    both ``s`` and ``beta`` are finite::

        f_neut = f - X (Xᵀ X)⁻¹ Xᵀ f

    i.e. the residual of the cross-sectional regression ``f ~ 1 + β``. This removes
    the "everything is a market-beta bet" degeneracy from momentum/reversal factors
    (alphaDesign.md §3). The solve uses :func:`numpy.linalg.lstsq` (minimum-norm), so
    a degenerate cross-section (constant β) gracefully reduces to demeaning.

    Rows where either input is NaN — and whole timestamps with fewer than 2 usable
    members — are NaN in the output. ``beta`` is aligned to ``s.index`` by reindex;
    inputs are not mutated.
    """
    _require_panel_index(s, "s")
    values = s.to_numpy(dtype=float, copy=True)
    betas = beta.reindex(s.index).to_numpy(dtype=float)
    out = np.full(len(s), np.nan)

    for positions in s.groupby(level=0, sort=False).indices.values():
        y = values[positions]
        x = betas[positions]
        usable = np.isfinite(y) & np.isfinite(x)
        n = int(usable.sum())
        if n < 2:
            continue
        design = np.column_stack([np.ones(n), x[usable]])
        coef, *_ = np.linalg.lstsq(design, y[usable], rcond=None)
        out[positions[usable]] = y[usable] - design @ coef

    return pd.Series(out, index=s.index, name=s.name)


_ALLOWED_STEPS: Final[frozenset[str]] = frozenset({"winsorize", "neutralize", "zscore", "rank"})


@dataclass(frozen=True, slots=True, kw_only=True)
class CSPipeline:
    """Per-timestamp cross-sectional processing chain, universe-masked.

    Default chain: ``winsorize → zscore`` (alphaDesign.md §3). Supported steps:

    - ``"winsorize"`` — :func:`winsorize_mad` with ``k``
    - ``"neutralize"`` — :func:`neutralize` against the ``exposures`` Series
      (required at :meth:`apply` time when this step is configured)
    - ``"zscore"`` — :func:`cs_zscore` with ``min_members``
    - ``"rank"`` — :func:`cs_rank`

    Universe masking happens FIRST: non-members are set to NaN before any statistic
    is computed per timestamp, so medians/means/stds/ranks are estimated over the
    point-in-time membership only. Computing cross-sectional stats over non-members
    is lookahead-adjacent selection bias — names selected with future information
    (later listing, later liquidity) would contaminate the historical cross-section.
    The mask must be derived from ``UniverseStore.membership_asof``.
    """

    steps: tuple[str, ...] = ("winsorize", "zscore")
    k: float = field(default=5.0)
    min_members: int = field(default=5)

    def __post_init__(self) -> None:
        unknown = [step for step in self.steps if step not in _ALLOWED_STEPS]
        if unknown:
            raise ValueError(
                f"unknown CSPipeline steps {unknown!r}; allowed: {sorted(_ALLOWED_STEPS)}"
            )
        if not np.isfinite(self.k) or self.k <= 0.0:
            raise ValueError(f"k must be a positive finite float; got {self.k}")
        if self.min_members < 2:
            raise ValueError(f"min_members must be >= 2; got {self.min_members}")

    def apply(
        self,
        frame: pd.DataFrame,
        universe_mask: pd.Series,
        *,
        exposures: pd.Series | None = None,
    ) -> pd.DataFrame:
        """Run the configured chain over every column of ``frame``.

        ``frame``: long factor panel — columns are factor names, index is the
        ``(ts_open, instrument_id)`` MultiIndex. ``universe_mask``: boolean Series on
        the same kind of index; rows absent from the mask are treated as
        non-members (fail-closed). ``exposures``: per-row beta Series, required iff
        ``"neutralize"`` is in :attr:`steps`.

        Returns a new DataFrame aligned to ``frame.index``; non-members are NaN in
        every output column. Inputs are not mutated.
        """
        if not isinstance(frame.index, pd.MultiIndex) or frame.index.nlevels != 2:
            raise ValueError(
                "frame must be indexed by a 2-level (ts_open, instrument_id) MultiIndex"
            )
        if "neutralize" in self.steps and exposures is None:
            raise ValueError("CSPipeline has a 'neutralize' step but no exposures were provided")

        mask = universe_mask.reindex(frame.index, fill_value=False).astype(bool)
        out: dict[str, pd.Series] = {}
        for column in frame.columns:
            series = frame[column].where(mask)  # mask non-members BEFORE any stats
            for step in self.steps:
                if step == "winsorize":
                    series = winsorize_mad(series, self.k)
                elif step == "neutralize":
                    assert exposures is not None  # narrowed above; mypy aid
                    series = neutralize(series, exposures)
                elif step == "zscore":
                    series = cs_zscore(series, min_members=self.min_members)
                else:  # "rank" — only remaining allowed step
                    series = cs_rank(series)
            out[str(column)] = series
        return pd.DataFrame(out, index=frame.index)
