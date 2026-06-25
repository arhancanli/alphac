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

from alphaforge.features.context import FeatureContext
from alphaforge.features.library import equity_fundamental as _eqf
from alphaforge.features.library import equity_price as _eqp
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
    total += register_crypto_momentum_grid(reg)
    return total
