#!/usr/bin/env python3
"""PROBE — ALPHAMAX BETA-NEUTRAL CONSTRUCTION (is dollar-neutral != risk-neutral?).

2026-08-01. MEASURE-ONLY. NEW file; reads src/** as a template and calls its pure
kernels, mutates NOTHING in src/**, appends NO experiments-ledger trial (this is a cheap
construction SCREEN, not a production walk-forward). TRIALS BURNED = 0. DSR at the current
ledger N is read-only via dsr_from_returns (a pure function) for the deflated view.
Writes only artifacts/probe/alphamax_betaneutral/.

====================================================================================
THE HYPOTHESIS (pre-registered; from the campaign brief)
====================================================================================
The live ALPHAMAX book enforces Sigma_w = 0 (configs/equity.yaml dollar_neutral: true,
src/alphaforge/portfolio/optimizer.py RankEqualVolFallback). A book neutral on DOLLARS
need not be neutral on RISK: momentum losers (the short leg) are typically HIGHER beta
than momentum winners, so a dollar-neutral momentum book carries a persistent NEGATIVE
net market beta plus a short-junk/short-vol exposure. In a junk rally (July 2026: SPY
+1.0% on the month while the sleeve lost -7.75%, both legs losing at once) that is
exactly the wrong side. If true, this is a CONSTRUCTION defect, not a signal defect.

====================================================================================
PRE-REGISTERED SPEC — locked BEFORE any number in this file was computed
====================================================================================
DATA / PANEL
  * Lake: data/lake (profile `equity`), the survivorship-free Polygon day-agg lake,
    17.8k names, 1997-2026. PIT universe = UniverseStore intervals (~2,000-2,150 names
    concurrent, 2000-01 .. 2026-07), applied as a mask BEFORE any cross-sectional stat.
  * RESEARCH panel (primary): every PIT-ever-member with bars; K = 100/side
    (configs/equity.yaml portfolio.rank_top_k), quarterly 63-bar reform
    (signals.horizon_bars), inverse-vol weights, w_max 0.15, per-leg gross 0.50 (total
    gross 1.0). The book window was pre-registered as 2003-01-01..2026-07-30; the repo's
    own XNYSCalendar serves NO session before 2004-01-02, so after the 252-session
    momentum warm-up the earliest formable reform is 2005-01-03 and that is the book
    start actually used. See the WINDOW NOTE beside the RESEARCH dict. Consequence: the
    GFC (2008) and the 2000-02 tech unwind are OUT OF REACH — a stated limitation.
  * LIVE-REPLICA panel: the 375 instrument_ids of the deployed artifact
    artifacts/walkforward/k30_dn_63, K = 30/side, per-leg gross 0.345 (total 0.69 ==
    the artifact's realized gross_mean), book 2023-07-06 (first OOS leg) .. 2026-07-30 —
    i.e. the ACTUAL live construction, extended past the artifact's 2026-06-01 end so the
    July-2026 squeeze is inside the measured window.
  * Costs ALWAYS: 6 bp one-way (1 commission + 3 half-spread + 2 latency, equity.yaml)
    on every unit of |dw| INCLUDING the hedge leg, + 50 bp/yr GC borrow accrued daily on
    the short gross (stocks and, if ever short, the hedge). 0.001 no-trade band (base.yaml).
  * PIT: every weight/beta/hedge decided from data through the CLOSE of bar t is effective
    for bar t+1's return; the trade cost lands on t+1. No same-bar fills. No full-sample
    statistic enters any decision (the two full-sample numbers reported — the market-model
    alpha/beta regression and the CTRL_NETLONG constant — are labelled DIAGNOSTIC and
    deliberately generous to the null).

MARKET PROXY
  * SPY total-return closes from data/lake_mf (Yahoo adjclose; consecutive-day RATIOS are
    true total returns, so this is PIT-safe). Available 2001-06-27 .. 2026-07-30, which is
    what sets the 2003-01-01 book start (252-session beta warm-up + slack).

NAME BETAS (PIT)
  * beta_i(t) = cov(r_i, r_mkt) / var(r_mkt) over the trailing 252 sessions ending at t
    (pairwise-complete, min 120 joint obs; names below that are INELIGIBLE at that reform).
  * beta clipped to [-2, 4] (a data guard, non-binding for essentially every name).

ARMS (all share ONE simulator, one universe, one cost model, one return series)
  BASE   dollar-neutral inverse-vol K/side. The live construction. Sigma_w = 0.
  V1     BETA-NEUTRAL leg sizing. With bL, bS the inverse-vol-weighted mean betas of the
         two legs, set leg grosses gL = 2G*bS/(bL+bS) and gS = 2G*bL/(bL+bS). TOTAL gross
         is held at 2G (so vol/cost stay comparable), ex-ante portfolio beta = 0, and the
         book is deliberately NOT dollar-neutral: net dollar = gL - gS is reported.
         Ratio guard: gS/gL clipped to [0.5, 2.0].
  V2     BETA-HEDGED. The dollar-neutral BASE book is left byte-identical; an explicit
         market position h = -beta_book (beta_book = Sigma_i w_i beta_i) is added and
         re-sized at each quarterly reform. Hedge trades cost 6 bp one-way like any other.
  V2m    same as V2 but the hedge is re-sized every 21 bars (hedge staleness robustness) —
         an implementation question, not a fitted knob.
  CTRL_NETLONG  DIAGNOSTIC CONTROL, not a candidate: the dollar-neutral BASE book plus a
         CONSTANT long market position equal to V2's FULL-SAMPLE mean hedge. It deliberately
         uses look-ahead because its job is to be GENEROUS to the null hypothesis "the whole
         gain is just being statically net long the market". If a variant cannot beat this,
         it has not demonstrated that DYNAMIC beta neutralisation is what earned the gain.
  V3     NOT an arm — the DIAGNOSTIC that tests the premise: the realized net beta of the
         BASE book, rolling 63-session OLS of its daily net returns on the market. Reported
         FIRST. If BASE's beta is already ~0, the hypothesis is dead and this probe says so.
  BASE_asis  reference arm: BASE re-run on the repo's own (split-broken) price panel — see
         the DATA-INTEGRITY FINDING below.

PRE-REGISTERED GATE (locked before computing; an honest NULL is a full success)
  STEP 0 — PREMISE. The hypothesis SURVIVES only if BASE's realized net beta is
    mean(rolling 63d beta) <= -0.05 AND negative in >= 60% of rolling windows.
    Otherwise: premise DEAD, report that plainly, and V1/V2 cannot be adopted whatever
    their Sharpe (a fix for a defect that does not exist is a fitted artefact).
  STEP 1 — ADOPTION. A variant is ADOPTED only if ALL of A-F hold:
    A BETA      |mean rolling beta| <= 0.05 AND |mean beta| cut by >= 50% vs BASE.
    B SHARPE    full-window net Sharpe >= BASE - 0.10 (must not COST Sharpe; need not gain).
    C TAIL      the WORST pre-registered stress episode's within-episode maxDD improves by
                >= 25% relative vs BASE, AND no episode's maxDD worsens by > 2.0 pp.
    D NOT WINDOW-FITTED  within-episode maxDD improves in >= 4 of the 7 episode windows AND
                in >= 3 of the 6 NON-2026-07 windows. (July 2026 is ONE episode; a variant
                that only helps there is window-fitted and is REJECTED here by construction.)
    E COST      turnover_ann up by <= 25% relative AND (cost+borrow) drag up by <= 25%.
    F HONESTY   the variant beats CTRL_NETLONG by >= 0.05 net Sharpe OR has a >= 10%
                relatively better worst-episode maxDD than CTRL_NETLONG.
  Verdict: all of A-F -> ADOPT. A-D but E or F marginal -> ADOPT-MARGINAL. Otherwise
  HONEST-NULL (or WORSE if Sharpe drops materially).

PRE-REGISTERED STRESS EPISODES (all of history, not just the recent one)
  2009 momentum crash (2009-03-01..2009-05-31) and its wider H1 (2009-01-01..2009-06-30);
  2020 Covid crash (2020-02-15..2020-04-30); 2020-11 vaccine rotation (2020-11-01..30);
  2021 meme squeeze (2021-01-01..2021-03-31); 2022 bear (full year); 2026-07 junk squeeze
  (2026-07-01..2026-07-30).

====================================================================================
DATA-INTEGRITY FINDING FOUND WHILE BUILDING THIS PROBE (disclosed, NOT silently worked
around; src/** NOT modified)
====================================================================================
src/alphaforge/features/library/equity_price.py::adjusted_close applies the split factor
in the WRONG DIRECTION. Polygon's stored `ratio` is split_to/split_from (a 4-for-1 split
stores 4.0; a 1-for-20 reverse split stores 0.05 — see
src/alphaforge/data/sources/polygon_source.py::_split_ratio). To express a PRE-ex bar in
POST-split share terms the pre-ex close must be MULTIPLIED BY 1/ratio; the kernel
multiplies by `ratio`:

    factor[applies, j] *= float(a_ratio[k])        # equity_price.py, the split branch

Verified on the panel the engine actually serves:
    AAPL 2020-08-31 (4-for-1): adjusted close 1996.92 on 08-28 -> 129.04 on 08-31
        (raw 499.23 * 4 instead of / 4)  => a fake -93.5% one-day return.
    TSLA 2020-08-31 (5-for-1): 11067.00 -> 498.32                => a fake -95.5%.
    ALIT 2026-07-01 (1-for-20 reverse): pre-ex closes divided by 20 => a fake +490x.
5,132 splits sit in data/lake/corporate_actions (~100-200/yr recently), and each one
corrupts that name's 12-1 momentum for the whole 252-session lookback that straddles the
ex-date: computed_mom = true_mom - 2*ln(ratio). A 4-for-1 splitter is pushed -2.77 in log
momentum (straight into the SHORT leg — i.e. the book systematically SHORTS the winners
that just split) and a 1-for-20 reverse-splitter is pushed +6.0 (straight into the LONG
leg — the book systematically BUYS the most distressed names). At K=100/side out of ~2,000
names, the slice of the cross-section carrying a live split artefact is more than enough to
crowd out the genuine tails.

CONSEQUENCE FOR THIS PROBE: a construction A/B run on split-broken prices would be
measuring the wrong book. So this probe runs BOTH panels through identical machinery:
  * FIXED (primary): the same repo kernel called with the split ratios inverted
    (ratio -> 1/ratio) in a LOCAL COPY of the actions frame — src is untouched, only the
    input is repaired. Signal, returns, vol and betas all come from this panel.
  * AS-IS (reference): the repo's own `_adjusted_close_panel` / `eq_mom_252_21`, i.e.
    exactly what the live sleeve trades on today. Run for BASE only, to size the bug.
Because every arm inside a panel shares one return series, the A/B is internally valid on
either panel; the FIXED panel is the decision-relevant one because nobody would adopt a
construction change on top of a signal that is known to be inverted on split names.

RETURN HYGIENE (identical for every arm, both panels): daily returns clipped to
[-0.5, +1.0]; any |ret| > 3.0 (an unrepaired corporate-action artefact) is set to 0.0 and
COUNTED in the report.

    uv run python scripts/probe_alphamax_betaneutral.py                # both panels
    uv run python scripts/probe_alphamax_betaneutral.py --panel live   # live replica only
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_betaneutral"
K30_WF = _REPO / "artifacts" / "walkforward" / "k30_dn_63" / "walkforward.json"
SPY_GLOB = "data/lake_mf/ohlcv_1d/instrument_id=XUSE:CASH:SPYUSD/*/*.parquet"

# ---- construction constants (configs/equity.yaml, configs/base.yaml, optimizer.py) ----
ANN = 365.0             # repo headline annualization basis (matches stored summaries)
TRADING_DAYS = 252.0    # borrow accrual + the honest calendar-Sharpe cross-check
VOL_WINDOW = 63         # trailing sessions for the inverse-vol denominator
VOL_MINP = 30
W_MAX = 0.15            # portfolio.w_max
COST_ONEWAY = 6e-4      # 1bp commission + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4      # 50 bp/yr GC borrow on the short gross (equity.yaml)
NO_TRADE_BAND = 0.001   # base.yaml no_trade_band
REFORM_BARS = 63        # rebalance_bars (quarterly production cadence)
HEDGE_RESET_BARS = 21   # V2m monthly hedge refresh
BETA_WINDOW = 252       # trailing sessions for the PIT name-beta regression
BETA_MINOBS = 120       # min joint obs before a name's beta is trusted
BETA_CLIP = (-2.0, 4.0)
ROLL_BETA_WINDOW = 63   # realized-beta diagnostic window (63d, the production horizon)
ROLL_BETA_MINP = 40
RET_CLIP = (-0.5, 1.0)  # template return hygiene (repo precedent)
RET_ARTEFACT = 3.0      # |ret| beyond this = unrepaired corporate action -> flattened, counted
LEG_RATIO_CLIP = (0.5, 2.0)   # V1 guard on gS/gL

# WINDOW NOTE (mechanical, disclosed — not a window search): the pre-registration asked for a
# 2003-01-01 book start, but src/alphaforge/config/sleeve.py's XNYSCalendar has NO sessions
# before 2004-01-02 (verified: expected_bar_opens returns 0 sessions for any range ending
# before then), so the engine cannot serve a single equity bar earlier. That caps the panel at
# 2004-01-02, and the 252-session momentum warm-up then makes 2005-01-03 the first session on
# which a reform can actually be formed. The book start is therefore 2005-01-03 — the earliest
# date the repo's own spine permits, chosen by that constraint alone. Every pre-registered
# stress episode except nothing is still inside the window (2009, 2020, 2020-11, 2021, 2022,
# 2026-07 all covered); the GFC/2008 and the 2000-02 tech unwind are NOT reachable and this is
# a stated limitation of the result, not a choice.
RESEARCH = {"panel_start": "2004-01-01", "book_start": "2005-01-03", "end": "2026-08-01",
            "K": 100, "gross_leg": 0.50}
LIVE = {"panel_start": "2021-01-01", "book_start": "2023-07-06", "end": "2026-08-01",
        "K": 30, "gross_leg": 0.345}

EPISODES: list[tuple[str, str, str]] = [
    ("2009 mom crash Mar-May", "2009-03-01", "2009-05-31"),
    ("2009 H1 wider", "2009-01-01", "2009-06-30"),
    ("2020 Covid crash", "2020-02-15", "2020-04-30"),
    ("2020-11 vaccine rot.", "2020-11-01", "2020-11-30"),
    ("2021 meme squeeze Q1", "2021-01-01", "2021-03-31"),
    ("2022 bear", "2022-01-01", "2022-12-31"),
    ("2026-07 junk squeeze", "2026-07-01", "2026-07-30"),
]
JULY26 = "2026-07 junk squeeze"
ARM_ORDER = ("BASE", "V1_betaneutral", "V2_betahedged", "V2m_hedge_21d", "CTRL_NETLONG", "BASE_asis")
CANDIDATES = ("V1_betaneutral", "V2_betahedged", "V2m_hedge_21d")


# ============================================================== probe feature specs
def _fixed_panel(ctx):
    """The repo's own adjusted-close kernel, fed a LOCAL COPY of the actions frame whose
    SPLIT ratios are inverted (ratio -> 1/ratio). src/** is untouched: only the input is
    repaired. See the module docstring's DATA-INTEGRITY FINDING."""
    from alphaforge.core.time import Timeframe
    from alphaforge.features.library.equity_price import adjusted_close

    raw = ctx.panel("close")
    actions = ctx.corporate_actions()
    if actions.empty:
        return raw
    a = actions.copy()
    is_split = a["action_type"].to_numpy(dtype=object) == "split"
    r = a["ratio"].to_numpy(dtype="float64").copy()
    ok = is_split & np.isfinite(r) & (r > 0.0)
    r[ok] = 1.0 / r[ok]
    a["ratio"] = r
    return adjusted_close(raw, a, tf_ms=Timeframe.D1.ms, include_dividends=False)


def _mom_fix_fn(ctx, spec):
    from alphaforge.features.context import long_series
    from alphaforge.features.library.momentum import xs_momentum

    return long_series(xs_momentum(_fixed_panel(ctx), lookback=252, skip=21), name=spec.name)


def _dret_fix_fn(ctx, spec):
    from alphaforge.features.context import long_series

    return long_series(_fixed_panel(ctx).pct_change(), name=spec.name)


def _dret_asis_fn(ctx, spec):
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel

    return long_series(_adjusted_close_panel(ctx).pct_change(), name=spec.name)


def _register(reg) -> None:
    from alphaforge.features.spec import Family, FeatureSpec

    have = {s.name for s in reg.all_specs()}
    for nm, fn, lb in (("probe_mom_fix", _mom_fix_fn, 253),
                       ("probe_dret_fix", _dret_fix_fn, 2),
                       ("probe_dret_asis", _dret_asis_fn, 2)):
        if nm in have:
            continue
        reg.register(lambda nm=nm, fn=fn, lb=lb: FeatureSpec(
            name=nm, family=Family.MOMENTUM, direction=1, cross_sectional=False,
            lookback_bars=lb, params={}, fn=fn))


# ===================================================================== panel builder
def build_panels(profile: str, ids_filter: set[str] | None, panel_start: str, end: str,
                 chunk_years: int) -> dict:
    """Wide float64 panels (index = session epoch-ms, columns = instrument ids).

    Computed in multi-year CHUNKS: every chunk's FeatureContext carries its own >=252-session
    warm-up, so momentum/returns at a chunk's first output row are already real and the split
    adjustment inside each chunk is self-consistent (a split just past a chunk edge is served
    by the NEXT chunk's warm-up window, so the pct_change across the edge is still correct).
    """
    import alphaforge.features.library  # noqa: F401
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research.ic_report import _membership_mask

    settings = load_settings(profile)
    tf = sleeve_for(settings.data.asset_class).anchor_tf
    reg = default_registry()
    _register(reg)
    by = {s.name: s for s in reg.all_specs()}
    specs = [by["probe_mom_fix"], by["probe_dret_fix"], by["eq_mom_252_21"], by["probe_dret_asis"]]

    lo0 = pd.Timestamp(panel_start, tz="UTC")
    hi0 = pd.Timestamp(end, tz="UTC")
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cur = lo0
    while cur < hi0:
        nxt = min(cur + pd.DateOffset(years=chunk_years), hi0)
        windows.append((cur, nxt))
        cur = nxt

    paths = LakePaths(settings.paths.lake_dir)
    chunks: list[pd.DataFrame] = []
    masks: list[pd.Series] = []
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        engine = FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class)
        members = set(universe.read_intervals().column("instrument_id").to_pylist())
        in_lake = set(paths.instrument_ids(ohlcv_dataset(tf)))
        ids = sorted(i for i in (members & in_lake) if i.startswith("XUSE"))
        if ids_filter is not None:
            ids = sorted(set(ids) & ids_filter)
        print(f"  universe: {len(ids)} PIT-ever-member equity ids with bars | panel {panel_start}..{end} | tf={tf.name}")
        for lo, hi in windows:
            raw = engine.compute_history(
                specs, ids,
                start=parse_utc(lo.strftime("%Y-%m-%dT00:00:00Z")),
                end=parse_utc(hi.strftime("%Y-%m-%dT00:00:00Z")),
            )
            masks.append(_membership_mask(universe, raw))
            chunks.append(raw)
            print(f"    chunk {lo.date()}..{hi.date()}: {len(raw):,} rows")
            del raw
            gc.collect()

    raw = pd.concat(chunks, axis=0)
    mask = pd.concat(masks, axis=0)
    chunks.clear()
    masks.clear()
    gc.collect()

    out: dict = {}
    for key, col in (("mom_fix", "probe_mom_fix"), ("ret_fix", "probe_dret_fix"),
                     ("mom_asis", "eq_mom_252_21"), ("ret_asis", "probe_dret_asis")):
        out[key] = raw[col].unstack("instrument_id").sort_index()
    ref = out["mom_fix"]
    out["member"] = mask.unstack("instrument_id").reindex(index=ref.index, columns=ref.columns,
                                                          fill_value=False)
    for k in ("ret_fix", "mom_asis", "ret_asis"):
        out[k] = out[k].reindex(index=ref.index, columns=ref.columns)
    del raw, mask
    gc.collect()
    return out


def load_market(dates_ms: np.ndarray) -> tuple[np.ndarray, int]:
    """SPY total-return daily returns aligned to the panel's session grid (NaN where SPY has
    no bar on that session). Yahoo adjclose => consecutive-day ratios are true total returns."""
    files = sorted(_REPO.glob(SPY_GLOB))
    if not files:
        raise FileNotFoundError(f"market proxy missing: {SPY_GLOB}")
    d = pd.concat([pd.read_parquet(f) for f in files]).sort_values("ts_open")
    d = d.drop_duplicates(subset="ts_open", keep="last")
    ts = d["ts_open"].to_numpy().astype("datetime64[ms]").astype("int64")
    px = pd.Series(d["close"].to_numpy(dtype=np.float64), index=ts)
    aligned = px.pct_change().reindex(dates_ms)
    return aligned.to_numpy(dtype=np.float64), int(np.isnan(aligned.to_numpy()).sum())


# ======================================================================= PIT betas
def betas_at_index(ret: np.ndarray, mkt: np.ndarray, t: int) -> np.ndarray:
    """PIT trailing-252-session OLS beta of every column on the market, using ONLY rows
    <= t (pairwise complete, min BETA_MINOBS joint obs). NaN where not estimable."""
    lo = max(0, t - BETA_WINDOW + 1)
    X = ret[lo:t + 1, :]
    m = mkt[lo:t + 1]
    ok_m = np.isfinite(m)
    okX = np.isfinite(X) & ok_m[:, None]
    Xs = np.where(okX, X, 0.0)
    ms = np.where(ok_m, m, 0.0)[:, None]
    n = okX.sum(axis=0).astype(np.float64)
    Sx = Xs.sum(axis=0)
    Sm = (ms * okX).sum(axis=0)
    Sxm = (Xs * ms).sum(axis=0)
    Smm = ((ms ** 2) * okX).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = Sxm - Sx * Sm / n
        var = Smm - Sm ** 2 / n
        beta = cov / var
    beta = np.where((n >= BETA_MINOBS) & np.isfinite(beta) & (var > 0), beta, np.nan)
    return np.clip(beta, BETA_CLIP[0], BETA_CLIP[1])


# ==================================================================== construction
def _leg_weights(sel: np.ndarray, invvol: np.ndarray, sign: float, gross: float) -> np.ndarray:
    """Inverse-vol weights for one leg, |Sigma| = gross, +-W_MAX clipped, per-leg renorm —
    mirrors src/alphaforge/portfolio/optimizer.py::RankEqualVolFallback."""
    w = np.zeros_like(invvol)
    if not sel.any() or gross <= 0.0:
        return w
    w[sel] = sign * invvol[sel]
    g = float(np.abs(w[sel]).sum())
    if g <= 0.0:
        return np.zeros_like(invvol)
    w[sel] *= gross / g
    w = np.clip(w, -W_MAX, W_MAX)
    g2 = float(np.abs(w[sel]).sum())
    ma = float(np.abs(w[sel]).max())
    if g2 > 0.0 and ma > 0.0:
        w[sel] *= min(gross / g2, W_MAX / ma)
    return w


def clean_returns(ret: np.ndarray) -> tuple[np.ndarray, int]:
    """Arm-independent return hygiene: NaN -> 0, |r| > RET_ARTEFACT -> 0 (unrepaired
    corporate action), then clip to RET_CLIP. Returns the cleaned panel + artefact count."""
    r = np.where(np.isfinite(ret), ret, 0.0)
    n_art = int(np.sum(np.abs(r) > RET_ARTEFACT))
    r = np.where(np.abs(r) > RET_ARTEFACT, 0.0, r)
    return np.clip(r, RET_CLIP[0], RET_CLIP[1]), n_art


def simulate(mom, ret_use, member, vol, mkt_use, betas, dates, t0, *, K, gross_leg,
             sizing="dollar", hedge_mode=None, hedge_static=0.0) -> dict:
    """One arm. `betas` maps a bar index -> the PIT name-beta vector at that bar.

    sizing:      'dollar' (Sigma w = 0)  |  'beta' (ex-ante portfolio beta = 0, gross held at 2G)
    hedge_mode:  None | 'reform' (resize at each reform) | 'monthly' (every HEDGE_RESET_BARS)
                 | 'static' (constant hedge_static, entered at the first reform, never re-sized)
    """
    T, N = mom.shape
    finite_vol = np.isfinite(vol) & (vol > 0)
    eligible_all = member & np.isfinite(mom) & finite_vol

    reb = set(range(t0, T, REFORM_BARS))
    hedge_reset = set(range(t0, T, HEDGE_RESET_BARS)) if hedge_mode == "monthly" else set()

    w = np.zeros(N, dtype=np.float64)
    w_prev = np.zeros(N, dtype=np.float64)
    h = 0.0
    net = np.full(T, np.nan)
    gross_r = np.full(T, np.nan)
    netdollar = np.full(T, np.nan)
    pending_cost = 0.0
    turnovers: list[float] = []
    hedges: list[float] = []
    exante_hedge: list[float] = []
    legbetas: list[tuple[float, float]] = []
    legcounts: list[tuple[int, int]] = []
    borrow_total = cost_total = 0.0

    for t in range(t0, T):
        g = float((w * ret_use[t]).sum()) + h * mkt_use[t]
        gross_r[t] = g
        netdollar[t] = float(w.sum()) + h
        short_gross = float(-np.minimum(w, 0.0).sum()) + max(-h, 0.0)
        borrow_t = short_gross * (BORROW_ANN / TRADING_DAYS)
        net[t] = g - borrow_t - pending_cost
        borrow_total += borrow_t
        cost_total += pending_cost
        pending_cost = 0.0

        do_reform = t in reb
        do_hedge_only = (not do_reform) and (t in hedge_reset)
        if not (do_reform or do_hedge_only):
            continue
        b = betas.get(t)
        if b is None:
            continue

        if do_reform:
            elig = eligible_all[t] & np.isfinite(b)
            n_elig = int(elig.sum())
            if n_elig < 4 * K:
                continue
            ei = np.where(elig)[0]
            order = ei[np.argsort(-mom[t][ei], kind="stable")]
            long_sel = np.zeros(N, dtype=bool)
            short_sel = np.zeros(N, dtype=bool)
            long_sel[order[:K]] = True
            short_sel[order[-K:]] = True
            short_sel &= ~long_sel

            invvol = np.where(finite_vol[t], 1.0 / np.where(vol[t] > 0, vol[t], np.nan), 0.0)
            invvol = np.nan_to_num(invvol, nan=0.0, posinf=0.0, neginf=0.0)
            wl = _leg_weights(long_sel, invvol, +1.0, gross_leg)
            ws = _leg_weights(short_sel, invvol, -1.0, gross_leg)
            bl = float((wl * b).sum()) / gross_leg
            bs = float((-ws * b).sum()) / gross_leg
            legbetas.append((bl, bs))
            legcounts.append((int(long_sel.sum()), int(short_sel.sum())))

            if sizing == "beta" and np.isfinite(bl) and np.isfinite(bs) and bl > 0.0 and bs > 0.0:
                tot = 2.0 * gross_leg
                ratio = min(max(bl / bs, LEG_RATIO_CLIP[0]), LEG_RATIO_CLIP[1])  # gS/gL
                gl = tot / (1.0 + ratio)
                gs = tot - gl
                wl = _leg_weights(long_sel, invvol, +1.0, gl)
                ws = _leg_weights(short_sel, invvol, -1.0, gs)

            new_w = wl + ws
            small = np.abs(new_w - w_prev) <= NO_TRADE_BAND
            new_w = np.where(small, w_prev, new_w)
        else:
            new_w = w_prev

        beta_book = float((new_w * np.nan_to_num(b, nan=0.0)).sum())
        exante_hedge.append(-beta_book)
        if hedge_mode in ("reform", "monthly"):
            new_h = -beta_book
        elif hedge_mode == "static":
            new_h = float(hedge_static)
        else:
            new_h = 0.0

        turnover = float(np.abs(new_w - w_prev).sum()) + abs(new_h - h)
        turnovers.append(turnover)
        pending_cost = turnover * COST_ONEWAY
        hedges.append(new_h)
        w = new_w
        w_prev = new_w
        h = new_h

    idx = dates[t0:]
    net_s = pd.Series(net[t0:], index=idx).dropna()
    n_days = len(net_s)
    return {
        "net": net_s,
        "gross": pd.Series(gross_r[t0:], index=idx).dropna(),
        "netdollar": pd.Series(netdollar[t0:], index=idx).dropna(),
        "turnover_ann": (float(np.sum(turnovers)) / n_days * ANN) if n_days else float("nan"),
        "cost_drag_ann_bps": (cost_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "borrow_drag_ann_bps": (borrow_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "n_reforms": len(turnovers),
        "avg_long_names": float(np.mean([x for x, _ in legcounts])) if legcounts else float("nan"),
        "avg_short_names": float(np.mean([y for _, y in legcounts])) if legcounts else float("nan"),
        "legbeta_long": float(np.nanmean([x for x, _ in legbetas])) if legbetas else float("nan"),
        "legbeta_short": float(np.nanmean([y for _, y in legbetas])) if legbetas else float("nan"),
        "legbeta_spread_min": float(np.nanmin([x - y for x, y in legbetas])) if legbetas else float("nan"),
        "legbeta_spread_max": float(np.nanmax([x - y for x, y in legbetas])) if legbetas else float("nan"),
        "legbeta_spread_frac_neg": float(np.mean([1.0 if (x - y) < 0 else 0.0 for x, y in legbetas])) if legbetas else float("nan"),
        "exante_hedge_mean": float(np.mean(exante_hedge)) if exante_hedge else float("nan"),
        "hedge_mean": float(np.mean(hedges)) if hedges else 0.0,
        "hedge_min": float(np.min(hedges)) if hedges else 0.0,
        "hedge_max": float(np.max(hedges)) if hedges else 0.0,
        "n_days": n_days,
    }


# ========================================================================== metrics
def _sharpe(v: np.ndarray) -> float:
    if v.size < 2:
        return float("nan")
    sd = float(np.std(v, ddof=1))
    return float(np.mean(v)) / sd * math.sqrt(ANN) if sd > 0 else float("nan")


def block_bootstrap_dsharpe(arm: np.ndarray, base: np.ndarray, block: int = 63,
                            n_boot: int = 2000, seed: int = 7) -> dict:
    """Moving-block bootstrap of the PAIRED net-Sharpe difference (arm - BASE).

    Blocks of `block` consecutive sessions are drawn with replacement and applied to BOTH
    series with the SAME index draw, so the two books stay paired and their (very high)
    correlation is preserved — the resulting interval is on the DIFFERENCE, not on either
    Sharpe alone. Block length 63 = the quarterly rebalance cadence (one holding period)."""
    T = arm.size
    if 4 * block > T:
        return {"mean": float("nan"), "p05": float("nan"), "p95": float("nan"),
                "frac_le_zero": float("nan"), "n_boot": 0}
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    off = np.arange(block)
    diffs = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        starts = rng.integers(0, T - block + 1, nb)
        idx = (starts[:, None] + off[None, :]).ravel()[:T]
        diffs[i] = _sharpe(arm[idx]) - _sharpe(base[idx])
    return {"mean": float(np.mean(diffs)), "p05": float(np.quantile(diffs, 0.05)),
            "p95": float(np.quantile(diffs, 0.95)),
            "frac_le_zero": float(np.mean(diffs <= 0.0)), "n_boot": n_boot}


def _maxdd(v: np.ndarray) -> float:
    if v.size == 0:
        return float("nan")
    eq = np.cumprod(1.0 + v)
    return float(np.max(1.0 - eq / np.maximum.accumulate(eq)))


def _nw_ols(y: np.ndarray, x: np.ndarray, lags: int = 5) -> tuple[float, float, float, float]:
    """OLS y = a + b*x with Newey-West (Bartlett) SEs. Returns (alpha, t_alpha, beta, t_beta)."""
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = y.size
    if n < 30:
        return (float("nan"),) * 4
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.pinv(X.T @ X)
    coef = XtX_inv @ (X.T @ y)
    e = y - X @ coef
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lags + 1):
        wgt = 1.0 - L / (lags + 1.0)
        G = Xe[L:].T @ Xe[:-L]
        S += wgt * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        t = coef / se
    return float(coef[0]), float(t[0]), float(coef[1]), float(t[1])


def metrics(sim: dict, mkt_s: pd.Series) -> dict:
    net = sim["net"]
    v = net.to_numpy(dtype=np.float64)
    g = sim["gross"].to_numpy(dtype=np.float64)
    sd = float(np.std(v, ddof=1))
    m = mkt_s.reindex(net.index).to_numpy(dtype=np.float64)
    alpha, t_alpha, beta_fs, t_beta = _nw_ols(v, m)
    j = pd.concat([net.rename("r"), pd.Series(m, index=net.index).rename("m")], axis=1)
    cov = j["r"].rolling(ROLL_BETA_WINDOW, min_periods=ROLL_BETA_MINP).cov(j["m"])
    var = j["m"].rolling(ROLL_BETA_WINDOW, min_periods=ROLL_BETA_MINP).var()
    rb = (cov / var).replace([np.inf, -np.inf], np.nan).dropna()
    nd = sim["netdollar"]
    out = {
        "net_sharpe_ann365": float(np.mean(v)) / sd * math.sqrt(ANN) if sd > 0 else float("nan"),
        "net_sharpe_ann252": float(np.mean(v)) / sd * math.sqrt(TRADING_DAYS) if sd > 0 else float("nan"),
        "gross_sharpe_ann365": float(np.mean(g)) / float(np.std(g, ddof=1)) * math.sqrt(ANN),
        "vol_ann365": sd * math.sqrt(ANN),
        "max_dd": _maxdd(v),
        "skew": float(pd.Series(v).skew()),
        "cagr": float(np.prod(1.0 + v)) ** (TRADING_DAYS / len(v)) - 1.0 if len(v) else float("nan"),
        "total_return": float(np.prod(1.0 + v)) - 1.0,
        "roll_beta_mean": float(rb.mean()), "roll_beta_median": float(rb.median()),
        "roll_beta_p10": float(rb.quantile(0.10)), "roll_beta_p90": float(rb.quantile(0.90)),
        "roll_beta_frac_neg": float((rb < 0).mean()), "roll_beta_n": int(rb.size),
        "fullsample_beta": beta_fs, "fullsample_beta_t": t_beta,
        "alpha_ann365_bps": alpha * ANN * 1e4, "alpha_t_nw": t_alpha,
        "netdollar_mean": float(nd.mean()), "netdollar_min": float(nd.min()),
        "netdollar_max": float(nd.max()),
        "episodes": episode_table(net),
    }
    for k in ("turnover_ann", "cost_drag_ann_bps", "borrow_drag_ann_bps", "n_reforms", "n_days",
              "avg_long_names", "avg_short_names", "legbeta_long", "legbeta_short",
              "legbeta_spread_min", "legbeta_spread_max", "legbeta_spread_frac_neg",
              "hedge_mean", "hedge_min", "hedge_max", "exante_hedge_mean"):
        out[k] = sim[k]
    out["_net"] = net
    return out


def episode_table(net: pd.Series) -> dict:
    s = pd.Series(net.to_numpy(), index=pd.to_datetime(net.index, unit="ms", utc=True))
    out = {}
    for label, lo, hi in EPISODES:
        w = s.loc[(s.index >= pd.Timestamp(lo, tz="UTC")) & (s.index <= pd.Timestamp(hi, tz="UTC"))]
        v = w.to_numpy(dtype=np.float64)
        out[label] = {"n_days": int(v.size),
                      "total_return": float(np.prod(1.0 + v) - 1.0) if v.size else float("nan"),
                      "max_dd": _maxdd(v),
                      "worst_day": float(np.min(v)) if v.size else float("nan")}
    return out


# =========================================================================== driver
def run_panel(tag: str, cfg: dict, profile: str, ids_filter, chunk_years: int) -> dict:
    print(f"\n### PANEL {tag} ###")
    P = build_panels(profile, ids_filter, cfg["panel_start"], cfg["end"], chunk_years)
    ref = P["mom_fix"]
    dates_all = ref.index.to_numpy(dtype=np.int64)
    mkt_all, n_miss = load_market(dates_all)
    last_ok = int(np.max(np.where(np.isfinite(mkt_all))[0]))  # SPY ends 1 session before the lake
    sl = slice(0, last_ok + 1)
    dates = dates_all[sl]
    mkt = mkt_all[sl]
    mom_fix = ref.to_numpy(dtype=np.float64)[sl]
    ret_fix_raw = P["ret_fix"].to_numpy(dtype=np.float64)[sl]
    mom_asis = P["mom_asis"].to_numpy(dtype=np.float64)[sl]
    ret_asis_raw = P["ret_asis"].to_numpy(dtype=np.float64)[sl]
    member = P["member"].to_numpy(dtype=bool)[sl]
    del P
    gc.collect()

    vol_fix = (pd.DataFrame(ret_fix_raw).rolling(VOL_WINDOW, min_periods=VOL_MINP).std()
               * math.sqrt(ANN)).to_numpy(dtype=np.float64)
    vol_asis = (pd.DataFrame(ret_asis_raw).rolling(VOL_WINDOW, min_periods=VOL_MINP).std()
                * math.sqrt(ANN)).to_numpy(dtype=np.float64)
    ret_fix, n_art_fix = clean_returns(ret_fix_raw)
    ret_asis, n_art_asis = clean_returns(ret_asis_raw)
    del ret_fix_raw, ret_asis_raw
    gc.collect()
    mkt_use = np.where(np.isfinite(mkt), mkt, 0.0)

    both = np.isfinite(mom_fix) & np.isfinite(mom_asis)
    mom_diff = both & (np.abs(mom_fix - mom_asis) > 1e-9)
    diff_pct = float(mom_diff.sum()) / max(1, int(both.sum()))
    print(f"  sessions T={len(dates)} ({pd.Timestamp(dates[0], unit='ms').date()} .. "
          f"{pd.Timestamp(dates[-1], unit='ms').date()}) x N={mom_fix.shape[1]} | market-NaN sessions {n_miss}")
    print(f"  SPLIT-BUG SIZE: 12-1 momentum cells where FIXED != AS-IS: {diff_pct:.2%} of jointly-finite "
          f"cells ({int(mom_diff.sum()):,}) | |ret|>{RET_ARTEFACT:.0f} artefact cells fixed {n_art_fix:,} "
          f"vs as-is {n_art_asis:,}")

    t0 = int(np.searchsorted(dates, int(pd.Timestamp(cfg["book_start"], tz="UTC").value // 10**6),
                             side="left"))
    print(f"  book t0 idx={t0} ({cfg['book_start']}) -> {len(dates) - t0} sessions | "
          f"K={cfg['K']}/side gross_leg={cfg['gross_leg']}")

    reform_idx = sorted(set(range(t0, len(dates), REFORM_BARS))
                        | set(range(t0, len(dates), HEDGE_RESET_BARS)))
    print(f"  estimating PIT trailing-{BETA_WINDOW}d betas at {len(reform_idx)} decision bars ...")
    betas = {t: betas_at_index(ret_fix, mkt, t) for t in reform_idx}
    betas_asis = {t: betas_at_index(ret_asis, mkt, t)
                  for t in sorted(set(range(t0, len(dates), REFORM_BARS)))}

    mkt_s = pd.Series(mkt, index=dates)
    common = {"K": cfg["K"], "gross_leg": cfg["gross_leg"]}
    args_fix = (mom_fix, ret_fix, member, vol_fix, mkt_use, betas, dates, t0)

    sims: dict = {}
    sims["BASE"] = simulate(*args_fix, sizing="dollar", hedge_mode=None, **common)
    sims["V1_betaneutral"] = simulate(*args_fix, sizing="beta", hedge_mode=None, **common)
    sims["V2_betahedged"] = simulate(*args_fix, sizing="dollar", hedge_mode="reform", **common)
    sims["V2m_hedge_21d"] = simulate(*args_fix, sizing="dollar", hedge_mode="monthly", **common)
    h_static = float(sims["V2_betahedged"]["hedge_mean"])
    sims["CTRL_NETLONG"] = simulate(*args_fix, sizing="dollar", hedge_mode="static",
                                    hedge_static=h_static, **common)
    sims["BASE_asis"] = simulate(mom_asis, ret_asis, member, vol_asis, mkt_use, betas_asis,
                                 dates, t0, sizing="dollar", hedge_mode=None, **common)

    res = {name: metrics(sim, mkt_s) for name, sim in sims.items()}
    return {"results": res, "h_static": h_static,
            "first": str(pd.Timestamp(dates[0], unit="ms").date()),
            "last": str(pd.Timestamp(dates[-1], unit="ms").date()),
            "n_names": int(mom_fix.shape[1]), "book_start": cfg["book_start"],
            "K": cfg["K"], "gross_leg": cfg["gross_leg"],
            "split_bug_mom_cells_pct": diff_pct, "split_bug_mom_cells_n": int(mom_diff.sum()),
            "artefact_cells_fix": n_art_fix, "artefact_cells_asis": n_art_asis,
            "market_nan_sessions": n_miss}


def evaluate_gate(res: dict) -> dict:
    base, ctrl = res["BASE"], res["CTRL_NETLONG"]
    premise = (base["roll_beta_mean"] <= -0.05) and (base["roll_beta_frac_neg"] >= 0.60)
    # Only episodes that actually fall inside this panel's window can be scored.
    active = [e[0] for e in EPISODES if base["episodes"][e[0]]["n_days"] > 0]
    evaluable = len(active) >= 4
    worst_ep = max(active, key=lambda lb: base["episodes"][lb]["max_dd"])
    out = {"premise_holds": bool(premise), "base_roll_beta_mean": base["roll_beta_mean"],
           "base_roll_beta_frac_neg": base["roll_beta_frac_neg"],
           "worst_episode_base": worst_ep, "active_episodes": active,
           "gate_evaluable": bool(evaluable), "arms": {}}
    base_drag = base["cost_drag_ann_bps"] + base["borrow_drag_ann_bps"]
    for arm in CANDIDATES:
        r = res[arm]
        A = (abs(r["roll_beta_mean"]) <= 0.05) and (
            abs(r["roll_beta_mean"]) <= 0.5 * abs(base["roll_beta_mean"]))
        B = r["net_sharpe_ann365"] >= base["net_sharpe_ann365"] - 0.10
        bw = base["episodes"][worst_ep]["max_dd"]
        rw = r["episodes"][worst_ep]["max_dd"]
        C1 = (bw > 0) and ((bw - rw) / bw >= 0.25)
        C2 = all(r["episodes"][lb]["max_dd"] - base["episodes"][lb]["max_dd"] <= 0.02
                 for lb in active)
        improved = [lb for lb in active
                    if r["episodes"][lb]["max_dd"] < base["episodes"][lb]["max_dd"]]
        D = evaluable and (len(improved) >= 4) and (len([x for x in improved if x != JULY26]) >= 3)
        r_drag = r["cost_drag_ann_bps"] + r["borrow_drag_ann_bps"]
        E = (((r["turnover_ann"] - base["turnover_ann"]) / base["turnover_ann"] <= 0.25)
             and (base_drag <= 0 or (r_drag - base_drag) / base_drag <= 0.25))
        cw = ctrl["episodes"][worst_ep]["max_dd"]
        F = (r["net_sharpe_ann365"] - ctrl["net_sharpe_ann365"] >= 0.05) or (
            (cw > 0) and ((cw - rw) / cw >= 0.10))
        out["arms"][arm] = {
            "A_beta": bool(A), "B_sharpe": bool(B), "C_tail": bool(C1 and C2),
            "D_notfitted": bool(D), "E_cost": bool(E), "F_beatsctrl": bool(F),
            "episodes_improved": improved, "n_improved": len(improved),
            "n_improved_ex_july26": len([x for x in improved if x != JULY26]),
            "worst_ep_dd_base": bw, "worst_ep_dd_arm": rw, "worst_ep_dd_ctrl": cw,
            "PASS": bool(evaluable and premise and A and B and C1 and C2 and D and E and F),
        }
    return out


def print_panel(tag: str, panel: dict) -> dict:
    res = panel["results"]
    base = res["BASE"]
    print("\n" + "=" * 140)
    print(f"PANEL {tag}: K={panel['K']}/side, quarterly 63-bar reform, inverse-vol, "
          f"{panel['n_names']} names, book {panel['book_start']}..{panel['last']} "
          f"({base['n_days']} sessions, {base['n_reforms']} reforms), total gross {2 * panel['gross_leg']:.2f}")
    print("=" * 140)

    print("\n--- V3 DIAGNOSTIC, REPORTED FIRST: is the premise even true? ---")
    print(f"  BASE realized net beta (rolling {ROLL_BETA_WINDOW}d OLS vs SPY): "
          f"mean {base['roll_beta_mean']:+.3f} | median {base['roll_beta_median']:+.3f} | "
          f"p10 {base['roll_beta_p10']:+.3f} | p90 {base['roll_beta_p90']:+.3f} | "
          f"negative in {base['roll_beta_frac_neg']:.1%} of {base['roll_beta_n']} windows")
    print(f"  BASE full-sample OLS beta {base['fullsample_beta']:+.3f} (NW t {base['fullsample_beta_t']:+.2f}); "
          f"ann alpha {base['alpha_ann365_bps']:+.0f} bp (NW t {base['alpha_t_nw']:+.2f})   [DIAGNOSTIC: full-sample]")
    print(f"  EX-ANTE leg betas at reform (inverse-vol weighted): LONG {base['legbeta_long']:.3f} vs "
          f"SHORT {base['legbeta_short']:.3f} -> spread {base['legbeta_long'] - base['legbeta_short']:+.3f} "
          f"(negative = losers higher beta = the hypothesised mechanism); spread negative at "
          f"{base['legbeta_spread_frac_neg']:.0%} of reforms, range "
          f"[{base['legbeta_spread_min']:+.2f}, {base['legbeta_spread_max']:+.2f}]")
    print(f"  AS-IS (repo split-broken panel) BASE: beta mean {res['BASE_asis']['roll_beta_mean']:+.3f}, "
          f"net Sharpe {res['BASE_asis']['net_sharpe_ann365']:+.3f} vs FIXED {base['net_sharpe_ann365']:+.3f}, "
          f"maxDD {res['BASE_asis']['max_dd']:.3f} vs {base['max_dd']:.3f}")

    print("\n--- ARM TABLE (net of 6 bp one-way + 50 bp/yr borrow; ann basis 365) ---")
    print(f"{'arm':<16}{'netSR365':>9}{'netSR252':>9}{'volAnn':>8}{'maxDD':>8}{'skew':>7}"
          f"{'rollBeta':>9}{'FSbeta':>8}{'alphaBp':>9}{'a_t':>7}{'net$':>8}{'turn':>7}"
          f"{'costBp':>8}{'borrBp':>8}")
    for arm in ARM_ORDER:
        r = res[arm]
        print(f"{arm:<16}{r['net_sharpe_ann365']:>9.3f}{r['net_sharpe_ann252']:>9.3f}"
              f"{r['vol_ann365']:>8.3f}{r['max_dd']:>8.3f}{r['skew']:>7.2f}"
              f"{r['roll_beta_mean']:>+9.3f}{r['fullsample_beta']:>+8.3f}"
              f"{r['alpha_ann365_bps']:>9.0f}{r['alpha_t_nw']:>+7.2f}{r['netdollar_mean']:>+8.3f}"
              f"{r['turnover_ann']:>7.2f}{r['cost_drag_ann_bps']:>8.0f}{r['borrow_drag_ann_bps']:>8.0f}")
    v2 = res["V2_betahedged"]
    v1 = res["V1_betaneutral"]
    print(f"  V2 hedge: mean {v2['hedge_mean']:+.3f} [{v2['hedge_min']:+.3f}, {v2['hedge_max']:+.3f}] "
          f"of total gross {2 * panel['gross_leg']:.2f}.  CTRL_NETLONG static hedge {panel['h_static']:+.3f} "
          f"(FULL-SAMPLE constant: deliberate look-ahead, generous to the null).")
    print(f"  V1 net dollar exposure: mean {v1['netdollar_mean']:+.3f} "
          f"[{v1['netdollar_min']:+.3f}, {v1['netdollar_max']:+.3f}] (BASE is 0.000 by construction) "
          f"— this is the dollar-neutrality SACRIFICED to buy beta neutrality.")

    print("\n--- MULTI-EPISODE STRESS TABLE  (total return / within-episode maxDD) ---")
    print(f"{'episode':<24}{'days':>5}" + "".join(f"{a[:15]:>18}" for a in ARM_ORDER))
    for label, _, _ in EPISODES:
        nd = res["BASE"]["episodes"][label]["n_days"]
        row = f"{label:<24}{nd:>5}"
        if nd == 0:
            print(row + "        (outside this panel's window)")
            continue
        for a in ARM_ORDER:
            e = res[a]["episodes"][label]
            cell = f"{e['total_return']:+.1%}/{e['max_dd']:.1%}"
            row += f"{cell:>18}"
        print(row)

    print("\n--- SUB-PERIOD ROBUSTNESS (guards against one episode carrying the whole result) ---")
    idx = pd.to_datetime(base["_net"].index, unit="ms", utc=True)
    years = sorted({int(y) for y in idx.year})
    half = len(base["_net"]) // 2
    print(f"{'arm':<16}{'H1 SR':>8}{'H2 SR':>8}{'ex-2009H1 SR':>14}{'ex-2009H1 maxDD':>17}"
          f"{'corr(BASE)':>12}{'yrs SR>BASE':>13}")
    base_net = base["_net"]
    for arm in ARM_ORDER:
        r = res[arm]
        s = pd.Series(r["_net"].to_numpy(), index=idx)
        h1 = _sharpe(s.iloc[:half].to_numpy())
        h2 = _sharpe(s.iloc[half:].to_numpy())
        keep = s.loc[~((s.index >= pd.Timestamp("2009-01-01", tz="UTC"))
                       & (s.index <= pd.Timestamp("2009-06-30", tz="UTC")))]
        corr = float(pd.Series(r["_net"].to_numpy()).corr(pd.Series(base_net.to_numpy())))
        wins = 0
        for y in years:
            sy = s.loc[s.index.year == y].to_numpy()
            by = pd.Series(base_net.to_numpy(), index=idx).loc[idx.year == y].to_numpy()
            if sy.size > 60 and _sharpe(sy) > _sharpe(by):
                wins += 1
        print(f"{arm:<16}{h1:>8.3f}{h2:>8.3f}{_sharpe(keep.to_numpy()):>14.3f}"
              f"{_maxdd(keep.to_numpy()):>17.3f}{corr:>12.4f}{wins:>9}/{len(years):<3}")

    print("\n--- NET SHARPE BY CALENDAR YEAR ---")
    print(f"{'arm':<16}" + "".join(f"{str(y)[2:]:>7}" for y in years))
    for arm in ARM_ORDER:
        s = pd.Series(res[arm]["_net"].to_numpy(), index=idx)
        row = f"{arm:<16}"
        for y in years:
            sy = s.loc[s.index.year == y].to_numpy()
            row += f"{_sharpe(sy):>7.2f}" if sy.size > 30 else f"{'n/a':>7}"
        print(row)

    print("\n--- PAIRED MOVING-BLOCK BOOTSTRAP of the net-Sharpe DIFFERENCE vs BASE "
          "(block=63 sessions = one holding period, 2000 draws) ---")
    bv = base_net.to_numpy(dtype=np.float64)
    for arm in ARM_ORDER[1:]:
        bs = block_bootstrap_dsharpe(res[arm]["_net"].to_numpy(dtype=np.float64), bv)
        res[arm]["bootstrap_dsharpe"] = bs
        print(f"  {arm:<16} dSR mean {bs['mean']:+.3f}  90% CI [{bs['p05']:+.3f}, {bs['p95']:+.3f}]  "
              f"P(dSR <= 0) = {bs['frac_le_zero']:.3f}")

    gate = evaluate_gate(res)
    print("\n--- PRE-REGISTERED GATE ---")
    print(f"  STEP 0 PREMISE (BASE mean rolling beta <= -0.05 AND negative in >= 60% of windows): "
          f"{'HOLDS' if gate['premise_holds'] else 'FAILS'} "
          f"(mean {gate['base_roll_beta_mean']:+.3f}, negative {gate['base_roll_beta_frac_neg']:.1%})")
    n_act = len(gate["active_episodes"])
    if not gate["gate_evaluable"]:
        print(f"  !! GATE NOT FULLY EVALUABLE on this panel: only {n_act}/7 pre-registered episodes "
              f"fall inside its window (gate D needs >= 4). This panel is DIAGNOSTIC; the RESEARCH "
              f"panel carries the verdict.")
    print(f"  worst BASE episode (of the {n_act} in-window) = {gate['worst_episode_base']} "
          f"(maxDD {base['episodes'][gate['worst_episode_base']]['max_dd']:.1%})")
    keys = ("A_beta", "B_sharpe", "C_tail", "D_notfitted", "E_cost", "F_beatsctrl")
    for arm, g in gate["arms"].items():
        flags = " ".join(f"{k[0]}{'+' if g[k] else '-'}" for k in keys)
        print(f"  {arm:<16} {flags}   maxDD improved in {g['n_improved']}/{n_act} in-window episodes "
              f"({g['n_improved_ex_july26']} excluding 2026-07)  -> {'PASS' if g['PASS'] else 'FAIL'}")
    return gate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_betaneutral")
    ap.add_argument("--profile", default="equity")
    ap.add_argument("--panel", default="both", choices=("both", "research", "live"))
    ap.add_argument("--chunk-years", type=int, default=3)
    a = ap.parse_args(argv)

    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentLog

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict = {"probe": "alphamax_betaneutral", "trials_burned": 0,
                     "note": "SCREEN ONLY — no experiments-ledger append; DSR read-only.",
                     "panels": {}}
    leds = {}
    for name, rel in (("var", "var/experiments.jsonl"), ("var_sharadar", "var_sharadar/experiments.jsonl")):
        fp = _REPO / rel
        if fp.exists():
            led = ExperimentLog(fp)
            leds[name] = (led.n_trials(), led.trial_sharpe_variance())
    payload["ledgers"] = {k: {"N": v[0], "var_sr": v[1]} for k, v in leds.items()}
    print(f"ledgers (read-only, NO trial appended): {payload['ledgers']}")

    jobs = []
    if a.panel in ("both", "live"):
        jobs.append(("LIVE-REPLICA k30_dn_63",
                     LIVE, set(json.loads(K30_WF.read_text())["config"]["instrument_ids"])))
    if a.panel in ("both", "research"):
        jobs.append(("RESEARCH top-2000 K=100", RESEARCH, None))

    for tag, cfg, idf in jobs:
        panel = run_panel(tag, cfg, a.profile, idf, a.chunk_years)
        panel["gate"] = print_panel(tag, panel)
        slug = "".join(c if c.isalnum() else "_" for c in tag)
        nets = pd.DataFrame({arm: r["_net"] for arm, r in panel["results"].items()})
        nets.index = pd.to_datetime(nets.index, unit="ms", utc=True)
        nets.to_csv(OUT_DIR / f"net_returns_{slug}.csv")
        for r in panel["results"].values():
            net = r.pop("_net")
            for lname, (n_led, var_sr) in leds.items():
                rep = dsr_from_returns(net, max(2, n_led), var_sr, ANN)
                r.setdefault("dsr", {})[lname] = {"N": n_led, "dsr": float(np.real(rep.dsr)),
                                                  "psr": float(np.real(rep.psr))}
        payload["panels"][tag] = panel

    (OUT_DIR / "report.json").write_text(json.dumps(payload, indent=2, default=float) + "\n",
                                         encoding="utf-8")
    print(f"\npersisted: {OUT_DIR / 'report.json'} and net_returns_*.csv")
    print("TRIALS BURNED THIS RUN: 0 (cheap construction screen; no experiments-ledger append).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
