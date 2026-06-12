"""Regime features (alphaDesign.md §2.7) — vol percentile, BTC correlation, breadth.

Time-series context features: ``reg_rvp_720``, ``reg_breadth_sma720`` and
``reg_breadth_mom168`` are BROADCAST (one market-level value per timestamp, repeated
for every requested instrument so the output honors the long ``(ts_open,
instrument_id)`` contract); ``reg_corr_btc_720`` is per-symbol. All are
``direction=0`` and ``cross_sectional=False`` (excluded from CS z-scoring; fed raw
to the ML feature matrix and the HMM observation builder).

BTC-anchor assumption (documented): the "market" is ``BINANCE:PERP:BTCUSDT``. The
design text says BTC/USDT spot, but the v1 lake is perp-only and the perp tracks
spot to within funding-rate basis points at the horizons used here (720-bar vol /
correlation windows), so the perp serves as the market proxy. The anchor id is a
spec param — a future spot lake changes one string, not the formulas. Anchor data
must be REQUESTED: the engine only loads ``instrument_ids`` into the context, so
anchor-dependent features raise ``ValueError`` if the anchor is not among them
(fail loud — an all-NaN regime column would silently poison the ML matrix).

Breadth universes are point-in-time (:meth:`FeatureContext.universe_asof` at each
bar open ``t`` — the design's ``U_t``; intervals are knowable from
``effective_from``, never today's listing set applied historically). Members not
present in the requested ``instrument_ids`` are excluded from numerator AND
denominator; callers must request a superset of the universe for exact breadth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import (
    _log,
    _roll_mean,
    _roll_sum,
    log_returns,
    yang_zhang,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "BTC_ANCHOR",
    "reg_breadth_mom168",
    "reg_breadth_sma720",
    "reg_corr_btc_720",
    "reg_rvp_720",
]

BTC_ANCHOR: Final[str] = "BINANCE:PERP:BTCUSDT"
"""The market anchor (perp as market proxy — see module docstring)."""


def _require_anchor(ctx: FeatureContext, spec: FeatureSpec) -> str:
    """The anchor instrument id, validated to be in the context (fail loud)."""
    anchor = str(spec.params["anchor"])
    if anchor not in ctx.instrument_ids:
        raise ValueError(
            f"feature {spec.name!r} needs anchor {anchor!r} in the requested "
            f"instrument_ids (the engine only loads requested instruments)"
        )
    return anchor


def _broadcast(ctx: FeatureContext, series: pd.Series, name: str) -> pd.Series:
    """Repeat a market-level time series for every requested instrument."""
    wide = pd.DataFrame(
        dict.fromkeys(ctx.instrument_ids, series),
        index=series.index,
    )
    wide.index.name = "ts_open"
    wide.columns.name = "instrument_id"
    return long_series(wide, name=name)


def _membership_mask(ctx: FeatureContext, index: pd.Index) -> pd.DataFrame:
    """Boolean (ts_open x instrument_id) frame of PIT universe membership.

    Row ``t`` is :meth:`FeatureContext.universe_asof` at the bar open ``t``
    (the design's ``U_t``), restricted to the requested instruments.
    """
    ids = list(ctx.instrument_ids)
    values = np.zeros((len(index), len(ids)), dtype=bool)
    for i, ts in enumerate(index):
        members = ctx.universe_asof(int(ts))
        for j, iid in enumerate(ids):
            values[i, j] = iid in members
    return pd.DataFrame(values, index=index, columns=pd.Index(ids))


def _breadth(ctx: FeatureContext, indicator: pd.DataFrame, name: str) -> pd.Series:
    """Share of PIT universe members whose indicator is 1.

    ``indicator`` is a float panel with values in {0.0, 1.0} and NaN where the
    underlying statistic is undefined (warmup / gaps). Non-members and undefined
    members are excluded from numerator AND denominator (the same fail-closed
    mask-before-stats rule the CS pipeline uses); NaN when no member has a
    defined indicator (including an empty universe).
    """
    mask = _membership_mask(ctx, indicator.index)
    share = indicator.where(mask).mean(axis=1)
    return _broadcast(ctx, share, name)


# -------------------------------------------------------------------- feature fns


def _reg_rvp_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``reg_rvp_720`` — realized-vol percentile of the anchor.

    Formula (alphaDesign.md §2.7), with ``sigma_t`` = annualized Yang-Zhang vol of the
    BTC anchor over ``n = params["vol_window"]`` bars (exact estimator:
    :func:`alphaforge.features.library.vol.yang_zhang`) and
    ``N = params["percentile_window"]``::

        RVP_t = (1/N) Σ_{k=0}^{N-1} 1{ sigma_{t-k} <= sigma_t }        # N = 8760 (1y)

    Implemented as a rolling rank (``method="max"`` counts ties as <=, matching the
    indicator; ``pct=True`` divides by N) with STRICT ``min_periods = N`` — the
    percentile of an incomplete year is not the statistic above. RVP in  (0, 1]
    (the k = 0 term always counts). Broadcast to all requested instruments.
    """
    anchor = _require_anchor(ctx, spec)
    n = int(spec.params["vol_window"])
    pct_window = int(spec.params["percentile_window"])
    cols = [anchor]
    sigma = yang_zhang(
        ctx.panel("open")[cols],
        ctx.panel("high")[cols],
        ctx.panel("low")[cols],
        ctx.panel("close")[cols],
        window=n,
        annualize=True,
    )[anchor]
    rvp = sigma.rolling(pct_window, min_periods=pct_window).rank(method="max", pct=True)
    return _broadcast(ctx, rvp, spec.name)


def _reg_corr_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``reg_corr_btc_720`` — rolling correlation vs the anchor.

    Formula (alphaDesign.md §2.7), per symbol ``i`` with 1h log returns ``r``
    (positional on the complete grid — gaps are NaN, never bridged) and
    ``W = params["window"]``::

        CORR_BTC(i, t) = corr_W( r_i, r_BTC )          # Pearson, trailing W bars

    The anchor's own column is set to exactly 1.0 wherever its trailing window
    holds ``W`` valid returns (and NaN otherwise) — by definition, and avoiding
    the 0/0 ambiguity of self-correlation under zero variance.

    Windows are reduced independently from their own contents via the
    computational form (prefix-independent ``_roll_sum``; a streaming pandas
    ``rolling(...).corr`` would break the atol = 0 parity contract)::

        corr = ( Σxy - Σx·Σy/n ) / sqrt( (Σx² - (Σx)²/n) · (Σy² - (Σy)²/n) )

    Strict windows: a NaN in EITHER series inside the window makes ``Σxy`` NaN
    and therefore the correlation NaN (``min_periods = window`` semantics; gaps
    are never bridged). Zero variance on either side => NaN (undefined).
    """
    anchor = _require_anchor(ctx, spec)
    window = int(spec.params["window"])
    returns = log_returns(ctx.panel("close"))
    x = returns.to_numpy(dtype="float64")
    y = returns[anchor].to_numpy(dtype="float64")[:, np.newaxis]
    n = float(window)
    sx = _roll_sum(x, window)
    sy = _roll_sum(y, window)
    sxy = _roll_sum(x * y, window)
    sxx = _roll_sum(x * x, window)
    syy = _roll_sum(y * y, window)
    cov = sxy - sx * sy / n
    var_x = np.maximum(sxx - sx * sx / n, 0.0)  # NaN-preserving cancellation clamp
    var_y = np.maximum(syy - sy * sy / n, 0.0)
    denom_sq = var_x * var_y
    with np.errstate(invalid="ignore", divide="ignore"):
        values = np.where(denom_sq > 0.0, cov / np.sqrt(denom_sq), np.nan)
    corr = pd.DataFrame(values, index=returns.index, columns=returns.columns)
    n_valid = _roll_sum((~np.isnan(y)).astype("float64"), window)[:, 0]
    corr[anchor] = np.where(n_valid == n, 1.0, np.nan)
    return long_series(corr[list(ctx.instrument_ids)], name=spec.name)


def _reg_breadth_sma_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``reg_breadth_sma{n}``.

    Formula (alphaDesign.md §2.7), over the PIT universe ``U_t`` with
    ``n = params["window"]``::

        BREADTH_SMA_t = (1/|U_t|) Σ_{iin U_t} 1{ C_{i,t} > SMA_n(C_i)_t }

    SMA is strict (``min_periods = n``) and reduced per-window
    (prefix-independent ``_roll_mean`` — a streaming mean's last-ulp drift could
    flip the indicator on a knife-edge close and break atol = 0 parity); members
    with an undefined indicator are excluded from numerator and denominator
    (see :func:`_breadth`). Broadcast.
    """
    window = int(spec.params["window"])
    close = ctx.panel("close")
    sma = pd.DataFrame(
        _roll_mean(close.to_numpy(dtype="float64"), window),
        index=close.index,
        columns=close.columns,
    )
    defined = close.notna() & sma.notna()
    indicator = pd.DataFrame(
        np.where(defined.to_numpy(), (close > sma).to_numpy(), np.nan),
        index=close.index,
        columns=close.columns,
    )
    return _breadth(ctx, indicator, spec.name)


def _reg_breadth_mom_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``reg_breadth_mom{n}``.

    Formula (alphaDesign.md §2.7), over the PIT universe ``U_t`` with
    ``n = params["window"]``::

        BREADTH_MOM_t = (1/|U_t|) Σ_{iin U_t} 1{ ln(C_{i,t} / C_{i,t-n}) > 0 }

    The n-bar log return is positional on the complete grid (NaN across gaps);
    undefined members are excluded from both sides of the fraction. Broadcast.
    """
    window = int(spec.params["window"])
    close = ctx.panel("close")
    log_ret = _log(close / close.shift(window))
    defined = log_ret.notna()
    indicator = pd.DataFrame(
        np.where(defined.to_numpy(), (log_ret > 0.0).to_numpy(), np.nan),
        index=close.index,
        columns=close.columns,
    )
    return _breadth(ctx, indicator, spec.name)


# ------------------------------------------------------------------- registrations


@feature
def reg_rvp_720() -> FeatureSpec:
    """Realized-vol percentile of the BTC anchor (YZ 720 within trailing 8760).

    Lookback derivation: the oldest of the ``N`` percentile slots is at
    ``t - (N - 1)``; its Yang-Zhang estimate needs ``vol_window + 1`` bars
    (it consumes ``C_{t-1}``) => ``(N - 1) + vol_window + 1 = N + vol_window``.
    """
    vol_window, pct_window = 720, 8760
    return FeatureSpec(
        name="reg_rvp_720",
        family=Family.REGIME,
        direction=0,
        cross_sectional=False,
        lookback_bars=pct_window + vol_window,
        params={
            "anchor": BTC_ANCHOR,
            "vol_window": vol_window,
            "percentile_window": pct_window,
        },
        fn=_reg_rvp_fn,
    )


@feature
def reg_corr_btc_720() -> FeatureSpec:
    """Per-symbol 720-bar correlation of 1h returns vs the BTC anchor.

    Lookback = ``window + 1``: ``window`` returns need ``window + 1`` closes.
    """
    window = 720
    return FeatureSpec(
        name="reg_corr_btc_720",
        family=Family.REGIME,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + 1,
        params={"anchor": BTC_ANCHOR, "window": window},
        fn=_reg_corr_fn,
    )


@feature
def reg_breadth_sma720() -> FeatureSpec:
    """Share of PIT universe members above their 720-bar SMA (lookback = window)."""
    window = 720
    return FeatureSpec(
        name="reg_breadth_sma720",
        family=Family.REGIME,
        direction=0,
        cross_sectional=False,
        lookback_bars=window,
        params={"window": window},
        fn=_reg_breadth_sma_fn,
    )


@feature
def reg_breadth_mom168() -> FeatureSpec:
    """Share of PIT universe members with a positive 168-bar log return.

    Lookback = ``window + 1``: the return needs ``C_{t-window}``.
    """
    window = 168
    return FeatureSpec(
        name="reg_breadth_mom168",
        family=Family.REGIME,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + 1,
        params={"window": window},
        fn=_reg_breadth_mom_fn,
    )
