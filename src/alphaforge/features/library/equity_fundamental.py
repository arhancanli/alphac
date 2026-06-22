"""Equity VALUE + QUALITY factors from the point-in-time fundamentals lake (Phase F2).

The genuinely DECORRELATED factor families after price-only momentum proved a ~zero-edge
null (net Sharpe 0.05; price factors are all correlated transforms of returns). These read
the :data:`~alphaforge.data.schemas.Dataset.FUNDAMENTALS` table through the PIT chokepoint
:meth:`~alphaforge.features.context.FeatureContext.fundamentals_asof_join`, so a factor at
decision close ``t`` uses ONLY quarters with ``available_at <= t`` (a quarter is unknowable
until its SEC filing) — the fundamentals analogue of the funding/corporate-action finding-18
discipline.

Two reduction kernels (both PIT, computed on the SPARSE quarterly frame BEFORE the as-of
merge so the prefix-independent finite-window parity holds, atol=0):

* **TTM (trailing twelve months)** for FLOW items (revenues, net_income, gross_profit,
  operating_income, cost_of_revenue): the rolling sum of the last 4 reported quarters,
  ``NaN`` until 4 exist OR if any of the 4 is null (numpy sum propagates NaN — "all 4
  required"). TTM removes fiscal seasonality; a single quarter's flow is noisy.
* **latest** for STOCK items (equity, assets, diluted_shares): the most recent reported
  quarter (balance-sheet stocks are point-in-time, not summed). ``diluted_shares`` is
  forward-filled to the last POSITIVE value first (19% of rows are null — the
  ingest-nulled garbage from Polygon's derived-Q4 — and shares change slowly).

Market cap is built PIT at feature time: ``mcap = C*_t x shares_ff`` where ``C*`` is the
SPLIT-ONLY adjusted close (:func:`~alphaforge.features.library.equity_price._adjusted_close_panel`
— price and the filed share count must be on the same split basis) and ``shares_ff`` is the
forward-filled diluted share count. It is never stored. Every value ratio (E/P, B/P, S/P) is
a cross-sectional z-scored rank, so the absolute mcap level is irrelevant — only the
cross-name ordering matters.

Crypto byte-identity: a perp book has no fundamentals partitions, so ``ctx.fundamentals()``
is empty and every factor here is all-NaN — it never perturbs a crypto factor (the crypto
signal path selects crypto specs by name; these eq_* specs are equity-only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.equity_price import _adjusted_close_panel
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "eq_asset_growth",
    "eq_book_to_price",
    "eq_earnings_yield",
    "eq_gross_profitability",
    "eq_operating_margin",
    "eq_quality_composite",
    "eq_roe",
    "eq_sales_to_price",
    "eq_value_composite",
]

_TTM_QUARTERS: Final[int] = 4
"""Trailing-twelve-month window in reported quarters (the flow-item smoother)."""

_SESSIONS_PER_QUARTER: Final[int] = 63
"""≈ XNYS sessions in a fiscal quarter (252/4) — sizes the lookback only."""

_RECENCY_SESSIONS: Final[int] = 170
"""Max filing-recency reach in sessions (~236 calendar-day worst-case filing lag). With the
TTM span it sizes ``lookback_bars`` so compute_asof's minimal window contains the 4 knowable
quarters (verified by the truncation harness)."""

#: lookback the as-of join + TTM need: (TTM+1) quarters of sessions + the filing-recency
#: reach + the bar itself (finding 20: derived from params at the single factory site).
_LOOKBACK_BARS: Final[int] = (_TTM_QUARTERS + 1) * _SESSIONS_PER_QUARTER + _RECENCY_SESSIONS + 1

_FLOW_TTM: Final[tuple[str, ...]] = (
    "revenues",
    "net_income",
    "gross_profit",
    "operating_income",
    "cost_of_revenue",
)
"""Flow line items reduced by TTM (summed); stocks (equity/assets/diluted_shares) are not."""


def _ttm(col: str) -> str:
    """TTM column name for a flow item (``revenues`` -> ``ttm_revenues``)."""
    return f"ttm_{col}"


def _grid_index(ctx: FeatureContext) -> pd.MultiIndex:
    """The canonical (ts_open, instrument_id) MultiIndex over the full bar grid.

    Derived from the split-only adjusted-close panel so every fundamental factor shares the
    SAME index the price factors produce (long_series' Cartesian product), and so the
    fail-closed corporate-actions guard runs for fundamentals too."""
    return cast("pd.MultiIndex", long_series(_adjusted_close_panel(ctx)).index)


def _trailing_sum_by_instrument(frame: pd.DataFrame, col: str, k: int) -> pd.Series:
    """Strict trailing-``k`` SUM of ``col`` per instrument, prefix-independent (atol=0).

    ``frame`` must be sorted by ``(instrument_id, period_end)``. Each output sums ONLY its
    own ``k`` quarters (numpy ``sliding_window_view``), never a streaming accumulator (which
    would carry last-ulp state from rows before the window and break finite-window parity —
    the same discipline as :func:`alphaforge.features.library.carry._trailing_mean_by_instrument`).
    ``NaN`` until ``k`` quarters exist AND if any quarter in the window is null (numpy sum
    propagates NaN — exactly the "all 4 trailing quarters required" rule).
    """
    vals = frame[col].to_numpy(dtype="float64")
    out = np.full(len(frame), np.nan, dtype="float64")
    for positions in frame.groupby("instrument_id", sort=False).indices.values():
        if len(positions) >= k:
            view = np.lib.stride_tricks.sliding_window_view(vals[positions], k)
            out[positions[k - 1 :]] = view.sum(axis=-1)
    return pd.Series(out, index=frame.index, dtype="float64")


def _ffill_positive_by_instrument(frame: pd.DataFrame, col: str) -> pd.Series:
    """Forward-fill the last POSITIVE value of ``col`` per instrument (for diluted_shares).

    A share count is a slow-moving stock; the latest filed quarter may carry a null (the
    ingest-nulled derived-Q4 garbage), so the as-of value should be the most recent strictly
    positive count. ``frame`` sorted by ``(instrument_id, period_end)``; NaN until the first
    positive value. Prefix-independent (each instrument scanned in isolation)."""
    vals = frame[col].to_numpy(dtype="float64")
    out = np.full(len(frame), np.nan, dtype="float64")
    for positions in frame.groupby("instrument_id", sort=False).indices.values():
        last = np.nan
        for p in positions:
            v = vals[p]
            if np.isfinite(v) and v > 0.0:
                last = v
            out[p] = last
    return pd.Series(out, index=frame.index, dtype="float64")


def _fundamental_frame(ctx: FeatureContext) -> pd.DataFrame:
    """The sparse quarterly fundamentals frame enriched with TTM-flow + forward-filled-share
    columns, sorted by ``(instrument_id, period_end)`` — the PIT source for every as-of join.

    Empty (crypto / no fundamentals) returns the empty frame unchanged; the factor bodies
    then yield all-NaN through the as-of join."""
    f = ctx.fundamentals()
    if f.empty:
        return f
    f = f.sort_values(["instrument_id", "period_end"], kind="stable").reset_index(drop=True)
    for col in _FLOW_TTM:
        f[_ttm(col)] = _trailing_sum_by_instrument(f, col, _TTM_QUARTERS)
    f["shares_ff"] = _ffill_positive_by_instrument(f, "diluted_shares")
    return f


def _market_cap(ctx: FeatureContext, frame: pd.DataFrame) -> pd.Series:
    """PIT market cap long-series ``C*_t x shares_ff`` over the canonical (ts_open, id) grid.

    ``C*`` is the split-only adjusted close (the fail-closed sanctioned panel); ``shares_ff``
    is the forward-filled-positive diluted share count as-of each decision. NaN where the
    price or the share count is unknown. Non-positive mcap is left as-is here; ratio bodies
    guard ``mcap > 0``."""
    px = _adjusted_close_panel(ctx)
    px_long = long_series(px)
    shares = ctx.fundamentals_asof_join(
        cast("pd.MultiIndex", px_long.index), column="shares_ff", frame=frame
    )
    return px_long * shares


def _value_ratio(ctx: FeatureContext, numerator_col: str, name: str) -> pd.Series:
    """``numerator / market_cap`` (E/P, S/P): numerator is a TTM-flow as-of column."""
    frame = _fundamental_frame(ctx)
    idx = _grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=name)
    mcap = _market_cap(ctx, frame)
    num = ctx.fundamentals_asof_join(idx, column=numerator_col, frame=frame)
    out = num.to_numpy(dtype="float64") / mcap.to_numpy(dtype="float64")
    out[~(mcap.to_numpy(dtype="float64") > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=name)


# --------------------------------------------------------------- feature fns (bodies)


def _eq_earnings_yield_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """E/P = TTM net income / market cap (the canonical value factor)."""
    return _value_ratio(ctx, _ttm("net_income"), spec.name)


def _eq_sales_to_price_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """S/P = TTM revenues / market cap."""
    return _value_ratio(ctx, _ttm("revenues"), spec.name)


def _eq_book_to_price_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """B/P = latest shareholders' equity / market cap; NaN where equity <= 0 (negative book
    value is not a meaningful value signal — distressed/buyback firms)."""
    frame = _fundamental_frame(ctx)
    idx = _grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    mcap = _market_cap(ctx, frame).to_numpy(dtype="float64")
    equity = ctx.fundamentals_asof_join(idx, column="equity", frame=frame).to_numpy(dtype="float64")
    out = equity / mcap
    out[~(mcap > 0.0) | ~(equity > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


def _eq_gross_profitability_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Gross profitability = TTM gross profit / total assets (Novy-Marx 2013).

    Gross profit prefers the reported TTM ``gross_profit``; where a filing omits it (66%
    coverage) it coalesces to ``TTM revenues - TTM cost_of_revenue`` (defensive — recovers
    little in the current lake but is the correct fallback). NaN where assets <= 0."""
    frame = _fundamental_frame(ctx)
    idx = _grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    gp = ctx.fundamentals_asof_join(idx, column=_ttm("gross_profit"), frame=frame).to_numpy(
        dtype="float64"
    )
    rev = ctx.fundamentals_asof_join(idx, column=_ttm("revenues"), frame=frame).to_numpy(
        dtype="float64"
    )
    cogs = ctx.fundamentals_asof_join(idx, column=_ttm("cost_of_revenue"), frame=frame).to_numpy(
        dtype="float64"
    )
    coalesced = np.where(np.isfinite(gp), gp, rev - cogs)
    assets = ctx.fundamentals_asof_join(idx, column="assets", frame=frame).to_numpy(dtype="float64")
    out = coalesced / assets
    out[~(assets > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


def _eq_roe_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """ROE = TTM net income / latest equity; NaN where equity <= 0."""
    frame = _fundamental_frame(ctx)
    idx = _grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    ni = ctx.fundamentals_asof_join(idx, column=_ttm("net_income"), frame=frame).to_numpy(
        dtype="float64"
    )
    equity = ctx.fundamentals_asof_join(idx, column="equity", frame=frame).to_numpy(dtype="float64")
    out = ni / equity
    out[~(equity > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


def _eq_operating_margin_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Operating margin = TTM operating income / TTM revenues; NaN where revenues <= 0."""
    frame = _fundamental_frame(ctx)
    idx = _grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    oi = ctx.fundamentals_asof_join(idx, column=_ttm("operating_income"), frame=frame).to_numpy(
        dtype="float64"
    )
    rev = ctx.fundamentals_asof_join(idx, column=_ttm("revenues"), frame=frame).to_numpy(
        dtype="float64"
    )
    out = oi / rev
    out[~(rev > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


# --------------------------------------------------------------- pre-registered composites
# docs/design/PRE_REGISTRATION.md: equal-weight cross-sectional z-composites (NOT IC-weighted
# blends — IC weighting is an in-sample fit). Each component is winsorized 1/99 then z-scored
# within the PIT cross-section; the composite is the mean of the AVAILABLE component z-scores
# (>= min_valid required). The engine re-winsorizes/z-scores the result (ordering-preserving).

_WINSOR: Final[float] = 0.01
_MIN_CS_NAMES: Final[int] = 5
"""Minimum names in a cross-section before a z-score is meaningful (else all-NaN that bar)."""


def _cs_zscore(s: pd.Series) -> pd.Series:
    """Winsorize 1/99 then z-score WITHIN each ts_open cross-section (index level 0).

    Prefix-independent: each ts_open is standardized in isolation, so a truncated frame's
    overlapping bars are byte-identical (the cross-section at t depends only on bar-t values).
    """

    def _z(g: pd.Series) -> pd.Series:
        v = g.to_numpy(dtype="float64")
        finite = np.isfinite(v)
        if int(finite.sum()) < _MIN_CS_NAMES:
            return pd.Series(np.nan, index=g.index, dtype="float64")
        lo = np.nanquantile(v, _WINSOR)
        hi = np.nanquantile(v, 1.0 - _WINSOR)
        w = np.clip(v, lo, hi)
        mu = np.nanmean(w)
        sd = np.nanstd(w)
        out = (w - mu) / sd if sd > 0.0 else np.zeros_like(w)
        out[~finite] = np.nan
        return pd.Series(out, index=g.index, dtype="float64")

    return s.groupby(level=0, group_keys=False).apply(_z)


def _equal_weight_composite(
    components: list[pd.Series], idx: pd.MultiIndex, *, min_valid: int, name: str
) -> pd.Series:
    """Mean of the available per-component cross-sectional z-scores; NaN if < min_valid present."""
    zs = [_cs_zscore(c).reindex(idx) for c in components]
    mat = pd.concat(zs, axis=1)
    valid = mat.notna().sum(axis=1).to_numpy()
    mean = mat.mean(axis=1, skipna=True).to_numpy(dtype="float64")
    # np.where returns a fresh writable array (.to_numpy() is read-only under CoW pandas 2.x).
    comp = np.where(valid >= min_valid, mean, np.nan)
    return pd.Series(comp, index=idx, dtype="float64", name=name)


def _eq_value_composite_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Value composite = equal-weight CS-z of [B/P, E/P, S/P], >=2-of-3 required (Asness/HML)."""
    idx = _grid_index(ctx)
    if _fundamental_frame(ctx).empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    comps = [_eq_book_to_price_fn(ctx, spec), _eq_earnings_yield_fn(ctx, spec),
             _eq_sales_to_price_fn(ctx, spec)]
    return _equal_weight_composite(comps, idx, min_valid=2, name=spec.name)


def _eq_quality_composite_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Quality composite = equal-weight CS-z of [GP/A, ROE], >=1 required (Novy-Marx/QMJ)."""
    idx = _grid_index(ctx)
    if _fundamental_frame(ctx).empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    comps = [_eq_gross_profitability_fn(ctx, spec), _eq_roe_fn(ctx, spec)]
    return _equal_weight_composite(comps, idx, min_valid=1, name=spec.name)


def _lag_by_instrument(frame: pd.DataFrame, col: str, k: int) -> pd.Series:
    """Value of ``col`` from ``k`` reported quarters earlier, per instrument (prefix-safe)."""
    vals = frame[col].to_numpy(dtype="float64")
    out = np.full(len(frame), np.nan, dtype="float64")
    for positions in frame.groupby("instrument_id", sort=False).indices.values():
        if len(positions) > k:
            out[positions[k:]] = vals[positions[:-k]]
    return pd.Series(out, index=frame.index, dtype="float64")


def _eq_asset_growth_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Asset growth = TTM-lag YoY total-asset growth (Fama-French CMA / Cooper-Gulen-Schill).

    growth = assets_t / assets_{t-4q} - 1. direction = -1 (LOW asset growth -> high expected
    return: the conservative-minus-aggressive investment premium). NaN where the 4-quarters-ago
    asset base is non-positive or unavailable.
    """
    f = ctx.fundamentals()
    idx = _grid_index(ctx)
    if f.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    f = f.sort_values(["instrument_id", "period_end"], kind="stable").reset_index(drop=True)
    f["assets_lag4"] = _lag_by_instrument(f, "assets", _TTM_QUARTERS)
    a = ctx.fundamentals_asof_join(idx, column="assets", frame=f).to_numpy(dtype="float64")
    a4 = ctx.fundamentals_asof_join(idx, column="assets_lag4", frame=f).to_numpy(dtype="float64")
    out = a / a4 - 1.0
    out[~(a4 > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


# --------------------------------------------------------------- registered factories


def _spec(name: str, family: Family, fn) -> FeatureSpec:  # type: ignore[no-untyped-def]
    """Build a value/quality FeatureSpec (all share direction=+1, cross_sectional, lookback)."""
    return FeatureSpec(
        name=name,
        family=family,
        direction=1,  # higher ratio/quality = higher expected return (CS-ranked)
        cross_sectional=True,
        lookback_bars=_LOOKBACK_BARS,
        params={
            "ttm_quarters": _TTM_QUARTERS,
            "sessions_per_quarter": _SESSIONS_PER_QUARTER,
            "recency_sessions": _RECENCY_SESSIONS,
        },
        fn=fn,
    )


@feature
def eq_earnings_yield() -> FeatureSpec:
    """E/P value factor: TTM net income / market cap. direction +1, CS."""
    return _spec("eq_earnings_yield", Family.VALUE, _eq_earnings_yield_fn)


@feature
def eq_book_to_price() -> FeatureSpec:
    """B/P value factor: latest equity / market cap (NaN if equity<=0). direction +1, CS."""
    return _spec("eq_book_to_price", Family.VALUE, _eq_book_to_price_fn)


@feature
def eq_sales_to_price() -> FeatureSpec:
    """S/P value factor: TTM revenues / market cap. direction +1, CS."""
    return _spec("eq_sales_to_price", Family.VALUE, _eq_sales_to_price_fn)


@feature
def eq_gross_profitability() -> FeatureSpec:
    """Novy-Marx quality factor: TTM gross profit / total assets. direction +1, CS."""
    return _spec("eq_gross_profitability", Family.QUALITY, _eq_gross_profitability_fn)


@feature
def eq_roe() -> FeatureSpec:
    """ROE quality factor: TTM net income / latest equity (NaN if equity<=0). direction +1, CS."""
    return _spec("eq_roe", Family.QUALITY, _eq_roe_fn)


@feature
def eq_operating_margin() -> FeatureSpec:
    """Operating-margin quality factor: TTM operating income / TTM revenues. direction +1, CS."""
    return _spec("eq_operating_margin", Family.QUALITY, _eq_operating_margin_fn)


@feature
def eq_value_composite() -> FeatureSpec:
    """Pre-registered VALUE composite: equal-weight CS-z of B/P+E/P+S/P (>=2-of-3). +1, CS."""
    return _spec("eq_value_composite", Family.VALUE, _eq_value_composite_fn)


@feature
def eq_quality_composite() -> FeatureSpec:
    """Pre-registered QUALITY composite: equal-weight CS-z of GP/A+ROE (>=1). +1, CS."""
    return _spec("eq_quality_composite", Family.QUALITY, _eq_quality_composite_fn)


@feature
def eq_asset_growth() -> FeatureSpec:
    """Pre-registered INVESTMENT factor: YoY asset growth (Fama-French CMA). direction -1, CS.

    Larger lookback than the ratio factors: the YoY lag needs 5 reported quarters (current +
    4 back) inside compute_asof's minimal window, plus the filing-recency reach."""
    return FeatureSpec(
        name="eq_asset_growth",
        family=Family.QUALITY,
        direction=-1,  # LOW asset growth = high expected return (conservative-minus-aggressive)
        cross_sectional=True,
        lookback_bars=(_TTM_QUARTERS + 2) * _SESSIONS_PER_QUARTER + _RECENCY_SESSIONS + 1,
        params={
            "ttm_quarters": _TTM_QUARTERS,
            "sessions_per_quarter": _SESSIONS_PER_QUARTER,
            "recency_sessions": _RECENCY_SESSIONS,
        },
        fn=_eq_asset_growth_fn,
    )
