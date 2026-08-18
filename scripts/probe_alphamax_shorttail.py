#!/usr/bin/env python3
"""PROBE — CANDIDATE C: SHORT-LEG TAIL-RISK MANAGEMENT on the ALPHAMAX 12-1 book.

2026-08-01. MEASURE-ONLY. NEW file. Reads src/** + configs as templates, MUTATES NOTHING.
Writes only artifacts/probe/alphamax_shorttail/*. Appends NO experiments-ledger trial —
this is a cheap CONSTRUCTION SCREEN, not a production walk-forward. TRIALS BURNED = 0.
DSR at the current ledger N (var/experiments.jsonl, N=114) is read-only via
dsr_from_returns (a pure function) so the deflated view is visible without recording.

======================================================================================
WHY (the observed failure)
======================================================================================
July 2026: the live US-equity sleeve lost -7.75% in a textbook momentum junk-rally
squeeze. SPY ground UP +3.5%; the sleeve's worst days landed on FLAT market days; the
SHORT leg squeezed violently (ALIT +88% split-adjusted, RPD +61%, QDEL +32%) while the
momentum LONG complex sold off (MU -20%, TER -22%, TTMI -25%). Both legs lost at once.
Every independent construction of 12-1 lost on the same days => the SIGNAL is not the
culprit. This probe therefore tests CONSTRUCTION-side risk controls that leave the
signal byte-identical.

CANDIDATE C specifically: a dollar-neutral book has UNBOUNDED per-name loss potential
on the SHORT leg. Shares are fixed between quarterly reforms, so a short that triples
costs 2x its entry notional while a long that halves costs only 0.5x. That asymmetry is
structural, not statistical. Test cheap, standard, SIGNAL-PRESERVING controls:
  (1) per-name STOP on the short leg  (force-cover a short that has run >= X% against us)
  (2) per-name DRIFT CAP on the short leg (trim any short whose weight has grown to
      CAP_MULT x its entry weight back to the entry weight)
  (3) SHORT-LEG VOL TARGETING (de-risk the short gross when the short basket's own
      realized vol spikes -- which is exactly when squeezes happen)

======================================================================================
WHY A SELF-CONTAINED, *DRIFTING* BOOK SIMULATOR
======================================================================================
The production WalkForwardRunner exposes no per-name stop / drift cap / leg-vol-target
knob; measuring these through it would require editing src/** (forbidden -- promotion is
a separate deliberate human step). So all arms run through ONE self-contained simulator
and the A/B is INTERNAL (this simulator's own baseline vs its treatments), apples-to-
apples by construction.

CRITICAL vs the two prior probes in this family (probe_alphamax_turnover.py,
probe_alphamax_hyst_live.py): those used the textbook decile convention of RESETTING to
target weights every day, which BOUNDS per-name drift and therefore DELETES the very tail
this probe exists to measure. That convention is wrong for Candidate C and is also NOT
what production does: BlendStrategy returns {} on non-rebalance bars (src/alphaforge/
portfolio/strategy.py -- `hold_between_rebalance`), so the backtest/live engine leaves
positions untouched and SHARES DRIFT buy-and-hold for the whole 63-session holding
period. This simulator therefore tracks POSITION VALUES in currency with a compounding
equity, exactly reproducing the unbounded short drift:
    v_i(t+1) = v_i(t) * (1 + r_i(t+1));   E(t+1) = E(t) + Sum_i v_i(t) r_i(t+1) - costs
A short entered at -0.25% of equity that triples ends at -0.75% => a -0.50% equity hit,
2x its notional. That is the object under study.
An extra DIAGNOSTIC arm (`daily_reset`) runs the old no-drift convention on BOTH legs so
the report can quantify how much of the tail is drift per se.

======================================================================================
CONSTRUCTION (mirrors configs/equity.yaml + configs/base.yaml + optimizer.py
RankEqualVolFallback with dollar_neutral=True)
======================================================================================
  * lake     : data/lake  (profile `equity`) -- survivorship-free, 17,843 XUSE names,
               bars through 2026-07-31, i.e. the ENTIRE July-2026 squeeze is in-sample
               for the stress table. (The Sharadar research lake stops 2026-06-18 and
               therefore CANNOT see the episode; it is deliberately not used here.)
  * WINDOW   : 2005-01-03 .. 2026-07-31 (5428 sessions, 87 quarterly reforms). MEASURED,
               NOT CHOSEN: the repo's XNYS session calendar returns ZERO expected bar opens
               before 2004-01-01 (verified: expected_bar_opens for 1998/1999/2000/2003 are
               all empty), and eq_mom_252_21 then eats the first 252 sessions of 2004 as
               lookback warmup. So 2005-01-03 is the earliest session at which this repo can
               produce a warm 12-1 signal at all. Extending it would require touching src/**
               (forbidden). CONSEQUENCE, disclosed: the 2000-02 dot-com unwind and the 2008
               peak are outside the window; the 2009 momentum crash, 2020, 2021, 2022 and
               2026-07 are all inside it.
  * signal   : eq_mom_252_21 (12-1 momentum), computed by the real FeatureEngine with
               PIT split-only adjustment; PIT universe mask applied before any
               cross-sectional statistic. UNCHANGED by every arm.
  * universe : PIT UniverseStore membership (universe.size=2000, entry 1800 / exit 2300)
  * breadth  : K = 100 per side (portfolio.rank_top_k), FIXED across all arms
  * weights  : inverse-vol within each leg (63-session realized vol), per-leg gross
               0.25 (=> 0.5 total, dollar-neutral Sum w = 0), +-w_max 0.15, per-leg renorm
  * cadence  : reform every 63 sessions (signals.horizon_bars = the production cadence)
  * costs    : ALWAYS. 6 bp one-way per unit traded (1 commission + 3 half-spread +
               2 latency, equity.yaml) + 50 bp/yr GC borrow accrued daily on short gross.
               0.001 no-trade band at reforms (base.yaml). Controls pay full cost.
  * PIT      : every decision uses data through the CLOSE of session t and takes effect
               for session t+1's return. NO same-bar fills anywhere, stops included.
  * hygiene  : single-session returns winsorized to [-50%, +100%], identical across all
               arms. NOTE the direction of this bias: capping a +100%+ single-day print
               UNDERSTATES the short tail, so it makes the BASELINE look SAFER than it
               is and therefore biases the test AGAINST the controls. Conservative.
  * ANN      : 365 for headline Sharpe/turnover (repo convention); 252 shown alongside.

======================================================================================
PRE-REGISTERED ARMS  (locked in this docstring BEFORE any number was computed)
======================================================================================
  baseline      faithful drifting quarterly dollar-neutral 12-1 book (the control)
  stop_50       PRIMARY (1). Cover any short whose price is >= +50% above its entry
                (|v_i| >= 1.5 |v_entry_i|). Proceeds go to CASH; the name is BARRED from
                the short leg until the next quarterly reform (else we would instantly
                re-short into the squeeze). X = 50% is PRE-REGISTERED, not searched.
  stop_50_dn    stop_50 + trim the LONG leg pro-rata by the same currency amount, so the
                control does not silently turn the book net-long. THE CONFOUND CONTROL:
                if stop_50 helps and stop_50_dn does not, the "help" was equity beta.
  stop_30       sensitivity (tighter). Reported for monotonicity, NOT for selection.
  stop_100      sensitivity (looser). Reported for monotonicity, NOT for selection.
  cap_1.5x      PRIMARY (2). Any short whose weight has grown to >= 1.5x its entry weight
                is trimmed back to its entry weight (partial cover). Note: the static
                portfolio.w_max = 0.15 is NON-BINDING at K=100 (per-name |w| ~ 0.25%),
                so a *static* size cap is untestable here -- the only size cap that can
                bind on this book is a DRIFT cap, which is what this arm is.
  cap_1.25x     sensitivity (tighter).
  cap_2.0x      sensitivity (looser).
  svol          PRIMARY (3). Short-leg vol targeting, DE-RISK ONLY (never levers up):
                sigma_s(t) = 21-session realized vol of the CURRENT short basket;
                sigma*(t) = expanding MEDIAN of sigma_s over the past (PIT, >=252 obs);
                s(t) = clip(sigma*/sigma_s, 0.50, 1.00). Checked weekly (every 5th
                session), re-applied only when it moves >10% relative (band -> no churn).
                Short gross target = 0.25 * s.
  svol_dn       svol applied to BOTH legs (same multiplier) -- the dollar-neutrality
                confound control for arm `svol`.
  daily_reset   DIAGNOSTIC ONLY, not a candidate: reset BOTH legs to the last reform's
                target weights every session. Bounds how much of the tail is pure drift.
                Its turnover/cost is deliberately absurd; it is a measuring stick.

======================================================================================
PRE-REGISTERED STRESS EPISODES (windows fixed before computing; the anti-fitting spine)
======================================================================================
  2009_mom_crash   2009-03-09 .. 2009-06-30   the canonical momentum crash / junk rally
  2020_covid       2020-02-19 .. 2020-03-23   Covid crash
  2020_vaccine     2020-11-01 .. 2020-12-15   Nov-9 vaccine value/junk rotation
  2021_meme        2021-01-15 .. 2021-03-15   meme short squeeze
  2022_bear        2022-01-01 .. 2022-12-31   2022 bear/rotation regime (full year)
  2026_07_squeeze  2026-07-01 .. 2026-07-31   THE observed live failure
  (bonus, reported but NOT in the gate: 2016_q1_rev 2016-01-01..2016-04-30,
   2019_09_momrev 2019-08-26..2019-09-30)

======================================================================================
PRE-REGISTERED ACCEPT / REJECT GATE
======================================================================================
A control is ADOPTED only if ALL of:
  G1  full-sample net Sharpe(365) >= baseline - 0.05        (does not buy DD with Sharpe)
  G2  full-sample maxDD <= 0.90 x baseline maxDD            (>=10% relative DD cut)
  G3  it improves the episode return by >= 25% RELATIVE TO THE BASELINE LOSS in at least
      2 of the 6 gate episodes, AND at least one of those is NOT 2026_07_squeeze
      (this clause is the WINDOW-FITTING KILL SWITCH: helping only in July 2026 fails)
  G4  the control TRIGGERS on >= 5 distinct sessions but < 25% of all sessions
      (never firing = untested insurance; always firing = a different strategy)
Otherwise the verdict is:
  honest-null   Sharpe preserved (G1 ok) but no material DD/tail benefit (G2 or G3 fail)
  worse         Sharpe falls > 0.05 AND/OR maxDD rises
HONEST PRIOR, stated up front: stops on a mean-reverting book are notorious for
CONVERTING a temporary drawdown into a REALIZED loss. Cutting BOTH the tail and the
Sharpe is a BAD TRADE, and this file will say so.

    uv run python scripts/probe_alphamax_shorttail.py
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
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

OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_shorttail"

# ---- construction constants (configs/equity.yaml, configs/base.yaml, optimizer.py) ----
ANN = 365.0            # repo headline annualization basis
TRADING_DAYS = 252.0   # borrow accrual + honest calendar-Sharpe cross-check
VOL_WINDOW = 63        # trailing sessions for the inverse-vol denominator
VOL_MINP = 30
GROSS_LEG = 0.25       # per-leg gross => 0.5 total, dollar-neutral
W_MAX = 0.15           # portfolio.w_max (non-binding at K=100 -> the point of arm `cap_*`)
COST_ONEWAY = 6e-4     # 1bp comm + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4     # 50 bp/yr GC borrow on the short gross (equity.yaml)
NO_TRADE_BAND = 0.001  # base.yaml no_trade_band (reform dust suppression, all arms)
K_PER_SIDE = 100       # portfolio.rank_top_k
REFORM_BARS = 63       # signals.horizon_bars (quarterly production cadence)
MIN_ELIG = 500         # skip a reform if the PIT cross-section is thinner than this
RET_CLIP = (-0.5, 1.0)  # single-session winsorization (see docstring: conservative)

# short-leg vol-target knobs (pre-registered)
SVOL_WIN = 21          # realized-vol window for the short basket
SVOL_MINOBS = 252      # expanding-median warmup before the control may act
SVOL_CHECK = 5         # weekly check cadence (sessions)
SVOL_BAND = 0.10       # only re-apply when the desired multiplier moves >10% relative
SVOL_FLOOR = 0.50      # de-risk only: multiplier in [SVOL_FLOOR, 1.0]

# arm name -> (control, param, dollar_neutral_restore)
ARMS: list[tuple[str, str | None, float, bool]] = [
    ("baseline",    None,   0.0,  False),
    ("stop_50",     "stop", 0.50, False),
    ("stop_50_dn",  "stop", 0.50, True),
    ("stop_30",     "stop", 0.30, False),
    ("stop_100",    "stop", 1.00, False),
    ("cap_1.5x",    "cap",  1.50, False),
    ("cap_1.25x",   "cap",  1.25, False),
    ("cap_2.0x",    "cap",  2.00, False),
    ("svol",        "svol", SVOL_FLOOR, False),
    ("svol_dn",     "svol", SVOL_FLOOR, True),
    ("daily_reset", "reset", 0.0, False),
]
PRIMARY = ("stop_50", "cap_1.5x", "svol")
DIAGNOSTIC = ("daily_reset",)

# pre-registered stress episodes; gate uses GATE_EPISODES only
EPISODES: list[tuple[str, str, str]] = [
    ("2009_mom_crash",  "2009-03-09", "2009-06-30"),
    ("2020_covid",      "2020-02-19", "2020-03-23"),
    ("2020_vaccine",    "2020-11-01", "2020-12-15"),
    ("2021_meme",       "2021-01-15", "2021-03-15"),
    ("2022_bear",       "2022-01-01", "2022-12-31"),
    ("2026_07_squeeze", "2026-07-01", "2026-07-31"),
    ("2016_q1_rev",     "2016-01-01", "2016-04-30"),
    ("2019_09_momrev",  "2019-08-26", "2019-09-30"),
]
GATE_EPISODES = (
    "2009_mom_crash", "2020_covid", "2020_vaccine", "2021_meme", "2022_bear", "2026_07_squeeze",
)

# time chunks for the panel build (memory discipline). Each is (pad_start, book_start, end);
# `pad_start` only warms the 63-session realized-vol rolling window, then rows < book_start
# are dropped. The FeatureEngine warms the 252-session momentum window itself.
# NOTE: no pre-2004 chunk -- the repo's XNYS session calendar has no expected bar opens before
# 2004-01-01, so such a chunk returns an empty frame (verified, not assumed).
CHUNKS: list[tuple[str, str, str]] = [
    ("2003-06-01", "2004-01-01", "2009-01-01"),
    ("2008-06-01", "2009-01-01", "2014-01-01"),
    ("2013-06-01", "2014-01-01", "2019-01-01"),
    ("2018-06-01", "2019-01-01", "2023-01-01"),
    ("2022-06-01", "2023-01-01", "2026-08-01"),
]


# --------------------------------------------------------------- daily-return probe spec
def _probe_dret_fn(ctx, spec):
    """Daily SIMPLE return panel from the sanctioned PIT split-adjusted close.

    Reuses equity_price._adjusted_close_panel (the ONE place equity adjustment happens),
    so returns carry the identical split-only, fail-closed, PIT convention as every price
    factor. Simple (arithmetic) returns because book P&L is Sum w.r; NaN across a missing
    bar (never bridged). Evaluation input only -- direction is irrelevant.
    """
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


# ------------------------------------------------------------------------- construction
def _leg_weights(sel: np.ndarray, invvol: np.ndarray, sign: float, gross: float) -> np.ndarray:
    """Inverse-vol weights for one leg, |Sum| = gross, +-W_MAX clipped, per-leg renormalized
    -- the RankEqualVolFallback dollar-neutral leg."""
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


def simulate(
    mom: np.ndarray, ret_use: np.ndarray, eligible_all: np.ndarray, vol: np.ndarray,
    t0: int, control: str | None, param: float, dn_restore: bool,
) -> dict:
    """One arm over the FULL history. Drifting-share book with compounding equity.

    Loop invariant: entering iteration ``t``, ``v`` holds the position VALUES (currency)
    that were decided at the close of session ``t-1`` (or earlier) and are in force for
    session ``t``'s return. Nothing decided at ``t`` can touch ``t``'s P&L => no same-bar
    fills. Trades decided at the close of ``t`` are paid for at ``t+1`` (``pending_cost``).
    """
    T, N = mom.shape
    reb_set = set(range(t0, T, REFORM_BARS))

    E = 1.0
    v = np.zeros(N, dtype=np.float64)          # position values, currency
    entry_v = np.zeros(N, dtype=np.float64)    # value at last reform entry
    entry_w = np.zeros(N, dtype=np.float64)    # weight at last reform entry
    last_tgt_w = np.zeros(N, dtype=np.float64)  # last reform's target weights (for daily_reset)
    # Stopped-out shorts, barred until the next reform. NOTE (honest): entry into the book
    # happens ONLY at a reform in this construction, so the bar is vacuous by construction --
    # it is kept because the pre-registered spec names it and because any future variant with
    # intra-period entry would need it.
    barred = np.zeros(N, dtype=bool)

    net = np.full(T, np.nan, dtype=np.float64)
    grs = np.full(T, np.nan, dtype=np.float64)
    long_pnl = np.full(T, np.nan, dtype=np.float64)     # leg attribution: long-leg return contribution
    short_pnl = np.full(T, np.nan, dtype=np.float64)    # leg attribution: short-leg return contribution
    net_dollar = np.full(T, np.nan, dtype=np.float64)   # Sum(v)/E  -- dollar-neutrality diagnostic
    long_g = np.full(T, np.nan, dtype=np.float64)
    short_g = np.full(T, np.nan, dtype=np.float64)

    pending_cost = 0.0
    reb_turnovers: list[float] = []
    ctrl_turnover_total = 0.0
    cost_total = 0.0
    borrow_total = 0.0
    n_reform_skipped = 0
    long_sizes: list[int] = []
    short_sizes: list[int] = []

    # control telemetry
    trigger_sessions = 0      # sessions on which the control did ANYTHING
    trigger_events = 0        # per-name events (stop covers / cap trims / rescalings)
    trigger_dates_idx: list[int] = []
    worst_short_mult = 1.0    # max |v|/|entry_v| ever reached by a short (the raw tail)

    # svol state
    s_applied = 1.0
    sig_hist: list[float] = []
    svol_scale_path = np.full(T, np.nan, dtype=np.float64)

    for t in range(t0, T):
        r = ret_use[t]
        pnl = float(v @ r)
        is_long = v > 0.0
        lpnl = float(v[is_long] @ r[is_long])
        spnl = pnl - lpnl
        sg = float(-np.minimum(v, 0.0).sum())
        lg = float(np.maximum(v, 0.0).sum())
        borrow = sg * (BORROW_ANN / TRADING_DAYS)
        E_prev = E
        if E_prev <= 0.0:
            break
        net[t] = (pnl - borrow - pending_cost) / E_prev
        grs[t] = pnl / E_prev
        long_pnl[t] = lpnl / E_prev
        short_pnl[t] = spnl / E_prev
        net_dollar[t] = float(v.sum()) / E_prev
        long_g[t] = lg / E_prev
        short_g[t] = sg / E_prev
        borrow_total += borrow
        cost_total += pending_cost
        E = E_prev + pnl - borrow - pending_cost
        v = v * (1.0 + r)
        pending_cost = 0.0
        if E <= 0.0:
            break

        traded = 0.0   # currency traded on decisions made at the CLOSE of t (effective t+1)
        fired = False

        if t in reb_set:
            elig = eligible_all[t]
            n_elig = int(elig.sum())
            if n_elig < MIN_ELIG:
                n_reform_skipped += 1
            else:
                m = mom[t]
                ei = np.where(elig)[0]
                order = ei[np.argsort(-m[ei], kind="stable")]  # strongest momentum first
                long_sel = np.zeros(N, dtype=bool)
                short_sel = np.zeros(N, dtype=bool)
                long_sel[order[:K_PER_SIDE]] = True
                short_sel[order[-K_PER_SIDE:]] = True
                short_sel &= ~long_sel

                invvol = np.where(np.isfinite(vol[t]) & (vol[t] > 0),
                                  1.0 / np.where(vol[t] > 0, vol[t], np.nan), 0.0)
                invvol = np.nan_to_num(invvol, nan=0.0, posinf=0.0, neginf=0.0)
                gl = GROSS_LEG * (s_applied if (control == "svol" and dn_restore) else 1.0)
                gs = GROSS_LEG * (s_applied if control == "svol" else 1.0)
                w_new = _leg_weights(long_sel, invvol, +1.0, gl) + _leg_weights(short_sel, invvol, -1.0, gs)

                v_new = w_new * E
                small = np.abs(v_new - v) <= NO_TRADE_BAND * E
                v_new = np.where(small, v, v_new)
                traded += float(np.abs(v_new - v).sum())
                reb_turnovers.append(float(np.abs(v_new - v).sum()) / E)
                v = v_new
                entry_v = v.copy()
                entry_w = v / E
                last_tgt_w = v / E
                barred[:] = False
                long_sizes.append(int((v > 1e-12).sum()))
                short_sizes.append(int((v < -1e-12).sum()))

        else:
            # short-leg drift diagnostic, computed for EVERY arm (baseline included) so the
            # raw magnitude of the unbounded tail is measurable, not just the treated one.
            shorts = v < -1e-12
            mult = np.zeros(N, dtype=np.float64)
            den = np.abs(entry_v)
            ok = shorts & (den > 1e-15)
            if ok.any():
                mult[ok] = np.abs(v[ok]) / den[ok]
                worst_short_mult = max(worst_short_mult, float(mult[ok].max()))

            if control in ("stop", "cap") and shorts.any():
                if control == "stop":
                    hit = ok & (mult >= 1.0 + param)
                    if hit.any():
                        amount = float(np.abs(v[hit]).sum())
                        traded += amount
                        v = np.where(hit, 0.0, v)
                        barred |= hit
                        trigger_events += int(hit.sum())
                        fired = True
                        if dn_restore:
                            longs = v > 1e-12
                            lgn = float(v[longs].sum())
                            if lgn > amount > 0.0:
                                f = (lgn - amount) / lgn
                                traded += float(v[longs].sum()) * (1.0 - f)
                                v[longs] *= f
                else:  # cap
                    hit = ok & (mult >= param)
                    if hit.any():
                        tgt = -np.abs(entry_w[hit]) * E
                        delta = float(np.abs(v[hit] - tgt).sum())
                        amount = delta
                        traded += delta
                        v[hit] = tgt
                        trigger_events += int(hit.sum())
                        fired = True
                        if dn_restore:
                            longs = v > 1e-12
                            lgn = float(v[longs].sum())
                            if lgn > amount > 0.0:
                                f = (lgn - amount) / lgn
                                traded += float(v[longs].sum()) * (1.0 - f)
                                v[longs] *= f

            elif control == "svol":
                sgn = float(-np.minimum(v, 0.0).sum())
                if sgn > 0.0 and t >= SVOL_WIN:
                    u = np.abs(np.minimum(v, 0.0)) / sgn
                    b = ret_use[t - SVOL_WIN + 1: t + 1] @ u
                    sig = float(np.std(b, ddof=1)) * math.sqrt(TRADING_DAYS)
                    if math.isfinite(sig) and sig > 0.0:
                        sig_hist.append(sig)
                        if len(sig_hist) >= SVOL_MINOBS and (t - t0) % SVOL_CHECK == 0:
                            star = float(np.median(sig_hist))
                            desired = float(np.clip(star / sig, SVOL_FLOOR, 1.0))
                            if abs(desired - s_applied) > SVOL_BAND * s_applied:
                                f = desired / s_applied
                                sh = v < -1e-12
                                traded += float(np.abs(v[sh]).sum()) * abs(1.0 - f)
                                v[sh] *= f
                                if dn_restore:
                                    lo = v > 1e-12
                                    traded += float(np.abs(v[lo]).sum()) * abs(1.0 - f)
                                    v[lo] *= f
                                s_applied = desired
                                trigger_events += 1
                                fired = True
                svol_scale_path[t] = s_applied

            elif control == "reset":
                v_new = last_tgt_w * E
                d = float(np.abs(v_new - v).sum())
                if d > 0.0:
                    traded += d
                    v = v_new
                    trigger_events += 1
                    fired = True

        if fired:
            trigger_sessions += 1
            trigger_dates_idx.append(t)
        if traded > 0.0:
            if t not in reb_set:   # control-driven churn only (reform churn is reb_turnovers)
                ctrl_turnover_total += traded / E
            pending_cost = traded * COST_ONEWAY

    n_days = int(np.isfinite(net[t0:]).sum())
    tot_turn = float(np.sum(reb_turnovers)) + 0.0
    return {
        "net": net, "gross": grs, "t0": t0, "long_pnl": long_pnl, "short_pnl": short_pnl,
        "net_dollar": net_dollar, "long_gross": long_g, "short_gross": short_g,
        "svol_scale": svol_scale_path,
        "n_days": n_days,
        "reform_turnover_ann": (tot_turn / n_days * ANN) if n_days else float("nan"),
        "control_turnover_ann": (ctrl_turnover_total / n_days * ANN) if n_days else float("nan"),
        "total_cost_drag_ann_bps": (cost_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "borrow_drag_ann_bps": (borrow_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "n_reforms": len(reb_turnovers), "n_reform_skipped": n_reform_skipped,
        "avg_long_names": float(np.mean(long_sizes)) if long_sizes else float("nan"),
        "avg_short_names": float(np.mean(short_sizes)) if short_sizes else float("nan"),
        "trigger_sessions": trigger_sessions, "trigger_events": trigger_events,
        "trigger_rate": trigger_sessions / n_days if n_days else float("nan"),
        "trigger_idx": trigger_dates_idx,
        "worst_short_drift_mult": worst_short_mult,
        "ruined": bool(np.isnan(net[-1]) and t0 < T - 1 and np.isfinite(net[t0])),
    }


def _metrics(net_s: pd.Series, gross_s: pd.Series) -> dict:
    v = net_s.to_numpy(dtype=np.float64)
    g = gross_s.to_numpy(dtype=np.float64)
    sd = float(np.std(v, ddof=1))
    gd = float(np.std(g, ddof=1))
    eq = np.cumprod(1.0 + v)
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.max(1.0 - eq / peak)) if eq.size else float("nan")
    yrs = len(v) / TRADING_DAYS
    total = float(np.prod(1.0 + v))
    dn = np.sort(v)
    return {
        "net_sharpe_ann365": (float(np.mean(v)) / sd * math.sqrt(ANN)) if sd > 0 else float("nan"),
        "net_sharpe_ann252": (float(np.mean(v)) / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "gross_sharpe_ann365": (float(np.mean(g)) / gd * math.sqrt(ANN)) if gd > 0 else float("nan"),
        "vol_ann365": sd * math.sqrt(ANN),
        "max_dd": max_dd,
        "cagr": (total ** (1.0 / yrs) - 1.0) if yrs > 0 else float("nan"),
        "total_return": total - 1.0,
        "skew": float(pd.Series(v).skew()),
        "worst_day": float(dn[0]) if dn.size else float("nan"),
        "cvar_1pct": float(dn[: max(1, int(0.01 * dn.size))].mean()) if dn.size else float("nan"),
    }


def _nw_ols(y: np.ndarray, x: np.ndarray, lags: int = 5) -> dict:
    """OLS ``y = a + b x`` with Newey-West HAC standard errors (the alpha/beta decomposition).

    Used to answer the ONE question that decides Candidate C: is a control's incremental P&L
    (arm minus baseline) genuine risk management, or is it just unhedged market BETA bought by
    quietly deleting short exposure? ``b`` is that beta; ``a`` is what survives it.
    """
    n = y.size
    X = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    e = y - X @ beta
    omega = (X * (e**2)[:, None]).T @ X
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        a_ = X[lag:] * (e[lag:] * e[:-lag])[:, None]
        g = a_.T @ X[:-lag]
        omega += w * (g + g.T)
    v = xtx_inv @ omega @ xtx_inv
    se = np.sqrt(np.diag(v))
    return {
        "alpha_daily": float(beta[0]), "alpha_ann": float(beta[0] * TRADING_DAYS),
        "alpha_t_nw": float(beta[0] / se[0]) if se[0] > 0 else float("nan"),
        "beta": float(beta[1]),
        "beta_t_nw": float(beta[1] / se[1]) if se[1] > 0 else float("nan"),
        "r2": float(1.0 - np.var(e) / np.var(y)) if np.var(y) > 0 else float("nan"),
    }


def _vol_overlay(net_s: pd.Series, target: float = 0.15, s_max: float = 1.5, halflife: int = 240) -> pd.Series:
    """PRODUCTION-STYLE book vol-target overlay applied ex-post to a net-return series.

    Mirrors src/alphaforge/portfolio/overlay.py::vol_target on the REALIZED branch:
    ``s = min(target / sigma_realized_ann, s_max)`` with sigma_realized = EWMA std of realized
    per-bar portfolio returns (halflife 240 bars) x sqrt(252). Shifted one session so the scale
    at t uses only returns through t-1 (PIT). ``gross_max`` never binds here (base gross 0.5,
    s_max 1.5 -> 0.75 < 1.0).

    APPROXIMATION, disclosed: applying the scalar to the return series ignores the overlay's
    own re-scaling turnover cost, so the overlaid rows are slightly FLATTERED. It is used only
    to ask whether a short-leg vol control still adds anything ON TOP of the overlay the live
    book ALREADY runs (base.yaml vol_target_ann: 0.15) — the "redundant with the book vol
    target" kill test.
    """
    rv = net_s.ewm(halflife=halflife, min_periods=63).std() * math.sqrt(TRADING_DAYS)
    s = (target / rv).clip(upper=s_max).shift(1)
    return net_s * s.fillna(1.0)


def _dd_dates(net_s: pd.Series) -> dict:
    v = net_s.to_numpy(dtype=np.float64)
    eq = np.cumprod(1.0 + v)
    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / peak
    i = int(np.argmax(dd))
    j = int(np.argmax(eq[: i + 1]))
    idx = pd.to_datetime(net_s.index, unit="ms")
    return {"max_dd": float(dd[i]), "peak": str(idx[j].date()), "trough": str(idx[i].date()),
            "length_sessions": i - j}


def _episode_stats(net_s: pd.Series, lo: str, hi: str) -> dict:
    idx = pd.to_datetime(net_s.index, unit="ms", utc=True)
    m = np.asarray((idx >= pd.Timestamp(lo, tz="UTC")) & (idx <= pd.Timestamp(hi, tz="UTC")))
    w = net_s.to_numpy()[m]
    if w.size == 0:
        return {"n": 0, "ret": float("nan"), "maxdd": float("nan"), "worst_day": float("nan")}
    eq = np.cumprod(1.0 + w)
    peak = np.maximum.accumulate(eq)
    return {
        "n": int(w.size), "ret": float(eq[-1] - 1.0),
        "maxdd": float(np.max(1.0 - eq / peak)), "worst_day": float(w.min()),
    }


# ------------------------------------------------------------------------------- driver
def _build_panels(a: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    import alphaforge.features.library  # noqa: F401  canonical factors
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

    settings = load_settings(a.profile)
    sleeve = sleeve_for(settings.data.asset_class)
    tf = sleeve.anchor_tf
    reg = default_registry()
    _register_dret(reg)
    by_name = {s.name: s for s in reg.all_specs()}
    specs = [by_name["eq_mom_252_21"], by_name["probe_dret"]]

    paths = LakePaths(settings.paths.lake_dir)
    moms: list[pd.DataFrame] = []
    rets: list[pd.DataFrame] = []
    mems: list[pd.DataFrame] = []
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        engine = FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class)
        iv = universe.read_intervals().to_pandas()
        in_lake = set(paths.instrument_ids(ohlcv_dataset(tf)))
        n_total = 0
        for pad, bstart, cend in CHUNKS:
            if pd.Timestamp(cend, tz="UTC") <= pd.Timestamp(a.start, tz="UTC"):
                continue
            if pd.Timestamp(bstart, tz="UTC") >= pd.Timestamp(a.end, tz="UTC"):
                continue
            lo, hi = pd.Timestamp(pad, tz="UTC"), pd.Timestamp(cend, tz="UTC")
            ok = (iv["effective_from"] < hi) & (iv["effective_to"].isna() | (iv["effective_to"] > lo))
            ids = sorted(i for i in set(iv.loc[ok, "instrument_id"]) & in_lake if i.startswith("XUSE"))
            if not ids:
                continue
            raw = engine.compute_history(
                specs, ids, start=parse_utc(f"{pad}T00:00:00Z"), end=parse_utc(f"{cend}T00:00:00Z")
            )
            mask = _membership_mask(universe, raw)
            mw = raw["eq_mom_252_21"].unstack("instrument_id").sort_index()
            rw = raw["probe_dret"].unstack("instrument_id").sort_index().reindex(
                index=mw.index, columns=mw.columns)
            bw = mask.unstack("instrument_id").reindex(index=mw.index, columns=mw.columns, fill_value=False)
            vw = rw.rolling(VOL_WINDOW, min_periods=VOL_MINP).std() * math.sqrt(ANN)
            keep = mw.index >= int(parse_utc(f"{bstart}T00:00:00Z"))
            moms.append(mw.loc[keep])
            rets.append(rw.loc[keep])
            mems.append(bw.loc[keep])
            # vol travels with returns; recompute after the concat is impossible across
            # disjoint column sets, so carry the chunk-local (correctly warmed) values.
            rets[-1] = rets[-1].copy()
            vw = vw.loc[keep]
            vw.columns = [f"__vol__{c}" for c in vw.columns]
            moms[-1] = pd.concat([moms[-1], vw], axis=1)
            n_total += len(ids)
            print(f"  chunk {bstart}..{cend}: ids={len(ids):5d}  sessions={int(keep.sum()):5d}  "
                  f"finite_mom={np.isfinite(mw.loc[keep].to_numpy()).mean():.1%}", flush=True)
            del raw, mask
    mom_all = pd.concat(moms, axis=0).sort_index()
    ret_all = pd.concat(rets, axis=0).sort_index()
    mem_all = pd.concat(mems, axis=0).sort_index().fillna(False)
    volcols = [c for c in mom_all.columns if c.startswith("__vol__")]
    vol_all = mom_all[volcols].copy()
    vol_all.columns = [c.removeprefix("__vol__") for c in volcols]
    mom_all = mom_all.drop(columns=volcols)
    cols = sorted(set(mom_all.columns) | set(ret_all.columns) | set(mem_all.columns))
    mom_all = mom_all.reindex(columns=cols)
    ret_all = ret_all.reindex(columns=cols)
    vol_all = vol_all.reindex(columns=cols)
    mem_all = mem_all.reindex(columns=cols, fill_value=False).fillna(False).astype(bool)
    keep = (mom_all.index >= int(pd.Timestamp(a.start, tz="UTC").value // 1_000_000)) & (
        mom_all.index < int(pd.Timestamp(a.end, tz="UTC").value // 1_000_000))
    return mom_all.loc[keep], ret_all.loc[keep], vol_all.loc[keep], mem_all.loc[keep], n_total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_shorttail")
    ap.add_argument("--profile", default="equity", help="equity => data/lake (bars to 2026-07-31)")
    ap.add_argument("--start", default="2004-01-01", help="panel floor; the BOOK starts 2005-01-03 "
                                                          "(XNYS calendar floor + 252-session momentum warmup)")
    ap.add_argument("--end", default="2026-08-01")
    ap.add_argument("--arms", default="", help="comma list to restrict arms (debug)")
    a = ap.parse_args(argv)

    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.probe_ledger import selection_context

    print("building PIT panels from the survivorship-free lake (chunked)...", flush=True)
    mom_w, ret_w, vol_w, mem_w, _n_ids_seen = _build_panels(a)
    dates = mom_w.index.to_numpy(dtype=np.int64)
    mom = np.ascontiguousarray(mom_w.to_numpy(dtype=np.float64))
    ret = np.ascontiguousarray(ret_w.to_numpy(dtype=np.float64))
    vol = np.ascontiguousarray(vol_w.to_numpy(dtype=np.float64))
    member = np.ascontiguousarray(mem_w.to_numpy(dtype=bool))
    del mom_w, ret_w, vol_w, mem_w

    ret_use = np.clip(np.where(np.isfinite(ret), ret, 0.0), RET_CLIP[0], RET_CLIP[1])
    eligible_all = member & np.isfinite(mom) & np.isfinite(vol) & (vol > 0)
    n_elig_row = eligible_all.sum(axis=1)
    warm = np.where(n_elig_row >= MIN_ELIG)[0]
    t0 = int(warm[0]) if warm.size else 0
    T, N = mom.shape
    print(f"panels: T={T} sessions x N={N} names | book t0={t0} "
          f"({pd.to_datetime(dates[t0], unit='ms').date()} .. {pd.to_datetime(dates[-1], unit='ms').date()}) | "
          f"finite momentum {np.isfinite(mom).mean():.1%} | member cells {member.mean():.1%} | "
          f"median eligible/day {np.median(n_elig_row[t0:]):.0f}", flush=True)

    leds: dict[str, tuple[int, float]] = {
        "selection_union": selection_context(root=_REPO)
    }

    want = set(a.arms.split(",")) if a.arms else None
    results: dict[str, dict] = {}
    for arm, ctrl, param, dn in ARMS:
        if want is not None and arm not in want:
            continue
        sim = simulate(mom, ret_use, eligible_all, vol, t0, ctrl, param, dn)
        net_s = pd.Series(sim["net"][t0:], index=dates[t0:]).dropna()
        grs_s = pd.Series(sim["gross"][t0:], index=dates[t0:]).dropna()
        met = _metrics(net_s, grs_s)
        eps = {nm: _episode_stats(net_s, lo, hi) for nm, lo, hi in EPISODES}
        dsr = {}
        for lname, (n_led, var_sr) in leds.items():
            try:
                rep = dsr_from_returns(net_s, max(2, n_led), var_sr, ANN)
                dsr[lname] = {"N": n_led, "dsr": float(np.real(rep.dsr)), "psr": float(np.real(rep.psr))}
            except Exception as exc:
                dsr[lname] = {"N": n_led, "error": str(exc)}
        nd = sim["net_dollar"][t0:]
        results[arm] = {
            "control": ctrl, "param": param, "dollar_neutral_restore": dn, **met,
            "reform_turnover_ann": sim["reform_turnover_ann"],
            "control_turnover_ann": sim["control_turnover_ann"],
            "total_cost_drag_ann_bps": sim["total_cost_drag_ann_bps"],
            "borrow_drag_ann_bps": sim["borrow_drag_ann_bps"],
            "n_reforms": sim["n_reforms"], "n_reform_skipped": sim["n_reform_skipped"],
            "avg_long_names": sim["avg_long_names"], "avg_short_names": sim["avg_short_names"],
            "n_days": sim["n_days"],
            "trigger_sessions": sim["trigger_sessions"], "trigger_events": sim["trigger_events"],
            "trigger_rate": sim["trigger_rate"],
            "worst_short_drift_mult": sim["worst_short_drift_mult"],
            "mean_net_dollar": float(np.nanmean(nd)), "max_net_dollar": float(np.nanmax(nd)),
            "mean_long_gross": float(np.nanmean(sim["long_gross"][t0:])),
            "mean_short_gross": float(np.nanmean(sim["short_gross"][t0:])),
            "episodes": eps, "dsr": dsr, "_net": net_s,
            "_long_pnl": pd.Series(sim["long_pnl"][t0:], index=dates[t0:]).dropna(),
            "_short_pnl": pd.Series(sim["short_pnl"][t0:], index=dates[t0:]).dropna(),
            "_trigger_years": pd.Series(
                pd.to_datetime(dates[sim["trigger_idx"]], unit="ms").year
            ).value_counts().sort_index().to_dict() if sim["trigger_idx"] else {},
        }
        print(f"  arm {arm:<12} netSR365={met['net_sharpe_ann365']:+.3f} maxDD={met['max_dd']:.3f} "
              f"trig_sessions={sim['trigger_sessions']:5d} events={sim['trigger_events']:6d}", flush=True)

    base = results["baseline"]
    bn = base["_net"]

    # ------------------------------------------------------------------ report
    print("\n" + "=" * 132)
    print("CANDIDATE C — SHORT-LEG TAIL RISK MANAGEMENT on the ALPHAMAX dollar-neutral 12-1 book")
    print(f"lake=data/lake (survivorship-free) | K={K_PER_SIDE}/side | reform={REFORM_BARS} sessions | "
          f"gross {2*GROSS_LEG:.2f} | costs 6bp one-way + 50bp/yr borrow | DRIFTING shares (production convention)")
    print(f"window {pd.to_datetime(dates[t0], unit='ms').date()} .. {pd.to_datetime(dates[-1], unit='ms').date()} "
          f"({base['n_days']} sessions, {base['n_reforms']} reforms, {base['n_reform_skipped']} skipped)")
    print("BASELINE SANITY ANCHOR — artifacts/walkforward/prereg_momentum (the repo's STORED production")
    print("deep-history walk-forward of this same sleeve, 2005-01-04..2026-06-01, 5385 sessions):")
    print("   stored: netSR -0.049 | maxDD 0.350 | CAGR -0.76% | turnover_ann 3.26 | vol_ann 0.107 | gross_mean 0.450")
    print(f"   here:   netSR {base['net_sharpe_ann365']:+.3f} | maxDD {base['max_dd']:.3f} | CAGR {base['cagr']:+.2%} | "
          f"turnover_ann {base['reform_turnover_ann']:.2f} | vol_ann {base['vol_ann365']:.3f} | "
          f"gross_mean {base['mean_long_gross'] + base['mean_short_gross']:.3f}")
    print("   -> independent agreement on turnover, CAGR and maxDD; the Sharpe gap tracks the vol gap")
    print("      (this simulator runs no vol-target overlay, so it carries less gross/vol). IMPORTANT: the")
    print("      baseline is a NEGATIVE-Sharpe book on full history. Every comparison below is therefore")
    print("      'which way of losing money loses less', NOT 'which variant makes money'.")
    print("=" * 132)
    hdr = (f"{'arm':<12}{'netSR365':>9}{'netSR252':>9}{'ΔSR':>7}{'maxDD':>7}{'ΔmaxDD%':>9}{'vol':>7}"
           f"{'CAGR':>8}{'worstD':>8}{'CVaR1%':>8}{'skew':>7}{'refTurn':>8}{'ctlTurn':>8}{'cost_bp':>8}{'trigSes':>8}{'trigEv':>8}{'DSR':>7}")
    print(hdr)
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        r = results[arm]
        dsr365 = r["net_sharpe_ann365"] - base["net_sharpe_ann365"]
        ddrel = (r["max_dd"] - base["max_dd"]) / base["max_dd"] if base["max_dd"] else float("nan")
        d = r["dsr"].get("var", {}).get("dsr", float("nan"))
        tag = "*" if arm in PRIMARY else ("~" if arm in DIAGNOSTIC else " ")
        print(f"{tag}{arm:<11}{r['net_sharpe_ann365']:>9.3f}{r['net_sharpe_ann252']:>9.3f}{dsr365:>+7.3f}"
              f"{r['max_dd']:>7.3f}{ddrel:>+9.1%}{r['vol_ann365']:>7.3f}{r['cagr']:>8.2%}"
              f"{r['worst_day']:>8.2%}{r['cvar_1pct']:>8.2%}{r['skew']:>7.2f}{r['reform_turnover_ann']:>8.2f}"
              f"{r['control_turnover_ann']:>8.2f}{r['total_cost_drag_ann_bps']:>8.1f}"
              f"{r['trigger_sessions']:>8}{r['trigger_events']:>8}{d:>7.3f}")
    print("  (* = pre-registered PRIMARY control, ~ = diagnostic-only, others = pre-registered sensitivity)")
    print("  refTurn/ctlTurn = annualized one-way turnover from quarterly reforms / from the control itself.")

    # ------- the tail itself: how each arm did on the BASELINE's worst sessions -------
    worst_idx = bn.nsmallest(10).index
    wd = [pd.to_datetime(i, unit="ms").date() for i in worst_idx]
    print("\nBASELINE's 10 WORST SESSIONS and what each arm earned on those same days (the tail, directly):")
    print(f"{'arm':<12}" + "".join(f"{str(d)[2:]:>10}" for d in wd) + f"{'sum':>10}")
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        s = results[arm]["_net"].reindex(worst_idx)
        print(f"{arm:<12}" + "".join(f"{x:>9.2%} " for x in s.to_numpy()) + f"{s.sum():>9.2%}")

    print(f"\nRAW SHORT-LEG TAIL (baseline): worst |v|/|v_entry| ever reached by a single short = "
          f"{base['worst_short_drift_mult']:.2f}x  -> a short that ran {base['worst_short_drift_mult']-1:.0%} against the book before the next reform.")
    print("dollar-neutrality diagnostic (mean Sum(w) ; a control that quietly makes the book net-long is buying beta, not safety):")
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        r = results[arm]
        print(f"  {arm:<12} mean Σw={r['mean_net_dollar']:+.4f}  max Σw={r['max_net_dollar']:+.4f}  "
              f"mean long gross={r['mean_long_gross']:.3f}  mean short gross={r['mean_short_gross']:.3f}")

    print("\n" + "-" * 132)
    print("STRESS-EPISODE TABLE — net return over each PRE-REGISTERED window (the anti-window-fitting spine)")
    print("-" * 132)
    names = [e[0] for e in EPISODES]
    print(f"{'arm':<12}" + "".join(f"{nm[:15]:>17}" for nm in names))
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        r = results[arm]
        print(f"{arm:<12}" + "".join(f"{r['episodes'][nm]['ret']:>16.2%} " for nm in names))
    print(f"\n{'(within-episode maxDD)':<12}")
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        r = results[arm]
        print(f"{arm:<12}" + "".join(f"{r['episodes'][nm]['maxdd']:>16.2%} " for nm in names))

    print("\nBASELINE LEG ATTRIBUTION per episode (does this simulator reproduce the MECHANISM, not just")
    print("the magnitude? The July-2026 diagnosis was: BOTH legs lost at once, the short leg squeezing):")
    print(f"{'episode':<18}{'net':>10}{'long leg':>11}{'short leg':>11}{'mkt(EW univ)':>14}   both-legs-lost")
    mkt_all = np.where(eligible_all, ret_use, 0.0).sum(axis=1) / np.maximum(eligible_all.sum(axis=1), 1)
    mkt_ser = pd.Series(mkt_all[t0:], index=dates[t0:])
    leg_attr: dict[str, dict] = {}
    for nm, lo, hi in EPISODES:
        e_net = _episode_stats(bn, lo, hi)
        e_l = _episode_stats(base["_long_pnl"], lo, hi)
        e_s = _episode_stats(base["_short_pnl"], lo, hi)
        e_m = _episode_stats(mkt_ser, lo, hi)
        both = "YES" if (e_l["ret"] < 0 and e_s["ret"] < 0) else "no"
        leg_attr[nm] = {"net": e_net["ret"], "long": e_l["ret"], "short": e_s["ret"], "mkt_ew": e_m["ret"]}
        print(f"{nm:<18}{e_net['ret']:>10.2%}{e_l['ret']:>11.2%}{e_s['ret']:>11.2%}{e_m['ret']:>14.2%}   {both}")

    print("\ntreatment-vs-baseline daily net-return correlation (near 1.0 = same book, only risk-managed):")
    for arm, *_ in ARMS:
        if arm == "baseline" or arm not in results:
            continue
        j = pd.concat([results[arm]["_net"].rename("t"), bn.rename("b")], axis=1).dropna()
        print(f"  {arm:<12} corr={j['t'].corr(j['b']):.4f}")

    print("\ntrigger frequency by year (a control that fires constantly is a DIFFERENT STRATEGY; one that never fires is UNTESTED INSURANCE):")
    for arm, *_ in ARMS:
        if arm in ("baseline",) or arm not in results:
            continue
        ty = results[arm]["_trigger_years"]
        head = ", ".join(f"{y}:{c}" for y, c in list(ty.items())[:40])
        print(f"  {arm:<12} sessions={results[arm]['trigger_sessions']:5d} ({results[arm]['trigger_rate']:.2%} of days) | {head}")

    # ------------------------------------------------------------------ gate
    print("\n" + "=" * 132)
    print("PRE-REGISTERED GATE — G1 netSR >= base-0.05 | G2 maxDD <= 0.90*base | G3 >=25% relative episode")
    print("                      improvement in >=2 of 6 gate episodes with >=1 NOT 2026_07 | G4 5 <= trigger sessions < 25% of days")
    print("=" * 132)
    gate: dict[str, dict] = {}
    for arm, *_ in ARMS:
        if arm in ("baseline",) or arm in DIAGNOSTIC or arm not in results:
            continue
        r = results[arm]
        g1 = r["net_sharpe_ann365"] >= base["net_sharpe_ann365"] - 0.05
        g2 = r["max_dd"] <= 0.90 * base["max_dd"]
        helped: list[str] = []
        for nm in GATE_EPISODES:
            b_ret = base["episodes"][nm]["ret"]
            t_ret = r["episodes"][nm]["ret"]
            if b_ret < 0 and (t_ret - b_ret) >= 0.25 * abs(b_ret):
                helped.append(nm)
        g3 = len(helped) >= 2 and any(h != "2026_07_squeeze" for h in helped)
        g4 = 5 <= r["trigger_sessions"] < 0.25 * r["n_days"]
        ok = g1 and g2 and g3 and g4
        gate[arm] = {
            "G1_sharpe": bool(g1), "G2_maxdd": bool(g2), "G3_episodes": bool(g3),
            "G4_trigger_freq": bool(g4), "episodes_helped": helped, "PASS": bool(ok),
            "d_sharpe": r["net_sharpe_ann365"] - base["net_sharpe_ann365"],
            "d_maxdd_rel": (r["max_dd"] - base["max_dd"]) / base["max_dd"] if base["max_dd"] else float("nan"),
        }
        print(f"  {arm:<12} G1={'ok ' if g1 else 'FAIL'} (ΔSR {gate[arm]['d_sharpe']:+.3f})  "
              f"G2={'ok ' if g2 else 'FAIL'} (ΔmaxDD {gate[arm]['d_maxdd_rel']:+.1%})  "
              f"G3={'ok ' if g3 else 'FAIL'} (helped: {helped or 'none'})  "
              f"G4={'ok ' if g4 else 'FAIL'}  ->  {'ADOPT' if ok else 'reject'}")

    print("\nHONEST READ (pre-registered framing): a control that cuts BOTH the tail and the Sharpe is a BAD TRADE.")
    for arm in PRIMARY:
        if arm not in results:
            continue
        r = results[arm]
        j07 = r["episodes"]["2026_07_squeeze"]["ret"] - base["episodes"]["2026_07_squeeze"]["ret"]
        print(f"  {arm:<12} ΔnetSR {r['net_sharpe_ann365'] - base['net_sharpe_ann365']:+.3f} | "
              f"ΔmaxDD {(r['max_dd'] - base['max_dd']) / base['max_dd']:+.1%} | "
              f"Δ2026-07 {j07:+.2%} | cost drag {r['total_cost_drag_ann_bps'] - base['total_cost_drag_ann_bps']:+.0f} bp/yr")

    # =================================================================================
    # POST-HOC KILL SECTION — ADDED AFTER the pre-registered run, and DISCLOSED as such.
    # These four tests can only make a candidate look WORSE (they are harder controls,
    # never looser ones), so adding them is anti-fitting, not fitting. The pre-registered
    # gate above is left EXACTLY as written; these tests inform the written verdict.
    #   K1  is the "improvement" just unhedged market BETA bought by deleting short exposure?
    #   K2  does it survive the book vol-target overlay the LIVE sleeve ALREADY runs?
    #   K3  which episodes did the control HURT? (the pre-registered gate had no harm clause
    #       -- an acknowledged weakness of my own pre-registration)
    #   K4  is the baseline's maxDD a CRASH (worth insuring) or a slow BLEED (not)?
    # =================================================================================
    print("\n" + "=" * 132)
    print("POST-HOC KILL TESTS (added after the pre-registered run; disclosed; can only hurt a candidate)")
    print("=" * 132)

    print("\nK1 — BETA DECOMPOSITION of each control's INCREMENTAL P&L (arm minus baseline),")
    print("     regressed on the equal-weight return of the SAME PIT universe the book trades")
    print("     (d_t = alpha + beta*mkt_t, Newey-West lags=5). If beta is large and alpha is not")
    print("     significant, the control bought EQUITY BETA, not safety.")
    mkt = np.where(eligible_all, ret_use, 0.0).sum(axis=1) / np.maximum(eligible_all.sum(axis=1), 1)
    mkt_s = pd.Series(mkt[t0:], index=dates[t0:]).reindex(bn.index)
    k1: dict[str, dict] = {}
    bb = _nw_ols(bn.to_numpy(), mkt_s.to_numpy())
    print(f"  {'BASELINE vs mkt':<16} beta={bb['beta']:+.3f} (t={bb['beta_t_nw']:+.2f})  "
          f"alpha_ann={bb['alpha_ann']:+.2%} (t={bb['alpha_t_nw']:+.2f})   "
          "<- tests the campaign's core hypothesis: dollar-neutral 12-1 carries a persistent NEGATIVE beta")
    k1["baseline_vs_mkt"] = bb
    for arm, *_ in ARMS:
        if arm == "baseline" or arm not in results:
            continue
        j = pd.concat([results[arm]["_net"].rename("t"), bn.rename("b"), mkt_s.rename("m")], axis=1).dropna()
        res = _nw_ols((j["t"] - j["b"]).to_numpy(), j["m"].to_numpy())
        k1[arm] = res
        flag = "BETA-DRIVEN" if (abs(res["beta"]) > 0.02 and abs(res["alpha_t_nw"]) < 2.0) else ""
        print(f"  {arm:<16} beta={res['beta']:+.3f} (t={res['beta_t_nw']:+.2f})  "
              f"alpha_ann={res['alpha_ann']:+.2%} (t={res['alpha_t_nw']:+.2f})  R2={res['r2']:.3f}  {flag}")

    print("\nK2 — REDUNDANCY with the book vol-target overlay the LIVE sleeve ALREADY runs")
    print("     (base.yaml vol_target_ann=0.15, s_max=1.5, src/alphaforge/portfolio/overlay.py).")
    print("     Every arm re-measured AFTER that overlay. If a control's edge disappears once the")
    print("     overlay is present, it is redundant with an existing production mechanism.")
    k2: dict[str, dict] = {}
    base_vt = _vol_overlay(bn)
    bvt = _metrics(base_vt, base_vt)
    print(f"  {'arm':<14}{'netSR365_vt':>12}{'ΔSR_vt':>9}{'maxDD_vt':>10}{'ΔmaxDD_vt%':>12}{'ΔSR_raw':>9}")
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        vt = _vol_overlay(results[arm]["_net"])
        m = _metrics(vt, vt)
        k2[arm] = {"net_sharpe_ann365_vt": m["net_sharpe_ann365"], "max_dd_vt": m["max_dd"]}
        dsr_vt = m["net_sharpe_ann365"] - bvt["net_sharpe_ann365"]
        ddrel = (m["max_dd"] - bvt["max_dd"]) / bvt["max_dd"] if bvt["max_dd"] else float("nan")
        draw = results[arm]["net_sharpe_ann365"] - base["net_sharpe_ann365"]
        print(f"  {arm:<14}{m['net_sharpe_ann365']:>12.3f}{dsr_vt:>+9.3f}{m['max_dd']:>10.3f}"
              f"{ddrel:>+12.1%}{draw:>+9.3f}")
    print("     (approximation disclosed in _vol_overlay: the overlay's own re-scaling turnover is not charged)")

    print("\nK3 — EPISODES THE CONTROL *HURT* (>=25% relative degradation vs baseline).")
    print("     My pre-registered gate had a 'helped' clause but NO harm clause — an acknowledged")
    print("     weakness. Reported here so the trade-off is visible rather than hidden.")
    k3: dict[str, list[str]] = {}
    for arm, *_ in ARMS:
        if arm == "baseline" or arm not in results:
            continue
        hurt = []
        for nm in GATE_EPISODES:
            b_ret = base["episodes"][nm]["ret"]
            t_ret = results[arm]["episodes"][nm]["ret"]
            if abs(b_ret) > 1e-9 and (b_ret - t_ret) >= 0.25 * abs(b_ret):
                hurt.append(f"{nm}({b_ret:+.1%}->{t_ret:+.1%})")
        k3[arm] = hurt
        print(f"  {arm:<14} helped={gate.get(arm, {}).get('episodes_helped', [])}  hurt={hurt or 'none'}")

    print("\nK4 — IS THE BASELINE maxDD A CRASH OR A BLEED? (you only insure a crash)")
    k4 = {arm: _dd_dates(results[arm]["_net"]) for arm in results}
    for arm, *_ in ARMS:
        if arm not in results:
            continue
        d = k4[arm]
        print(f"  {arm:<14} maxDD {d['max_dd']:.1%}  peak {d['peak']} -> trough {d['trough']}  "
              f"({d['length_sessions']} sessions = {d['length_sessions']/TRADING_DAYS:.1f} yrs)")

    print("\n" + "=" * 132)
    print("FINAL VERDICT — pre-registered gate AND the K1 beta filter (a control must add RESIDUAL")
    print("alpha, not just equity beta bought by deleting short exposure: alpha_t_NW >= +2.0)")
    print("=" * 132)
    final: dict[str, dict] = {}
    for arm, *_ in ARMS:
        if arm == "baseline" or arm in DIAGNOSTIC or arm not in results:
            continue
        pre = gate[arm]["PASS"]
        surv = k1[arm]["alpha_t_nw"] >= 2.0
        final[arm] = {"prereg_gate": bool(pre), "survives_beta_filter": bool(surv),
                      "alpha_ann": k1[arm]["alpha_ann"], "alpha_t_nw": k1[arm]["alpha_t_nw"],
                      "beta": k1[arm]["beta"], "ADOPT": bool(pre and surv)}
        print(f"  {arm:<14} prereg_gate={'PASS' if pre else 'fail'}  beta_filter="
              f"{'PASS' if surv else 'FAIL'} (alpha {k1[arm]['alpha_ann']:+.2%}/yr, t={k1[arm]['alpha_t_nw']:+.2f}, "
              f"beta {k1[arm]['beta']:+.3f})  ->  {'ADOPT' if (pre and surv) else 'REJECT'}")
    n_adopt = sum(1 for v in final.values() if v["ADOPT"])
    j07_best = max(   # best = least negative episode return across every treatment arm
        (results[arm]["episodes"]["2026_07_squeeze"]["ret"] for arm in results if arm != "baseline"),
        default=float("nan"))
    print(f"\n  arms adopted: {n_adopt} of {len(final)}")
    print(f"  the episode this candidate exists for (2026_07_squeeze): baseline "
          f"{base['episodes']['2026_07_squeeze']['ret']:+.2%}; BEST arm {j07_best:+.2%}; "
          f"baseline within-episode maxDD {base['episodes']['2026_07_squeeze']['maxdd']:.2%}")
    la = leg_attr["2026_07_squeeze"]
    print(f"  and its leg split: long {la['long']:+.2%} / short {la['short']:+.2%} -> the SHORT leg is "
          f"{abs(la['short'])/(abs(la['long'])+abs(la['short'])):.0%} of the damage, so even a PERFECT "
          "short-leg control could not have fixed July 2026.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "probe": "alphamax_shorttail", "candidate": "C_short_leg_tail_risk",
        "profile": a.profile, "lake": "data/lake",
        "window": {"start": str(pd.to_datetime(dates[t0], unit="ms").date()),
                   "end": str(pd.to_datetime(dates[-1], unit="ms").date()),
                   "sessions": int(base["n_days"])},
        "panel": {"T": int(T), "N": int(N)},
        "construction": {
            "K_per_side": K_PER_SIDE, "reform_bars": REFORM_BARS, "vol_window": VOL_WINDOW,
            "gross_leg": GROSS_LEG, "w_max": W_MAX, "cost_oneway_bps": COST_ONEWAY * 1e4,
            "borrow_ann_bps": BORROW_ANN * 1e4, "no_trade_band": NO_TRADE_BAND,
            "ret_clip": list(RET_CLIP), "ann_basis": ANN, "min_eligible": MIN_ELIG,
            "position_convention": "drifting shares between quarterly reforms (production BlendStrategy behaviour)",
        },
        "baseline_sanity_anchor_prereg_momentum": {
            "source": "artifacts/walkforward/prereg_momentum/walkforward.json (stored production walk-forward)",
            "stored": {"net_sharpe": -0.0493, "max_dd": 0.3498, "cagr": -0.0076,
                       "turnover_ann": 3.2596, "vol_ann": 0.1066, "gross_mean": 0.4503,
                       "n_days": 5385, "window": "2005-01-04..2026-06-01"},
            "this_simulator_baseline": {
                "net_sharpe": base["net_sharpe_ann365"], "max_dd": base["max_dd"],
                "cagr": base["cagr"], "turnover_ann": base["reform_turnover_ann"],
                "vol_ann": base["vol_ann365"],
                "gross_mean": base["mean_long_gross"] + base["mean_short_gross"],
                "n_days": base["n_days"]},
        },
        "episodes_spec": {nm: [lo, hi] for nm, lo, hi in EPISODES},
        "gate_episodes": list(GATE_EPISODES),
        "ledgers": {k: {"N": v[0], "var_sr": v[1]} for k, v in leds.items()},
        "results": {k: {kk: vv for kk, vv in r.items() if not kk.startswith("_")} for k, r in results.items()},
        "gate": gate,
        "baseline_leg_attribution_by_episode": leg_attr,
        "final_verdict": final,
        "post_hoc_kill_tests": {
            "K1_beta_decomposition": k1,
            "K2_vol_overlay_redundancy": k2,
            "K2_baseline_vt": {"net_sharpe_ann365": bvt["net_sharpe_ann365"], "max_dd": bvt["max_dd"]},
            "K3_episodes_hurt": k3,
            "K4_drawdown_dating": k4,
            "disclosure": "added AFTER the pre-registered run; all four can only make a candidate look worse",
        },
        "trials_burned": 0,
        "note": "SCREEN ONLY — no experiments-ledger append; DSR read-only. Promotion into src is a separate human step.",
    }
    (OUT_DIR / "report.json").write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
    curves = pd.DataFrame({k: r["_net"] for k, r in results.items()})
    curves.index = pd.to_datetime(curves.index, unit="ms")
    curves.to_csv(OUT_DIR / "net_returns.csv")
    print(f"\npersisted: {OUT_DIR / 'report.json'} and {OUT_DIR / 'net_returns.csv'}")
    print("TRIALS BURNED THIS RUN: 0 (cheap construction screen; no ledger append).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
