"""The registered factor library (alphaDesign.md §2).

Importing this package registers every library factor into
:func:`alphaforge.features.registry.default_registry` via the :func:`feature`
decorator (factor *bodies* here, machinery in :mod:`alphaforge.features` —
buildabilityCritique.md ruling 3.4). Registered (Phase 4):

* :mod:`~alphaforge.features.library.vol` (§2.2) — ``vol_yz_168``, ``vol_yz_720``,
  ``vol_pk_168``, ``vol_ratio_168_720`` (direction 0 features) + the sigma_hat helpers
  (``ewma_vol`` et al.) every other module reuses.
* :mod:`~alphaforge.features.library.momentum` (§2.3) — ``mom_xs_168_24``,
  ``mom_xs_504_48``, ``mom_xs_2160_168`` (CS, skip-momentum) and ``mom_ts_168``,
  ``mom_ts_504``, ``mom_ts_2160`` (vol-normalized TS momentum).
* :mod:`~alphaforge.features.library.mean_reversion` (§2.4) — ``mr_res_24``,
  ``mr_res_72`` (beta-residual reversal vs the equal-weight PIT-universe market).
* :mod:`~alphaforge.features.library.carry` (§2.5) — ``carry_fund_21``,
  ``carry_fund_90`` (interval-aware annualized funding carry; direction +1, CS).
* :mod:`~alphaforge.features.library.liquidity` (§2.6) — ``liq_amihud_720``,
  ``liq_volz_720``, ``liq_volz_24h_sum``, ``liq_cs_spread_168`` (direction 0
  risk/cost features).
* :mod:`~alphaforge.features.library.market` (buildability finding 3.9) —
  ``adv_quote_30d``, ``sigma_daily`` (THE shared cost/risk/universe inputs).
* :mod:`~alphaforge.features.library.regime_features` (§2.7) — ``reg_rvp_720``,
  ``reg_corr_btc_720``, ``reg_breadth_sma720``, ``reg_breadth_mom168``
  (broadcast/per-symbol regime context; direction 0, not CS).
* :mod:`~alphaforge.features.library.equity_price` (EQUITIES_SLEEVE.md §4) — the
  first EQUITIES-sleeve factors on daily (D1 session) bars: ``eq_mom_252_21`` (12-1
  momentum), ``eq_rev_21`` (1-month reversal), ``eq_lowvol_252`` (low-vol anomaly,
  direction -1), ``eq_beta_252`` (rolling market beta, direction 0), ``eq_bab_252``
  (betting-against-beta, direction +1), ``eq_vol_252`` / ``eq_amihud_63`` (vol +
  Amihud illiquidity context, direction 0). Reuse the crypto factor math verbatim
  where structurally identical (skip-momentum, ``rolling_beta``, ``amihud_illiq``) on
  a PIT split/dividend-adjusted close panel.

Shared non-negotiables: every value at decision bar ``t`` is a pure function of
data available at the bar close ``t + Δ``; window math runs on the complete
expected bar grid (gaps ⇒ NaN, never bridged or forward-filled); inputs are never
mutated; ``lookback_bars`` derives from params at the single factory construction
site; EWMA-family specs follow the 10-span truncation convention (parity rtol
1e-9, finite-window specs atol 0).
"""

from alphaforge.features.library.carry import (
    HOURS_PER_YEAR,
    MAX_FUNDING_INTERVAL_HOURS,
    carry_fund_21,
    carry_fund_90,
)
from alphaforge.features.library.carry_dynamics import (
    Z_CLIP,
    carry_mom_21_63,
    carry_z_252,
)
from alphaforge.features.library.equity_liquidity_alpha import (
    ILREV_WINDOW,
    eq_ilrev,
)
from alphaforge.features.library.equity_price import (
    SESSIONS_PER_YEAR,
    adjusted_close,
    eq_amihud_63,
    eq_bab_252,
    eq_beta_252,
    eq_lowvol_252,
    eq_mom_252_21,
    eq_rev_21,
    eq_vol_252,
    realized_vol,
    reversal,
)
from alphaforge.features.library.equity_fundamental import (
    eq_asset_growth,
    eq_book_to_price,
    eq_earnings_yield,
    eq_gross_profitability,
    eq_operating_margin,
    eq_quality_composite,
    eq_roe,
    eq_sales_to_price,
    eq_value_composite,
)
from alphaforge.features.library.equity_residual import (
    EQ_BETA_WINDOW,
    eq_rev_resid_21,
    residual_reversal_finite,
)
from alphaforge.features.library.liquidity import (
    AMIHUD_EPS,
    CS_DENOM,
    amihud_illiq,
    corwin_schultz_spread,
    liq_amihud_720,
    liq_cs_spread_168,
    liq_volz_24h_sum,
    liq_volz_720,
    volume_zscore,
)
from alphaforge.features.library.market import (
    BARS_PER_DAY,
    DAY_MS,
    SIGMA_DAILY_HALFLIFE,
    adv_quote_30d,
    sigma_daily,
)
from alphaforge.features.library.market_state import (
    beta_lowbeta_720,
)
from alphaforge.features.library.mean_reversion import (
    BETA_WINDOW,
    market_return,
    mr_res_24,
    mr_res_72,
    residual_reversal,
    rolling_beta,
)
from alphaforge.features.library.momentum import (
    mom_ts_168,
    mom_ts_504,
    mom_ts_2160,
    mom_xs_168_24,
    mom_xs_504_48,
    mom_xs_2160_168,
    ts_momentum,
    xs_momentum,
)
from alphaforge.features.library.momentum_slow import (
    mom_res_2160_168,
    residual_momentum,
)
from alphaforge.features.library.regime_features import (
    BTC_ANCHOR,
    reg_breadth_mom168,
    reg_breadth_sma720,
    reg_corr_btc_720,
    reg_rvp_720,
)
from alphaforge.features.library.vol import (
    BARS_PER_YEAR_H1,
    EWMA_VOL_SPAN,
    ewma_vol,
    ewma_vol_from_returns,
    log_returns,
    parkinson,
    vol_pk_168,
    vol_ratio_168_720,
    vol_yz_168,
    vol_yz_720,
    yang_zhang,
)
from alphaforge.features.library.vol_premium import (
    LOWVOL_EPS,
    lowvol_720,
    semivar_skew_504,
    semivariance_skew,
)

__all__ = [
    "AMIHUD_EPS",
    "BARS_PER_DAY",
    "BARS_PER_YEAR_H1",
    "BETA_WINDOW",
    "BTC_ANCHOR",
    "CS_DENOM",
    "DAY_MS",
    "EQ_BETA_WINDOW",
    "EWMA_VOL_SPAN",
    "HOURS_PER_YEAR",
    "ILREV_WINDOW",
    "LOWVOL_EPS",
    "MAX_FUNDING_INTERVAL_HOURS",
    "SESSIONS_PER_YEAR",
    "SIGMA_DAILY_HALFLIFE",
    "Z_CLIP",
    "adjusted_close",
    "adv_quote_30d",
    "amihud_illiq",
    "beta_lowbeta_720",
    "carry_fund_21",
    "carry_fund_90",
    "carry_mom_21_63",
    "carry_z_252",
    "corwin_schultz_spread",
    "eq_amihud_63",
    "eq_asset_growth",
    "eq_bab_252",
    "eq_beta_252",
    "eq_book_to_price",
    "eq_earnings_yield",
    "eq_gross_profitability",
    "eq_ilrev",
    "eq_lowvol_252",
    "eq_mom_252_21",
    "eq_operating_margin",
    "eq_quality_composite",
    "eq_rev_21",
    "eq_rev_resid_21",
    "eq_roe",
    "eq_sales_to_price",
    "eq_value_composite",
    "eq_vol_252",
    "ewma_vol",
    "ewma_vol_from_returns",
    "liq_amihud_720",
    "liq_cs_spread_168",
    "liq_volz_24h_sum",
    "liq_volz_720",
    "log_returns",
    "lowvol_720",
    "market_return",
    "mom_res_2160_168",
    "mom_ts_168",
    "mom_ts_504",
    "mom_ts_2160",
    "mom_xs_168_24",
    "mom_xs_504_48",
    "mom_xs_2160_168",
    "mr_res_24",
    "mr_res_72",
    "parkinson",
    "realized_vol",
    "reg_breadth_mom168",
    "reg_breadth_sma720",
    "reg_corr_btc_720",
    "reg_rvp_720",
    "residual_momentum",
    "residual_reversal",
    "residual_reversal_finite",
    "reversal",
    "rolling_beta",
    "semivar_skew_504",
    "semivariance_skew",
    "sigma_daily",
    "ts_momentum",
    "vol_pk_168",
    "vol_ratio_168_720",
    "vol_yz_168",
    "vol_yz_720",
    "volume_zscore",
    "xs_momentum",
    "yang_zhang",
]
