#!/usr/bin/env python3
"""PROBE — PRE-REGISTERED ECONOMIC-TREND SLEEVE SPEC (Track A / Step 2). LOCKED 2026-07-11.

AQR-style "economic trend": trend-following on FUNDAMENTALS, not prices. For each macro
THEME the sleeve measures whether the underlying economics are trending up or down
(point-in-time, first-release vintage data from data/lake_macro_vintage — Step 1's
contract) and takes positions in the 17-ETF managed-futures universe (data/lake_mf)
with exposure SIGNS fixed by economic logic BEFORE any backtest was run.

THIS FILE IS THE PRE-REGISTRATION. Everything below was locked before the strategy was
ever evaluated on real data. This session runs --selftest ONLY (synthetic data). The
real gauntlet (--run-real) is a later, separately audited step; when it runs it appends
exactly ONE trial to var/experiments.jsonl and publishes the result EITHER WAY.

================================ 1. DATA (SERIES LIST) ================================
All macro inputs come from data/lake_macro_vintage via its data contract:
  tier 1 (unrevised daily, publication = obs + 1 business day):
      BAA10Y, T10YIE, DFF, DGS2, DTWEXBGS, DTWEXM
  tier 2 (RTDSM first-release vintages; growth rates computed WITHIN the latest vintage
      available at the signal date — never across vintages):
      EMPLOY, IPT, RUC, HSTARTS, RCONM, PCPI, PCPIX
Stored but UNUSED in v1 (disclosed; adding any later requires a NEW pre-registration):
      DGS10, DGS3MO, T5YIE, DCOILWTICO, BAMLH0A0HYM2.
Prices: data/lake_mf ohlcv_1d (open + close), the blessed 17-ETF fixed basket.

============================ 2. THEME CONSTRUCTION (LOCKED) ===========================
ONE blend, no search: for each indicator, at monthly signal date t,
    x_k(t) = (change over k months) / k          for k in {3, 6, 12}  (per-month rate)
    blend(t) = mean(x_3, x_6, x_12)              ALL three lookbacks required, else NaN
  change definition by series type:
    tier 2 levels (EMPLOY, IPT, HSTARTS, RCONM, PCPI, PCPIX): log change within the
        latest vintage v available at t, from obs (m_last - k months) to m_last, where
        m_last = last observation in that vintage. RUC (a rate, %): LEVEL change in pp.
    tier 1 rates/spreads (BAA10Y, T10YIE, DFF, DGS2): LEVEL change in pp between the
        PIT as-of values at (t - k months) and t (as-of = latest publication_date <= t).
    tier 1 indexes (DTWEXBGS, DTWEXM): LOG change between the same as-of values.
  z-scoring (per indicator): direction sign applied to the blend FIRST (see table),
    then an EXPANDING z over the indicator's own monthly blend history (grid below),
    including the current value, ddof=0, minimum 36 monthly observations (inactive =>
    NaN before warmup), clipped to +/-2.
  theme score T(t) = mean of the member indicators' z values available at t, clip +/-2.
    An inactive theme (no member active) contributes 0 to every market score.
  monthly grid: last trading day of each month on the union ETF calendar in the price
    era; last CALENDAR day of month before it. z history starts 1980-01-31.

  THEMES and members (direction in parens; one-line logic):
    GROWTH   : EMPLOY(+)  payroll trend is the real-activity pulse
               IPT(+)     industrial production is the classic coincident cycle gauge
               RUC(-)     rising unemployment = growth falling
               HSTARTS(+) housing starts lead the domestic cycle
               RCONM(+)   real consumption is the demand engine (retail-sales substitute)
               BAA10Y(-)  credit spreads widen ahead of downturns (timely, market-based)
    INFLATION: PCPI(+)    headline CPI trend
               PCPIX(+)   core CPI trend (persistent component)
               T10YIE(+)  market-priced inflation expectations (timely; 2003+)
    POLICY   : DFF(+)     the policy rate itself: rising = tightening
               DGS2(+)    2y yield = the market's forward policy path
    DOLLAR   : USD_TW(+)  trade-weighted USD trend; DTWEXBGS once it has a 36-month
               blend history at t, else DTWEXM (splice: changes are always computed
               WITHIN one series, never across).

===================== 3. THE 17-MARKET x 4-THEME SIGN MATRIX (LOCKED) =================
"+1" = theme trending UP is LONG the market. Fixed by economic logic before any data.

  market  GRW  INF  POL  USD   one-line economic justification (each nonzero cell)
  SPY     +1   -1   -1    0   growth->earnings up; inflation compresses multiples and
                             forces tightening (1970s, 2022); tightening raises the
                             discount rate. USD ambiguous for mega-cap US = 0.
  QQQ     +1   -1   -1    0   same channels; longest-duration equities.
  IWM     +1   -1   -1    0   small caps are the most cyclical and rate-sensitive.
  EFA     +1    0    0   -1   US growth proxies the global cycle; USD-up = tighter
                             global conditions + translation drag on foreign equity.
                             US-measured inflation/policy channels diluted abroad = 0.
  EEM     +1    0   -1   -1   EM = highest-beta claim on global growth; Fed tightening
                             exports tight conditions to EM (taper-tantrum channel);
                             USD-up hits dollar-debt EM hardest.
  TLT     -1   -1   -1    0   growth-up lifts real yields; inflation erodes nominal
                             coupons; tightening lifts the whole curve.
  IEF     -1   -1   -1    0   same duration logic, intermediate tenor.
  SHY      0   -1   -1    0   the front end IS the policy instrument and reprices to
                             expected Fed response to inflation; growth reaches it only
                             via policy (already captured) = 0 (avoids triple-count).
  GLD      0   +1   -1   -1   canonical inflation hedge; tightening raises real rates =
                             the opportunity cost of zero-yield metal; USD-invoiced.
                             Not demand-cyclical = growth 0.
  SLV      0   +1   -1   -1   precious metal, same monetary logic (industrial tint
                             noted, kept 0 for symmetry with GLD).
  USO     +1   +1    0   -1   oil demand is the business cycle; energy is the most
                             volatile inflation component; USD-invoiced commodity.
  UNG      0   +1    0    0   energy price level feeds inflation; US natgas is weather/
                             storage-driven (not cleanly cyclical) and domestically
                             priced (no dollar cell).
  DBC     +1   +1    0   -1   broad commodity demand is cyclical; the inflation-hedge
                             basket; USD-invoiced.
  DBA      0   +1    0   -1   food is the other volatile inflation component; ag supply
                             shocks dominate demand (growth 0); USD-invoiced.
  FXE      0    0   -1   -1   US tightening widens the US-EU rate differential in the
                             dollar's favor; EURUSD is the dollar index's largest
                             mirror component.
  FXY     -1    0   -1   -1   yen = funding/safe-haven currency: US growth-up = risk-on
                             = yen weakens; US tightening widens the differential vs a
                             pinned BoJ; mirror of USD strength.
  UUP      0    0   +1   +1   long-USD ETF: tightening attracts capital into the
                             dollar; the dollar theme's own instrument.

Market score s_m(t) = PLAIN SUM over themes of sign(m,theta) * T_theta(t) (a market
pushed by three aligned themes deserves more conviction; risk is equalized next).

========================= 4. PORTFOLIO CONSTRUCTION (LOCKED) ==========================
  sizing     : w_m proportional to s_m / max(vol_m, 5%); vol_m = trailing 63-trading-day
               std of daily close-to-close returns, annualized with sqrt(252). The 5%
               annualized floor stops SHY/FXY notional blow-ups.
  normalize  : gross = sum|w| = 1; per-name cap |w_m| <= 0.34 (mirrors the blessed
               configs/managed_futures.yaml w_max) applied as ONE clip -> ONE
               renormalize -> ONE final clip (gross may end slightly < 1; no iteration).
  net        : unconstrained (directional book, like the managed_futures profile).
  eligibility: a market trades once it has >= 63 daily returns and a close at t;
               require >= 8 eligible markets at a rebalance, else skip (hold weights).
               If every market score is ~0 (all themes inactive/zero): go FLAT.
  rebalance  : monthly, at the close of the LAST TRADING DAY of each month, using only
               data with publication_date <= t.

============================ 5. EXECUTION AND COSTS (LOCKED) ==========================
  fill       : signal at close t -> fill at the NEXT trading day's OPEN. Fill-day
               accounting: the OLD book earns the overnight gap close(t)->open(t+1);
               the NEW book earns open(t+1)->close(t+1); afterwards close-to-close.
               Constant-weight approximation between fills (no drift compounding),
               same convention as scripts/probe_carry_gauntlet.py.
  costs      : committed managed-futures ETF schedule (configs/managed_futures.yaml):
               1bp commission + 3bp half-spread + 2bp latency = 6bp ONE-WAY, charged on
               fill-day turnover sum|w_new - w_old|. Short borrow 50bp/yr accrued each
               trading day on the short-side gross (/252). The vol-target overlay's
               re-lever trades at fold boundaries are also charged |dk| * 6bp.
  no peeking : no same-bar fills anywhere; macro enters only via publication_date.

====================== 6. WALK-FORWARD SHAPE AND VALIDATION (LOCKED) ==================
Mirrors mf_gauntlet: 2y train (504 sessions) / 6m test (126) / 21-session embargo,
purged, stitched-OOS. THIS SPEC HAS NO FITTED PARAMETERS — "train" reduces to
estimating the vol-target leverage constant k = 0.15 / (sd_train * sqrt(365)), clipped
[0, 3] (the repo's headline 365-day annualization basis; Sharpe/DSR are invariant to
k, so the stitched series is effectively pure OOS). Backtest window 2003-01-01 ..
2026-06-01 (mirrors mf_gauntlet), markets entering as they list.

Metrics via the BLESSED machinery only: alphaforge.analytics.metrics.summarize /
daily_returns / DAYS_PER_YEAR and alphaforge.validation.dsr.dsr_from_returns.

DSR protocol (var/experiments.jsonl): the real run appends exactly ONE trial via
ExperimentLog.record (idempotent config hash of the SPEC dict below). Headline DSR =
dsr_from_returns(oos_daily_returns, n_trials = ledger.n_trials() AFTER the append,
sr_trials_variance = ledger.trial_sharpe_variance(), DAYS_PER_YEAR). Also reported for
cross-probe comparability: fresh-trial DSR (n_trials=2, variance=1.0), the
probe_carry_gauntlet convention. Ledger N at spec time: 102.

=========================== 7. PRE-REGISTERED REPORTING GATES =========================
Report ALL of (publish either way):
  net Sharpe (blessed summarize, vol-targeted stitched-OOS equity),
  DSR at ledger N (protocol above) + fresh-trial DSR,
  max drawdown, skew (daily), ann vol, Sortino, CAGR,
  corr to AlphaTrend OOS daily returns (artifacts/walkforward/mf_live_fwd/
    equity.parquet, log-return daily overlap) — computed on the UNLEVERED net series,
  corr to SPY (data/lake_mf SPY closes, same convention),
  crisis table: GFC 2007-10-01..2009-03-31 (data allows: sleeve trades from 2003),
    COVID 2020-02-15..2020-04-30, 2022 bear 2022-01-01..2022-12-31 — per window:
    sleeve cumulative net return (vol-targeted), sleeve max DD in window, SPY
    cumulative return.
ADOPT-CONSIDERATION BAR (locked): net Sharpe >= 0.40 AND corr-to-AlphaTrend < 0.50
AND crisis survival, where crisis survival := in EACH window the vol-targeted sleeve's
cumulative net return > -22.5% (1.5x the 15% vol target) AND pooled across the three
windows its mean daily net return exceeds SPY's. Failing any gate = publish the null.

================================== 8. SELF-TEST =======================================
--selftest builds SYNTHETIC vintage + price data (no real lake file is read) and
proves, using the SAME pipeline functions as the real run:
  S1  signals use only publication-date-available values (vintage boundary: the blend's
      m_last advances only when a new vintage is legitimately published; exact
      hand-computed blend value on a known 1%/mo trend),
  S2  a revision AFTER publication does not change historical signals (two parallel
      universes differing only in a revision: identical signals strictly before the
      revising vintage date; different once the revised obs enters a blend endpoint),
  S3  tier-1 publication lag respected (a value is invisible before publication_date),
  S4  next-open fill honesty (an overnight gap after the rebalance decision accrues to
      the OLD book, never the new one; exact cost arithmetic; borrow accrual),
  S5  end-to-end PIT immunity (full pipeline on synthetic macro + prices: truncating
      future vintages leaves all past rebalance weights byte-identical; a published
      macro crash flips the book short only after publication; flat before z warmup).

Usage:
    uv run python scripts/probe_econtrend.py --selftest     # THIS session (synthetic)
    uv run python scripts/probe_econtrend.py --run-real     # LATER, audited step only
New files only: this script + artifacts/sweep/econtrend_probe/** (real run). Nothing
in src/, existing scripts, configs, or launchd jobs is touched.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LAKE_MACRO = _ROOT / "data" / "lake_macro_vintage"
LAKE_MF = _ROOT / "data" / "lake_mf"
OUT = _ROOT / "artifacts" / "sweep" / "econtrend_probe"
ALPHATREND_EQ = _ROOT / "artifacts" / "walkforward" / "mf_live_fwd" / "equity.parquet"
LEDGER = _ROOT / "var" / "experiments.jsonl"

# ---------------------------- LOCKED SPEC CONSTANTS ----------------------------
LOOKBACKS_M = (3, 6, 12)          # the ONE pre-registered blend (per-month-normalized mean)
Z_MIN_OBS = 36                    # months of blend history before an indicator activates
Z_CLIP = 2.0                      # indicator z and theme score clip
HISTORY_START = pd.Timestamp("1980-01-31")
BACKTEST_START = pd.Timestamp("2003-01-01")
BACKTEST_END = pd.Timestamp("2026-06-01")
VOL_LOOKBACK_D = 63               # trailing daily returns for sizing vol
VOL_ANN_DAYS = 252.0              # ETF trading-day annualization for sizing vol
VOL_FLOOR_ANN = 0.05              # 5% floor stops SHY/FXY notional blow-ups
NAME_CAP = 0.34                   # mirrors configs/managed_futures.yaml w_max
MIN_BREADTH = 8                   # eligible markets required to rebalance
ONE_WAY = 6e-4                    # 1+3+2 bp committed ETF schedule (managed_futures.yaml)
BORROW_DAILY = 50e-4 / 252.0      # 50bp/yr short borrow, accrued per trading day
VOL_TARGET_ANN = 0.15
WF_TRAIN, WF_TEST, WF_EMBARGO = 504, 126, 21
INIT_CASH = 50_000.0

# indicator registry: name -> (tier, transform, direction). "log"/"level" per the spec.
INDICATORS = {
    "growth": [
        ("EMPLOY", "t2", "log", +1),
        ("IPT", "t2", "log", +1),
        ("RUC", "t2", "level", -1),
        ("HSTARTS", "t2", "log", +1),
        ("RCONM", "t2", "log", +1),
        ("BAA10Y", "t1", "level", -1),
    ],
    "inflation": [
        ("PCPI", "t2", "log", +1),
        ("PCPIX", "t2", "log", +1),
        ("T10YIE", "t1", "level", +1),
    ],
    "policy": [
        ("DFF", "t1", "level", +1),
        ("DGS2", "t1", "level", +1),
    ],
    "dollar": [
        ("USD_TW", "splice", "log", +1),  # DTWEXBGS once warm at t, else DTWEXM
    ],
}
THEMES = ("growth", "inflation", "policy", "dollar")

# the LOCKED 17 x 4 sign matrix (see docstring section 3 for per-cell justification)
SIGN = {
    #         GRW  INF  POL  USD
    "SPY": (+1, -1, -1, 0),
    "QQQ": (+1, -1, -1, 0),
    "IWM": (+1, -1, -1, 0),
    "EFA": (+1, 0, 0, -1),
    "EEM": (+1, 0, -1, -1),
    "TLT": (-1, -1, -1, 0),
    "IEF": (-1, -1, -1, 0),
    "SHY": (0, -1, -1, 0),
    "GLD": (0, +1, -1, -1),
    "SLV": (0, +1, -1, -1),
    "USO": (+1, +1, 0, -1),
    "UNG": (0, +1, 0, 0),
    "DBC": (+1, +1, 0, -1),
    "DBA": (0, +1, 0, -1),
    "FXE": (0, 0, -1, -1),
    "FXY": (-1, 0, -1, -1),
    "UUP": (0, 0, +1, +1),
}

CRISIS_WINDOWS = {
    "GFC_2008": ("2007-10-01", "2009-03-31"),
    "COVID_2020": ("2020-02-15", "2020-04-30"),
    "BEAR_2022": ("2022-01-01", "2022-12-31"),
}
GATES = {
    "adopt_min_net_sharpe": 0.40,
    "adopt_max_corr_alphatrend": 0.50,      # signed corr must be < 0.50
    "crisis_max_window_loss": -0.225,       # each window: cum net return > -1.5 vol-units
    "crisis_pooled_beat_spy": True,         # pooled crisis days: mean daily ret > SPY's
}

# the canonical spec dict — hashed by ExperimentLog for the ONE ledger trial
SPEC = {
    "probe": "econtrend",
    "version": "1.0",
    "lookbacks_m": list(LOOKBACKS_M),
    "blend": "mean of per-month-normalized 3/6/12m changes; all three required",
    "z": {"window": "expanding incl current", "min_obs": Z_MIN_OBS, "ddof": 0, "clip": Z_CLIP},
    "themes": {th: [[n, tier, tr, d] for (n, tier, tr, d) in mems] for th, mems in INDICATORS.items()},
    "sign_matrix": {m: list(v) for m, v in SIGN.items()},
    "score": "plain sum over themes of sign * theme_z",
    "sizing": {"vol_lookback_d": VOL_LOOKBACK_D, "ann_days": VOL_ANN_DAYS, "vol_floor_ann": VOL_FLOOR_ANN,
               "gross": 1.0, "name_cap": NAME_CAP, "min_breadth": MIN_BREADTH, "net": "unconstrained"},
    "rebalance": "monthly last trading day; close signal -> next-open fill; old book earns the gap",
    "costs": {"one_way_bps": 6.0, "borrow_bps_ann_short": 50.0, "overlay_relever_charged": True},
    "wf": {"train": WF_TRAIN, "test": WF_TEST, "embargo": WF_EMBARGO, "vol_target_ann": VOL_TARGET_ANN,
           "note": "no fitted params; train = vol estimation only"},
    "window": [str(BACKTEST_START.date()), str(BACKTEST_END.date())],
    "history_start": str(HISTORY_START.date()),
    "gates": GATES,
    "crisis_windows": CRISIS_WINDOWS,
}


# =============================================================================
# PIT primitives (pure functions over prepared frames — shared by selftest + real)
# =============================================================================

def prep_t1(df: pd.DataFrame) -> dict:
    """Tier-1 table -> sorted arrays. Columns: obs_period, value_first_release, publication_date."""
    d = df.sort_values("publication_date").reset_index(drop=True)
    return {
        "pub": d["publication_date"].to_numpy(dtype="datetime64[ns]"),
        "obs": d["obs_period"].to_numpy(dtype="datetime64[ns]"),
        "val": d["value_first_release"].to_numpy(dtype=float),
    }


def t1_asof(p: dict, date: pd.Timestamp) -> float | None:
    """Latest value with publication_date <= date (PIT)."""
    pos = int(np.searchsorted(p["pub"], np.datetime64(pd.Timestamp(date), "ns"), side="right"))
    if pos == 0:
        return None
    # obs and pub are jointly monotone for tier-1 daily series, but be robust anyway:
    sl_obs, sl_val = p["obs"][:pos], p["val"][:pos]
    return float(sl_val[int(np.argmax(sl_obs))])


def prep_t2(vlong: pd.DataFrame) -> dict:
    """Vintage-long table -> {sorted vintage dates, vintage_date -> obs-indexed Series}."""
    vd = np.sort(vlong["vintage_date"].unique())
    by = {
        pd.Timestamp(v): g.set_index("obs_period")["value"].sort_index().dropna()
        for v, g in vlong.groupby("vintage_date")
    }
    return {"vdates": vd, "by": by}


def t2_vintage_asof(p: dict, date: pd.Timestamp) -> pd.Series | None:
    """The full latest vintage with vintage_date <= date (the PIT growth-rate object)."""
    pos = int(np.searchsorted(p["vdates"], np.datetime64(pd.Timestamp(date), "ns"), side="right"))
    if pos == 0:
        return None
    return p["by"][pd.Timestamp(p["vdates"][pos - 1])]


def _rate(a: float, b: float, transform: str, k: int) -> float:
    """Per-month change rate from b (k months ago) to a (now)."""
    if transform == "log":
        if a is None or b is None or a <= 0 or b <= 0:
            return float("nan")
        return math.log(a / b) / k
    return (a - b) / k


def blend_at(tier: str, prepped: dict, date: pd.Timestamp, transform: str) -> float:
    """The pre-registered blend: mean of per-month-normalized 3/6/12m changes at `date`.
    ALL three lookbacks required, else NaN. Tier 2: within the latest vintage at date."""
    xs = []
    if tier == "t1":
        a = t1_asof(prepped, date)
        if a is None:
            return float("nan")
        for k in LOOKBACKS_M:
            b = t1_asof(prepped, pd.Timestamp(date) - pd.DateOffset(months=k))
            if b is None:
                return float("nan")
            xs.append(_rate(a, b, transform, k))
    else:  # t2
        v = t2_vintage_asof(prepped, date)
        if v is None or len(v) == 0:
            return float("nan")
        m_last = v.index.max()
        a = float(v.loc[m_last])
        for k in LOOKBACKS_M:
            m_prev = m_last - pd.DateOffset(months=k)
            if m_prev not in v.index:
                return float("nan")
            xs.append(_rate(a, float(v.loc[m_prev]), transform, k))
    x = float(np.mean(xs))
    return x if math.isfinite(x) else float("nan")


def expanding_z(x: pd.Series, min_obs: int = Z_MIN_OBS, clip: float = Z_CLIP) -> pd.Series:
    """Expanding z (incl current value, ddof=0), NaN until min_obs non-NaN, clipped."""
    cnt = x.expanding().count()
    mu = x.expanding().mean()
    sd = x.expanding().std(ddof=0)
    z = (x - mu) / sd
    z[(cnt < min_obs) | (sd <= 0) | x.isna()] = np.nan
    return z.clip(-clip, clip)


# =============================================================================
# Signal pipeline (shared)
# =============================================================================

def monthly_grid(price_index: pd.DatetimeIndex, history_start: pd.Timestamp) -> pd.DatetimeIndex:
    """Last trading day per month in the price era; calendar month-ends before it."""
    s = price_index.to_series()
    pe = pd.DatetimeIndex(s.groupby([price_index.year, price_index.month]).last().values)
    first_month = pe[0].replace(day=1)
    pre = pd.date_range(history_start, first_month - pd.Timedelta(days=1), freq="ME")
    return pre.append(pe)


def indicator_z_table(sources: dict, grid: pd.DatetimeIndex) -> dict[tuple[str, str], pd.Series]:
    """{(theme, indicator) -> monthly z series} on `grid`, direction applied pre-z.

    `sources` maps indicator name -> prepared frame(s):
      tier "t1"/"t2": {"tier": ..., "prep": prepped}
      tier "splice" (USD_TW): {"tier": "splice", "primary": prep_t1(BGS), "fallback": prep_t1(M)}
    """
    out: dict[tuple[str, str], pd.Series] = {}
    for theme, members in INDICATORS.items():
        for (name, tier, transform, direction) in members:
            if name not in sources:
                continue
            src = sources[name]
            if src["tier"] == "splice":
                zp = expanding_z(pd.Series(
                    [direction * blend_at("t1", src["primary"], d, transform) for d in grid], index=grid))
                zf = expanding_z(pd.Series(
                    [direction * blend_at("t1", src["fallback"], d, transform) for d in grid], index=grid))
                out[(theme, name)] = zp.where(zp.notna(), zf)  # primary once warm at t, else fallback
            else:
                b = pd.Series([direction * blend_at(src["tier"], src["prep"], d, transform) for d in grid], index=grid)
                out[(theme, name)] = expanding_z(b)
    return out


def theme_scores(ztab: dict[tuple[str, str], pd.Series], grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Theme score = mean of member z's available at each date, clipped to +/-Z_CLIP."""
    cols = {}
    for th in THEMES:
        members = [s for (t, _n), s in ztab.items() if t == th]
        if members:
            cols[th] = pd.concat(members, axis=1).mean(axis=1, skipna=True).clip(-Z_CLIP, Z_CLIP)
        else:
            cols[th] = pd.Series(np.nan, index=grid)
    return pd.DataFrame(cols, index=grid)


def build_weights(scores: pd.Series, vols: pd.Series) -> pd.Series | None:
    """Locked construction: s/max(vol,floor), gross 1, cap 0.34 (clip->renorm->clip)."""
    v = vols.clip(lower=VOL_FLOOR_ANN)
    raw = scores / v
    g = float(raw.abs().sum())
    if g < 1e-12:
        return None  # flat
    w = raw / g
    w = w.clip(-NAME_CAP, NAME_CAP)
    g2 = float(w.abs().sum())
    if g2 > 0:
        w = w / g2
    return w.clip(-NAME_CAP, NAME_CAP)


def rebalance_weights(
    themes: pd.DataFrame,
    close_px: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    markets: list[str],
) -> dict[pd.Timestamp, pd.Series]:
    """Target weights decided at the close of each rebalance date (PIT trailing vols)."""
    rets = close_px.pct_change()
    out: dict[pd.Timestamp, pd.Series] = {}
    for t in rebalance_dates:
        th = themes.loc[t].fillna(0.0)  # inactive theme contributes 0
        if float(th.abs().sum()) == 0.0:
            out[t] = pd.Series(0.0, index=markets)  # no active theme: flat
            continue
        hist = rets.loc[:t]
        elig, s, v = [], {}, {}
        for m in markets:
            r = hist[m].dropna()
            if len(r) < VOL_LOOKBACK_D or not np.isfinite(close_px.loc[t].get(m, np.nan)):
                continue
            elig.append(m)
            s[m] = float(sum(SIGN[m][i] * th[THEMES[i]] for i in range(4)))
            v[m] = float(r.tail(VOL_LOOKBACK_D).std(ddof=1) * math.sqrt(VOL_ANN_DAYS))
        if len(elig) < MIN_BREADTH:
            continue  # skip rebalance (hold current book)
        w = build_weights(pd.Series(s), pd.Series(v))
        out[t] = pd.Series(0.0, index=markets) if w is None else w.reindex(markets).fillna(0.0)
    return out


# =============================================================================
# Backtest engine (shared): next-open fill, committed costs, borrow
# =============================================================================

def run_backtest(
    open_px: pd.DataFrame,
    close_px: pd.DataFrame,
    weights_by_date: dict[pd.Timestamp, pd.Series],
) -> pd.Series:
    """Daily net returns. Weights decided at close t fill at the NEXT day's open:
    old book earns close(t)->open(t+1); new book earns open(t+1)->close(t+1)."""
    grid = close_px.index
    cols = close_px.columns
    w_cur = pd.Series(0.0, index=cols)
    pending: pd.Series | None = None
    if len(grid) and grid[0] in weights_by_date:
        pending = weights_by_date[grid[0]].reindex(cols).fillna(0.0)
    idx_out, val_out = [], []
    for i in range(1, len(grid)):
        d, prev = grid[i], grid[i - 1]
        c_prev, c_d, o_d = close_px.loc[prev], close_px.loc[d], open_px.loc[d]
        if pending is not None:
            gap = (o_d / c_prev - 1.0)
            intr = (c_d / o_d - 1.0)
            turnover = float((pending - w_cur).abs().sum())
            r = float((w_cur * gap).fillna(0.0).sum()) + float((pending * intr).fillna(0.0).sum())
            r -= turnover * ONE_WAY
            w_cur, pending = pending, None
        else:
            r = float((w_cur * (c_d / c_prev - 1.0)).fillna(0.0).sum())
        r -= float(w_cur.clip(upper=0.0).abs().sum()) * BORROW_DAILY  # short borrow, EOD book
        idx_out.append(d)
        val_out.append(r)
        if d in weights_by_date:
            pending = weights_by_date[d].reindex(cols).fillna(0.0)
    return pd.Series(val_out, index=pd.DatetimeIndex(idx_out), dtype=float)


def purged_wf_voltarget(net: pd.Series, train: int = WF_TRAIN, test: int = WF_TEST,
                        embargo: int = WF_EMBARGO) -> pd.Series:
    """Deflated purged walk-forward vol-target overlay (mirrors mf_gauntlet cadence).
    No fitted params exist in this spec, so 'train' only estimates the leverage
    constant; Sharpe/DSR are invariant to it. Re-lever trades charged |dk| * 6bp."""
    r = net.to_numpy(float)
    n = len(r)
    idx = net.index
    oos = pd.Series(dtype=float)
    start, k_prev = 0, 0.0
    while start + train + embargo + test <= n:
        tr = r[start:start + train]
        lo = start + train + embargo
        hi = lo + test
        sd = float(np.std(tr, ddof=1))
        k = float(np.clip((VOL_TARGET_ANN / (sd * math.sqrt(365.0))) if sd > 0 else 0.0, 0.0, 3.0))
        seg = r[lo:hi] * k
        seg[0] -= abs(k - k_prev) * ONE_WAY  # re-lever the book at the fold boundary
        k_prev = k
        oos = pd.concat([oos, pd.Series(seg, index=idx[lo:hi])])
        start += test
    return oos


def equity_from_returns(net: pd.Series, init: float = INIT_CASH) -> pd.Series:
    """Epoch-ms indexed equity curve for the blessed summarize()/dsr path."""
    eq = init * (1.0 + net).cumprod()
    ms = pd.DatetimeIndex(eq.index).to_numpy(dtype="datetime64[ms]").astype("int64")
    return pd.Series(eq.to_numpy(float), index=pd.Index(ms, name="ts"), name="equity")


# =============================================================================
# SELF-TEST (synthetic; no real lake file is read)
# =============================================================================

def _syn_vintage(rev_obs: pd.Timestamp | None = None, rev_value: float = 500.0,
                 rev_from: pd.Timestamp | None = None,
                 growth: str = "steady") -> pd.DataFrame:
    """Synthetic tier-2 vintage-long frame. Obs 2000-01..2014-12. Vintage on the 15th of
    month m+1 contains obs 2000-01..m (first release = truth, no revision), except:
    if rev_obs is set, every vintage >= rev_from records rev_value for that obs.
    growth='steady': +1%/mo exactly. 'accel_crash': monotone-accelerating growth
    (0.5%/mo + 1bp/mo, so the trend z stays > 0 by construction) until 2009-12, then
    -3%/mo (the crash whose publication timing S5 asserts on)."""
    months = pd.date_range("2000-01-01", "2014-12-01", freq="MS")
    vals = np.empty(len(months))
    v = 100.0
    for i, m in enumerate(months):
        if growth == "steady":
            g = 0.01
        else:
            g = (0.005 + 0.0001 * i) if m <= pd.Timestamp("2009-12-01") else -0.03
        v = v * math.exp(g) if i else 100.0
        vals[i] = v
    rows = []
    for j, m in enumerate(months):
        vd = (m + pd.DateOffset(months=1)).replace(day=15)  # vintage publishing obs..m
        for i in range(j + 1):
            val = vals[i]
            if rev_obs is not None and rev_from is not None and months[i] == rev_obs and vd >= rev_from:
                val = rev_value
            rows.append((months[i], vd, val))
    return pd.DataFrame(rows, columns=["obs_period", "vintage_date", "value"])


def _syn_t1() -> pd.DataFrame:
    """Synthetic tier-1 frame: daily obs, pub = obs + 1 business day, level jumps 0->100
    at obs 2010-06-15 (published 2010-06-16)."""
    obs = pd.date_range("2005-01-03", "2012-12-31", freq="B")
    val = np.where(obs >= pd.Timestamp("2010-06-15"), 100.0, 0.0)
    pub = pd.DatetimeIndex(np.busday_offset(obs.to_numpy().astype("datetime64[D]"), 1, roll="forward"))
    return pd.DataFrame({"obs_period": obs, "value_first_release": val, "publication_date": pub})


def selftest() -> int:
    print("================ ECON-TREND SPEC — SELF-TEST (synthetic only) ================")
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        if not cond:
            failures.append(name)

    # ---------- S1: publication-date availability + exact blend arithmetic ----------
    vl = _syn_vintage(growth="steady")
    p2 = prep_t2(vl)
    v_a = t2_vintage_asof(p2, pd.Timestamp("2010-03-14"))  # latest vintage = 2010-02-15 (obs..2010-01)
    v_b = t2_vintage_asof(p2, pd.Timestamp("2010-03-15"))  # vintage 2010-03-15 (obs..2010-02)
    check("S1a vintage boundary: m_last advances only on the vintage date",
          v_a.index.max() == pd.Timestamp("2010-01-01") and v_b.index.max() == pd.Timestamp("2010-02-01"),
          f"m_last {v_a.index.max().date()} -> {v_b.index.max().date()}")
    b = blend_at("t2", p2, pd.Timestamp("2010-03-14"), "log")
    check("S1b exact blend on a known exp(0.01)/mo trend equals 0.01",
          abs(b - 0.01) < 1e-12, f"blend={b:.12f} vs 0.01")

    # ---------- S2: revision immunity (two universes differing ONLY in a revision) ----------
    # obs 2010-06 first released in vintage 2010-07-15 (truth); universe B revises it to 500
    # in every vintage >= 2010-08-15. The revised obs first touches a blend endpoint when
    # m_last - 3m = 2010-06, i.e. vintage 2010-10-15 -> grid date 2010-10-31.
    vl_a = _syn_vintage(growth="steady")
    vl_b = _syn_vintage(rev_obs=pd.Timestamp("2010-06-01"), rev_value=500.0,
                        rev_from=pd.Timestamp("2010-08-15"), growth="steady")
    pa, pb = prep_t2(vl_a), prep_t2(vl_b)
    grid2 = pd.date_range("2003-01-31", "2011-12-31", freq="ME")
    ba = pd.Series([blend_at("t2", pa, d, "log") for d in grid2], index=grid2)
    bb = pd.Series([blend_at("t2", pb, d, "log") for d in grid2], index=grid2)
    pre = grid2[grid2 < pd.Timestamp("2010-08-15")]
    check("S2a revision does NOT change any signal before the revising vintage date",
          bool(np.allclose(ba.loc[pre], bb.loc[pre], equal_nan=True, atol=0, rtol=0)))
    d_rev = pd.Timestamp("2010-10-31")
    check("S2b revision IS used once published and touching a blend endpoint",
          abs(ba.loc[d_rev] - bb.loc[d_rev]) > 1e-6,
          f"unrevised {ba.loc[d_rev]:.6f} vs revised {bb.loc[d_rev]:.6f}")

    # ---------- S3: tier-1 publication lag ----------
    t1 = prep_t1(_syn_t1())
    check("S3 tier-1 value invisible before publication_date (obs 06-15, pub 06-16)",
          t1_asof(t1, pd.Timestamp("2010-06-15")) == 0.0 and t1_asof(t1, pd.Timestamp("2010-06-16")) == 100.0)

    # ---------- S4: next-open fill honesty + exact cost arithmetic ----------
    days = pd.date_range("2020-01-01", periods=10, freq="B")
    A = "MKT"
    close = pd.DataFrame({A: [100.0] * 10}, index=days)
    open_ = close.copy()
    t_reb = days[4]
    close.iloc[5:] = 110.0
    open_.iloc[5:] = 110.0  # +10% overnight gap AFTER the rebalance decision
    w = pd.Series({A: 0.5})
    net = run_backtest(open_, close, {t_reb: w})
    r_fill = float(net.loc[days[5]])
    check("S4a overnight gap after the decision accrues to the OLD (empty) book",
          abs(r_fill - (-0.5 * ONE_WAY)) < 1e-15,
          f"fill-day ret {r_fill:.8f} == -turnover*6bp {-0.5 * ONE_WAY:.8f}; leaky close-fill would be {0.5 * 0.10 - 0.5 * ONE_WAY:.6f}")
    # pre-existing book: the OLD weights earn the gap
    net2 = run_backtest(open_, close, {days[1]: w, t_reb: w})
    r_fill2 = float(net2.loc[days[5]])
    check("S4b a pre-existing book DOES earn the gap (old-book accounting)",
          abs(r_fill2 - 0.5 * 0.10) < 1e-12, f"fill-day ret {r_fill2:.8f} == 0.05 (turnover 0)")
    # borrow accrual on a short book, flat prices
    flat_c = pd.DataFrame({A: [100.0] * 10}, index=days)
    net3 = run_backtest(flat_c, flat_c, {days[1]: pd.Series({A: -0.5})})
    r_borrow = float(net3.loc[days[3]])
    check("S4c short borrow accrues 50bp/yr / 252 on short gross",
          abs(r_borrow - (-0.5 * BORROW_DAILY)) < 1e-15, f"{r_borrow:.10f}")

    # ---------- S5: end-to-end PIT immunity through the FULL pipeline ----------
    # one market, growth theme only (synthetic indicator wired as EMPLOY), sign +1.
    vl5 = _syn_vintage(growth="accel_crash")
    days5 = pd.date_range("2004-01-01", "2012-12-31", freq="B")
    # deterministic non-constant prices (vol > 0 for sizing); macro drives weights only
    px = 100.0 * np.cumprod(1.0 + 0.005 * np.array([1 if i % 2 else -1 for i in range(len(days5))]))
    close5 = pd.DataFrame({"SPY": px}, index=days5)
    open5 = close5.copy()

    global INDICATORS, SIGN, MIN_BREADTH  # temporarily rewire the registry (restored below)
    saved = (INDICATORS, SIGN, MIN_BREADTH)
    try:
        INDICATORS = {"growth": [("EMPLOY", "t2", "log", +1)], "inflation": [], "policy": [], "dollar": []}
        SIGN = {"SPY": (+1, 0, 0, 0)}
        MIN_BREADTH = 1

        def pipeline(vlong: pd.DataFrame) -> dict[pd.Timestamp, pd.Series]:
            sources = {"EMPLOY": {"tier": "t2", "prep": prep_t2(vlong)}}
            grid = monthly_grid(close5.index, pd.Timestamp("2003-06-30"))
            ztab = indicator_z_table(sources, grid)
            th = theme_scores(ztab, grid)
            reb = grid[(grid >= days5[0]) & (grid <= days5[-1])]
            return rebalance_weights(th, close5, reb, ["SPY"])

        w_full = pipeline(vl5)
        # (i) truncating FUTURE vintages leaves all past weights byte-identical
        cutoff = pd.Timestamp("2010-01-31")
        w_trunc = pipeline(vl5[vl5["vintage_date"] <= cutoff].reset_index(drop=True))
        same = all(
            np.allclose(w_full[t].to_numpy(), w_trunc[t].to_numpy(), atol=0, rtol=0)
            for t in w_full if t <= cutoff and t in w_trunc
        )
        check("S5a full-pipeline PIT immunity: future vintages never alter past weights",
              same and sum(1 for t in w_full if t <= cutoff) > 12)
        # (ii) flat before z warmup (36 monthly obs from 2003-06 grid start => active ~2006-06)
        early = [t for t in sorted(w_full) if t < pd.Timestamp("2006-05-31")]
        check("S5b flat before the 36-month z warmup",
              all(float(w_full[t].abs().sum()) == 0.0 for t in early), f"{len(early)} early rebalances flat")
        # (iii) the macro crash (obs 2010-01.. published from vintage 2010-02-15) flips the
        # book short, and never before its first publication
        neg = [t for t in sorted(w_full) if float(w_full[t]["SPY"]) < -0.05]
        crash_neg = [t for t in neg if t >= pd.Timestamp("2010-02-15")]
        pre_crash_neg = [t for t in neg if t < pd.Timestamp("2010-02-15")]
        deep = [t for t in sorted(w_full) if pd.Timestamp("2010-08-01") <= t <= pd.Timestamp("2011-06-30")]
        check("S5c published crash flips the book short, never before publication",
              len(pre_crash_neg) == 0 and len(crash_neg) > 0
              and all(float(w_full[t]["SPY"]) < 0 for t in deep),
              f"first short {crash_neg[0].date() if crash_neg else 'never'}")
    finally:
        INDICATORS, SIGN, MIN_BREADTH = saved

    print("------------------------------------------------------------------------------")
    if failures:
        print(f"result: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("result: ALL SELF-TESTS PASS — spec pipeline is PIT-honest on synthetic data")
    return 0


# =============================================================================
# REAL RUN (the later, audited step — NOT executed in the authoring session)
# =============================================================================

def _load_real_sources() -> dict:
    t1dir, t2dir = LAKE_MACRO / "tier1_daily", LAKE_MACRO / "tier2_vintage"

    def t1(sid: str) -> dict:
        df = pd.read_parquet(t1dir / f"{sid}.parquet").rename(
            columns={"obs_date": "obs_period", "value": "value_first_release"})
        return prep_t1(df)

    sources: dict = {}
    for members in INDICATORS.values():
        for (name, tier, _tr, _d) in members:
            if tier == "t1":
                sources[name] = {"tier": "t1", "prep": t1(name)}
            elif tier == "t2":
                sources[name] = {"tier": "t2",
                                 "prep": prep_t2(pd.read_parquet(t2dir / f"{name}_vintage_long.parquet"))}
            elif tier == "splice":
                sources[name] = {"tier": "splice", "primary": t1("DTWEXBGS"), "fallback": t1("DTWEXM")}
    return sources


def _load_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    import glob
    opens, closes = {}, {}
    for m in SIGN:
        fs = sorted(glob.glob(str(LAKE_MF / f"ohlcv_1d/instrument_id=XUSE:CASH:{m}USD/**/*.parquet"), recursive=True))
        df = pd.concat([pd.read_parquet(f, columns=["ts_open", "open", "close"]) for f in fs])
        df = df.sort_values("ts_open").drop_duplicates("ts_open")
        idx = pd.to_datetime(df["ts_open"])
        idx = idx.dt.tz_localize(None) if idx.dt.tz is not None else idx
        opens[m] = pd.Series(df["open"].to_numpy(float), index=idx)
        closes[m] = pd.Series(df["close"].to_numpy(float), index=idx)
    o, c = pd.DataFrame(opens).sort_index(), pd.DataFrame(closes).sort_index()
    return o, c


def run_real() -> int:
    """The audited gauntlet run. Appends exactly ONE trial to var/experiments.jsonl."""
    from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns, summarize
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentLog

    print("ECON-TREND — REAL GAUNTLET (audited step). Spec locked 2026-07-11; publishing either way.")
    OUT.mkdir(parents=True, exist_ok=True)

    open_px, close_px = _load_prices()
    grid = monthly_grid(close_px.index, HISTORY_START)
    sources = _load_real_sources()
    print("computing indicator z table (monthly, PIT) ...")
    ztab = indicator_z_table(sources, grid)
    th = theme_scores(ztab, grid)
    reb_dates = grid[(grid >= BACKTEST_START) & (grid <= BACKTEST_END) & grid.isin(close_px.index)]
    weights = rebalance_weights(th, close_px, reb_dates, list(SIGN))
    if not weights:
        print("BLOCKER: no rebalance produced weights — report to auditor.")
        return 1
    era = close_px.index[(close_px.index >= BACKTEST_START) & (close_px.index <= BACKTEST_END)]
    net = run_backtest(open_px.loc[era], close_px.loc[era], weights)
    first_reb = min(weights)
    net = net.loc[first_reb:]

    oos = purged_wf_voltarget(net)
    eq_oos = equity_from_returns(oos)
    summ = summarize(eq_oos)
    d_rets = daily_returns(eq_oos)
    skew = float(((d_rets - d_rets.mean()) ** 3).mean() / d_rets.std(ddof=0) ** 3)
    summ_full = summarize(equity_from_returns(net))

    # ---- ledger: exactly ONE trial (idempotent on the SPEC hash), THEN headline DSR ----
    from alphaforge.core.time import now_ms
    log = ExperimentLog(LEDGER)
    sr_pp = float(d_rets.mean() / d_rets.std(ddof=1))
    log.record(SPEC, sharpe_ann=float(summ.sharpe), sharpe_per_period=sr_pp,
               n_obs=int(len(d_rets)), skew=skew,
               kurtosis=float(((d_rets - d_rets.mean()) ** 4).mean() / d_rets.std(ddof=0) ** 4),
               now_ms=now_ms())
    n_ledger = log.n_trials()
    dsr_ledger = dsr_from_returns(d_rets, n_ledger, log.trial_sharpe_variance(), DAYS_PER_YEAR)
    dsr_fresh = dsr_from_returns(d_rets, 2, 1.0, DAYS_PER_YEAR)

    # ---- pre-registered correlations (on the UNLEVERED net series) ----
    at = pd.read_parquet(ALPHATREND_EQ)
    at_ret = pd.Series(np.log(at["equity"].to_numpy(float)),
                       index=pd.to_datetime(at["ts"], unit="ms")).diff()
    j = pd.concat([net.rename("e"), at_ret.rename("a")], axis=1).dropna()
    corr_at = float(np.corrcoef(j["e"], j["a"])[0, 1]) if len(j) > 30 else float("nan")
    spy = close_px["SPY"].pct_change()
    js = pd.concat([net.rename("e"), spy.rename("s")], axis=1).dropna()
    corr_spy = float(np.corrcoef(js["e"], js["s"])[0, 1]) if len(js) > 30 else float("nan")

    # ---- pre-registered crisis table (vol-targeted OOS series) ----
    oos_dt = pd.Series(oos.to_numpy(), index=pd.DatetimeIndex(oos.index))
    crisis, pooled_e, pooled_s = {}, [], []
    for name, (a, bdt) in CRISIS_WINDOWS.items():
        seg = oos_dt.loc[a:bdt]
        spyseg = spy.loc[a:bdt].dropna()
        if len(seg) < 10:
            crisis[name] = {"n_days": int(len(seg)), "note": "insufficient OOS coverage"}
            continue
        eqw = (1 + seg).cumprod()
        crisis[name] = {
            "n_days": int(len(seg)),
            "sleeve_cum_ret": round(float(eqw.iloc[-1] - 1), 4),
            "sleeve_max_dd": round(float((eqw / eqw.cummax() - 1).min()), 4),
            "spy_cum_ret": round(float((1 + spyseg).prod() - 1), 4),
            "survives_loss_gate": bool(eqw.iloc[-1] - 1 > GATES["crisis_max_window_loss"]),
        }
        pooled_e.append(seg)
        pooled_s.append(spyseg)
    pooled_beat = (float(pd.concat(pooled_e).mean()) > float(pd.concat(pooled_s).mean())) if pooled_e else False
    crisis_ok = pooled_beat and all(c.get("survives_loss_gate", False) for c in crisis.values())

    gate_sharpe = float(summ.sharpe) >= GATES["adopt_min_net_sharpe"]
    gate_corr = corr_at < GATES["adopt_max_corr_alphatrend"]
    result = {
        "probe": "econtrend", "spec_version": SPEC["version"],
        "window": f"{net.index.min().date()}..{net.index.max().date()}",
        "n_oos_days": int(len(d_rets)), "n_rebalances": len(weights),
        "net_sharpe": round(float(summ.sharpe), 3),
        "net_sharpe_no_voltarget_fullsample": round(float(summ_full.sharpe), 3),
        "dsr_ledger": round(float(dsr_ledger.dsr), 3), "ledger_n": n_ledger,
        "dsr_fresh_trial": round(float(dsr_fresh.dsr), 3),
        "psr": round(float(dsr_fresh.psr), 3),
        "ann_vol": round(float(summ.vol_ann), 3), "max_dd": round(float(summ.max_dd), 3),
        "sortino": round(float(summ.sortino), 3), "cagr": round(float(summ.cagr), 3),
        "skew": round(skew, 3),
        "corr_to_alphatrend": round(corr_at, 3), "corr_to_spy": round(corr_spy, 3),
        "crisis_table": crisis, "crisis_pooled_beats_spy": pooled_beat,
        "gates": {"net_sharpe>=0.40": gate_sharpe, "corr_alphatrend<0.50": gate_corr,
                  "crisis_survival": crisis_ok},
        "ADOPT_CONSIDERATION": bool(gate_sharpe and gate_corr and crisis_ok),
        "one_way_cost_bps": 6.0,
    }
    (OUT / "econtrend_result.json").write_text(json.dumps(result, indent=2))
    net.to_frame("ret").to_parquet(OUT / "primary_daily_returns.parquet")
    oos.to_frame("ret").to_parquet(OUT / "oos_daily_returns.parquet")
    eq_oos.to_frame("equity").to_parquet(OUT / "equity.parquet")
    pd.DataFrame({str(t.date()): w for t, w in sorted(weights.items())}).T.to_parquet(OUT / "weights.parquet")
    th.to_parquet(OUT / "theme_scores.parquet")

    print("\n==================== ECONOMIC TREND — GAUNTLET (pre-registered) ====================")
    for k, v in result.items():
        print(f"  {k:36s}: {v}")
    print(f"  artifacts                           : {OUT}")
    print("=====================================================================================")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--run-real" in args:
        return run_real()
    print(__doc__)
    print("\nNothing run. Use --selftest (synthetic) or --run-real (audited step only).")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
