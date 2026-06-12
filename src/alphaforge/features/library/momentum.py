"""Momentum factors (alphaDesign.md §2.3).

Two families on the sanctioned complete-grid panel layout (gaps stay NaN — a log
ratio whose endpoints straddle a missing bar is NaN, never bridged; inputs are
never mutated):

* **Cross-sectional momentum with skip** ``mom_xs_{L}_{S}``: ``ln(C_{t-S}/C_{t-L})``.
  The skip removes the short-horizon reversal contaminating raw momentum. Tagged
  ``cross_sectional=True`` (raw values pass through the CS pipeline §3 before use);
  finite window — parity atol 0; needs exactly ``L + 1`` bars.
* **Time-series momentum (vol-normalized)** ``mom_ts_{L}``:
  ``ln(C_t/C_{t-L}) / (sigma_hat_t·sqrt(L))`` with sigma_hat =
  :func:`~alphaforge.features.library.vol.ewma_vol`
  (span 168) — approximately a t-stat of the trend, comparable across assets and
  time, hence ``cross_sectional=False`` (already vol-normalized). EWMA-family:
  ``lookback_bars = max(L + 1, 15·span)`` (the library's
  :data:`~alphaforge.features.library.vol.EWMA_HEADROOM_SPANS` convention —
  documented truncation error < 1e-12, buildabilityCritique.md §6.1), parity
  rtol 1e-9.

Registered: ``mom_xs_168_24`` (7d skip 1d), ``mom_xs_504_48`` (21d skip 2d — the
spec's anchor), ``mom_xs_2160_168`` (90d skip 7d); ``mom_ts_168``, ``mom_ts_504``,
``mom_ts_2160`` (same L set, no skip — TS momentum conventionally uses the full
window). All ``direction=+1``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import (
    EWMA_HEADROOM_SPANS,
    EWMA_VOL_SPAN,
    _log,
    ewma_vol,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    import pandas as pd

    from alphaforge.features.context import FeatureContext

__all__ = [
    "mom_ts_168",
    "mom_ts_504",
    "mom_ts_2160",
    "mom_xs_168_24",
    "mom_xs_504_48",
    "mom_xs_2160_168",
    "ts_momentum",
    "xs_momentum",
]


def xs_momentum(close: pd.DataFrame, *, lookback: int, skip: int) -> pd.DataFrame:
    """Cross-sectional momentum with skip (alphaDesign.md §2.3)::

        MOM_{L,S}(i,t) = ln( C_{i,t-S} / C_{i,t-L} )

    Computed positionally on the complete grid (``shift`` is an exact time op);
    NaN until ``L`` prior grid slots exist and NaN whenever either endpoint bar is
    missing — gaps are never bridged.
    """
    if lookback <= 0:
        raise ValueError(f"xs_momentum lookback must be > 0, got {lookback}")
    if not 0 <= skip < lookback:
        raise ValueError(
            f"xs_momentum requires 0 <= skip < lookback, got skip={skip}, L={lookback}"
        )
    return _log(close.shift(skip) / close.shift(lookback))


def ts_momentum(close: pd.DataFrame, *, lookback: int, vol: pd.DataFrame) -> pd.DataFrame:
    """Vol-normalized time-series momentum (alphaDesign.md §2.3)::

        TSMOM_L(i,t) = ln( C_{i,t} / C_{i,t-L} ) / ( sigma_hat_{i,t} · sqrt(L) )

    ``vol`` is the per-bar sigma_hat panel aligned to ``close`` (the registered specs use
    :func:`~alphaforge.features.library.vol.ewma_vol` span 168). The denominator
    is the L-bar vol forecast, so the statistic is approximately a t-stat of the
    trend. NaN where sigma_hat is NaN or zero (never ±inf) or either close endpoint is
    missing.
    """
    if lookback <= 0:
        raise ValueError(f"ts_momentum lookback must be > 0, got {lookback}")
    mom = _log(close / close.shift(lookback))
    return mom / (vol.where(vol > 0.0) * math.sqrt(lookback))


# -------------------------------------------------------------------- feature fns


def _mom_xs_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``mom_xs_{L}_{S}``: ``ln(C_{t-S}/C_{t-L})``.

    Pure function of closes available at the decision close ``t + Δ`` (both
    endpoints are strictly in the past); NaN until ``L + 1`` bars exist.
    """
    out = xs_momentum(
        ctx.panel("close"),
        lookback=int(spec.params["lookback"]),
        skip=int(spec.params["skip"]),
    )
    return long_series(out, name=spec.name)


def _mom_ts_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``mom_ts_{L}``: ``ln(C_t/C_{t-L}) / (sigma_hat_t·sqrt(L))``.

    sigma_hat = zero-mean EWMA vol of 1-bar log returns (span = ``params["span"]``,
    ``min_periods = span``). EWMA-family: values match the batch path to 1e-9
    relative under the ``lookback_bars >= 10·span`` truncation convention.
    """
    close = ctx.panel("close")
    sigma = ewma_vol(close, span=int(spec.params["span"]))
    out = ts_momentum(close, lookback=int(spec.params["lookback"]), vol=sigma)
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


def _xs_spec(lookback: int, skip: int) -> FeatureSpec:
    """Single construction site for ``mom_xs_*`` (lookback_bars derived: L + 1)."""
    return FeatureSpec(
        name=f"mom_xs_{lookback}_{skip}",
        family=Family.MOMENTUM,
        direction=1,
        cross_sectional=True,
        lookback_bars=lookback + 1,  # consumes C_{t-L} and the bar t itself
        params={"lookback": lookback, "skip": skip},
        fn=_mom_xs_fn,
    )


def _ts_spec(lookback: int) -> FeatureSpec:
    """Single construction site for ``mom_ts_*``.

    ``lookback_bars = max(L + 1, 15·span)``: the log-ratio needs ``L + 1`` bars,
    the EWMA sigma_hat needs the 15-span truncation headroom
    (:data:`~alphaforge.features.library.vol.EWMA_HEADROOM_SPANS` — dropped
    recursion weight ``e^-30``, documented truncation error < 1e-12) — whichever
    is larger.
    """
    span = EWMA_VOL_SPAN
    return FeatureSpec(
        name=f"mom_ts_{lookback}",
        family=Family.MOMENTUM,
        direction=1,
        cross_sectional=False,  # already vol-normalized => comparable as-is
        lookback_bars=max(lookback + 1, EWMA_HEADROOM_SPANS * span),
        params={"lookback": lookback, "span": span, "ewma_family": True},
        fn=_mom_ts_fn,
    )


@feature
def mom_xs_168_24() -> FeatureSpec:
    """7d momentum, 1d skip: ``ln(C_{t-24}/C_{t-168})``."""
    return _xs_spec(168, 24)


@feature
def mom_xs_504_48() -> FeatureSpec:
    """21d momentum, 2d skip (the spec's anchor): ``ln(C_{t-48}/C_{t-504})``."""
    return _xs_spec(504, 48)


@feature
def mom_xs_2160_168() -> FeatureSpec:
    """90d momentum, 7d skip: ``ln(C_{t-168}/C_{t-2160})``."""
    return _xs_spec(2160, 168)


@feature
def mom_ts_168() -> FeatureSpec:
    """7d vol-normalized TS momentum: ``ln(C_t/C_{t-168})/(sigma_hat_t·sqrt(168))``."""
    return _ts_spec(168)


@feature
def mom_ts_504() -> FeatureSpec:
    """21d vol-normalized TS momentum: ``ln(C_t/C_{t-504})/(sigma_hat_t·sqrt(504))``."""
    return _ts_spec(504)


@feature
def mom_ts_2160() -> FeatureSpec:
    """90d vol-normalized TS momentum: ``ln(C_t/C_{t-2160})/(sigma_hat_t·sqrt(2160))``."""
    return _ts_spec(2160)
