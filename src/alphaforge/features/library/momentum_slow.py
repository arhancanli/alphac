"""Slow residual-momentum factor (build slate Pod A, momentum leg).

The single registered factor here is ``mom_res_2160_168`` - vol-scaled residual
momentum with a 90-day formation window and a 7-day skip (Blitz-Huij-Martens style
residual momentum, adapted to crypto perps). It is the slate's attempt to revive
the dead momentum sleeve with NEW orthogonal information.

Economics. Raw crypto cross-sectional momentum is flat (the IC report: every
``mom_*`` t-stat < 1.6 at h=72, ``mom_ts_168`` outright negative) because a raw
winner basket is a hidden long-BTC-beta bet - it loads on the market, not on
idiosyncratic trend. Stripping the market beta out leaves the *residual* return
``eps``, whose trend is the documented clean momentum signal. Two design choices make
the factor orthogonal to the live edges by construction:

* the **market strip** (``eps = r - beta*m``, same residual the reversal module forms)
  removes the BTC-beta bet that kills raw momentum and that ``beta_lowbeta_720``
  trades directly - residual momentum is neither;
* the **7-day skip** (``skip = 168`` bars) excludes the most recent week from the
  formation window, which is exactly the band the live residual-reversal factors
  (``mr_res_24`` / ``mr_res_72``, horizons <= 72 bars) live in. The signal is the
  trend in residuals from 7d to 90d ago - disjoint from the <=3d reversal window.

Pipeline (per bar ``t`` on the complete-grid panel; gaps stay NaN, inputs never
mutated):

1. Equal-weight PIT-universe market return ``m_t`` and rolling market beta
   ``beta_{i,t}`` (window ending ``t-1``) - both reused verbatim from
   :mod:`alphaforge.features.library.mean_reversion` (``market_return`` /
   ``rolling_beta`` / the cached ``_member_mask``), so the residual is the *same*
   object the reversal factors strip.

2. Residual return ``eps_{i,t} = r_{i,t} - beta_{i,t}*m_t``.

3. Skipped residual sum over the formation window ``[skip, lookback)`` (here
   ``lookback = 2160`` bars = 90d, ``skip = 168`` bars = 7d), i.e. ``W = lookback -
   skip = 1992`` residuals from ``t-skip-W+1 .. t-skip``::

       S_{i,t} = Sum_{k=skip}^{lookback-1} eps_{i,t-k}

   computed positionally as the prefix-independent ``W``-bar rolling sum
   (:func:`~alphaforge.features.library.vol._roll_sum`) shifted ``skip`` slots - a
   gap anywhere in the summed window NaNs the output (never a shrunk sum, never
   bridged across a missing bar).

4. Residual-vol scaling ``sigma_{eps,i,t}`` = the zero-mean EWMA vol (span ``span = 168``)
   of ``eps_i`` (:func:`~alphaforge.features.library.vol.ewma_vol_from_returns`), so
   the factor is approximately a t-stat of the residual trend, comparable across
   assets::

       RESMOM(i,t) = S_{i,t} / ( sigma_{eps,i,t} * sqrt(W) )

The factor is ``RESMOM`` itself - NOT negated; ``direction = +1`` (higher residual
trend => expected continuation). ``cross_sectional=True`` (winsorize / neutralize /
z-score over the PIT universe before blending). Low turnover (a 90d formation
ranking is near-static over the 3-day rebalance) => high capacity, survives cost.

Lookback honesty (leakage finding 20): ``lookback_bars = beta_window +
max(EWMA_HEADROOM_SPANS * span, lookback)``. The deepest residual the factor
touches is ``eps_{t-lookback+1}`` (the far edge of the skipped sum), and each residual
needs a full beta window of returns behind it; the EWMA sigma_eps additionally needs the
library's 15-span truncation headroom. With ``beta_window=720``, ``lookback=2160``,
``span=168``: ``720 + max(15*168, 2160) = 720 + max(2520, 2160) = 720 + 2520 =
3240``. EWMA-family (sigma_eps is an infinite-memory recursion) => parity rtol 1e-9.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.mean_reversion import (
    BETA_WINDOW,
    _member_mask,
    market_return,
    rolling_beta,
)
from alphaforge.features.library.vol import (
    EWMA_HEADROOM_SPANS,
    EWMA_VOL_SPAN,
    _roll_sum,
    ewma_vol_from_returns,
    log_returns,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "mom_res_2160_168",
    "residual_momentum",
]


def residual_momentum(
    returns: pd.DataFrame,
    market: pd.Series,
    *,
    lookback: int,
    skip: int,
    beta_window: int = BETA_WINDOW,
    vol_span: int = EWMA_VOL_SPAN,
) -> pd.DataFrame:
    """Vol-scaled residual momentum with a skip (build slate Pod A)::

        beta_{i,t}   = Cov_{Wbeta}(r_i, m) / Var_{Wbeta}(m)        # returns through t-1
        eps_{i,t}   = r_{i,t} - beta_{i,t} * m_t
        W         = lookback - skip
        S_{i,t}   = Sum_{k=skip}^{lookback-1} eps_{i,t-k}      # W residuals, skip-lagged
        sigma_{eps,i,t} = EWMA vol of eps_i (zero-mean, span=vol_span, min_periods=span)
        RESMOM(i,t) = S_{i,t} / ( sigma_{eps,i,t} * sqrt(W) )

    Positive value => the asset's residual returns from ``skip`` to ``lookback``
    bars ago trended up => expected continuation (``direction=+1``; NOT negated).
    The ``W``-bar sum requires ``W`` valid residuals (``min_periods = W`` via the
    prefix-independent reducer - gaps make the factor NaN, never a shorter sum) and
    the result is NaN (never +/-inf) where ``sigma_eps`` is NaN or zero.

    ``beta`` / ``eps`` are exactly the reversal module's residual (same ``rolling_beta``
    and ``market``), so the skip band keeps this orthogonal to residual reversal.
    """
    if lookback < 2:
        raise ValueError(f"residual_momentum lookback must be >= 2, got {lookback}")
    if not 0 <= skip < lookback:
        raise ValueError(
            f"residual_momentum requires 0 <= skip < lookback, got skip={skip}, lookback={lookback}"
        )
    window = lookback - skip
    beta = rolling_beta(returns, market, window=beta_window)
    resid = returns.sub(beta.mul(market, axis=0))
    sigma = ewma_vol_from_returns(resid, span=vol_span)
    resid_sum = pd.DataFrame(
        _roll_sum(resid.to_numpy(dtype="float64"), window),
        index=returns.index,
        columns=returns.columns,
    ).shift(skip)  # exclude the most recent ``skip`` bars (positional == time op on the grid)
    return resid_sum / (sigma.where(sigma > 0.0) * math.sqrt(window))


# -------------------------------------------------------------------- feature fns


def _mom_res_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``mom_res_{L}_{S}`` - see :func:`residual_momentum`.

    ``RESMOM(i,t) = Sum_{k=skip}^{L-1} eps_{i,t-k} / (sigma_{eps,i,t}*sqrt(L-skip))`` with
    eps the residual of r_i against the equal-weight PIT-universe market return and beta
    estimated over ``beta_window`` bars ending ``t-1``. Every input is available at
    the decision close ``t + Delta``: closes through ``t`` and the skip pushes the
    formation window strictly into the past; membership at ``t`` (knowable from
    ``effective_from``).
    """
    close = ctx.panel("close")
    returns = log_returns(close)
    mask = _member_mask(ctx, close.index, [str(c) for c in close.columns])
    mkt = market_return(returns, mask)
    out = residual_momentum(
        returns,
        mkt,
        lookback=int(spec.params["lookback"]),
        skip=int(spec.params["skip"]),
        beta_window=int(spec.params["beta_window"]),
        vol_span=int(spec.params["span"]),
    )
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


def _mom_res_spec(lookback: int, skip: int) -> FeatureSpec:
    """Single construction site for ``mom_res_*``.

    ``lookback_bars = beta_window + max(15*span, lookback)``: the deepest residual
    is ``eps_{t-lookback+1}`` (far edge of the skipped sum) and each residual needs a
    full beta window of returns behind it, while the EWMA sigma_eps needs the 15-span
    truncation headroom (:data:`~alphaforge.features.library.vol.EWMA_HEADROOM_SPANS`
    - dropped recursion weight ``e^-30``, error < 1e-12). Derived from params here
    (leakage finding 20).
    """
    beta_window = BETA_WINDOW
    span = EWMA_VOL_SPAN
    return FeatureSpec(
        name=f"mom_res_{lookback}_{skip}",
        family=Family.MOMENTUM,
        direction=1,  # positive = residual trend up = expected continuation
        cross_sectional=True,
        lookback_bars=beta_window + max(EWMA_HEADROOM_SPANS * span, lookback),
        params={
            "lookback": lookback,
            "skip": skip,
            "beta_window": beta_window,
            "span": span,
            "ewma_family": True,
        },
        fn=_mom_res_fn,
    )


@feature
def mom_res_2160_168() -> FeatureSpec:
    """90d residual momentum, 7d skip: ``Sum_{k=168}^{2159} eps_{t-k}/(sigma_eps*sqrt(1992))``."""
    return _mom_res_spec(2160, 168)
