#!/usr/bin/env python3
"""PROBE — ALPHATREND BREADTH EXPANSION A/B: 17-ETF baseline vs ~33-ETF expanded universe.

2026-07-12. MEASURE-ONLY (read-only imports from src; modifies no source, config, or production-lake
state). Each measured basket is union-registered before DSR. AlphaTrend = managed-futures TREND
sleeve: TS price-trend across a fixed ETF basket, built by TrendVolTarget = sign(blended
mf_trend_63/126/252)/sigma, gross-normalized/clipped, book vol-targeted. Its honest Sharpe ceiling
~ sqrt(N_eff), N_eff = N/(1+(N-1)*rhobar^2). The 17-ETF basket is already only ~0.13 pairwise
correlated, so REDUNDANCY isn't the binding constraint -- TOO-FEW decorrelated MARKETS is. This
probe tests the sleeve's real free lever: does adding ~16 genuinely-decorrelated liquid Alpaca-
tradable ETFs (single-country equity, credit, inflation-linked rates, G10 FX, base metals) raise
the deflated Sharpe / lower maxDD NET of the added cost -- and honestly (not from one lucky market)?

SAME-VINTAGE, SELF-CONTAINED A/B. Both baskets are priced from ONE fresh Yahoo pull into the
research lake data/lake_mf_exp (scripts/mf_etf_load.py with MF_EXTRA_TICKERS; production
data/lake_mf is left byte-identical). Each basket is run through the SAME TrendVolTarget replica
(verbatim from probe_alphatrend_arp.py, itself verified vs the frozen mf artifact), so replica-vs-
engine differences cancel in the A/B delta. Per-instrument warm-up is handled by the book's active-
set gate: an ETF joins only once it has a warm signal + sufficient covariance-window history, so the
short-history names (INDA/MCHI/EMB/HYG) simply enter the expanded book as they list -- both books
start from the same ~2006 date driven by the 17 core.

VOL-MATCHING for maxDD/skew: Sharpe & skew are scale-invariant; maxDD is NOT. A book that merely
realizes lower vol at the gross cap gives a smaller maxDD you'd just lever back. So maxDD/skew are
compared after scaling every net stream to a COMMON annual vol (baseline realized vol). Pre-match
realized vol (the diversification signature) is reported separately.

LEAVE-ONE-OUT: the expanded book is rebuilt excluding its single biggest PnL contributor, to prove
any improvement isn't one lucky market.

PIT + committed costs: weights decided through close t are effective t+1 (never same-bar). Costs =
6bp/side rebalance turnover (1bp comm + 3bp half-spread + 2bp latency, managed_futures.yaml) +
50bp/yr borrow on the short leg, accrued daily. Piecewise-constant monthly target weights.

Screen only. A full engine deflated WF on a promoted universe is a separate next step, justified
only if expanded beats baseline here. Under a paused campaign, unregistered baskets fail union
preflight before market data is loaded.

    uv run python scripts/probe_alphatrend_breadth.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.core.time import now_ms  # noqa: E402
from alphaforge.portfolio.covariance import ledoit_wolf_cc  # read-only import  # noqa: E402
from alphaforge.validation.dsr import dsr_from_returns  # read-only import  # noqa: E402
from alphaforge.validation.experiments import ExperimentUnion  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

LAKE = REPO / "data" / "lake_mf_exp" / "ohlcv_1d"   # research lake (prod data/lake_mf untouched)
OUT = REPO / "artifacts" / "sweep" / "alphatrend_breadth"
LEDGER = REPO / "var" / "experiments.jsonl"

ANN = 252.0
# --- construction constants (match src: zoo._MF_TREND_* + managed_futures.yaml) ---
VOL_SPAN = 33
BLEND_LB = (63, 126, 252)
GROSS_MAX = 1.0
W_MAX = 0.34
VOL_TARGET = 0.15
VOL_SCALE_MAX = 3.0
REBALANCE = 21
COV_WINDOW = 252
MIN_MEMBERS = 5
START = "2006-01-03"
COST_PER_SIDE = 6e-4
BORROW_ANN = 50e-4

# --- the two baskets -------------------------------------------------------
BASE17 = ["SPY", "QQQ", "IWM", "EFA", "EEM",
          "IEF", "TLT", "SHY",
          "GLD", "SLV", "USO", "DBC", "DBA", "UNG",
          "UUP", "FXE", "FXY"]
# 16 additions spanning exposures the 17 under-cover (see report notes)
ADD16 = ["EWJ", "EWG", "EWU", "EWZ", "INDA", "MCHI", "EWY", "EWA",  # single-country equity
         "LQD", "HYG", "EMB",                                        # credit (IG / HY / EM sov)
         "TIP",                                                      # inflation-linked rates
         "FXB", "FXA", "FXC",                                        # G10 FX (GBP/AUD/CAD)
         "DBB"]                                                      # base metals
EXPANDED = BASE17 + ADD16


# ------------------------------------------------------------------- data
def load_panel(tickers: list[str]) -> pd.DataFrame:
    """Wide date x ETF panel of total-return-adjusted daily closes from the research lake."""
    cols = {}
    want = set(tickers)
    for d in sorted(glob.glob(str(LAKE / "instrument_id=*"))):
        iid = Path(d).name.split("=", 1)[1]
        tkr = iid.split(":")[-1].replace("USD", "")
        if tkr not in want:
            continue
        files = sorted(glob.glob(str(Path(d) / "**" / "*.parquet"), recursive=True))
        if not files:
            continue
        df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("ts_open")
        s = pd.Series(
            df["close"].to_numpy(dtype=np.float64),
            index=pd.to_datetime(df["ts_open"]).dt.tz_localize(None).dt.normalize(),
        )
        cols[tkr] = s[~s.index.duplicated(keep="last")]
    # keep column order as requested (only those present)
    panel = pd.DataFrame({t: cols[t] for t in tickers if t in cols}).sort_index()
    return panel


def ewma_vol(logret: pd.DataFrame, span: int) -> pd.DataFrame:
    return logret.pow(2).ewm(span=span, adjust=False, min_periods=span).mean().pow(0.5)


def mf_trend(logclose: pd.DataFrame, sigma: pd.DataFrame, lb: int) -> pd.DataFrame:
    mom = logclose - logclose.shift(lb)
    return mom / (sigma.where(sigma > 0.0) * np.sqrt(lb))


# ---------------------------------------------------------- construction (verbatim replica)
def target_weights(
    signal_row: np.ndarray, sigma_ann: np.ndarray, cov_ann: np.ndarray
) -> np.ndarray:
    """sign inverse-vol -> gross-norm/clip -> book vol-target overlay (gross-capped). Live path."""
    sign = np.sign(signal_row)
    g = np.zeros_like(sign)
    ok = (sigma_ann > 0) & np.isfinite(sign)
    g[ok] = sign[ok] / sigma_ann[ok]
    gross = np.abs(g).sum()
    if gross <= 0:
        return np.zeros_like(g)
    w = g * (GROSS_MAX / gross)
    w = np.clip(w, -W_MAX, W_MAX)
    gc, ma = np.abs(w).sum(), np.abs(w).max()
    if gc > 0 and ma > 0:
        w = w * min(GROSS_MAX / gc, W_MAX / ma)
    ex_ante = float(np.sqrt(max(w @ cov_ann @ w, 0.0)))
    s = VOL_SCALE_MAX if ex_ante <= 0 else min(VOL_TARGET / ex_ante, VOL_SCALE_MAX)
    w = s * w
    gr = np.abs(w).sum()
    if gr > GROSS_MAX:
        w = w * (GROSS_MAX / gr)
    return w


def build_book(panel: pd.DataFrame) -> tuple[pd.Series, dict, pd.Series]:
    """Build the piecewise-constant TrendVolTarget book on a given ETF panel; return net returns,
    diagnostics, and per-ticker net PnL contribution (for leave-one-out)."""
    tickers = list(panel.columns)
    logclose = np.log(panel)
    ret = panel.pct_change()
    logret = logclose.diff()
    sigma = ewma_vol(logret, VOL_SPAN)
    blend3 = sum(mf_trend(logclose, sigma, lb) for lb in BLEND_LB) / float(len(BLEND_LB))

    all_dates = panel.index
    warm = blend3.loc[blend3.index >= pd.Timestamp("2004-01-01")].dropna(how="all").index
    grid = [d for d in all_dates if d >= warm.min()]
    rebal_dates = grid[::REBALANCE]

    W = pd.DataFrame(np.nan, index=all_dates, columns=tickers)
    prev = pd.Series(0.0, index=tickers)
    turn_events: list[float] = []
    n_active: list[int] = []
    for t in rebal_dates:
        win = ret.loc[:t].tail(COV_WINDOW)
        sig = blend3.loc[t]
        active = [
            c for c in tickers
            if np.isfinite(sig.get(c, np.nan)) and win[c].notna().sum() >= int(0.8 * COV_WINDOW)
        ]
        if len(active) < MIN_MEMBERS:
            W.loc[t] = prev.to_numpy()
            continue
        a = np.asarray(active)
        sub = win[active].to_numpy()
        sub = np.where(np.isfinite(sub), sub, 0.0)
        T = sub.shape[0]
        S = (sub.T @ sub) / float(T)
        S = 0.5 * (S + S.T)
        try:
            S_shr, _ = ledoit_wolf_cc(sub, S)
        except Exception:
            S_shr = S
        cov_ann = S_shr * ANN
        sigma_ann = np.sqrt(np.clip(np.diag(cov_ann), 1e-12, None))
        raw = sig[active].to_numpy(dtype=np.float64)
        demeaned = raw - raw.mean()
        w_act = target_weights(demeaned, sigma_ann, cov_ann)
        w_full = pd.Series(0.0, index=tickers)
        w_full[a] = w_act
        turn_events.append(float(np.abs(w_full - prev).sum()))
        n_active.append(len(active))
        W.loc[t] = w_full.to_numpy()
        prev = w_full
    W = W.ffill().fillna(0.0)
    Wp = W.shift(1).fillna(0.0)
    contrib_by_tkr = (Wp * ret.reindex(all_dates)).sum(axis=0)  # per-ticker gross PnL contribution
    gross_ret = (Wp * ret.reindex(all_dates)).sum(axis=1)
    borrow = np.clip(-Wp, 0.0, None).sum(axis=1) * (BORROW_ANN / ANN)
    cost = pd.Series(0.0, index=all_dates)
    for t, dt in zip(rebal_dates, turn_events, strict=False):
        if t in cost.index:
            cost.loc[t] += dt * COST_PER_SIDE
    net = (gross_ret - borrow - cost).dropna()
    net = net.loc[net.index >= pd.Timestamp(START)]
    turn_ann = float(np.sum(turn_events) / (len(net) / ANN)) if len(net) else float("nan")
    diag = {"turnover_ann": turn_ann, "n_rebals": len(rebal_dates), "gross_cost": float(cost.sum()),
            "avg_active": float(np.mean(n_active)) if n_active else float("nan"),
            "max_active": int(np.max(n_active)) if n_active else 0}
    return net, diag, contrib_by_tkr


# ------------------------------------------------------------------- metrics
def sharpe(r: pd.Series) -> float:
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def sortino(r: pd.Series) -> float:
    dn = r[r < 0].std(ddof=0)
    return float(r.mean() / dn * np.sqrt(ANN)) if dn > 0 else float("nan")


def maxdd(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def skew(r: pd.Series) -> float:
    x = r.dropna().to_numpy()
    sd = x.std(ddof=0)
    return float(((x - x.mean()) ** 3).mean() / sd ** 3) if sd > 0 else float("nan")


def vol_ann(r: pd.Series) -> float:
    return float(r.std(ddof=0) * np.sqrt(ANN))


def to_vol(r: pd.Series, target: float) -> pd.Series:
    v = vol_ann(r)
    return r * (target / v) if v > 0 else r


def spy_corr(net: pd.Series, spy_ret: pd.Series) -> float:
    j = pd.concat([net.rename("b"), spy_ret.rename("s")], axis=1).dropna()
    return float(np.corrcoef(j["b"], j["s"])[0, 1]) if len(j) > 30 else float("nan")


def breadth(ret_panel: pd.DataFrame) -> tuple[float, float, int]:
    """Avg pairwise correlation (rhobar) + effective breadth N_eff on a returns panel."""
    cc = ret_panel.corr()
    off = ~np.eye(cc.shape[0], dtype=bool)
    rhobar = float(np.nanmean(cc.to_numpy()[off]))
    N = cc.shape[0]
    n_eff = N / (1.0 + (N - 1) * rhobar ** 2)
    return rhobar, n_eff, N


def main() -> int:
    configs = {
        "BASE_17": {
            "basket": "BASE_17",
            "tickers": list(BASE17),
            "signal": "blend_63_126_252",
            "vol_span": VOL_SPAN,
            "rebalance_bars": REBALANCE,
            "gross_max": GROSS_MAX,
            "cost_per_side": COST_PER_SIDE,
            "borrow_ann": BORROW_ANN,
        },
        "EXPANDED_33": {
            "basket": "EXPANDED_33",
            "tickers": list(EXPANDED),
            "signal": "blend_63_126_252",
            "vol_span": VOL_SPAN,
            "rebalance_bars": REBALANCE,
            "gross_max": GROSS_MAX,
            "cost_per_side": COST_PER_SIDE,
            "borrow_ann": BORROW_ANN,
        },
        "EXPANDED_MINUS_LARGEST_CONTRIBUTOR": {
            "basket": "EXPANDED_MINUS_LARGEST_CONTRIBUTOR",
            "candidate_tickers": list(EXPANDED),
            "selection_rule": "drop_largest_full_sample_pnl_contributor",
            "signal": "blend_63_126_252",
            "vol_span": VOL_SPAN,
            "rebalance_bars": REBALANCE,
            "gross_max": GROSS_MAX,
            "cost_per_side": COST_PER_SIDE,
            "borrow_ann": BORROW_ANN,
        },
        "GREEDY_NEFF_PRUNED": {
            "basket": "GREEDY_NEFF_PRUNED",
            "base_tickers": list(BASE17),
            "candidate_additions": list(ADD16),
            "selection_rule": "greedy_add_only_if_neff_gain_gt_0",
            "signal": "blend_63_126_252",
            "vol_span": VOL_SPAN,
            "rebalance_bars": REBALANCE,
            "gross_max": GROSS_MAX,
            "cost_per_side": COST_PER_SIDE,
            "borrow_ann": BORROW_ANN,
        },
    }
    union = ExperimentUnion.discover(LEDGER, REPO)
    union.preflight_hypotheses(
        [{"probe": "alphatrend_breadth", **config} for config in configs.values()]
    )

    OUT.mkdir(parents=True, exist_ok=True)
    panel_base = load_panel(BASE17)
    panel_exp = load_panel(EXPANDED)
    present_exp = list(panel_exp.columns)
    dropped = [t for t in EXPANDED if t not in present_exp]

    net_base, dg_base, _ = build_book(panel_base)
    net_exp, dg_exp, contrib_exp = build_book(panel_exp)

    # common window (both ~2006 start; intersection keeps the A/B honest)
    common = net_base.index.intersection(net_exp.index)
    rb, re_ = net_base.loc[common], net_exp.loc[common]
    match_vol = round(vol_ann(rb), 4)  # vol-match to baseline realized vol

    # SPY return stream for corr-to-SPY
    spy_ret = panel_exp["SPY"].pct_change()

    # breadth of each basket over the common window (raw ETF returns, pairwise-complete corr)
    rhobar_b, neff_b, N_b = breadth(panel_base.pct_change().reindex(common))
    rhobar_e, neff_e, N_e = breadth(panel_exp.pct_change().reindex(common))

    # ---- per-candidate decorrelation screen + greedy N_eff-maximizing pruned basket ----
    # The step-2 mandate: DROP additions that duplicate an existing exposure. Measure each
    # candidate's correlation to the 17 core (over the common window, pairwise-complete)
    # and greedily keep only additions that RAISE combined N_eff (genuinely decorrelated).
    ret_all = panel_exp.pct_change().reindex(common)
    cand_rows = []
    for c in ADD16:
        if c not in ret_all.columns:
            continue
        cc = ret_all[[c, *BASE17]].corr()[c].drop(c)
        cand_rows.append(
            {
                "add": c,
                "corr_SPY": round(float(ret_all[[c, "SPY"]].corr().iloc[0, 1]), 3),
                "avg_corr_17": round(float(cc.mean()), 3),
                "max_corr_17": round(float(cc.abs().max()), 3),
                "closest": cc.abs().idxmax(),
            }
        )
    cand_tab = pd.DataFrame(cand_rows).set_index("add").sort_values("avg_corr_17")

    def neff_of(tickers: list[str]) -> float:
        _, ne, _ = breadth(ret_all[tickers])
        return ne

    selected = list(BASE17)
    remaining = [c for c in ADD16 if c in ret_all.columns]
    kept_adds: list[str] = []
    while remaining:
        base_ne = neff_of(selected)
        gains = [(neff_of([*selected, c]) - base_ne, c) for c in remaining]
        gains.sort(reverse=True)
        best_gain, best_c = gains[0]
        if best_gain <= 0:   # no remaining candidate raises N_eff -> stop
            break
        selected.append(best_c)
        kept_adds.append(best_c)
        remaining.remove(best_c)
    pruned_tickers = list(selected)

    # ---- leave-one-out on the biggest PnL contributor of the expanded book ----
    biggest = contrib_exp.reindex(present_exp).astype(float).idxmax()
    loo_tickers = [t for t in present_exp if t != biggest]
    panel_loo = load_panel(loo_tickers)
    net_loo, dg_loo, _ = build_book(panel_loo)
    rl = net_loo.loc[net_loo.index.intersection(common)]
    rhobar_l, neff_l, N_l = breadth(panel_loo.pct_change().reindex(rl.index))

    # ---- the greedy N_eff-maximizing PRUNED basket (best-case decorrelated expansion) ----
    panel_pruned = load_panel(pruned_tickers)
    net_pruned, dg_pruned, _ = build_book(panel_pruned)
    rp = net_pruned.loc[net_pruned.index.intersection(common)]
    rhobar_p, neff_p, N_p = breadth(panel_pruned.pct_change().reindex(rp.index))

    audit_before = union.n_trials()
    measured = {
        "BASE_17": rb,
        "EXPANDED_33": re_,
        "EXPANDED_MINUS_LARGEST_CONTRIBUTOR": rl,
        "GREEDY_NEFF_PRUNED": rp,
    }
    for name, returns in measured.items():
        record_probe_trial(
            "alphatrend_breadth",
            configs[name],
            returns,
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
    trials_logged = union.n_trials() - audit_before
    n_trials = union.n_hypotheses()
    sr_var = union.hypothesis_sharpe_variance()

    def row(name: str, r: pd.Series, rhobar: float, neff: float, N: int, dg: dict) -> dict:
        rm = to_vol(r, match_vol)
        dsr = dsr_from_returns(rm, max(2, n_trials), sr_var, ANN)
        return {
            "basket": name,
            "N": N,
            "net_sharpe": round(sharpe(r), 3),
            "DSR@N": round(float(dsr.dsr), 3),
            "vol_ann": round(vol_ann(r), 4),
            "maxDD_vm": round(maxdd(rm), 4),
            "skew": round(skew(r), 3),
            "sortino": round(sortino(r), 3),
            "corr_SPY": round(spy_corr(r, spy_ret), 3),
            "turn_ann": round(dg["turnover_ann"], 2),
            "rhobar": round(rhobar, 3),
            "N_eff": round(neff, 2),
        }

    rows = [
        row("BASE_17", rb, rhobar_b, neff_b, N_b, dg_base),
        row("EXPANDED_33", re_, rhobar_e, neff_e, N_e, dg_exp),
        row(f"EXP_minus_{biggest}", rl, rhobar_l, neff_l, N_l, dg_loo),
        row(f"PRUNED_{N_p}", rp, rhobar_p, neff_p, N_p, dg_pruned),
    ]

    tab = pd.DataFrame(rows).set_index("basket")
    b = tab.loc["BASE_17"]
    e = tab.loc["EXPANDED_33"]

    lines: list[str] = []

    def say(s: str = "") -> None:
        lines.append(s)
        print(s)

    say("=" * 92)
    say("ALPHATREND BREADTH EXPANSION A/B — 17-ETF baseline vs 33-ETF expanded universe")
    say(f"window {common.min().date()}..{common.max().date()}  n={len(common)} sessions  "
        f"| ledger N={n_trials} ({trials_logged} trials logged by this screen)")
    say(f"added ({len(ADD16)}): {' '.join(ADD16)}")
    if dropped:
        say(f"DROPPED (insufficient history/liquidity): {' '.join(dropped)}")
    say(f"vol-match target = baseline realized vol = {match_vol:.3f}  (maxDD/skew compared here)")
    say(f"expanded book: avg {dg_exp['avg_active']:.1f} / max {dg_exp['max_active']} active names "
        f"(short-history names join as they list)")
    say("=" * 92)
    say(tab.to_string())
    say()
    say("BREADTH CHECK (did decorrelation actually rise?):")
    say(f"  BASE_17     : rhobar={rhobar_b:+.3f}  N_eff={neff_b:.2f} of {N_b}  "
        f"(sqrt(N_eff)={np.sqrt(neff_b):.2f})")
    say(f"  EXPANDED_33 : rhobar={rhobar_e:+.3f}  N_eff={neff_e:.2f} of {N_e}  "
        f"(sqrt(N_eff)={np.sqrt(neff_e):.2f})")
    say(f"  delta       : d_rhobar={rhobar_e - rhobar_b:+.3f}  d_N_eff={neff_e - neff_b:+.2f}  "
        f"-> ceiling lift ~ x{np.sqrt(neff_e / neff_b):.3f}")
    say()
    say("EXPANDED vs BASELINE (net of the added cost):")
    say(
        f"  dSharpe  = {e.net_sharpe - b.net_sharpe:+.3f}   "
        f"({b.net_sharpe:.3f} -> {e.net_sharpe:.3f})"
    )
    say(f"  dDSR@N   = {e['DSR@N'] - b['DSR@N']:+.3f}   ({b['DSR@N']:.3f} -> {e['DSR@N']:.3f})")
    say(f"  dMaxDD   = {e.maxDD_vm - b.maxDD_vm:+.4f}  (vol-matched; +=shallower="
        f"{'better' if e.maxDD_vm > b.maxDD_vm else 'worse'})")
    say(f"  dSkew    = {e['skew'] - b['skew']:+.3f}   dCorrSPY={e.corr_SPY - b.corr_SPY:+.3f}   "
        f"dTurn={e.turn_ann - b.turn_ann:+.2f}")
    say()
    say(f"LEAVE-ONE-OUT (biggest expanded contributor = {biggest}):")
    lo = tab.loc[f"EXP_minus_{biggest}"]
    say(f"  drop {biggest} -> Sharpe {e.net_sharpe:.3f} -> {lo.net_sharpe:.3f} "
        f"(d={lo.net_sharpe - e.net_sharpe:+.3f}); still >= baseline {b.net_sharpe:.3f}? "
        f"{'YES' if lo.net_sharpe >= b.net_sharpe else 'NO'}")

    say()
    say("PER-CANDIDATE DECORRELATION (are the additions actually decorrelated from the 17?):")
    say(cand_tab.to_string())
    say(f"  (17-core rhobar={rhobar_b:+.3f} — an addition only helps N_eff if its avg_corr_17 is "
        f"below this)")
    say()
    p = tab.loc[f"PRUNED_{N_p}"]
    say(f"GREEDY N_eff-MAXIMIZING PRUNED BASKET (best-case decorrelated expansion, {N_p} names):")
    kept_text = " ".join(kept_adds) if kept_adds else "(none raised N_eff)"
    say(f"  kept additions ({len(kept_adds)}): {kept_text}")
    say(f"  PRUNED rhobar={rhobar_p:+.3f}  N_eff={neff_p:.2f} of {N_p}  "
        f"(vs base N_eff={neff_b:.2f})   Sharpe {p.net_sharpe:.3f} vs baseline {b.net_sharpe:.3f} "
        f"(d={p.net_sharpe - b.net_sharpe:+.3f})")

    # crisis maxDD (vol-matched) — the crash-protection check
    crises = {"GFC_2008": ("2007-10-01", "2009-03-31"),
              "COVID_2020": ("2020-02-15", "2020-04-30"),
              "BEAR_2022": ("2022-01-01", "2022-12-31")}
    say()
    say("crisis maxDD (vol-matched, more-negative = deeper):")
    crow = {}
    for name, r in (("BASE_17", rb), ("EXPANDED_33", re_)):
        rm = to_vol(r, match_vol)
        crow[name] = {c: round(maxdd(rm.loc[(rm.index >= a) & (rm.index <= z)]), 4)
                      for c, (a, z) in crises.items()}
    say(pd.DataFrame(crow).to_string())

    report = {
        "probe": "alphatrend_breadth",
        "window": [str(common.min().date()), str(common.max().date())],
        "n_sessions": len(common), "ledger_N": int(n_trials),
        "trials_logged_this_run": trials_logged,
        "trial_configs": configs,
        "added": ADD16, "dropped": dropped,
        "breadth": {"base": {"rhobar": rhobar_b, "N_eff": neff_b, "N": N_b},
                    "expanded": {"rhobar": rhobar_e, "N_eff": neff_e, "N": N_e}},
        "biggest_contributor": biggest,
        "candidate_decorrelation": json.loads(cand_tab.reset_index().to_json(orient="records")),
        "pruned_kept_adds": kept_adds, "pruned_tickers": pruned_tickers,
        "table": json.loads(tab.reset_index().to_json(orient="records")),
        "crisis_maxdd_volmatched": crow,
        "diag": {"base": dg_base, "expanded": dg_exp, "loo": dg_loo},
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    (OUT / "report.txt").write_text("\n".join(lines))
    say()
    say(f"artifacts -> {OUT}  (report.txt / report.json)  | records appended: {trials_logged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
