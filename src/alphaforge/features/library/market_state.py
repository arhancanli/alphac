"""Market-state / beta factors (build slate Pod A, market-state leg).

The single registered factor here is the **betting-against-beta** signal
``beta_lowbeta_720`` (Frazzini-Pedersen 2014, adapted to crypto perps). It is a
NEW, slow, high-capacity alpha that is orthogonal *by construction* to the live
edges (funding carry + residual reversal): reversal only uses market beta as a
*nuisance* to strip out of returns, whereas this factor trades the beta itself.

Economics. Leverage-constrained participants (retail, most of crypto) cannot lever
a low-beta book to a target return, so they overweight high-beta "convex" alts and
bid them up; high beta therefore becomes negatively priced on a risk-adjusted
basis. The cross-sectional bet "long low-beta, short high-beta" earns the spread.
The factor value is the raw beta and ``direction = -1`` carries the sign (higher
beta => lower expected risk-adjusted return) - the ``fn`` never negates, matching
the library convention that the spec's ``direction`` owns the sign
(cf. :mod:`alphaforge.features.library.carry`).

Pipeline (per bar ``t`` on the complete-grid panel; gaps stay NaN, inputs never
mutated):

1. Market return - equal-weight over the point-in-time universe ``U_t`` via
   :func:`~alphaforge.features.library.mean_reversion.market_return` and the cached
   PIT membership mask ``_member_mask`` (same machinery as residual reversal, so
   the two share one ``universe_asof`` sweep semantics)::

       m_t = (1/N_t) Sum_{i in  U_t} r_{i,t}

2. Rolling beta over ``W_beta = BETA_WINDOW = 720`` bars (30d), strictly on returns
   **through t-1** (the conservative, leak-proof reading reused verbatim from
   :func:`~alphaforge.features.library.mean_reversion.rolling_beta`, which lags the
   window by one slot and NaNs a near-constant market)::

       beta_{i,t} = Cov_720(r_i, m) / Var_720(m)        # window ending t-1

The factor is ``beta_{i,t}`` itself. ``cross_sectional=True`` (winsorize + neutralize
+ z-score over the PIT universe before blending) and the build slate's mandatory
mitigation - neutralizing the low-beta sleeve against size/carry - is applied in
the downstream CS pipeline ``neutralize`` step, not here.

Why it survives costs (the gate the desk learned the hard way): a 30-day beta
ranking barely moves over the 72-bar (3-day) rebalance (rank-autocorrelation
~0.9), so turnover is the lowest in the slate and the edge amortizes its cost.

Lookback honesty (leakage finding 20): ``lookback_bars = BETA_WINDOW + 2 = 722``,
derived from params at the single factory site. ``rolling_beta`` consumes the
window of ``BETA_WINDOW`` returns ending at ``t-1`` (i.e. returns at indices
``t-720 .. t-1``); the oldest, a 1-bar log return at index ``t-720``, needs the
close at ``t-721``, so the factor reaches ``BETA_WINDOW + 1 = 721`` bars BACK
from ``t`` and therefore needs ``BETA_WINDOW + 2 = 722`` bars INCLUDING ``t``
(``lookback_bars`` counts the bar being valued, spec.py). Finite window => parity
atol = 0 (no EWMA recursion anywhere in this factor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaforge.features.context import long_series
from alphaforge.features.library.mean_reversion import (
    BETA_WINDOW,
    _member_mask,
    market_return,
    rolling_beta,
)
from alphaforge.features.library.vol import log_returns
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    import pandas as pd

    from alphaforge.features.context import FeatureContext

__all__ = [
    "beta_lowbeta_720",
]


def _beta_lowbeta_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``beta_lowbeta_720``: raw rolling market beta.

    ``beta_{i,t} = Cov_{Wbeta}(r_i, m) / Var_{Wbeta}(m)`` over the ``beta_window`` bars
    ending at ``t-1``, with ``m`` the equal-weight PIT-universe market return.
    Returned raw (no negation): ``direction = -1`` on the spec carries the
    low-beta sign, so the value is comparable to the reversal module's internal
    ``beta`` for cross-checking. Every input is available at the decision close
    ``t + Delta``: closes through ``t`` (the bar ``t`` return is *not* used - beta
    is lagged to ``t-1``), membership at ``t`` (knowable from ``effective_from``).

    NaN until the beta window is full of valid ``(r_i, m)`` pairs and NaN where the
    market variance is (numerically) zero - both inherited from ``rolling_beta``,
    so a gap never silently shrinks the window or bridges across missing bars.
    """
    close = ctx.panel("close")
    returns = log_returns(close)
    mask = _member_mask(ctx, close.index, [str(c) for c in close.columns])
    mkt = market_return(returns, mask)
    beta = rolling_beta(returns, mkt, window=int(spec.params["beta_window"]))
    return long_series(beta, name=spec.name)


@feature
def beta_lowbeta_720() -> FeatureSpec:
    """Betting-against-beta: raw 30d market beta, priced inversely (direction -1).

    ``lookback_bars = beta_window + 2 = 722``: the beta window of ``beta_window``
    returns ending ``t-1`` reaches back to the return at ``t-beta_window``, whose
    1-bar log ratio consumes the close at ``t-beta_window-1`` -- so the factor needs
    ``beta_window + 1`` bars of history before ``t`` plus the bar ``t`` itself
    (``lookback_bars`` counts the valued bar; finding 20: derived from params at
    this single site). Finite window => parity atol = 0.
    """
    beta_window = BETA_WINDOW
    return FeatureSpec(
        name="beta_lowbeta_720",
        family=Family.REGIME,
        direction=-1,  # higher beta => lower risk-adjusted expected return (BAB)
        cross_sectional=True,
        # beta uses returns t-beta_window..t-1; oldest return needs C_{t-beta_window-1};
        # +1 for that extra close, +1 for the bar t itself (counted in lookback_bars).
        lookback_bars=beta_window + 2,
        params={"beta_window": beta_window},
        fn=_beta_lowbeta_fn,
    )
