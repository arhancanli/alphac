"""Research strategy ZOO — programmatically registered parameter-grid factors for the brutal
multiple-testing campaign (generate hundreds -> IC screen -> deflated walk-forward gauntlet).

NOT imported by the deployed factor library: ``alphaforge.features.library`` stays at its
committed canonical size (the registry-count guard in tests/integration/test_factor_invariants
keeps holding), so the zoo never touches a deployed run. The screen harness
(``scripts/zoo_screen.py``) imports this module explicitly and calls :func:`register_all`,
which adds the grid factors to ``default_registry()`` just for that process; the IC report then
screens every one. The Deflated-Sharpe denominator in the downstream gauntlet must count ALL of
them.

Grids INHERIT each canonical factor's family / direction / cross-sectional flag / BODY and only
vary (lookback, skip, window) — so every zoo factor reuses a body the truncation-invariance suite
already proved PIT-safe; only the parameters differ. Equity factors (eq_*) screen on the equity
profile; crypto factors (mom_xs_*/mom_ts_*) on the crypto profile — the IC report filters by the
profile's asset class, so registering both is harmless.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.features.context import FeatureContext, long_series
from alphaforge.features.library import equity_fundamental as _eqf
from alphaforge.features.library import equity_price as _eqp
from alphaforge.features.library.carry import _carry_spec
from alphaforge.features.library.mean_reversion import _mr_spec
from alphaforge.features.library.momentum import _ts_spec, _xs_spec
from alphaforge.features.registry import FeatureRegistry, default_registry
from alphaforge.features.spec import Family, FeatureSpec

# ----- EQUITY grids (D1 sessions): inherit the canonical body, vary the window ---------------
_EQ_MOM_LOOKBACKS = (21, 42, 63, 126, 189, 252, 378, 504, 756, 1008)
_EQ_MOM_SKIPS = (0, 5, 10, 21, 42, 63)
_EQ_REV_WINDOWS = (5, 10, 21, 42, 63, 126)
_EQ_VOL_WINDOWS = (21, 63, 126, 252, 504)
_EQ_BAB_WINDOWS = (126, 252, 504, 756)

# ----- CRYPTO grids (H1 bars) ---------------------------------------------------------------
_XS_LOOKBACKS = (10, 21, 42, 63, 126, 168, 252, 336, 504, 720, 1008, 1512, 2160)
_XS_SKIPS = (0, 5, 10, 21, 42, 63, 168)
_TS_LOOKBACKS = (21, 63, 126, 252, 504, 720, 1080, 2160)
_CARRY_SETTLEMENTS = (7, 14, 28, 42, 63, 126, 180)  # canonical 21/90 excluded
_MR_WINDOWS = (12, 48, 168)  # canonical 24/72 excluded


def _variant(base: FeatureSpec, name: str, *, lookback_bars: int, params: dict) -> FeatureSpec:
    """A grid variant of a canonical factor: same family/direction/CS-flag/body, new params."""
    return FeatureSpec(
        name=name,
        family=base.family,
        direction=base.direction,
        cross_sectional=base.cross_sectional,
        lookback_bars=lookback_bars,
        params=params,
        fn=base.fn,
    )


def register_equity_grid(reg: FeatureRegistry) -> int:
    """Register the equity momentum / reversal / low-vol / BAB parameter grids."""
    have = {s.name for s in reg.all_specs()}
    mom, rev = _eqp.eq_mom_252_21(), _eqp.eq_rev_21()
    vol, bab = _eqp.eq_lowvol_252(), _eqp.eq_bab_252()
    n = 0

    def _add(spec: FeatureSpec) -> None:
        nonlocal n
        if spec.name not in have:
            reg.register(lambda spec=spec: spec)
            have.add(spec.name)
            n += 1

    for lookback in _EQ_MOM_LOOKBACKS:
        for skip in _EQ_MOM_SKIPS:
            if skip >= lookback:
                continue
            _add(_variant(mom, f"eq_mom_{lookback}_{skip}", lookback_bars=lookback + 1,
                          params={"lookback": lookback, "skip": skip}))
    for window in _EQ_REV_WINDOWS:
        _add(_variant(rev, f"eq_rev_{window}", lookback_bars=window + 1, params={"window": window}))
    for window in _EQ_VOL_WINDOWS:
        _add(_variant(vol, f"eq_lowvol_{window}", lookback_bars=window + 1,
                      params={"window": window}))
    for window in _EQ_BAB_WINDOWS:
        _add(_variant(bab, f"eq_bab_{window}", lookback_bars=window + 2, params={"window": window}))
    return n


# ----- EQUITY fundamental-ratio grid (value yields + cash-based profitability) --------------
# Numerators are TTM-flow as-of columns (ttm_*); denominators are market_cap / assets / equity.
# Only the ratios NOT already canonical are listed (no eq_earnings_yield / eq_roe / GP-A dupes),
# so the campaign N isn't inflated by exact duplicates. All direction +1 (higher = cheaper /
# more profitable = higher expected return), Sloan/Novy-Marx/Ball-Gerakos cash-profitability.
_VALUE_YIELDS = (  # numerator / market_cap
    ("eq_val_gpp", "ttm_gross_profit"),
    ("eq_val_ocfp", "ttm_op_cash_flow"),
    ("eq_val_fcfp", "ttm_free_cash_flow"),
    ("eq_val_oip", "ttm_operating_income"),
)
_ASSET_RATIOS = (  # numerator / assets
    ("eq_qual_roa", "ttm_net_income"),
    ("eq_qual_ocfa", "ttm_op_cash_flow"),
    ("eq_qual_oia", "ttm_operating_income"),
    ("eq_qual_fcfa", "ttm_free_cash_flow"),
    ("eq_qual_turn", "ttm_revenues"),
)
_EQUITY_RATIOS = (  # numerator / equity
    ("eq_qual_gpe", "ttm_gross_profit"),
    ("eq_qual_ocfe", "ttm_op_cash_flow"),
)


def _ratio_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Generic PIT fundamental ratio: numerator / denom. ``params``: numerator (frame col),
    denom ('market_cap' or a frame col like 'assets'/'equity'). NaN where denom <= 0."""
    frame = _eqf._fundamental_frame(ctx)
    idx = _eqf._grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    num = ctx.fundamentals_asof_join(
        idx, column=spec.params["numerator"], frame=frame
    ).to_numpy("float64")
    denom_key = spec.params["denom"]
    den = (
        _eqf._market_cap(ctx, frame).to_numpy("float64")
        if denom_key == "market_cap"
        else ctx.fundamentals_asof_join(idx, column=denom_key, frame=frame).to_numpy("float64")
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den
    out[~(den > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


def register_equity_fundamental_grid(reg: FeatureRegistry) -> int:
    """Register the value-yield + cash-profitability ratio grid (non-canonical ratios only)."""
    have = {s.name for s in reg.all_specs()}
    lb = _eqf._LOOKBACK_BARS
    n = 0
    for table, family, denom in (
        (_VALUE_YIELDS, Family.VALUE, "market_cap"),
        (_ASSET_RATIOS, Family.QUALITY, "assets"),
        (_EQUITY_RATIOS, Family.QUALITY, "equity"),
    ):
        for name, numerator in table:
            if name in have:
                continue
            spec = FeatureSpec(name=name, family=family, direction=1, cross_sectional=True,
                               lookback_bars=lb, params={"numerator": numerator, "denom": denom},
                               fn=_ratio_fn)
            reg.register(lambda spec=spec: spec)
            have.add(name)
            n += 1
    return n


def register_crypto_momentum_grid(reg: FeatureRegistry) -> int:
    """Register the crypto XS (lookback x skip) + TS momentum grids."""
    have = {s.name for s in reg.all_specs()}
    n = 0
    for lookback in _XS_LOOKBACKS:
        for skip in _XS_SKIPS:
            if skip >= lookback:
                continue
            name = f"mom_xs_{lookback}_{skip}"
            if name in have:
                continue
            reg.register(lambda lookback=lookback, skip=skip: _xs_spec(lookback, skip))
            n += 1
    for lookback in _TS_LOOKBACKS:
        name = f"mom_ts_{lookback}"
        if name in have:
            continue
        reg.register(lambda lookback=lookback: _ts_spec(lookback))
        n += 1
    return n


# ----- EQUITY NOVEL signals (not parameter variants of a canonical factor) ------------------
def _eq_52whigh_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """52-week-high proximity = close / rolling-max(close, W). Near 1 = near its high (George-Hwang
    anchoring momentum). direction +1. Pure function of adjusted closes through t."""
    px = _eqp._adjusted_close_panel(ctx)
    w = int(spec.params["window"])
    with np.errstate(divide="ignore", invalid="ignore"):
        prox = px / px.rolling(w, min_periods=w).max()
    return long_series(prox, name=spec.name)


def _eq_maxret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """MAX / lottery effect = the single largest daily return over the last W sessions (Bali-Cakici-
    Whitelaw). Lottery-like stocks are overpriced and underperform. direction -1."""
    px = _eqp._adjusted_close_panel(ctx)
    w = int(spec.params["window"])
    maxr = px.pct_change().rolling(w, min_periods=w).max()
    return long_series(maxr, name=spec.name)


def _eq_fundmom_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Fundamental momentum = YoY growth in TTM net income (improving earnings -> outperformance).
    direction +1. NaN where the year-ago TTM earnings base is non-positive."""
    frame = _eqf._fundamental_frame(ctx)
    idx = _eqf._grid_index(ctx)
    if frame.empty:
        return pd.Series(np.nan, index=idx, dtype="float64", name=spec.name)
    f = frame.copy()
    f["ttm_ni_lag4"] = _eqf._lag_by_instrument(f, "ttm_net_income", _eqf._TTM_QUARTERS)
    ni = ctx.fundamentals_asof_join(idx, column="ttm_net_income", frame=f).to_numpy("float64")
    ni4 = ctx.fundamentals_asof_join(idx, column="ttm_ni_lag4", frame=f).to_numpy("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = ni / ni4 - 1.0
    out[~(ni4 > 0.0)] = np.nan
    return pd.Series(out, index=idx, dtype="float64", name=spec.name)


def register_equity_novel_grid(reg: FeatureRegistry) -> int:
    """Register the equity novel signals: 52-week-high, lottery/MAX, fundamental momentum."""
    have = {s.name for s in reg.all_specs()}
    fund_lb = (_eqf._TTM_QUARTERS * 2 + 1) * _eqf._SESSIONS_PER_QUARTER + _eqf._RECENCY_SESSIONS + 1
    specs = [
        *(FeatureSpec(name=f"eq_52whigh_{w}", family=Family.MOMENTUM, direction=1,
                      cross_sectional=True, lookback_bars=w + 1, params={"window": w},
                      fn=_eq_52whigh_fn) for w in (126, 252)),
        *(FeatureSpec(name=f"eq_maxret_{w}", family=Family.REVERSAL, direction=-1,
                      cross_sectional=True, lookback_bars=w + 2, params={"window": w},
                      fn=_eq_maxret_fn) for w in (21, 63)),
        FeatureSpec(name="eq_fundmom", family=Family.QUALITY, direction=1, cross_sectional=True,
                    lookback_bars=fund_lb, params={}, fn=_eq_fundmom_fn),
    ]
    n = 0
    for s in specs:
        if s.name not in have:
            reg.register(lambda s=s: s)
            have.add(s.name)
            n += 1
    return n


def register_crypto_carry_reversal_grid(reg: FeatureRegistry) -> int:
    """Register the crypto funding-carry (n-settlement) + residual-reversal (window) grids."""
    have = {s.name for s in reg.all_specs()}
    n = 0
    for k in _CARRY_SETTLEMENTS:
        name = f"carry_fund_{k}"
        if name in have:
            continue
        reg.register(lambda k=k, name=name: _carry_spec(name, k))
        have.add(name)
        n += 1
    for w in _MR_WINDOWS:
        name = f"mr_res_{w}"
        if name in have:
            continue
        reg.register(lambda w=w: _mr_spec(w))
        have.add(name)
        n += 1
    return n


def register_all(reg: FeatureRegistry | None = None) -> int:
    """Register every zoo grid into ``reg`` (default: the global registry). Returns the count.

    Extended as the strategy-zoo design lands (value/quality fundamental-ratio grids, crypto
    carry/reversal/vol grids, + hand-coded novel signals). Each addition raises the
    multiple-testing N the gauntlet must deflate against — that honesty is the whole point.
    """
    reg = reg or default_registry()
    total = 0
    total += register_equity_grid(reg)
    total += register_equity_fundamental_grid(reg)
    total += register_equity_novel_grid(reg)
    total += register_crypto_momentum_grid(reg)
    total += register_crypto_carry_reversal_grid(reg)
    return total
