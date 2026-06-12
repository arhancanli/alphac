"""Short-term mean reversion on beta-residual returns (alphaDesign.md §2.4).

Reversal is computed on **residual** returns so the factor never fades the market
itself. The full pipeline, evaluated per bar ``t`` on the complete-grid panel
layout (gaps stay NaN, inputs are never mutated):

1. Market return — equal-weight over the point-in-time universe ``U_t``
   (:meth:`FeatureContext.universe_asof` per grid timestamp, intersected with the
   requested cross-section)::

       m_t = (1/N_t) Σ_{i ∈ U_t} r_{i,t}

2. Rolling beta over ``W_β = 720`` bars (30d), strictly on returns **through
   t-1** (the conservative variant the design instructs)::

       β_{i,t} = Cov_720(r_i, m) / Var_720(m)        # window ending t-1

3. Residual return::

       ε_{i,t} = r_{i,t} - β_{i,t} · m_t

4. Reversal factor over horizon ``W``::

       MR_W(i,t) = - Σ_{k=0}^{W-1} ε_{i,t-k} / ( sigma_{ε,i,t} · sqrt(W) )

   with ``sigma_{ε,i,t}`` the zero-mean EWMA vol (span 168) of ``ε_i``
   (:func:`~alphaforge.features.library.vol.ewma_vol_from_returns`). The negative
   sign makes **higher factor ⇒ recent residual loser ⇒ expected outperformer**
   (``direction=+1``).

Registered: ``mr_res_24`` (1d, primary) and ``mr_res_72`` (3d) — both
``cross_sectional=True``. EWMA-family specs: ``lookback_bars = 720 + 15·168 =
3240`` (beta window + the library's 15-span EWMA truncation headroom
:data:`~alphaforge.features.library.vol.EWMA_HEADROOM_SPANS` — documented
truncation error < 1e-12, buildabilityCritique.md §6.1); parity rtol 1e-9.

The market proxy is computed over the *requested* instruments that are PIT
universe members at each ``t`` — engine calls must pass the full universe
cross-section for the canonical factor values.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import (
    EWMA_HEADROOM_SPANS,
    EWMA_VOL_SPAN,
    _roll_sum,
    _roll_var,
    ewma_vol_from_returns,
    log_returns,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Sequence

    from alphaforge.features.context import FeatureContext

__all__ = [
    "BETA_WINDOW",
    "market_return",
    "mr_res_24",
    "mr_res_72",
    "residual_reversal",
    "rolling_beta",
]

BETA_WINDOW: int = 720
"""Rolling beta window ``W_β`` in 1h bars (30d) — alphaDesign.md §2.4."""


def market_return(returns: pd.DataFrame, member_mask: pd.DataFrame) -> pd.Series:
    """Equal-weight market return over the per-timestamp universe members.

    ``m_t = (1/N_t) Σ_{i ∈ U_t} r_{i,t}`` — the mean of member returns at each
    grid row, skipping members whose return is NaN (a gapped member drops out of
    the average for that bar rather than poisoning it). NaN where no member has a
    valid return. ``member_mask`` is a boolean frame aligned to ``returns``.
    """
    if returns.shape != member_mask.shape:
        raise ValueError(
            f"market_return requires aligned shapes, got returns {returns.shape} "
            f"vs member_mask {member_mask.shape}"
        )
    return returns.where(member_mask).mean(axis=1)


def rolling_beta(
    returns: pd.DataFrame, market: pd.Series, *, window: int = BETA_WINDOW
) -> pd.DataFrame:
    """Rolling market beta, strictly from information through ``t-1``.

    ``β_{i,t} = Cov_window(r_i, m) / Var_window(m)`` where both moments are
    sample statistics (ddof=1; the ddof cancels in the ratio) over the ``window``
    bars ending at ``t-1`` — implemented as the window ending at ``t`` shifted
    one slot, the conservative reading of alphaDesign.md §2.4 step 2. NaN until
    the window is full of valid ``(r_i, m)`` pairs (a gap anywhere in the window
    yields NaN, never a silently shrunk window) and NaN where ``Var(m)`` is
    (numerically) zero.

    Moments use the computational form ``Cov = (Σxy - ΣxΣy/n)/(n-1)`` evaluated
    per-window with the prefix-independent reducers of
    :mod:`alphaforge.features.library.vol` — each output depends only on its own
    window, which is what keeps the (EWMA-relaxed) batch/live parity of the
    consuming specs from inheriting streaming-accumulator drift.

    Degenerate-market guard: the computational form cancels catastrophically on a
    (near-)constant market window — ``Σm² - (Σm)²/n`` leaves rounding residue of
    order ``n·eps·Σm²`` instead of exactly 0, and ``cov/var`` on two such residues
    is pure noise. ``Var(m)`` is therefore floored at ``8·n·eps`` RELATIVE to the
    window's mean square ``Σm²/(n-1)``: anything below it is indistinguishable
    from zero variance ⇒ β is NaN. Real return windows sit many orders of
    magnitude above the floor (their variance ≈ their mean square).
    """
    if window < 2:
        raise ValueError(f"rolling_beta window must be >= 2, got {window}")
    r = returns.to_numpy(dtype="float64")
    m = market.to_numpy(dtype="float64")
    m_col = m[:, np.newaxis]
    s_rm = _roll_sum(r * m_col, window)
    s_r = _roll_sum(r, window)
    s_m = _roll_sum(m_col, window)
    s_mm = _roll_sum(m_col * m_col, window)
    cov = (s_rm - s_r * s_m / float(window)) / float(window - 1)
    var = _roll_var(m_col, window)
    rel_floor = 8.0 * window * float(np.finfo(np.float64).eps)
    var_floor = rel_floor * s_mm / float(window - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        beta_arr = np.where(var > var_floor, cov / var, np.nan)
    beta = pd.DataFrame(beta_arr, index=returns.index, columns=returns.columns)
    return beta.shift(1)


def residual_reversal(
    returns: pd.DataFrame,
    market: pd.Series,
    *,
    window: int,
    beta_window: int = BETA_WINDOW,
    vol_span: int = EWMA_VOL_SPAN,
) -> pd.DataFrame:
    """Vol-scaled residual reversal (alphaDesign.md §2.4 steps 2-4)::

        β_{i,t}   = Cov_{Wβ}(r_i, m) / Var_{Wβ}(m)      # returns through t-1
        ε_{i,t}   = r_{i,t} - β_{i,t} · m_t
        sigma_{ε,i,t} = EWMA vol of ε_i (zero-mean, span=vol_span, min_periods=span)
        MR_W(i,t) = - Σ_{k=0}^{W-1} ε_{i,t-k} / ( sigma_{ε,i,t} · sqrt(W) )

    Positive value ⇒ the asset's last ``W`` bars underperformed its beta-implied
    return ⇒ expected to outperform (reversal). The ``W``-bar sum requires ``W``
    valid residuals (``min_periods = window`` — gaps make the factor NaN, never a
    shorter sum) and the result is NaN (never ±inf) where ``sigma_ε`` is NaN or zero.
    """
    if window < 1:
        raise ValueError(f"residual_reversal window must be >= 1, got {window}")
    beta = rolling_beta(returns, market, window=beta_window)
    resid = returns.sub(beta.mul(market, axis=0))
    sigma = ewma_vol_from_returns(resid, span=vol_span)
    resid_sum = pd.DataFrame(
        _roll_sum(resid.to_numpy(dtype="float64"), window),
        index=returns.index,
        columns=returns.columns,
    )
    return -resid_sum / (sigma.where(sigma > 0.0) * math.sqrt(window))


# -------------------------------------------------------------------- feature fns


_MASK_CACHE: WeakKeyDictionary[
    FeatureContext, dict[tuple[int, int, int, tuple[str, ...]], pd.DataFrame]
] = WeakKeyDictionary()
"""Per-context memo of the PIT membership mask (see :func:`_member_mask`).

A :class:`FeatureContext` is immutable and PIT-fixed, so the mask for a given
``(grid, columns)`` is a deterministic pure function of the context — memoizing it
changes no semantics. The payoff is the canonical batch call: ``mr_res_24`` and
``mr_res_72`` computed on ONE engine context share one per-timestamp
``universe_asof`` sweep instead of two. Weak keys: entries die with their context.
"""


def _member_mask(ctx: FeatureContext, index: pd.Index, columns: Sequence[str]) -> pd.DataFrame:
    """Boolean (grid ts x instrument) PIT membership mask.

    Row ``t`` is the point-in-time universe ``U_t`` via ``ctx.universe_asof(t)``
    (PIT by construction: membership intervals are knowable from their
    ``effective_from``), restricted to the requested ``columns``. Membership is
    piecewise-constant, so identical membership sets share one cached row vector;
    the full mask is memoized per context (:data:`_MASK_CACHE`). The returned
    frame is a copy-on-write shallow copy — consumers never see a shared buffer.
    """
    cols = list(columns)
    key = (
        int(index[0]) if len(index) else 0,
        int(index[-1]) if len(index) else 0,
        len(index),
        tuple(cols),
    )
    per_ctx = _MASK_CACHE.get(ctx)
    if per_ctx is None:
        per_ctx = {}
        _MASK_CACHE[ctx] = per_ctx
    mask = per_ctx.get(key)
    if mask is None:
        data = np.zeros((len(index), len(cols)), dtype=bool)
        row_cache: dict[frozenset[str], np.ndarray] = {}
        for i, ts in enumerate(index):
            members = ctx.universe_asof(int(ts))
            row = row_cache.get(members)
            if row is None:
                row = np.array([col in members for col in cols], dtype=bool)
                row_cache[members] = row
            data[i] = row
        mask = pd.DataFrame(data, index=index, columns=pd.Index(cols))
        per_ctx[key] = mask
    return mask.copy(deep=False)


def _mr_res_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``mr_res_{W}`` — see :func:`residual_reversal`.

    ``MR_W(i,t) = -Σ_{k<W} ε_{i,t-k} / (sigma_{ε,i,t}·sqrt(W))`` with ε the residual
    of r_i against the equal-weight PIT-universe market return and β estimated
    over ``beta_window`` bars ending ``t-1``. Every input is available at the
    decision close ``t + Δ``: closes through ``t``, membership at ``t``
    (knowable from ``effective_from``).
    """
    close = ctx.panel("close")
    returns = log_returns(close)
    mask = _member_mask(ctx, close.index, [str(c) for c in close.columns])
    mkt = market_return(returns, mask)
    out = residual_reversal(
        returns,
        mkt,
        window=int(spec.params["window"]),
        beta_window=int(spec.params["beta_window"]),
        vol_span=int(spec.params["span"]),
    )
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


def _mr_spec(window: int) -> FeatureSpec:
    """Single construction site for ``mr_res_*``.

    ``lookback_bars = beta_window + 15·span`` (= 3240): the EWMA sigma_ε needs
    15 spans of residuals (:data:`~alphaforge.features.library.vol.EWMA_HEADROOM_SPANS`
    truncation convention — dropped recursion weight ``e^-30``, error < 1e-12)
    and each residual needs a full beta window of returns behind it; the
    ``W``-bar sum (W ≤ 72) is covered by that headroom.
    """
    beta_window = BETA_WINDOW
    span = EWMA_VOL_SPAN
    return FeatureSpec(
        name=f"mr_res_{window}",
        family=Family.REVERSAL,
        direction=1,  # positive = recent residual loser = expected outperformer
        cross_sectional=True,
        lookback_bars=beta_window + EWMA_HEADROOM_SPANS * span,
        params={
            "window": window,
            "beta_window": beta_window,
            "span": span,
            "ewma_family": True,
        },
        fn=_mr_res_fn,
    )


@feature
def mr_res_24() -> FeatureSpec:
    """1d residual reversal (primary): ``-Σ_{k<24} ε_{t-k}/(sigma_ε·sqrt(24))``."""
    return _mr_spec(24)


@feature
def mr_res_72() -> FeatureSpec:
    """3d residual reversal: ``-Σ_{k<72} ε_{t-k}/(sigma_ε·sqrt(72))``."""
    return _mr_spec(72)
