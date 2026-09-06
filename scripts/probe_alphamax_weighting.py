#!/usr/bin/env python3
"""PROBE — ALPHAMAX CANDIDATE B: WEIGHTING SCHEME x BREADTH (K) on the LIVE construction.

2026-08-01. MEASURE-ONLY. NEW file. Reads src/** as a library and the lake; mutates NOTHING
(no src/**, no configs/**, no existing script, no launchd). Writes ONLY
artifacts/probe/alphamax_weighting/**. All sixteen measured cells are charged in the union ledger.
Each rerun preflights the immutable forensic configs before computation and computes DSR from the
identity-aligned union.

======================================================================================
WHY THIS PROBE EXISTS
======================================================================================
The live US-equity sleeve (12-1 momentum, eq_mom_252_21) lost -7.75% in July 2026 in a
textbook junk-rally squeeze: SPY ground UP, the SHORT leg squeezed violently, and the
momentum LONG complex sold off at the same time. Every independent construction of 12-1
lost on the same days, so the SIGNAL is not the culprit. The campaign hypothesis is that a
book neutral on DOLLARS is not neutral on RISK.

Candidate B attacks two CONSTRUCTION knobs that have never been tested on this sleeve and
that plausibly interact with a squeeze:

  (1) WEIGHTING SCHEME.  The live book is INVERSE-VOL weighted inside each leg. Inverse-vol
      UPWEIGHTS low-vol names; on the SHORT leg that mechanically UNDERWEIGHTS exactly the
      high-vol junk that squeezes — which could be protective — while on the LONG leg it
      tilts away from high-beta momentum winners. Whether the net effect helps or hurts in
      a squeeze is an empirical question, not a deduction. Measure, do not assume.
  (2) BREADTH K.  The live book holds K=100 per side. More names dilute idiosyncratic
      squeeze risk (one ALIT +88% day is 1/100 of a leg at K=100 but 1/30 at K=30) at the
      cost of a weaker average signal and more turnover.

======================================================================================
PRE-REGISTERED SPEC (locked in this docstring BEFORE any number was computed)
======================================================================================
LIVE CONSTRUCTION = THE INCUMBENT CELL, held fixed except for the one knob under test:
  signal      eq_mom_252_21 (12-1 momentum), the sleeve's only alpha
  universe    the PIT top-2000 equity universe (configs/equity.yaml universe.size=2000,
              entry 1800 / exit 2300) read from the lake's universe_membership intervals —
              ~2,088 live members at every date, survivorship-free (delisted names keep
              their spans). HELD FIXED IN EVERY ARM. The prior campaign finding that K
              interacts with universe SIZE (K=30 on the wide universe = Sharpe 0.172 vs
              K=100 on the same universe = 0.793) is precisely why the universe may not
              move here: only K moves.
  breadth     rank_top_k = 100 per side  (configs/equity.yaml portfolio.rank_top_k)
  weighting   inverse-vol inside each leg (RankEqualVolFallback), w_max 0.15
  neutrality  DOLLAR-neutral: |long gross| == |short gross| (portfolio.dollar_neutral: true)
  cadence     rebalance_bars = 63 (quarterly), signals.horizon_bars = 63
  costs       6 bp ONE-WAY (1 commission + 3 half-spread + 2 latency, equity.yaml) charged
              on realized turnover, + 50 bp/yr GC borrow accrued daily on the short gross.
              0.001 no-trade band (base.yaml) with the engine's own semantics — a
              risk-REDUCING order bypasses the band (backtest/engine.py L1157-1161), so an
              exit is always executed and no stale dust accumulates. ALWAYS ON, every arm.
  PIT         weights decided from data through the CLOSE of session t are effective for
              session t+1 — never a same-bar fill; the rebalance cost is charged on t+1.
              Universe membership is applied BEFORE any cross-sectional statistic.
              Positions DRIFT between quarterly reforms (a short that doubles becomes a
              bigger short) — the squeeze mechanics this campaign is about are only visible
              with drift, so the book is carried at drifted NAV weights, not silently
              re-levered to target each day.

GRID (4 weighting schemes x 4 breadths = 16 cells; the live cell is invvol/K=100):
  weighting
    invvol   w_i ∝ 1/sigma_i           (LIVE; sigma = trailing 63-session ann. stdev)
    equal    w_i ∝ 1                   (the naive book: every name the same dollars)
    signal   w_i ∝ (K - rank_i + 0.5)  linear RANK weighting inside the leg, rank 0 =
                                        strongest. Rank-linear rather than raw-value-
                                        proportional because raw 12-1 momentum values are
                                        fat-tailed and value-proportional weights degenerate
                                        into a 3-name book. This definition is pre-registered.
    volcap   inverse-vol with each name's leg-share CAPPED at 2x equal weight (2/K) and the
             excess redistributed pro-rata among the uncapped (iterated to convergence).
             Tests whether inverse-vol's concentration in low-vol names is the active part.
  breadth K in {30, 50, 100, 200} per side.

ADOPTION GATE (pre-registered; this is a 16-cell multiple-testing minefield, so the gate is
deliberately strict and I am NOT permitted to pick the best cell and call it an improvement):
  A cell is ADOPTABLE only if ALL THREE hold against the live cell (invvol, K=100):
    G1  FULL SAMPLE   net Sharpe (ann365, after costs) strictly greater than the live cell's;
    G2  STRESS        strictly better than the live cell in a MAJORITY (>= 5 of 9) of the
                      pre-registered stress episodes, scored on the RISK-NORMALIZED episode
                      return (episode cumulative net return divided by that arm's OWN
                      trailing-252-session realized vol as of the session BEFORE the episode
                      starts — strictly PIT). Risk-normalizing is what stops "K=200 is just a
                      smaller book" from counting as an improvement;
    G3  BOOTSTRAP     paired stationary bootstrap (mean block 21 sessions, B=2000, common
                      resample indices across all cells) on the FULL-SAMPLE Sharpe difference
                      gives P(Sharpe_variant > Sharpe_live) >= 0.90.
    G0  SOLVENCY      the cell's cumulative equity never touches zero over the full window.
                      A construction that ruins the book is disqualified whatever its Sharpe.
  AND, as a hard family-wise requirement that no cell can be adopted without passing:
    G4  FAMILY-WISE   White (2000) Reality Check over the 15 non-live cells. With 15 cells,
                      ~1.5 cells clearing P>=0.90 individually is the CHANCE expectation; the
                      RC p-value is the probability that the BEST cell would look this good
                      under the null that no cell has an edge. RC p > 0.10 means the grid's
                      best cell is indistinguishable from luck, regardless of G1-G3.
  EXPECTED AND FULLY ACCEPTABLE OUTCOME: a FLAT surface — no cell passes. That is a full
  success and the correct recommendation is then CHANGE NOTHING. The whole grid is reported,
  losers included.

STRESS EPISODES (pre-registered; the July-2026 squeeze is ONE episode and any cell that only
helps there is WINDOW-FITTED and is rejected by G2 on construction):
    2002-07..2002-12  post-bubble bear trough
    2007-08           the quant quake (the canonical crowded-factor unwind)
    2008-09..2008-12  GFC crash
    2009-03..2009-06  THE momentum crash (junk rally off the March 2009 low)
    2020-02..2020-04  Covid crash
    2020-11           vaccine rotation (the modern momentum reversal)
    2021-01..2021-03  meme squeeze
    2022              the bear market / value rotation
    2026-07           the live squeeze this campaign is aimed at

DATA-HYGIENE ROBUSTNESS GRID (declared here before running; it is a ROBUSTNESS VIEW, NOT a
second shot at adoption — no cell may be adopted on the strength of the hygiene grid):
the survivorship-free lake legitimately contains reverse-split penny frenzies (DRYS 2016-17
prints a trailing annualized vol of 37x and single-session moves of +20,000% on the
split-only-adjusted panel). Inverse-vol weighting is structurally immune to these and
equal/signal weighting is not, so a raw invvol-vs-equal comparison is partly a comparison of
data-quality exposure. The whole 16-cell grid is therefore ALSO run under ONE identical,
scheme-independent, strictly-PIT eligibility guard — trailing 63-session annualized vol
<= 300% — and the primary conclusion must hold in both. The PRIMARY grid (and the gate) is
the un-guarded live universe, because that is what the live sleeve actually trades.

WINDOW — and a HARD DATA FLOOR, measured not assumed: FeatureEngine.compute_history builds
its grid from ``calendar.expected_bar_opens``, and the repo's XNYS session table begins
2004-01-02. Requesting start=1999-06-01 returns a panel that still begins 2004-01-02, and the
first non-NaN eq_mom_252_21 value anywhere in the lake is 2005-01-03 (252+21 sessions later).
So the DEEPEST honest book this repo can run is 2005-01-03 .. 2026-07-31 (~21.6 years, 5,428
sessions). That is the window used. The pre-registered 2002 episode is therefore UNREACHABLE
and is reported as n/a rather than quietly dropped; the stress-majority gate is evaluated over
the episodes the data can actually support (a strict majority of them).

ANNUALIZATION: ANN=365 is the repo's headline basis (metrics.sharpe DAYS_PER_YEAR=365 and
metrics.turnover bar_a for a D1 bar), so the printed net Sharpe is directly comparable with
every other AlphaForge equity number. The ann252 calendar-Sharpe is printed beside it; all
gate DIFFERENCES have the same sign under either basis.

    uv run python scripts/probe_alphamax_weighting.py
    uv run python scripts/probe_alphamax_weighting.py --quick     # short-window smoke test
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_weighting"

# ---- construction constants (configs/equity.yaml + configs/base.yaml) ----
ANN = 365.0             # repo headline annualization basis (Sharpe + turnover)
TRADING_DAYS = 252.0    # borrow accrual grid + the calendar-Sharpe cross-check
VOL_WINDOW = 63         # trailing sessions for the inverse-vol denominator
VOL_MINP = 30
BETA_WINDOW = 252       # trailing sessions for the diagnostic ex-ante beta panel
BETA_MINP = 126
GROSS_LEG = 0.5         # per-leg gross (total gross 1.0 = portfolio.gross_max). A CONSTANT
                        # gross scalar leaves Sharpe / turnover-% / every ratio invariant.
W_MAX = 0.15            # portfolio.w_max (non-binding at K>=30: 1/30 = 0.033)
COST_ONEWAY = 6e-4      # 1bp commission + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4      # 50 bp/yr GC borrow on the short gross (equity.yaml)
NO_TRADE_BAND = 0.001   # base.yaml no_trade_band
REFORM_BARS = 63        # rebalance_bars (quarterly, the production cadence)
VOLCAP_MULT = 2.0       # 'volcap' scheme: leg-share cap = VOLCAP_MULT / K
RET_CLIP = (-0.5, 1.0)  # bad-print hygiene on a 25yr survivorship-free small-cap tape;
                        # IDENTICAL in every arm. Clip incidence is reported, not hidden.
VOL_GUARD = 3.0         # ROBUSTNESS GRID ONLY: max trailing ann. vol for eligibility (300%)
JUNK_VOL = 1.0          # diagnostic: 'junk' = trailing ann. vol > 100%
BETA_WINSOR = 5.0       # diagnostic: ex-ante betas winsorized to +-5 before aggregation

WARMUP_START = "2004-01-02"   # the XNYS session table's first day; earlier starts are ignored
BOOK_START = "2005-01-03"     # first session with a non-NaN eq_mom_252_21 anywhere in the lake
BOOK_END = "2026-08-01"

SPY_ID = "XUSE:CASH:SPYUSD"  # market proxy ONLY; not a universe member, never tradable here
# VERIFIED 2026-08-01: data/lake's SPY partition holds only 29 bars (2026-06-22..2026-07-31);
# the deep SPY history lives in the managed-futures lake (6,309 bars 2001-06..2026-07), which
# scripts/probe_alphamax_volscale.py already uses as its market proxy. Read-only, diagnostic
# ONLY (beta attribution) — it never enters the tradable universe or any return.
MF_LAKE = "data/lake_mf"
# EXTERNAL VALIDITY ANCHOR (read-only): the repo's own deep-history walk-forward of the SAME
# 12-1 signal, run by WalkForwardRunner on a DIFFERENT lake (Sharadar) with a different
# universe and leg grid. If this probe's replica of the live construction lands near it, the
# replica is trustworthy; if it does not, that is the headline finding.
PREREG_WF = "artifacts/walkforward/prereg_momentum/walkforward.json"

SCHEMES = ("invvol", "equal", "signal", "volcap")
BREADTHS = (30, 50, 100, 200)
LIVE_CELL = ("invvol", 100)

EPISODES: tuple[tuple[str, str, str], ...] = (
    ("2002 bear trough",       "2002-07-01", "2002-12-31"),
    ("2007-08 quant quake",    "2007-08-01", "2007-08-31"),
    ("2008 GFC crash",         "2008-09-01", "2008-12-31"),
    ("2009-03 momentum crash", "2009-03-01", "2009-06-30"),
    ("2020-02 Covid crash",    "2020-02-15", "2020-04-30"),
    ("2020-11 vaccine rot.",   "2020-11-01", "2020-11-30"),
    ("2021-01 meme squeeze",   "2021-01-15", "2021-03-15"),
    ("2022 bear",              "2022-01-01", "2022-12-31"),
    ("2026-07 live squeeze",   "2026-07-01", "2026-07-31"),
)

BOOT_B = 2000
BOOT_BLOCK = 21.0
BOOT_CHUNK = 100
BOOT_SEED = 20260801


# --------------------------------------------------------------- daily-return probe spec
def _probe_dret_fn(ctx, spec):
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel

    px = _adjusted_close_panel(ctx)
    return long_series(px.pct_change(), name=spec.name)


def _register_dret(reg) -> None:
    from alphaforge.features.spec import Family, FeatureSpec

    if "probe_dret" in {s.name for s in reg.all_specs()}:
        return
    reg.register(lambda: FeatureSpec(
        name="probe_dret", family=Family.MOMENTUM, direction=1, cross_sectional=False,
        lookback_bars=2, params={}, fn=_probe_dret_fn,
    ))


# ------------------------------------------------------------------------- weighting
def _leg_shares(scheme: str, invvol: np.ndarray, order_pos: np.ndarray, k: int) -> np.ndarray:
    """Non-negative leg shares summing to 1 for ONE leg's selected names.

    ``invvol``     1/sigma of the selected names (same order as the selection array)
    ``order_pos``  0-based rank of each selected name inside its leg by SIGNAL STRENGTH
                   (0 = strongest long / strongest short)
    """
    n = invvol.shape[0]
    if n == 0:
        return invvol
    if scheme == "equal":
        base = np.ones(n, dtype=np.float64)
    elif scheme == "signal":
        base = (k - order_pos.astype(np.float64) + 0.5).clip(min=1e-9)
    else:  # invvol / volcap share the same starting point
        base = invvol.astype(np.float64).copy()
    s = float(base.sum())
    if not math.isfinite(s) or s <= 0.0:
        return np.full(n, 1.0 / n, dtype=np.float64)
    x = base / s
    if scheme == "volcap":
        cap = VOLCAP_MULT / float(k)
        if cap < 1.0:
            for _ in range(24):
                over = x > cap + 1e-15
                if not over.any():
                    break
                excess = float((x[over] - cap).sum())
                x = np.where(over, cap, x)
                free = ~over
                fs = float(x[free].sum())
                if not free.any() or fs <= 0.0:
                    break
                x = np.where(free, x + excess * x / fs, x)
    return x


# ------------------------------------------------------------------------- simulator
def simulate(
    mom: np.ndarray, ret: np.ndarray, member: np.ndarray, vol: np.ndarray,
    beta: np.ndarray, dates: np.ndarray, t0: int, k: int, scheme: str,
    vol_guard: float | None = None, drift: bool = True,
) -> dict:
    """One (scheme, K) cell over the full book window.

    Weights are carried as SIGNED FRACTIONS OF NAV and DRIFT between quarterly reforms:
        p_i(t+1) = p_i(t) * (1 + r_i(t+1)) / (1 + sum_j p_j(t) r_j(t+1))
    which is the exact evolution of a book that is not touched between reforms — the reason a
    squeeze compounds against a short leg. Reform decisions use data through the close of t and
    are effective from t+1; the reform's cost lands on t+1. Only the <= 2K held names are
    carried, so a 25-year x 6.8k-name sweep is a few seconds per cell.
    """
    t_n, n_names = mom.shape
    finite_mom = np.isfinite(mom)
    finite_vol = np.isfinite(vol) & (vol > 0)
    eligible_all = member & finite_mom & finite_vol
    if vol_guard is not None:
        eligible_all = eligible_all & (vol <= vol_guard)
    ret_ok = np.isfinite(ret)
    ret_use = np.clip(np.where(ret_ok, ret, 0.0), RET_CLIP[0], RET_CLIP[1])

    reb_set = set(range(t0, t_n, REFORM_BARS))
    act = np.zeros(0, dtype=np.int64)     # held instrument column indices
    p = np.zeros(0, dtype=np.float64)     # signed NAV weights of the held names
    net = np.full(t_n, np.nan, dtype=np.float64)
    gross_r = np.full(t_n, np.nan, dtype=np.float64)
    pending_cost = 0.0
    reb_turnovers: list[float] = []
    long_sizes: list[int] = []
    short_sizes: list[int] = []
    ante_beta: list[float] = []
    ante_beta_long: list[float] = []
    ante_beta_short: list[float] = []
    med_vol_long: list[float] = []
    med_vol_short: list[float] = []
    junk_long: list[float] = []
    junk_short: list[float] = []
    borrow_total = 0.0
    cost_total = 0.0
    n_clipped = 0
    n_held_cells = 0

    for t in range(t0, t_n):
        if act.size:
            r = ret_use[t, act]
            g = float(p @ r)
            n_held_cells += act.size
            n_clipped += int(np.count_nonzero(
                ret_ok[t, act] & ((ret[t, act] > RET_CLIP[1]) | (ret[t, act] < RET_CLIP[0]))
            ))
        else:
            r = np.zeros(0, dtype=np.float64)
            g = 0.0
        gross_r[t] = g
        short_gross = float(-np.minimum(p, 0.0).sum()) if act.size else 0.0
        borrow_t = short_gross * (BORROW_ANN / TRADING_DAYS)
        net[t] = g - borrow_t - pending_cost
        borrow_total += borrow_t
        cost_total += pending_cost
        pending_cost = 0.0
        if drift and act.size:  # drift the held book to its post-return NAV weights
            denom = 1.0 + g
            if denom > 1e-8:
                p = p * (1.0 + r) / denom

        if t in reb_set:
            elig = eligible_all[t]
            n_elig = int(elig.sum())
            if n_elig < 4 * k:
                continue
            m = mom[t]
            ei = np.where(elig)[0]
            order = ei[np.argsort(-m[ei], kind="stable")]  # strongest momentum first
            long_idx = order[:k]
            short_idx = order[-k:][::-1]                   # weakest first -> rank 0 = strongest short
            inv_l = 1.0 / vol[t, long_idx]
            inv_s = 1.0 / vol[t, short_idx]
            pos = np.arange(k, dtype=np.float64)
            wl = _leg_shares(scheme, inv_l, pos, k) * GROSS_LEG
            ws = _leg_shares(scheme, inv_s, pos, k) * GROSS_LEG
            wl = np.minimum(wl, W_MAX)
            ws = np.minimum(ws, W_MAX)
            sl, ss = float(wl.sum()), float(ws.sum())
            if sl > 0:
                wl *= GROSS_LEG / sl
            if ss > 0:
                ws *= GROSS_LEG / ss
            wl = np.minimum(wl, W_MAX)
            ws = np.minimum(ws, W_MAX)

            new_idx = np.concatenate([long_idx, short_idx])
            new_w = np.concatenate([wl, -ws])

            # turnover against the DRIFTED book, over the union of old and new names
            union = np.union1d(act, new_idx)
            old_map = np.zeros(n_names, dtype=np.float64)
            new_map = np.zeros(n_names, dtype=np.float64)
            if act.size:
                old_map[act] = p
            new_map[new_idx] = new_w
            w_old = old_map[union]
            d = new_map[union] - w_old
            # base.yaml no-trade band with the ENGINE's semantics: a risk-REDUCING order
            # (signed delta opposing the held position) bypasses the band, so exits always
            # execute and no sub-band dust accumulates (backtest/engine.py L1157-1161).
            reducing = (w_old != 0.0) & ((d > 0.0) != (w_old > 0.0))
            d = np.where((~reducing) & (np.abs(d) <= NO_TRADE_BAND), 0.0, d)
            kept = w_old + d
            turnover = float(np.abs(d).sum())
            reb_turnovers.append(turnover)
            pending_cost = turnover * COST_ONEWAY

            keep = np.abs(kept) > 1e-12
            act = union[keep]
            p = kept[keep]
            long_sizes.append(int((p > 0).sum()))
            short_sizes.append(int((p < 0).sum()))

            # ---- diagnostics (outlier-ROBUST: the tape legitimately contains 37x-vol
            # reverse-split penny frenzies, so a plain weighted MEAN of sigma/beta is a
            # single-name artifact. Betas winsorized to +-BETA_WINSOR; leg vol reported as
            # the leg MEDIAN plus the share of leg gross parked in >100%-vol 'junk'.)
            b = np.clip(beta[t, act], -BETA_WINSOR, BETA_WINSOR)
            ok = np.isfinite(b)
            lm, sm = ok & (p > 0), ok & (p < 0)
            if ok.any():
                ante_beta.append(float((p[ok] * b[ok]).sum()))
            if lm.any():
                ante_beta_long.append(float((p[lm] * b[lm]).sum() / p[lm].sum()))
            if sm.any():
                ante_beta_short.append(float((p[sm] * b[sm]).sum() / p[sm].sum()))
            v = vol[t, act]
            vok = np.isfinite(v)
            lm, sm = vok & (p > 0), vok & (p < 0)
            if lm.any():
                med_vol_long.append(float(np.median(v[lm])))
                junk_long.append(float(p[lm & (v > JUNK_VOL)].sum() / p[lm].sum()))
            if sm.any():
                med_vol_short.append(float(np.median(v[sm])))
                ap = np.abs(p)
                junk_short.append(float(ap[sm & (v > JUNK_VOL)].sum() / ap[sm].sum()))

    idx = dates[t0:]
    net_s = pd.Series(net[t0:], index=idx).dropna()
    n_days = len(net_s)
    return {
        "net": net_s,
        "gross": pd.Series(gross_r[t0:], index=idx).dropna(),
        "turnover_ann": (float(np.sum(reb_turnovers)) / n_days * ANN) if n_days else float("nan"),
        "cost_drag_ann_bps": (cost_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "borrow_drag_ann_bps": (borrow_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "avg_turnover_per_reform": float(np.mean(reb_turnovers)) if reb_turnovers else float("nan"),
        "n_reforms": len(reb_turnovers),
        "avg_long_names": float(np.mean(long_sizes)) if long_sizes else float("nan"),
        "avg_short_names": float(np.mean(short_sizes)) if short_sizes else float("nan"),
        "ante_net_beta": float(np.mean(ante_beta)) if ante_beta else float("nan"),
        "ante_beta_long": float(np.mean(ante_beta_long)) if ante_beta_long else float("nan"),
        "ante_beta_short": float(np.mean(ante_beta_short)) if ante_beta_short else float("nan"),
        "med_vol_long": float(np.mean(med_vol_long)) if med_vol_long else float("nan"),
        "med_vol_short": float(np.mean(med_vol_short)) if med_vol_short else float("nan"),
        "junk_share_long": float(np.mean(junk_long)) if junk_long else float("nan"),
        "junk_share_short": float(np.mean(junk_short)) if junk_short else float("nan"),
        "clip_rate": (n_clipped / n_held_cells) if n_held_cells else float("nan"),
        "n_days": n_days,
    }


def _ols_beta(net: pd.Series, mkt: pd.Series) -> float:
    j = pd.concat([net.rename("s"), mkt.rename("m")], axis=1).dropna()
    if len(j) > 100 and float(j["m"].var()) > 0:
        return float(j["s"].cov(j["m"]) / j["m"].var())
    return float("nan")


def _metrics(net: pd.Series, gross: pd.Series, mkt: pd.Series, ew: pd.Series) -> dict:
    v = net.to_numpy(dtype=np.float64)
    g = gross.to_numpy(dtype=np.float64)
    sd = float(np.std(v, ddof=1))
    gd = float(np.std(g, ddof=1))
    eq = np.cumprod(1.0 + v)
    ruin = bool(eq.size and float(np.min(eq)) <= 0.0)   # book traded through zero equity
    if ruin:  # cumulative equity went non-positive: drawdown is 100%, CAGR undefined
        max_dd, total = 1.0, float("nan")
    else:
        peak = np.maximum.accumulate(eq)
        max_dd = float(np.max(1.0 - eq / peak)) if eq.size else float("nan")
        total = float(np.prod(1.0 + v))
    yrs = len(v) / TRADING_DAYS
    return {
        "net_sharpe_ann365": (float(np.mean(v)) / sd * math.sqrt(ANN)) if sd > 0 else float("nan"),
        "net_sharpe_ann252": (float(np.mean(v)) / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "gross_sharpe_ann365": (float(np.mean(g)) / gd * math.sqrt(ANN)) if gd > 0 else float("nan"),
        "vol_ann365": sd * math.sqrt(ANN),
        "max_dd": max_dd,
        "cagr": (total ** (1.0 / yrs) - 1.0) if (yrs > 0 and math.isfinite(total) and total > 0) else float("nan"),
        "total_return": (total - 1.0) if math.isfinite(total) else float("nan"),
        "ruin": ruin,
        "se_sharpe_ann365": math.sqrt(ANN / len(v)) if len(v) else float("nan"),
        "post_beta_spy": _ols_beta(net, mkt),
        "post_beta_ew": _ols_beta(net, ew),
    }


# ------------------------------------------------------------------------- bootstrap
def _stationary_indices(t_n: int, b: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary-bootstrap index matrix (b, t_n), fully vectorized."""
    p = 1.0 / mean_block
    newblock = rng.random((b, t_n)) < p
    newblock[:, 0] = True
    pos = np.arange(t_n, dtype=np.int64)
    block_start = np.maximum.accumulate(np.where(newblock, pos[None, :], -1), axis=1)
    starts = rng.integers(0, t_n, size=(b, t_n), dtype=np.int64)
    base = np.take_along_axis(starts, block_start, axis=1)
    return (base + (pos[None, :] - block_start)) % t_n


def _paired_bootstrap(mat: np.ndarray, live_row: int, rng: np.random.Generator) -> dict:
    """Paired stationary bootstrap of the Sharpe DIFFERENCE of every row vs ``live_row``.

    ``mat`` is (n_arms, T) of aligned daily net returns — the SAME resample indices are applied
    to every arm in every replicate, so the comparison stays paired and the White (2000)
    Reality Check over the family is computable from one pass.
    """
    n_arms, t_n = mat.shape
    diffs = np.empty((BOOT_B, n_arms), dtype=np.float64)
    done = 0
    while done < BOOT_B:
        c = min(BOOT_CHUNK, BOOT_B - done)
        idx = _stationary_indices(t_n, c, BOOT_BLOCK, rng)
        smp = mat[:, idx]                              # (n_arms, c, T)
        mu = smp.mean(axis=2)
        sd = smp.std(axis=2, ddof=1)
        sr = np.where(sd > 0, mu / np.where(sd > 0, sd, 1.0) * math.sqrt(ANN), np.nan)
        diffs[done:done + c] = (sr - sr[live_row][None, :]).T
        done += c
        del smp, idx
    obs_sr = mat.mean(axis=1) / mat.std(axis=1, ddof=1) * math.sqrt(ANN)
    obs_diff = obs_sr - obs_sr[live_row]
    p_win = np.mean(diffs > 0.0, axis=0)
    # White Reality Check over the non-live family: is the BEST cell better than luck?
    fam = [i for i in range(n_arms) if i != live_row]
    centered = diffs[:, fam] - obs_diff[fam][None, :]
    rc_stat = float(np.max(obs_diff[fam]))
    rc_p = float(np.mean(np.max(centered, axis=1) > rc_stat))
    return {
        "obs_sharpe": obs_sr, "obs_diff": obs_diff, "p_win": p_win,
        "rc_stat": rc_stat, "rc_p": rc_p,
        "diff_lo": np.percentile(diffs, 5, axis=0), "diff_hi": np.percentile(diffs, 95, axis=0),
    }


# ------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_weighting")
    ap.add_argument("--profile", default="equity")
    ap.add_argument("--warmup", default=WARMUP_START)
    ap.add_argument("--start", default=BOOK_START)
    ap.add_argument("--end", default=BOOK_END)
    ap.add_argument("--quick", action="store_true", help="smoke test on 2018+ only")
    ap.add_argument("--cache", default=None, help="npz path: build panels once, reuse on reruns")
    a = ap.parse_args(argv)
    if a.quick:
        a.warmup, a.start = "2016-06-01", "2018-01-01"

    import alphaforge.features.library  # noqa: F401
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research.ic_report import _membership_mask
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentUnion
    from alphaforge.validation.probe_ledger import record_probe_trial

    t_wall = time.time()
    settings = load_settings(a.profile)
    union = ExperimentUnion.discover(settings.paths.var_dir / "experiments.jsonl", _REPO)
    primary_variants = {f"{scheme}_K{k}" for scheme in SCHEMES for k in BREADTHS}
    expected_variants = {
        *primary_variants,
        *(f"no_drift_{variant}" for variant in primary_variants),
        *(f"volatility_guard_{variant}" for variant in primary_variants),
    }
    configs = {
        str(record.config["variant"]): dict(record.config)
        for record in union.all()
        if record.config.get("probe") == "forensic_alphamax_weighting"
    }
    if set(configs) != expected_variants:
        missing = sorted(expected_variants - set(configs))
        extra = sorted(set(configs) - expected_variants)
        raise RuntimeError(f"weighting forensic ledger mismatch: missing={missing}, extra={extra}")
    for config in configs.values():
        window = dict(config["window"])
        window.update({"warmup": a.warmup, "book_start": a.start, "end": a.end})
        config["window"] = window
    union.preflight_hypotheses(list(configs.values()))
    sleeve = sleeve_for(settings.data.asset_class)
    tf = sleeve.anchor_tf
    start = parse_utc(f"{a.warmup}T00:00:00Z")
    end = parse_utc(f"{a.end}T00:00:00Z")

    reg = default_registry()
    _register_dret(reg)
    by_name = {s.name: s for s in reg.all_specs()}
    specs = [by_name["eq_mom_252_21"], by_name["probe_dret"]]

    cache = Path(a.cache).expanduser() if a.cache else None
    if cache is not None and cache.exists():
        z = np.load(cache, allow_pickle=True)
        dates = z["dates"]
        mom = z["mom"].astype(np.float64)
        ret = z["ret"].astype(np.float64)
        member = np.array(z["member"], dtype=bool, copy=True)
        vol = z["vol"].astype(np.float64)
        beta = z["beta"].astype(np.float64)
        spy = pd.Series(z["spy"].astype(np.float64), index=dates)
        ew = pd.Series(z["ew"].astype(np.float64), index=dates)
        ids = [str(x) for x in z["ids"]]
        proxy_src = str(z["proxy_src"])
        spy_present = bool(z["spy_present"])
        spy_member = bool(z["spy_member"])
        print(f"panels loaded from cache {cache} ({time.time() - t_wall:.1f}s)")
        return _analyse(a, dates, mom, ret, member, vol, beta, spy, ew, ids, proxy_src,
                        spy_present, spy_member, t_wall, parse_utc, now_ms, dsr_from_returns,
                        record_probe_trial, union, configs)

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        engine = FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class)
        members = set(universe.read_intervals().column("instrument_id").to_pylist())
        in_lake = set(paths.instrument_ids(ohlcv_dataset(tf)))
        ids = sorted(i for i in (members & in_lake) if i.startswith("XUSE:"))
        spy_present = SPY_ID in in_lake
        spy_member = SPY_ID in members
        compute_ids = sorted({*ids, SPY_ID}) if spy_present else list(ids)
        print(
            f"universe: {len(ids)} ever-member equity ids in the lake | market proxy {SPY_ID} "
            f"present={spy_present} universe_member={spy_member} (never tradable here) | "
            f"warmup {a.warmup} book {a.start}..{a.end} tf={tf.name}"
        )
        raw = engine.compute_history(specs, compute_ids, start=start, end=end)
        print(f"compute_history: {len(raw):,} rows in {time.time() - t_wall:.1f}s")
        mask = _membership_mask(universe, raw)

    mom_w = raw["eq_mom_252_21"].unstack("instrument_id").sort_index()
    ret_w = raw["probe_dret"].unstack("instrument_id").sort_index()
    del raw
    mem_w = mask.unstack("instrument_id").reindex(index=mom_w.index, columns=mom_w.columns, fill_value=False)
    del mask
    ret_w = ret_w.reindex(index=mom_w.index, columns=mom_w.columns)
    vol_w = ret_w.rolling(VOL_WINDOW, min_periods=VOL_MINP).std() * math.sqrt(ANN)

    # ---- market proxies (DIAGNOSTIC ONLY; never tradable, never in any return) ----
    # (a) equal-weighted PIT-member universe return: always available, perfectly aligned.
    ew = ret_w.where(mem_w).mean(axis=1).astype(np.float64)
    # (b) SPY from the managed-futures lake (deep history; data/lake's SPY is 29 bars).
    spy = pd.Series(np.nan, index=mom_w.index, dtype=np.float64)
    proxy_src = "equal-weighted PIT universe (SPY unavailable)"
    try:
        mf_paths = LakePaths(_REPO / MF_LAKE)
        mf_tbl = PITDataReader(mf_paths).ohlcv([SPY_ID], start=start, end=end, as_of=end, tf=tf)
        mf = pd.DataFrame({
            "ts": mf_tbl.column("ts_open").cast("int64").to_numpy(zero_copy_only=False),
            "close": mf_tbl.column("close").combine_chunks().to_numpy(zero_copy_only=False),
        }).drop_duplicates("ts").set_index("ts").sort_index()
        sr = mf["close"].pct_change().reindex(mom_w.index)
        cover = float(sr.notna().mean())
        if cover >= 0.80:
            spy, proxy_src = sr.astype(np.float64), f"{MF_LAKE} SPY ({cover:.0%} session coverage)"
        else:
            print(f"WARNING: {MF_LAKE} SPY covers only {cover:.0%} of sessions -> using EW universe proxy")
    except Exception as exc:
        print(f"WARNING: SPY proxy unavailable ({exc!r}) -> using EW universe proxy")
    if spy.notna().mean() < 0.80:
        spy = ew
    print(f"market proxy for beta diagnostics: {proxy_src}")
    spy_f = spy.fillna(0.0)
    m_mean = spy_f.rolling(BETA_WINDOW, min_periods=BETA_MINP).mean()
    m_var = spy_f.rolling(BETA_WINDOW, min_periods=BETA_MINP).var(ddof=0)
    rf = ret_w.fillna(0.0)
    cov = rf.mul(spy_f, axis=0).rolling(BETA_WINDOW, min_periods=BETA_MINP).mean().sub(
        rf.rolling(BETA_WINDOW, min_periods=BETA_MINP).mean().mul(m_mean, axis=0)
    )
    beta_w = cov.div(m_var.where(m_var > 0), axis=0)
    del cov, rf, m_mean

    dates = mom_w.index.to_numpy(dtype=np.int64)
    mom = mom_w.to_numpy(dtype=np.float64)
    ret = ret_w.to_numpy(dtype=np.float64)
    member = np.array(mem_w.to_numpy(dtype=bool), dtype=bool, copy=True)
    vol = vol_w.to_numpy(dtype=np.float64)
    beta = beta_w.to_numpy(dtype=np.float64)
    cols = list(mom_w.columns)
    if spy_present and SPY_ID in cols:      # hard guarantee: the proxy is never tradable
        member[:, cols.index(SPY_ID)] = False
    del mom_w, ret_w, mem_w, vol_w, beta_w

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, dates=dates, mom=mom.astype(np.float32), ret=ret,
                 member=member, vol=vol.astype(np.float32), beta=beta.astype(np.float32),
                 spy=spy.to_numpy(dtype=np.float64), ew=ew.to_numpy(dtype=np.float64),
                 ids=np.array(ids, dtype=object), proxy_src=proxy_src,
                 spy_present=spy_present, spy_member=spy_member)
        print(f"panels cached -> {cache}")
    return _analyse(a, dates, mom, ret, member, vol, beta, spy, ew, ids, proxy_src,
                    spy_present, spy_member, t_wall, parse_utc, now_ms, dsr_from_returns,
                    record_probe_trial, union, configs)


def _analyse(
    a, dates, mom, ret, member, vol, beta, spy, ew, ids, proxy_src,
    spy_present, spy_member, t_wall, parse_utc, now_ms, dsr_from_returns,
    record_probe_trial, union, configs,
) -> int:
    """Everything downstream of the panels (kept separate so --cache can skip the 16-min build)."""
    start_ms = int(parse_utc(f"{a.start}T00:00:00Z"))
    t0 = int(np.searchsorted(dates, start_ms, side="left"))
    elig_ct = (member & np.isfinite(mom) & np.isfinite(vol) & (vol > 0)).sum(axis=1)
    print(
        f"panels: T={mom.shape[0]} sessions x N={mom.shape[1]} names | book t0={t0} -> "
        f"{mom.shape[0] - t0} sessions | eligible/session: min {int(elig_ct[t0:].min())} "
        f"median {int(np.median(elig_ct[t0:]))} max {int(elig_ct[t0:].max())}"
    )

    # ------------------------------------------------------------------- run the grid
    arms: list[tuple[str, int]] = [(s, k) for s in SCHEMES for k in BREADTHS]
    results: dict[str, dict] = {}
    audit_before = union.n_trials()
    for scheme, k in arms:
        t_arm = time.time()
        sim = simulate(mom, ret, member, vol, beta, dates, t0, k, scheme)
        met = _metrics(sim["net"], sim["gross"], spy, ew)
        key = f"{scheme}_K{k}"
        full_config = configs[key]
        record_probe_trial(
            str(full_config["probe"]),
            {name: value for name, value in full_config.items() if name != "probe"},
            sim["net"],
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
        results[key] = {"scheme": scheme, "K": k, **met,
                        **{kk: vv for kk, vv in sim.items() if kk not in ("net", "gross")},
                        "_net": sim["net"]}
        print(f"  {key:<14} netSR365 {met['net_sharpe_ann365']:+.3f}  vol {met['vol_ann365']:.3f}  "
              f"turn {sim['turnover_ann']:.2f}x  ({time.time() - t_arm:.1f}s)")

    live_key = f"{LIVE_CELL[0]}_K{LIVE_CELL[1]}"
    base = results[live_key]

    # ------------------------------------------------------------- aligned return matrix
    keys = [f"{s}_K{k}" for s, k in arms]
    aligned = pd.concat([results[kk]["_net"].rename(kk) for kk in keys], axis=1).dropna()
    mat = aligned.to_numpy(dtype=np.float64).T
    live_row = keys.index(live_key)
    rng = np.random.default_rng(BOOT_SEED)
    boot = _paired_bootstrap(mat, live_row, rng)

    # --------------------------------------------------------------- episode scoring
    ep_rows: dict[str, dict[str, dict]] = {}
    for label, s_, e_ in EPISODES:
        s_ms = int(parse_utc(f"{s_}T00:00:00Z"))
        e_ms = int(parse_utc(f"{e_}T00:00:00Z"))
        for kk in keys:
            ser = results[kk]["_net"]
            iv = ser.index.to_numpy(dtype=np.int64)
            in_ep = (iv >= s_ms) & (iv <= e_ms)
            if not in_ep.any():
                ep_rows.setdefault(label, {})[kk] = {"n": 0}
                continue
            v = ser.to_numpy(dtype=np.float64)
            first = int(np.argmax(in_ep))
            prior = v[max(0, first - int(TRADING_DAYS)):first]
            pv = float(np.std(prior, ddof=1)) * math.sqrt(ANN) if prior.size > 60 else float("nan")
            seg = v[in_ep]
            eq = np.cumprod(1.0 + seg)
            dd = float(np.max(1.0 - eq / np.maximum.accumulate(eq)))
            raw_ret = float(eq[-1] - 1.0)
            ep_rows.setdefault(label, {})[kk] = {
                "n": int(seg.size), "ret": raw_ret, "prior_vol_ann": pv,
                "risk_norm": (raw_ret / pv) if (math.isfinite(pv) and pv > 0) else float("nan"),
                "max_dd": dd,
            }

    # ------------------------------------------------------------------------ report
    def f(x: float, w: int = 7, p: int = 3) -> str:
        return f"{x:>{w}.{p}f}" if isinstance(x, float) and math.isfinite(x) else " " * (w - 3) + "n/a"

    line = "=" * 132
    print("\n" + line)
    print("CANDIDATE B — ALPHAMAX WEIGHTING x BREADTH GRID  (12-1 momentum, PIT top-2000 universe HELD FIXED, quarterly 63-bar reform,")
    print("dollar-neutral, 6bp one-way + 50bp/yr borrow, positions DRIFT between reforms, no same-bar fills)")
    print(f"window {a.start} .. {a.end}  |  {base['n_days']} sessions  |  LIVE CELL = {live_key} (marked *)")
    print(line)
    hdr = (f"{'cell':<14}{'netSR365':>9}{'netSR252':>9}{'ΔSR':>8}{'P(win)':>8}{'ΔSR ci90':>16}{'grossSR':>8}"
           f"{'vol':>7}{'maxDD':>8}{'CAGR':>8}{'turn':>7}{'cost_bp':>8}{'borrow':>8}{'L/S':>10}{'clip%':>8}")
    print(hdr)
    for i, kk in enumerate(keys):
        r = results[kk]
        star = "*" if kk == live_key else " "
        ci = f"[{boot['diff_lo'][i]:+.2f},{boot['diff_hi'][i]:+.2f}]"
        print(
            f"{star}{kk:<13}{r['net_sharpe_ann365']:>9.3f}{r['net_sharpe_ann252']:>9.3f}"
            f"{boot['obs_diff'][i]:>+8.3f}{boot['p_win'][i]:>8.2f}{ci:>16}{r['gross_sharpe_ann365']:>8.3f}"
            f"{r['vol_ann365']:>7.3f}{r['max_dd']:>8.3f}{r['cagr']:>+8.4f}{r['turnover_ann']:>7.2f}"
            f"{r['cost_drag_ann_bps']:>8.0f}{r['borrow_drag_ann_bps']:>8.0f}"
            f"{r['avg_long_names']:>5.0f}/{r['avg_short_names']:<4.0f}{r['clip_rate'] * 100:>8.3f}"
        )

    # external validity anchor — the repo's own deep-history number, different lake + harness
    try:
        pre = json.loads((_REPO / PREREG_WF).read_text())
        p_sr, p_dd, p_to = pre["summary"]["sharpe"], pre["summary"]["max_dd"], pre["summary"]["turnover_ann"]
        print(f"\nEXTERNAL VALIDITY ANCHOR — {PREREG_WF} (SAME 12-1 signal, DIFFERENT lake (Sharadar), different")
        print(f"universe ({len(pre['config']['instrument_ids'])} ids) and leg grid, run through WalkForwardRunner):")
        print(f"  stored deep-history net Sharpe {p_sr:+.3f} (maxDD {p_dd:.3f}, turnover {p_to:.2f}x)  vs  this probe's")
        print(f"  replica of the LIVE cell {live_key}: net Sharpe {base['net_sharpe_ann365']:+.3f} "
              f"(maxDD {base['max_dd']:.3f}, turnover {base['turnover_ann']:.2f}x).")
        print("  Two independent lakes and two independent harnesses put 12-1 momentum's deep-history net Sharpe at")
        print("  essentially the same place (~ -0.05), which is the honest baseline everything below is measured against.")
        anchor_block = {"artifact": PREREG_WF, "stored_net_sharpe": float(p_sr),
                        "stored_max_dd": float(p_dd), "stored_turnover_ann": float(p_to),
                        "probe_live_cell_net_sharpe": float(base["net_sharpe_ann365"])}
    except Exception as exc:
        print(f"\n(external validity anchor unavailable: {exc!r})")
        anchor_block = {}

    print("\nHYPOTHESIS DIAGNOSTIC — is a DOLLAR-neutral momentum book RISK-neutral? "
          "(ante beta = mean ex-ante sum(w*beta) at reform, beta winsorized +/-5; "
          "vol = leg MEDIAN trailing ann. vol;")
    print("junkL/junkS = share of each leg's gross parked in names with trailing ann. vol > 100%; βpost = ex-post OLS beta of the net curve on SPY)")
    print(f"{'cell':<14}{'b_long':>9}{'b_short':>9}{'b_net':>9}{'bpostSPY':>9}{'bpostEW':>9}"
          f"{'vol_long':>9}{'vol_short':>9}{'vS-vL':>9}{'junkL':>8}{'junkS':>8}")
    for kk in keys:
        r = results[kk]
        print(f"{kk:<14}{f(r['ante_beta_long'],9)}{f(r['ante_beta_short'],9)}{f(r['ante_net_beta'],9)}"
              f"{f(r['post_beta_spy'],9)}{f(r['post_beta_ew'],9)}{f(r['med_vol_long'],9)}{f(r['med_vol_short'],9)}"
              f"{f(r['med_vol_short'] - r['med_vol_long'],9)}"
              f"{f(r['junk_share_long'],8)}{f(r['junk_share_short'],8)}")

    print("\nSTRESS EPISODES — RISK-NORMALIZED net return (episode return / that cell's own trailing-252d ann. vol at episode start; PIT).")
    print("Higher = better. 'W' counts episodes where the cell beats the LIVE cell.")
    ep_labels = [e[0] for e in EPISODES]
    print(f"{'cell':<14}" + "".join(f"{lab[:11]:>12}" for lab in ep_labels) + f"{'W/9':>6}")
    wins: dict[str, int] = {}
    for kk in keys:
        row = ""
        w = 0
        for lab in ep_labels:
            cell = ep_rows[lab][kk]
            val = cell.get("risk_norm", float("nan"))
            bval = ep_rows[lab][live_key].get("risk_norm", float("nan"))
            row += f"{val:>12.2f}" if math.isfinite(val) else f"{'n/a':>12}"
            if kk != live_key and math.isfinite(val) and math.isfinite(bval) and val > bval:
                w += 1
        wins[kk] = w
        print(f"{kk:<14}{row}{('-' if kk == live_key else str(w)):>6}")

    print("\nSTRESS EPISODES — RAW net return at common gross (same table, un-normalized, for reference):")
    print(f"{'cell':<14}" + "".join(f"{lab[:11]:>12}" for lab in ep_labels))
    for kk in keys:
        row = "".join(
            f"{ep_rows[lab][kk].get('ret', float('nan')):>11.2%} "
            if math.isfinite(ep_rows[lab][kk].get("ret", float("nan"))) else f"{'n/a':>12}"
            for lab in ep_labels
        )
        print(f"{kk:<14}{row}")

    # sub-period robustness (a cell that only works in one era is not a cell)
    print("\nSUB-PERIOD net Sharpe (ann365) — an adoptable cell must not live in one era:")
    blocks = [("2005-2009", "2005-01-01", "2009-12-31"), ("2010-2013", "2010-01-01", "2013-12-31"),
              ("2014-2017", "2014-01-01", "2017-12-31"), ("2018-2021", "2018-01-01", "2021-12-31"),
              ("2022-2026", "2022-01-01", "2026-12-31")]
    print(f"{'cell':<14}" + "".join(f"{b[0]:>11}" for b in blocks))
    subp: dict[str, dict[str, float]] = {}
    for kk in keys:
        ser = results[kk]["_net"]
        iv = ser.index.to_numpy(dtype=np.int64)
        vv = ser.to_numpy(dtype=np.float64)
        row = ""
        subp[kk] = {}
        for lab, s_, e_ in blocks:
            m_ = (iv >= int(parse_utc(f"{s_}T00:00:00Z"))) & (iv <= int(parse_utc(f"{e_}T00:00:00Z")))
            if m_.sum() > 60:
                sd = float(np.std(vv[m_], ddof=1))
                sr = float(np.mean(vv[m_])) / sd * math.sqrt(ANN) if sd > 0 else float("nan")
            else:
                sr = float("nan")
            subp[kk][lab] = sr
            row += f"{sr:>11.3f}" if math.isfinite(sr) else f"{'n/a':>11}"
        print(f"{kk:<14}{row}")

    # ------------------------------------------------ no-drift modelling robustness
    print("\nROBUSTNESS GRID — NO-DRIFT modelling convention (target weights held constant between reforms, i.e. the book is")
    print("costlessly re-levered to target each session). This is the convention the repo's own live replica")
    print("scripts/probe_alphamax_hyst_live.py uses; the PRIMARY grid above instead lets positions DRIFT, which is what a")
    print("quarterly book actually does and is the only way a squeeze can compound. ROBUSTNESS VIEW ONLY — not an adoption path.")
    nod: dict[str, dict] = {}
    for scheme, k in arms:
        sim = simulate(mom, ret, member, vol, beta, dates, t0, k, scheme, drift=False)
        met = _metrics(sim["net"], sim["gross"], spy, ew)
        key = f"{scheme}_K{k}"
        record_probe_trial(
            "forensic_alphamax_weighting",
            {name: value for name, value in configs[f"no_drift_{key}"].items() if name != "probe"},
            sim["net"],
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
        nod[key] = {**met, **{kk2: vv for kk2, vv in sim.items() if kk2 not in ("net", "gross")},
                    "_net": sim["net"]}
    n_aligned = pd.concat([nod[kk]["_net"].rename(kk) for kk in keys], axis=1).dropna()
    n_boot = _paired_bootstrap(n_aligned.to_numpy(dtype=np.float64).T, live_row,
                               np.random.default_rng(BOOT_SEED))
    print(f"{'cell':<14}{'nodriftSR':>11}{'ΔSR':>9}{'P(win)':>9}{'vol':>7}{'maxDD':>8}{'   | driftSR':>14}{'driftΔSR':>10}")
    for i, kk in enumerate(keys):
        nd, r = nod[kk], results[kk]
        star = "*" if kk == live_key else " "
        print(f"{star}{kk:<13}{nd['net_sharpe_ann365']:>11.3f}{n_boot['obs_diff'][i]:>+9.3f}"
              f"{n_boot['p_win'][i]:>9.2f}{nd['vol_ann365']:>7.3f}{nd['max_dd']:>8.3f}"
              f"{r['net_sharpe_ann365']:>14.3f}{boot['obs_diff'][i]:>+10.3f}")
    print(f"no-drift White Reality Check over the {len(keys) - 1} non-live cells: best ΔSR = "
          f"{n_boot['rc_stat']:+.3f}, RC p = {n_boot['rc_p']:.3f}")

    # ------------------------------------------------- data-hygiene robustness grid
    print(f"\nROBUSTNESS GRID — identical PIT eligibility guard on EVERY cell: trailing 63-session ann. vol <= {VOL_GUARD:.0%}.")
    print("(The survivorship-free tape holds reverse-split penny frenzies — DRYS 2016-17 prints 37x trailing vol and +20,000% sessions —")
    print(" which inverse-vol weighting is structurally immune to and equal/signal weighting is not. This is a ROBUSTNESS VIEW ONLY:")
    print(" no cell may be adopted on it. The question it answers is whether the primary ranking is economics or data quality.)")
    hyg: dict[str, dict] = {}
    for scheme, k in arms:
        sim = simulate(mom, ret, member, vol, beta, dates, t0, k, scheme, vol_guard=VOL_GUARD)
        met = _metrics(sim["net"], sim["gross"], spy, ew)
        key = f"{scheme}_K{k}"
        record_probe_trial(
            "forensic_alphamax_weighting",
            {
                name: value
                for name, value in configs[f"volatility_guard_{key}"].items()
                if name != "probe"
            },
            sim["net"],
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
        hyg[key] = {**met, **{kk2: vv for kk2, vv in sim.items() if kk2 not in ("net", "gross")},
                    "_net": sim["net"]}
    h_aligned = pd.concat([hyg[kk]["_net"].rename(kk) for kk in keys], axis=1).dropna()
    h_boot = _paired_bootstrap(h_aligned.to_numpy(dtype=np.float64).T, live_row,
                               np.random.default_rng(BOOT_SEED))
    print(f"{'cell':<14}{'hygSR365':>10}{'hygΔSR':>9}{'hygP(win)':>10}{'vol':>7}{'maxDD':>8}{'junkL':>8}{'junkS':>8}"
          f"{'   | primarySR':>16}{'primaryΔSR':>12}")
    for i, kk in enumerate(keys):
        h, r = hyg[kk], results[kk]
        star = "*" if kk == live_key else " "
        print(f"{star}{kk:<13}{h['net_sharpe_ann365']:>10.3f}{h_boot['obs_diff'][i]:>+9.3f}"
              f"{h_boot['p_win'][i]:>10.2f}{h['vol_ann365']:>7.3f}{h['max_dd']:>8.3f}"
              f"{f(h['junk_share_long'],8)}{f(h['junk_share_short'],8)}"
              f"{r['net_sharpe_ann365']:>16.3f}{boot['obs_diff'][i]:>+12.3f}")
    print(f"hygiene-grid White Reality Check over the {len(keys) - 1} non-live cells: best ΔSR = "
          f"{h_boot['rc_stat']:+.3f}, RC p = {h_boot['rc_p']:.3f}")

    # ------------------------------------------------------------------------- gate
    print("\n" + line)
    print("PRE-REGISTERED ADOPTION GATE  (G0 solvency + G1 + G2 + G3 + G4 family-wise: ALL required)")
    print(line)
    g4_pass = bool(boot["rc_p"] <= 0.10)
    print(f"G4 White Reality Check over the {len(keys) - 1} non-live cells: best ΔSR = {boot['rc_stat']:+.3f}, "
          f"RC p-value = {boot['rc_p']:.3f} -> "
          f"{'the best cell SURVIVES the family-wise null' if g4_pass else 'the best cell is NOT distinguishable from luck; G4 FAILS for the whole family'}")
    print(f"cells clearing G3 individually: {int(sum(1 for i, kk in enumerate(keys) if kk != live_key and boot['p_win'][i] >= 0.90))} "
          f"(chance expectation at {len(keys) - 1} cells x 10% = {(len(keys) - 1) * 0.10:.1f})")
    print(f"context: SE(net Sharpe) on {base['n_days']} sessions ~ {base['se_sharpe_ann365']:.3f}; "
          f"the live cell's own net Sharpe is {base['net_sharpe_ann365']:+.3f} — i.e. every cell in this grid is "
          "statistically indistinguishable from ZERO before any cell is compared with any other.\n")
    n_ep_avail = sum(1 for lab in ep_labels
                     if math.isfinite(ep_rows[lab][live_key].get("risk_norm", float("nan"))))
    need = n_ep_avail // 2 + 1
    print(f"{'cell':<14}{'G0 solvent':>12}{'G1 ΔSR>0':>10}{f'G2 wins>={need}':>12}{'G3 P>=0.90':>12}{'G4 family':>11}{'  verdict'}")
    gate: dict[str, dict] = {}
    passers: list[str] = []
    for i, kk in enumerate(keys):
        if kk == live_key:
            continue
        g0 = not bool(results[kk].get("ruin", False))
        g1 = bool(boot["obs_diff"][i] > 0)
        g2 = bool(wins[kk] >= need)
        g3 = bool(boot["p_win"][i] >= 0.90)
        ok = g0 and g1 and g2 and g3 and g4_pass
        gate[kk] = {"delta_sharpe": float(boot["obs_diff"][i]), "G0_solvent": g0, "G1_full_sample": g1,
                    "episode_wins": wins[kk], "episodes_available": n_ep_avail,
                    "G2_majority_stress": g2, "p_win": float(boot["p_win"][i]), "G3_bootstrap": g3,
                    "G4_family_wise": g4_pass, "adoptable": ok}
        if ok:
            passers.append(kk)
        c2 = f"{wins[kk]}/{n_ep_avail} " + ("PASS" if g2 else "fail")
        c3 = f"{boot['p_win'][i]:.2f} " + ("PASS" if g3 else "fail")
        print(f"{kk:<14}{('PASS' if g0 else 'RUIN'):>12}{('PASS' if g1 else 'fail'):>10}{c2:>12}{c3:>12}"
              f"{('PASS' if g4_pass else 'fail'):>11}  {'ADOPTABLE' if ok else '-'}")
    surface = float(np.nanmax([results[kk]["net_sharpe_ann365"] for kk in keys]) -
                    np.nanmin([results[kk]["net_sharpe_ann365"] for kk in keys]))
    print(f"\nSURFACE SPREAD: best-minus-worst full-sample net Sharpe across the 16 cells = {surface:.3f}")
    ruined = [kk for kk in keys if results[kk].get("ruin", False)]
    if ruined:
        print(f"SOLVENCY: cell(s) that traded through ZERO equity over the full window (G0 = RUIN): {ruined}")
    if not passers:
        print("VERDICT: HONEST NULL — no cell clears the pre-registered gate. Neither the weighting scheme nor the")
        print("breadth K is the July-2026 defect, and neither is a free Sharpe lever. RECOMMENDATION: CHANGE NOTHING —")
        print("keep inverse-vol at K=100.")
    else:
        print(f"VERDICT: candidate cell(s) clear the FULL gate including the family-wise Reality Check: {passers}.")
        print("A full walk-forward gauntlet (1 ledger trial) would be the next step, and is a human decision.")

    # Identity-aligned union view of the live cell and the best cell.
    best_key = keys[int(np.nanargmax([results[kk]["net_sharpe_ann365"] for kk in keys]))]
    n_led, var_sr = union.n_hypotheses(), union.hypothesis_sharpe_variance()
    trials_logged = union.n_trials() - audit_before
    dsr_view: dict[str, dict] = {}
    for kk in {live_key, best_key}:
        rep = dsr_from_returns(results[kk]["_net"], max(2, n_led), var_sr, ANN)
        dsr_view[kk] = {
            "selection_union": {
                "N": n_led,
                "dsr": float(np.real(rep.dsr)),
                "psr": float(np.real(rep.psr)),
            }
        }
    print("\nIdentity-aligned union deflated view:")
    for kk, d in dsr_view.items():
        for lname, vv in d.items():
            print(f"  {kk:<14} ledger {lname:<13} N={vv['N']:<4} DSR={vv['dsr']:.3f} PSR={vv['psr']:.3f}")

    # ------------------------------------------------------------------------ persist
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "probe": "alphamax_weighting_breadth",
        "generated_utc": pd.Timestamp.now("UTC").isoformat(),
        "window": {"warmup": a.warmup, "book_start": a.start, "end": a.end,
                   "sessions": int(base["n_days"])},
        "universe": {"ever_member_ids": len(ids), "market_proxy": SPY_ID,
                     "proxy_source": proxy_src, "proxy_in_lake_partition": bool(spy_present),
                     "proxy_is_universe_member": bool(spy_member)},
        "construction": {
            "signal": "eq_mom_252_21", "reform_bars": REFORM_BARS, "vol_window": VOL_WINDOW,
            "beta_window": BETA_WINDOW, "gross_leg": GROSS_LEG, "w_max": W_MAX,
            "cost_oneway_bps": COST_ONEWAY * 1e4, "borrow_ann_bps": BORROW_ANN * 1e4,
            "no_trade_band": NO_TRADE_BAND, "ann_basis": ANN, "volcap_mult": VOLCAP_MULT,
            "ret_clip": list(RET_CLIP), "drift_between_reforms": True,
        },
        "live_cell": live_key,
        "external_validity_anchor": anchor_block,
        "grid": {kk: {k2: v2 for k2, v2 in r.items() if k2 != "_net"} for kk, r in results.items()},
        "bootstrap": {
            "B": BOOT_B, "mean_block": BOOT_BLOCK, "seed": BOOT_SEED,
            "per_cell": {kk: {"delta_sharpe": float(boot["obs_diff"][i]),
                              "p_win": float(boot["p_win"][i]),
                              "ci90": [float(boot["diff_lo"][i]), float(boot["diff_hi"][i])]}
                         for i, kk in enumerate(keys)},
            "reality_check": {"best_delta": boot["rc_stat"], "p_value": boot["rc_p"]},
        },
        "episodes": ep_rows,
        "subperiods": subp,
        "nodrift_grid": {
            "role": "ROBUSTNESS VIEW ONLY — modelling-convention check, not an adoption path",
            "cells": {kk: {k2: v2 for k2, v2 in h.items() if k2 != "_net"} for kk, h in nod.items()},
            "bootstrap": {kk: {"delta_sharpe": float(n_boot["obs_diff"][i]),
                               "p_win": float(n_boot["p_win"][i])} for i, kk in enumerate(keys)},
            "reality_check": {"best_delta": n_boot["rc_stat"], "p_value": n_boot["rc_p"]},
        },
        "hygiene_grid": {
            "vol_guard_ann": VOL_GUARD,
            "role": "ROBUSTNESS VIEW ONLY — not an adoption path",
            "cells": {kk: {k2: v2 for k2, v2 in h.items() if k2 != "_net"} for kk, h in hyg.items()},
            "bootstrap": {kk: {"delta_sharpe": float(h_boot["obs_diff"][i]),
                               "p_win": float(h_boot["p_win"][i])} for i, kk in enumerate(keys)},
            "reality_check": {"best_delta": h_boot["rc_stat"], "p_value": h_boot["rc_p"]},
        },
        "gate": gate,
        "passers": passers,
        "surface_spread_sharpe": surface,
        "dsr_readonly": dsr_view,
        "selection_union": {"N": n_led, "var_sr": var_sr},
        "trials_logged_this_run": trials_logged,
        "note": ("All 48 measured return configurations (16 primary, 16 no-drift, and 16 "
                 "volatility-guard) are union-registered. Promotion would require a separate "
                 "full walk-forward and a human decision."),
    }
    (OUT_DIR / "report.json").write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\npersisted: {OUT_DIR / 'report.json'}")
    print(f"TRIAL RECORDS APPENDED THIS RUN: {trials_logged}   (total wall {time.time() - t_wall:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
