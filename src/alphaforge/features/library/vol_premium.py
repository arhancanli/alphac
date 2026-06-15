"""Volatility-premium factors (BUILD SLATE Pod C) -- the low-volatility anomaly
``lowvol_720`` and the downside/upside semivariance asymmetry ``semivar_skew_504``.

Both are cross-sectional alphas derived purely from OHLCV on the sanctioned
complete-grid panel layout (gaps stay NaN -- never bridged; inputs never mutated). They
trade *volatility composition*, which is orthogonal to the live carry and reversal
edges (those trade funding level and net price direction respectively):

* ``lowvol_720`` -- the low-volatility anomaly. Leverage-constrained investors overpay
  for high-vol "lottery" names (exceptionally strong in crypto, where retail crowds
  high-vol alts), so low realized vol earns a risk-adjusted premium. Signal is
  ``- ln(sigma_YZ,720 + eps)`` (per-bar Yang-Zhang sigma over 30d): higher value =>
  lower vol => higher expected forward return, hence ``direction=+1``. The ``ln`` tames
  heavy-tailed vol before the CS winsorize/z-score. A 30d window makes the ranking
  persistent across the 3-day rebalance (lowest turnover / highest capacity in the vol
  family). NOTE for the desk: low-vol crypto names are often large-caps with low
  funding, so this CAN be a hidden short-carry/size bet -- the slate mandates
  neutralizing the processed factor against ``carry_fund_21`` (and optionally
  ``adv_quote_30d`` log-size) in the CS pipeline before it enters the blend. This module
  ships the RAW factor; neutralization is a pipeline step, not a factor-body change.

* ``semivar_skew_504`` -- realized downside/upside semivariance asymmetry (21d).
  Decompose realized variance by the sign of the contributing 1h return::

      RS_down = sum_{r<0} r^2,   RS_up = sum_{r>0} r^2          # over W = 504 returns
      SKEW    = (RS_up - RS_down) / (RS_up + RS_down)   in [-1, +1]

  "Bad volatility" (downside-dominated realized variance, SKEW < 0) commands a discount
  and mean-reverts (Barndorff-Nielsen signed-jump / Bollerslev). The sign decomposition
  makes it orthogonal to symmetric vol (``lowvol_720``, sign-blind) and to reversal
  (variance *composition*, not net direction). Bounded [-1, 1] => naturally stable, low
  turnover at the 21d window. ``direction=+1`` is the PRIOR (an upside-dominated name is
  expected to outperform); the slate flags the sign as a one-character change to be
  CONFIRMED by RankIC before commit -- the academic compensation sign is the opposite
  of the crowding/mean-reversion sign, so if standalone IC disagrees with
  ``direction=+1``, flip ``direction`` (not the body) and re-run.

Both are finite-window (parity atol = 0). ``lowvol_720`` inherits Yang-Zhang's
``window + 1`` requirement (it consumes ``C_{t-1}``) => ``lookback_bars = 721``.
``semivar_skew_504`` consumes ``W`` 1h log returns, each needing a previous close, so
the first finite value sits at ``W + 1`` bars => ``lookback_bars = 505``. Lookback is
derived from params at the single spec-factory site (leakage finding 20).

Registered: ``lowvol_720``, ``semivar_skew_504``. Both ``family=VOLATILITY``,
``direction=+1``, ``cross_sectional=True``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import (
    _roll_sum,
    log_returns,
    yang_zhang,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "LOWVOL_EPS",
    "lowvol_720",
    "semivar_skew_504",
    "semivariance_skew",
]

LOWVOL_EPS: float = 1e-12
"""Additive floor inside the ``- ln(sigma + eps)`` of ``lowvol_720``.

A genuinely zero per-bar Yang-Zhang sigma (a perfectly flat 30d window) is already a
degenerate, non-tradeable name; the eps keeps the log finite (a large positive factor
value) instead of producing ``-inf``, and the downstream CS winsorizer caps it. NaN
sigma (insufficient/gapped history) still propagates to NaN through the log.
"""


def semivariance_skew(close: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Realized downside/upside semivariance asymmetry over ``window`` 1h returns.

    Formula::

        r_t      = ln(C_t / C_{t-1})
        RS_down  = sum_{k=0..W-1} r_{t-k}^2 * 1{r_{t-k} < 0}
        RS_up    = sum_{k=0..W-1} r_{t-k}^2 * 1{r_{t-k} > 0}
        SKEW(t)  = (RS_up - RS_down) / (RS_up + RS_down)         in [-1, +1]

    The two masked-and-squared return panels are summed with the prefix-independent
    :func:`~alphaforge.features.library.vol._roll_sum` (``min_periods = window`` -- any
    gap inside the window yields NaN, never bridged). The denominator is the realized
    variance over the window (modulo the ``1/W`` constant, which cancels); it is NaN
    (never +/-inf) where the total is non-positive -- i.e. an all-flat / fully-gapped
    window. Inputs are never mutated.
    """
    if window < 1:
        raise ValueError(f"semivariance_skew window must be >= 1, got {window}")
    r = log_returns(close).to_numpy(dtype="float64")
    sq = r * r
    # NaN returns (gaps) must poison the window: keep them NaN in BOTH legs so the
    # _roll_sum (which NaN-propagates) yields NaN, never a silently shorter sum.
    down_sq = np.where(r < 0.0, sq, np.where(np.isnan(r), np.nan, 0.0))
    up_sq = np.where(r > 0.0, sq, np.where(np.isnan(r), np.nan, 0.0))
    rs_down = _roll_sum(down_sq, window)
    rs_up = _roll_sum(up_sq, window)
    total = rs_up + rs_down
    with np.errstate(invalid="ignore", divide="ignore"):
        skew = np.where(total > 0.0, (rs_up - rs_down) / total, np.nan)
    return pd.DataFrame(skew, index=close.index, columns=close.columns)


# -------------------------------------------------------------------- feature fns


def _lowvol_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``lowvol_720``: ``- ln(sigma_YZ,window + eps)``.

    sigma is the per-bar (un-annualized) Yang-Zhang OHLC vol over ``params["window"]``
    bars; the annualization constant is irrelevant (a monotone CS transform), so it is
    omitted. ``- ln`` makes higher value => lower vol => higher expected forward
    return. Pure function of bars available at the decision close ``t + Delta``; NaN
    until ``window + 1`` bars exist (Yang-Zhang consumes ``C_{t-1}``).
    """
    window = int(spec.params["window"])
    sigma = yang_zhang(
        ctx.panel("open"),
        ctx.panel("high"),
        ctx.panel("low"),
        ctx.panel("close"),
        window=window,
        annualize=False,
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        values = -np.log(sigma.to_numpy(dtype="float64") + LOWVOL_EPS)
    out = pd.DataFrame(values, index=sigma.index, columns=sigma.columns)
    return long_series(out, name=spec.name)


def _semivar_skew_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``semivar_skew_504``: ``(RS_up - RS_down)/(RS_up + RS_down)``.

    See :func:`semivariance_skew`. Pure function of the ``window`` 1h log returns ending
    at the decision close ``t + Delta``; NaN until ``window + 1`` bars exist and NaN on
    an all-flat / fully-gapped window.
    """
    out = semivariance_skew(ctx.panel("close"), window=int(spec.params["window"]))
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


@feature
def lowvol_720() -> FeatureSpec:
    """Low-volatility anomaly: ``- ln(sigma_YZ,720 + eps)`` (30d). direction +1, CS.

    ``lookback_bars = window + 1 = 721`` (Yang-Zhang consumes ``C_{t-1}``); finite
    window, parity atol = 0.
    """
    window = 720
    return FeatureSpec(
        name="lowvol_720",
        family=Family.VOLATILITY,
        direction=+1,  # -ln(sigma): lower vol => higher expected forward return
        cross_sectional=True,
        lookback_bars=window + 1,  # YZ consumes C_{t-1}
        params={"window": window},
        fn=_lowvol_fn,
    )


@feature
def semivar_skew_504() -> FeatureSpec:
    """Downside/upside semivariance asymmetry over 504 1h returns (21d). direction +1, CS.

    ``lookback_bars = window + 1 = 505`` (each 1h return consumes a previous close);
    finite window, parity atol = 0. ``direction=+1`` is the prior -- confirm the sign
    by RankIC before commit (module docstring).
    """
    window = 504
    return FeatureSpec(
        name="semivar_skew_504",
        family=Family.VOLATILITY,
        direction=+1,  # prior: upside-dominated name expected to outperform (confirm via IC)
        cross_sectional=True,
        lookback_bars=window + 1,  # each 1h log return consumes a previous close
        params={"window": window},
        fn=_semivar_skew_fn,
    )
