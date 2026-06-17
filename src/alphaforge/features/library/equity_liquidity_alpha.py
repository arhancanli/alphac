"""Illiquidity-premium alpha for the US-equity sleeve (S7).

A TRADEABLE (``direction=+1``) illiquidity factor, distinct from the ``direction=0``
Amihud *context* ``eq_amihud_63`` in :mod:`alphaforge.features.library.equity_price`.
It reuses the SAME Amihud (2002) machinery —
:func:`~alphaforge.features.library.liquidity.amihud_illiq`, ``ln(ILLIQ + eps)`` of
the mean ``|r| / dollar-volume`` over the window — on the PIT adjusted close + dollar
(``quote_volume``) volume, but registers it as a cross-sectional alpha: more illiquid
names (higher Amihud) are priced to earn a higher gross return (Amihud 1986/2002;
Pástor-Stambaugh 2003 liquidity risk), so ``direction=+1`` reads "higher illiquidity
⇒ higher expected return."

HONEST CAVEAT — the illiquidity premium is largely compensation-for-cost, not free
alpha. This is WHY the same number is exposed ``direction=0`` as ``eq_amihud_63``: the
desk's default stance (inherited from the crypto liquidity module) is that the
illiquidity premium is unreliable and conflicts with tradability. The premium that
shows up in *gross* (paper) returns is, to a large extent, the very transaction cost
the illiquidity measures — you earn the spread you also pay. Any sleeve weight on this
factor MUST be judged NET OF REALISTIC COST (effective spread + market impact +
borrow, with capacity/turnover constraints), not on the gross IC; a positive gross IC
here is the null hypothesis, not the discovery. It is registered as a candidate alpha
so the cost-aware backtest can adjudicate it, NOT because the gross signal is trusted.
The factor value is the raw Amihud illiquidity and ``direction=+1`` carries the sign —
the body never negates (library convention: the spec's ``direction`` owns the sign,
cf. :mod:`alphaforge.features.library.market_state`), so the raw value stays bit-for-bit
identical to the ``eq_amihud_63`` context (one shared body — the "context == alpha
input" invariant cannot drift, EQUITIES_CRITIQUE N3).

Pipeline (per decision bar ``t`` on the complete session grid; gaps stay NaN, inputs
never mutated): ``ILLIQ(i,t)`` = mean over valid bars in ``[t-W+1, t]`` of
``|r_{i,k}| / QV_{i,k}`` (bars with ``QV == 0`` or an undefined return skipped — the
standard Amihud "skip"), value ``= ln(ILLIQ + 1e-12)``, on the PIT
split/total-return-adjusted close (a 2:1 split must never inflate ``|r|``). Reduced
window-independently (parity atol = 0).

Registered ``eq_ilrev`` (the illiquidity-premium *reversal*-style cross-sectional
alpha; ``direction=+1``, ``cross_sectional=True``). The CS pipeline winsor→z-scores it
within the PIT universe before blending.

EQUITY-SLEEVE OPT-IN (crypto byte-identical). Registers through the same
:func:`~alphaforge.features.registry.feature` decorator but is NOT added to any
crypto/default active-factor set; it runs on the EQUITY/D1 path and CANNOT compute
until the equity engine guard lifts (the ``_adjusted_close_panel`` fail-closed gate
applies). The crypto compute path touches none of this — no crypto factor body,
window, or constant changes (parity unaffected).

Lookback honesty (leakage finding 20): ``lookback_bars = window + 1`` (the returns
inside Amihud need the previous close ``C*_{t-1}``), derived from params at the single
factory site. Finite window ⇒ parity atol = 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaforge.features.context import long_series
from alphaforge.features.library.equity_price import _adjusted_close_panel
from alphaforge.features.library.liquidity import amihud_illiq
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    import pandas as pd

    from alphaforge.features.context import FeatureContext

__all__ = [
    "ILREV_WINDOW",
    "eq_ilrev",
]

ILREV_WINDOW: int = 63
"""Amihud illiquidity window in NYSE sessions (~a quarter), matching ``eq_amihud_63``
— this alpha and that ``direction=0`` context share the SAME Amihud number/body, only
the ``direction`` (and ``cross_sectional``) differ."""


# -------------------------------------------------------------------- feature fns


def _eq_ilrev_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_ilrev``: Amihud illiquidity as a tradeable alpha.

    ``ln(ILLIQ + eps)`` of the mean ``|r| / QV`` over ``window`` sessions, reusing
    :func:`~alphaforge.features.library.liquidity.amihud_illiq` verbatim on the PIT
    adjusted close + dollar (``quote_volume``) volume — the EXACT body of the
    ``direction=0`` ``eq_amihud_63`` context, so the raw value is bit-identical (the
    "context == alpha input" invariant, EQUITIES_CRITIQUE N3). Returned raw (no
    negation): ``direction=+1`` on the spec carries the illiquidity-premium sign
    (higher illiquidity ⇒ higher expected GROSS return — judged net-of-cost
    downstream). Every input is available at the decision close ``t + Δ``: PIT
    adjusted closes through ``t`` and dollar volume through ``t``. NaN until
    ``window + 1`` bars exist (the returns need the previous close).
    """
    out = amihud_illiq(
        _adjusted_close_panel(ctx),
        ctx.panel("quote_volume"),
        window=int(spec.params["window"]),
    )
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


@feature
def eq_ilrev() -> FeatureSpec:
    """Illiquidity-premium alpha: Amihud ``ln(ILLIQ+eps)`` over 63 sessions. direction +1, CS.

    The TRADEABLE counterpart to the ``direction=0`` ``eq_amihud_63`` context — the
    SAME Amihud number priced as an alpha (more illiquid ⇒ higher expected gross
    return). HONEST CAVEAT: the illiquidity premium is largely compensation-for-cost
    and a positive gross IC is the null, not the discovery — this factor MUST be
    judged net of realistic cost (see module docstring). ``cross_sectional=True``: the
    CS pipeline winsor→z-scores within the PIT universe. ``lookback_bars = window + 1 =
    64`` (the returns need ``C*_{t-1}``). Finite window ⇒ parity atol = 0.

    EQUITY-sleeve opt-in: registered but NOT in any crypto/default active set; runs on
    the EQUITY/D1 path only (crypto byte-identical).
    """
    window = ILREV_WINDOW
    return FeatureSpec(
        name="eq_ilrev",
        family=Family.LIQUIDITY,
        direction=1,  # higher illiquidity => higher expected GROSS return (judge net-of-cost)
        cross_sectional=True,
        lookback_bars=window + 1,  # Amihud returns need C*_{t-1}
        params={"window": window},
        fn=_eq_ilrev_fn,
    )
