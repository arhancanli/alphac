"""Liquidity & microstructure proxies (alphaDesign.md §2.6).

All operate on the sanctioned complete-grid panel layout
(:meth:`FeatureContext.panel`): row position == time slot, so ``shift``/``rolling``
are exact time operations, gaps stay NaN and are never bridged, and inputs are never
mutated. All four registered features are ``direction=0`` (risk features, universe
filters and execution-cost inputs — the illiquidity *premium* is unreliable at
hours-to-days horizons and conflicts with tradability) and ``cross_sectional=False``
(consumed raw by the cost model / universe filter / ML; CS post-processing would
destroy their units).

Registered (windows in 1h bars; lookbacks derived from params, finding 20):

* ``liq_amihud_720`` — Amihud (2002) illiquidity, ``ln(ILLIQ + 1e-12)``,
  lookback 721 (returns need the previous close).
* ``liq_volz_720`` — abnormal volume z-score on ``ln(1 + QV)``, lookback 720.
* ``liq_volz_24h_sum`` — same z-score on rolling 24-bar volume sums (suppresses
  intraday seasonality), lookback 743.
* ``liq_cs_spread_168`` — Corwin-Schultz (2012) two-bar spread estimator,
  7d mean, lookback 169.

Missing-data policies (declared, parity-safe — identical windows give identical
values on both engine paths):

* Amihud: bars with ``QV == 0`` or an undefined return (gap) are SKIPPED — the mean
  runs over the valid bars in the window (denominator = valid count, the standard
  Amihud reading of "skip"); at least one valid bar required, else NaN.
* Volume z-score: STRICT full window (``min_periods = window``) — a z-score against
  a partial/gappy distribution is biased, so any NaN in the window yields NaN.
* Corwin-Schultz: STRICT 168-bar mean (the design formula is ``(1/168)Σ``); per-bar
  estimates undefined at gaps poison the week — deliberate, the estimator feeds the
  execution-cost model and must not be quietly thinned.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import (
    _log,
    _roll_mean,
    _roll_sum,
    _roll_var,
    log_returns,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "AMIHUD_EPS",
    "CS_DENOM",
    "amihud_illiq",
    "corwin_schultz_spread",
    "liq_amihud_720",
    "liq_cs_spread_168",
    "liq_volz_24h_sum",
    "liq_volz_720",
    "volume_zscore",
]

AMIHUD_EPS: Final[float] = 1e-12
"""Additive floor inside the Amihud log (scale stability; alphaDesign.md §2.6)."""

CS_DENOM: Final[float] = 3.0 - 2.0 * math.sqrt(2.0)
"""Corwin-Schultz constant ``3 - 2√2 ≈ 0.171573`` (exact, not the rounded value)."""


def _roll_nanmean(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling NaN-skipping mean over axis 0, prefix-independent.

    Pads ``window - 1`` leading NaN rows so every output reduces a full-width
    window view (``numpy sliding_window_view``) — partial leading windows then
    fall out of NaN-skipping naturally, reproducing ``min_periods = 1`` semantics
    while each value depends ONLY on its own window contents (the streaming
    pandas accumulator would break the atol = 0 parity contract; see the
    prefix-independence note in :mod:`alphaforge.features.library.vol`).
    All-NaN windows yield NaN (0/0). The padded base is FORTRAN-ordered so the
    reduction axis is unit-stride — same layout-independence rationale as
    ``_roll_sum``.
    """
    padded = np.asfortranarray(
        np.vstack([np.full((window - 1, arr.shape[1]), np.nan, dtype="float64"), arr]),
        dtype="float64",
    )
    view = np.lib.stride_tricks.sliding_window_view(padded, window, axis=0)
    sums = np.nansum(view, axis=-1)
    counts = np.sum(~np.isnan(view), axis=-1).astype("float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        out: np.ndarray = np.where(counts > 0, sums / counts, np.nan)
    return out


def _wide(values: np.ndarray, like: pd.DataFrame) -> pd.DataFrame:
    """Wrap a reduced array back into ``like``'s index/columns (float64)."""
    return pd.DataFrame(values, index=like.index, columns=like.columns)


def amihud_illiq(
    close: pd.DataFrame, quote_volume: pd.DataFrame, *, window: int = 720
) -> pd.DataFrame:
    """Amihud (2002) illiquidity over ``window`` bars, log-transformed.

    Formula (alphaDesign.md §2.6), with ``r`` = 1-bar log return and quote (USDT)
    volume ``QV``::

        ILLIQ(i, t) = mean over valid bars k in  [t-n+1, t] of |r_{i,k}| / QV_{i,k}
        value       = ln( ILLIQ + 1e-12 )

    "Valid" excludes bars with ``QV = 0`` (division blow-up on dead bars — the
    design's "skipped") and bars whose return is undefined (data gap: both the gap
    slot and the slot after it, since ``r`` is computed positionally on the
    complete grid). The mean divides by the count of valid bars; NaN when the
    window holds none. Higher value = more illiquid. Windows are reduced
    independently (:func:`_roll_nanmean`), so batch/live parity is exact (atol=0).
    """
    if window < 1:
        raise ValueError(f"amihud window must be >= 1, got {window}")
    abs_ret = log_returns(close).abs()
    qv = quote_volume.where(quote_volume > 0.0)  # QV == 0 (and NaN) bars skipped
    ratio = (abs_ret / qv).to_numpy(dtype="float64")
    illiq = _wide(_roll_nanmean(ratio, window), close)
    return _log(illiq + AMIHUD_EPS)


def volume_zscore(
    quote_volume: pd.DataFrame, *, window: int = 720, sum_bars: int = 1
) -> pd.DataFrame:
    """Abnormal-volume z-score on ``ln(1 + QV)`` over ``window`` bars.

    Formula (alphaDesign.md §2.6)::

        x_t  = ln(1 + QV_t)                    # log first: crypto volume is heavy-tailed
        VZ_t = ( x_t - μ_t ) / s_t

    with ``μ, s`` = rolling mean / sample std (ddof=1) of ``x`` over the window
    *including the current bar*. ``sum_bars > 1`` first replaces ``QV`` with its
    rolling ``sum_bars``-bar sum (``min_periods = sum_bars``) — the
    ``liq_volz_24h_sum`` variant, which suppresses intraday volume seasonality.
    STRICT windows (``min_periods = window``): any gap inside the window => NaN.
    A constant-volume window has ``s = 0`` => NaN (no abnormality is measurable).
    Windows are reduced independently (prefix-independent reducers from
    :mod:`alphaforge.features.library.vol`), so batch/live parity is exact (atol=0).
    """
    if window < 2:
        raise ValueError(f"volume_zscore window must be >= 2 (uses ddof=1), got {window}")
    if sum_bars < 1:
        raise ValueError(f"volume_zscore sum_bars must be >= 1, got {sum_bars}")
    qv_arr = quote_volume.to_numpy(dtype="float64")
    if sum_bars > 1:
        qv_arr = _roll_sum(qv_arr, sum_bars)
    x = np.log1p(qv_arr)
    mu = _roll_mean(x, window)
    sd = np.sqrt(_roll_var(x, window))
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(sd > 0.0, (x - mu) / sd, np.nan)
    return _wide(z, quote_volume)


def corwin_schultz_spread(
    high: pd.DataFrame, low: pd.DataFrame, *, smooth: int = 168
) -> pd.DataFrame:
    """Corwin-Schultz (2012) two-bar spread estimator, ``smooth``-bar mean.

    Formula (alphaDesign.md §2.6), per bar ``t`` from two consecutive bars::

        beta_t = [ln(H_{t-1}/L_{t-1})]² + [ln(H_t/L_t)]²
        gamma_t = [ln( max(H_{t-1}, H_t) / min(L_{t-1}, L_t) )]²
        alpha_t = (√(2beta_t) - √beta_t) / (3 - 2√2)  -  √( gamma_t / (3 - 2√2) )
        S_t = 2(e^{alpha_t} - 1) / (1 + e^{alpha_t})
        S_t <- max(S_t, 0)                       # standard negative-spread floor
        CS_SPREAD(i, t) = (1/smooth) Σ_{k=0}^{smooth-1} S_{t-k}

    Applied to 1h bars as a *ranking* proxy (CS derived it for daily bars — do not
    interpret as an absolute spread). The smoothing mean is STRICT
    (``min_periods = smooth``); a per-bar estimate touching a gap is NaN (the
    ``t-1`` shift is positional on the complete grid) and poisons its windows.
    The smoothing windows are reduced independently (prefix-independent
    ``_roll_mean``), so batch/live parity is exact (atol = 0).
    """
    if smooth < 1:
        raise ValueError(f"corwin_schultz smooth must be >= 1, got {smooth}")
    hl_sq = _log(high / low).pow(2)
    beta = hl_sq.shift(1) + hl_sq
    hmax = pd.DataFrame(
        np.maximum(high.to_numpy(dtype="float64"), high.shift(1).to_numpy(dtype="float64")),
        index=high.index,
        columns=high.columns,
    )
    lmin = pd.DataFrame(
        np.minimum(low.to_numpy(dtype="float64"), low.shift(1).to_numpy(dtype="float64")),
        index=low.index,
        columns=low.columns,
    )
    gamma = _log(hmax / lmin).pow(2)
    alpha = ((2.0 * beta).pow(0.5) - beta.pow(0.5)) / CS_DENOM - (gamma / CS_DENOM).pow(0.5)
    exp_alpha = np.exp(alpha.to_numpy(dtype="float64"))
    spread = pd.DataFrame(
        2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha),
        index=alpha.index,
        columns=alpha.columns,
    )
    spread = spread.clip(lower=0.0)  # NaN-preserving floor
    return _wide(_roll_mean(spread.to_numpy(dtype="float64"), smooth), high)


# -------------------------------------------------------------------- feature fns


def _amihud_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``liq_amihud_{n}`` — see :func:`amihud_illiq`."""
    window = int(spec.params["window"])
    out = amihud_illiq(ctx.panel("close"), ctx.panel("quote_volume"), window=window)
    return long_series(out, name=spec.name)


def _volz_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for the volume z-scores — see :func:`volume_zscore`."""
    window = int(spec.params["window"])
    sum_bars = int(spec.params["sum_bars"])
    out = volume_zscore(ctx.panel("quote_volume"), window=window, sum_bars=sum_bars)
    return long_series(out, name=spec.name)


def _cs_spread_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``liq_cs_spread_{n}`` — see :func:`corwin_schultz_spread`."""
    smooth = int(spec.params["smooth"])
    out = corwin_schultz_spread(ctx.panel("high"), ctx.panel("low"), smooth=smooth)
    return long_series(out, name=spec.name)


# ------------------------------------------------------------------- registrations


@feature
def liq_amihud_720() -> FeatureSpec:
    """Amihud illiquidity, 30d window (lookback = window + 1: returns need C_{t-1})."""
    window = 720
    return FeatureSpec(
        name="liq_amihud_720",
        family=Family.LIQUIDITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + 1,
        params={"window": window},
        fn=_amihud_fn,
    )


@feature
def liq_volz_720() -> FeatureSpec:
    """Abnormal volume z-score, 30d window (lookback = window: no shift needed)."""
    window = 720
    return FeatureSpec(
        name="liq_volz_720",
        family=Family.LIQUIDITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=window,
        params={"window": window, "sum_bars": 1},
        fn=_volz_fn,
    )


@feature
def liq_volz_24h_sum() -> FeatureSpec:
    """Volume z-score on 24-bar sums (lookback = window + sum_bars - 1)."""
    window, sum_bars = 720, 24
    return FeatureSpec(
        name="liq_volz_24h_sum",
        family=Family.LIQUIDITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + sum_bars - 1,
        params={"window": window, "sum_bars": sum_bars},
        fn=_volz_fn,
    )


@feature
def liq_cs_spread_168() -> FeatureSpec:
    """Corwin-Schultz spread, 7d mean (lookback = smooth + 1: beta needs the prior bar)."""
    smooth = 168
    return FeatureSpec(
        name="liq_cs_spread_168",
        family=Family.LIQUIDITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=smooth + 1,
        params={"smooth": smooth},
        fn=_cs_spread_fn,
    )
