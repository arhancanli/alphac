"""Beta-residualized 1-month reversal for the US-equity sleeve (S6).

The institutionally credible short-term reversal. Plain 1-month reversal
(``eq_rev_21`` in :mod:`alphaforge.features.library.equity_price`) is dominated by
microstructure noise — bid-ask bounce, non-synchronous trading, the very effects the
literature shows are NOT capturable net of cost — and a raw winner/loser basket is
also a hidden market-beta bet (a name that fell because the whole market fell is not
an idiosyncratic loser). Stripping the market-beta exposure out of the return BEFORE
forming the reversal leaves the *residual* (idiosyncratic) return, whose 1-month
mean-reversion is the clean, replicated signal (cf. the crypto residual-reversal
``mr_res_*`` in :mod:`alphaforge.features.library.mean_reversion`).

This is the daily (D1 session) equity analogue of the crypto residual reversal, but
**finite-window** (no EWMA vol scaling): the equity price sleeve is finite-window
throughout (parity atol = 0; EQUITIES_SLEEVE.md §4), so this factor stays in that
contract. The pipeline, per decision bar ``t`` on the complete (session) grid (gaps
stay NaN, never bridged; inputs never mutated):

1. ``r_t = ln(C*_t / C*_{t-1})`` — daily log returns on the PIT split/total-return
   adjusted close panel (:func:`~alphaforge.features.library.equity_price._adjusted_close_panel`,
   the single-site adjustment; a 2:1 split must never print as a -50% return).

2. ``m_t`` — equal-weight PIT-universe daily market return and ``β_{i,t}`` — the SAME
   rolling 252-session market beta as ``eq_beta_252`` (the ``direction=0`` utility
   input), reusing :func:`~alphaforge.features.library.equity_price._market_beta`
   verbatim (which itself reuses the crypto ``market_return`` / ``rolling_beta`` /
   cached ``_member_mask``). Beta is strictly through ``t-1`` (conservative,
   leak-proof), so the residual is the exact object ``eq_beta_252`` describes.

3. Residual return ``ε_{i,t} = r_{i,t} - β_{i,t} · m_t``.

4. Reversal over the formation window ``W`` (21 sessions) — the NEGATED cumulative
   residual::

       REV_resid_W(i, t) = - Σ_{k=0}^{W-1} ε_{i,t-k}

   computed positionally as the prefix-independent ``W``-bar rolling sum
   (:func:`~alphaforge.features.library.vol._roll_sum`; ``min_periods = W`` — a gap
   anywhere in the window NaNs the output, never a shrunk sum). The negative sign
   makes **higher value ⇒ recent idiosyncratic loser ⇒ expected outperformer**
   (``direction=+1``), exactly the ``eq_rev_21`` / ``mr_res_*`` reversal sign
   convention; the body never relies on ``direction`` to flip it.

Registered ``eq_rev_resid_21`` (``direction=+1``, ``cross_sectional=True``). The CS
pipeline winsor→z-scores it within the PIT universe before blending.

EQUITY-SLEEVE OPT-IN (crypto byte-identical). This factor registers through the same
:func:`~alphaforge.features.registry.feature` decorator but is NOT added to any
crypto/default active-factor set; it runs on the EQUITY/D1 path and CANNOT compute
until the equity engine guard is lifted (``_adjusted_close_panel`` additionally fails
closed without a corporate-actions surface). The crypto compute path touches none of
this — no crypto factor body, window, or constant changes (parity unaffected).

Lookback honesty (leakage finding 20): ``lookback_bars = beta_window + window + 1``
(= 274). The reversal sum covers residuals ``ε_t … ε_{t-(W-1)}``; the OLDEST one,
``ε_{t-(W-1)}``, carries its own full ``β`` window. That beta is lagged through ``t-W``
and uses ``beta_window`` returns ending ``t-W``, whose oldest return
(``r_{t-W-beta_window+1}``) consumes the close ``C*_{t-W-beta_window}``. So the factor
reaches ``beta_window + W`` bars back from ``t`` — the formation window SHIFTS the beta
window back by ``W-1``; it does NOT vanish under the larger ``beta_window`` ⇒
``lookback_bars = beta_window + window + 1``. Finite window ⇒ parity atol = 0 (no EWMA
recursion anywhere).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.equity_price import _adjusted_close_panel, _market_beta
from alphaforge.features.library.mean_reversion import _member_mask, market_return
from alphaforge.features.library.vol import _roll_sum, log_returns
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "EQ_BETA_WINDOW",
    "eq_rev_resid_21",
    "residual_reversal_finite",
]

EQ_BETA_WINDOW: int = 252
"""Beta-residualization window in NYSE sessions (252 ~= 1 year), matching
``eq_beta_252`` — the same rolling-beta utility this factor residualizes against."""


def residual_reversal_finite(
    returns: pd.DataFrame,
    beta: pd.DataFrame,
    market: pd.Series,
    *,
    window: int,
) -> pd.DataFrame:
    """Finite-window beta-residual reversal (EQUITIES_SLEEVE.md §4, S6)::

        ε_{i,t}            = r_{i,t} - β_{i,t} · m_t                 # idiosyncratic return
        REV_resid_W(i, t)  = - Σ_{k=0}^{W-1} ε_{i,t-k}

    The market component is stripped FIRST (``ε = r - β·m``) so the reversal never
    fades the market itself, then the negated cumulative residual over ``window``
    sessions is the signal: positive ⇒ the asset's last ``W`` sessions underperformed
    its beta-implied return ⇒ expected to revert up (``direction=+1``; the body never
    relies on ``direction`` to flip the sign).

    ``β`` is supplied pre-computed (the SAME rolling beta as ``eq_beta_252``, lagged
    strictly through ``t-1``) so the residual is the exact object that utility
    describes. The ``W``-session sum requires ``W`` valid residuals
    (``min_periods = window`` via the prefix-independent
    :func:`~alphaforge.features.library.vol._roll_sum` — a gap anywhere in the window
    yields NaN, never a shrunk sum, never bridged across a missing bar). NO EWMA vol
    scaling: this is the finite-window equity contract (parity atol = 0), unlike the
    crypto ``residual_reversal``. Inputs are never mutated.

    Args:
        returns: wide float64 daily log-return panel on the complete session grid.
        beta: wide rolling-beta panel aligned to ``returns`` (``eq_beta_252``'s beta,
            already lagged through ``t-1``).
        market: equal-weight PIT-universe daily market return aligned to
            ``returns.index``.
        window: reversal formation window ``W`` in sessions (> 0).
    """
    if window <= 0:
        raise ValueError(f"residual_reversal_finite window must be > 0, got {window}")
    resid = returns.sub(beta.mul(market, axis=0))
    resid_sum = pd.DataFrame(
        _roll_sum(resid.to_numpy(dtype="float64"), window),
        index=returns.index,
        columns=returns.columns,
    )
    return -resid_sum


# -------------------------------------------------------------------- feature fns


def _eq_rev_resid_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_rev_resid_21`` — see :func:`residual_reversal_finite`.

    ``REV_resid_W(i,t) = -Σ_{k<W} ε_{i,t-k}`` with ``ε`` the residual of ``r_i``
    against the equal-weight PIT-universe daily market return and ``β`` estimated over
    ``beta_window`` sessions ending ``t-1`` (the SAME beta as ``eq_beta_252``, via
    :func:`~alphaforge.features.library.equity_price._market_beta`). Every input is
    available at the decision close ``t + Δ``: PIT adjusted closes through ``t`` (the
    bar-``t`` return enters the reversal sum but NOT the beta — beta is lagged to
    ``t-1``), membership at ``t`` (knowable from ``effective_from``).
    """
    adj_close = _adjusted_close_panel(ctx)
    returns = log_returns(adj_close)
    mask = _member_mask(ctx, adj_close.index, [str(c) for c in adj_close.columns])
    mkt = market_return(returns, mask)
    beta = _market_beta(ctx, adj_close, window=int(spec.params["beta_window"]))
    out = residual_reversal_finite(returns, beta, mkt, window=int(spec.params["window"]))
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


@feature
def eq_rev_resid_21() -> FeatureSpec:
    """Beta-residualized 1-month reversal: ``-Σ_{k<21} ε_{t-k}`` (21 sessions). direction +1, CS.

    The institutionally credible reversal — the idiosyncratic-return reversal after
    removing the 252-session market-beta exposure (``eq_beta_252``); plain
    ``eq_rev_21`` is microstructure-contaminated and a hidden beta bet.
    ``cross_sectional=True``: the CS pipeline winsor→z-scores within the PIT universe.
    ``lookback_bars = beta_window + window + 1 = 274`` (the oldest residual in the
    formation window carries its OWN full beta window, shifting the reach back by
    ``W-1`` — see module docstring). Finite window ⇒ parity atol = 0.

    EQUITY-sleeve opt-in: registered but NOT in any crypto/default active set; runs on
    the EQUITY/D1 path only (crypto byte-identical).
    """
    window = 21
    beta_window = EQ_BETA_WINDOW
    return FeatureSpec(
        name="eq_rev_resid_21",
        family=Family.REVERSAL,
        direction=1,  # higher = recent idiosyncratic loser = expected outperformer
        cross_sectional=True,
        # Deepest input: the beta of the OLDEST residual in the W-session reversal sum.
        # The sum covers eps_t..eps_{t-(W-1)}; eps_{t-(W-1)}'s beta (lagged through t-W)
        # uses beta_window returns ending t-W, whose oldest return consumes the close
        # C*_{t-W-beta_window}. So the factor reaches beta_window + W bars back from t
        # ⇒ lookback_bars = beta_window + window + 1 (the formation window SHIFTS the
        # beta window back by W-1; it does NOT vanish under beta_window).
        lookback_bars=beta_window + window + 1,
        params={"window": window, "beta_window": beta_window},
        fn=_eq_rev_resid_fn,
    )
