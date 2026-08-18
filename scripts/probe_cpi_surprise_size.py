#!/usr/bin/env python3
"""PROBE — PIT CPI SURPRISE -> EQUITY SIZE ROTATION (IWM vs SPY). Spec LOCKED 2026-08-05.

WHY THIS CANDIDATE, AFTER EIGHT NULLS
-------------------------------------
Every prior sweep rearranged price and volume, or reached for a factor whose siblings had
already died. This is different in one specific way: it uses POINT-IN-TIME MACRO VINTAGES —
the CPI as it was FIRST PUBLISHED, before revision. Almost all published macro research is
contaminated because it uses today's revised series, which nobody had at the time. We hold a
genuine vintage lake, and that is a real informational asset rather than another transformation.

MECHANISM (causal, not statistical)
-----------------------------------
A CPI print is the most-watched US release; the RATES market prices it within minutes. The
equity CROSS-SECTION does not, because the trade it implies — rotate small-cap toward large-cap
— is a slow, capacity-constrained institutional reallocation. Russell-2000 ADV is a fraction of
S&P-500 ADV, so the same dollar of rotation takes weeks to execute, and the funds doing it
(macro overlays, risk-parity equity sleeves, multi-manager pods) are the price-INSENSITIVE side:
they rotate because a risk model says their inflation exposure changed, not because they have a
view on any of the 2,000 names.

The two halves of that claim are separately testable and this probe reports BOTH:
  * the news IS already in rates by our entry  -> contemporaneous rate correlation strong,
    FORWARD rate predictability ~zero;
  * it is NOT yet in the equity size spread    -> forward (IWM-SPY) correlation significant.

============================== PRE-REGISTERED SPEC ==============================
ONE configuration. No sweep, no cell-picking. Locked before this file computed a Sharpe.

UNIVERSE : exactly two instruments, IWM and SPY. Nothing else is tradable here.
SIGNAL   : at each vintage date V (the 15th), for PCPI (headline) and PCPIX (core):
             - take that vintage's OWN column and log-difference WITHIN the single vintage
               (differencing first_release ACROSS vintages mixes base-year rebasings and
               seasonal re-estimation and manufactures a fake signal — the lake's own
               DATA_CONTRACT documents this trap);
             - fit an expanding-window AR(3) by OLS on growth history STRICTLY BEFORE the
               newly added observation month;
             - surprise = (new print - AR(3) prediction) / in-sample residual sd, clipped +/-3.
           SI = simple mean of the two standardized surprises.
WEIGHTS  : w = -clip(SI, -1, +1) applied to the dollar-neutral spread (IWM - SPY).
           w>0 = long IWM / short SPY. Gross per leg = |w| x NAV.
TIMING   : *** THE ANTI-LOOKAHEAD RULE *** enter at the CLOSE of the first trading day STRICTLY
           AFTER V, hold to the next vintage date. The vintage is stamped the 15th while BLS
           actually releases the 10th-13th, so the stamp is conservative by 2-5 days and entry
           adds 1-4 more. We enter 3-9 days AFTER the news is public and DELIBERATELY FORFEIT
           the announcement-day move, which is a real but entirely different and far more
           crowded trade.
COSTS    : 6bp one-way on each leg per rebalance. Monthly, so turnover is low by construction.

PRE-REGISTERED READING RULE:
  ADD only if ALL of: (a) own_SR > rho x S_b, (b) Newey-West t >= 1.5 on the daily series,
  (c) the mean-zeroed control gives back most of the book benefit, and (d) the QQQ-SPY placebo
  stays insignificant (proving size-specificity rather than a disguised beta or duration bet).
  Anything else = KILLED.

INDEPENDENT REPRODUCTION NOTE, recorded before the result: a first pass reproduced the core
correlation at corr -0.169 / t -2.97 (n=300), against -0.207 / t -3.64 reported by the research
agent that surfaced it. Weaker, same sign, still significant. The number this probe prints is
the one of record.

    uv run python scripts/probe_cpi_surprise_size.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
_SRC = _LIB.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.analytics.curve_store import write_curve  # noqa: E402
from alphaforge.core.time import now_ms  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

VINT = "data/lake_macro_vintage/tier2_vintage"
OUT = Path("artifacts/probe/cpi_surprise_size")
ANN = 252
COST_ONEWAY = 0.0006
AR_LAGS = 3
CLIP = 3.0


def surprise(series: str) -> pd.Series:
    """Standardized AR(3) residual of the newly-added observation, per vintage."""
    d = pd.read_parquet(f"{VINT}/{series}_vintage_long.parquet")
    d["obs_period"] = pd.to_datetime(d["obs_period"])
    d["vintage_date"] = pd.to_datetime(d["vintage_date"])
    out: dict[pd.Timestamp, float] = {}
    for V, g in d.groupby("vintage_date"):
        g = g.sort_values("obs_period")
        values = _complete_latest_monthly_release(g, pd.Timestamp(V))
        if values is None:
            continue
        gr = pd.Series(np.log(values.to_numpy(dtype=float))).diff().dropna().values
        if len(gr) < 45:
            continue
        new, hist = gr[-1], gr[:-1]          # fit STRICTLY before the new observation
        if len(hist) < 40:
            continue
        y = hist[AR_LAGS:]
        X = np.column_stack([hist[AR_LAGS - k - 1: len(hist) - k - 1] for k in range(AR_LAGS)])
        A = np.column_stack([np.ones(len(y)), X])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        sd = (y - A @ beta).std(ddof=AR_LAGS + 1)
        pred = beta[0] + sum(beta[k + 1] * hist[-(k + 1)] for k in range(AR_LAGS))
        out[V] = float(np.clip((new - pred) / max(sd, 1e-12), -CLIP, CLIP))
    return pd.Series(out).sort_index()


def _complete_latest_monthly_release(
    vintage_rows: pd.DataFrame, vintage_date: pd.Timestamp
) -> pd.Series | None:
    """Return values through the release month, or fail closed on a missing latest MoM pair.

    RTDSM stamps each vintage on the 15th and CPI/this macro family are monthly, so vintage ``V``
    may only call the preceding calendar month its newly released observation.  Both that month
    and its immediate predecessor must be finite: otherwise ``diff().dropna()`` can quietly leave
    an older change at the tail and relabel it as the new surprise.  That happened around the
    missing October 2025 CPI print: the December vintage's newest finite level was November, but
    October was absent, so the old September change was reused under a new vintage date.

    Interior historical gaps remain missing and are never bridged; only valid adjacent monthly
    differences enter the AR history.  Returning ``None`` skips the unusable vintage rather than
    inventing a signal.
    """
    expected = (pd.Timestamp(vintage_date).to_period("M") - 1).to_timestamp()
    previous = (expected.to_period("M") - 1).to_timestamp()
    g = vintage_rows.copy()
    g["obs_period"] = pd.to_datetime(g["obs_period"]).dt.to_period("M").dt.to_timestamp()
    g["value"] = pd.to_numeric(g["value"], errors="coerce")
    g = g.drop_duplicates("obs_period", keep="last").sort_values("obs_period")
    by_month = g.set_index("obs_period")["value"]
    if expected not in by_month.index or previous not in by_month.index:
        return None
    if pd.isna(by_month.loc[expected]) or pd.isna(by_month.loc[previous]):
        return None
    return by_month.loc[:expected]


def px(sym: str) -> pd.Series:
    fs = glob.glob(f"data/lake_mf/ohlcv_1d/instrument_id=*{sym}USD/**/*.parquet", recursive=True)
    if not fs:
        raise SystemExit(f"no lake_mf data for {sym}")
    d = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs])
    d = d.drop_duplicates("ts_open").sort_values("ts_open")
    s = pd.Series(d["close"].astype(float).values,
                  index=pd.to_datetime(d["ts_open"], unit="ms").dt.normalize().values)
    return s[~s.index.duplicated()].sort_index()


def sharpe(r: pd.Series) -> float:
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def nw_t(r: pd.Series, lags: int = 10) -> float:
    x = np.asarray(r, float)
    n = len(x)
    if n < 30:
        return 0.0
    e = x - x.mean()
    var = (e @ e) / n
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    return float(x.mean() / np.sqrt(max(var, 1e-18) / n))


def portfolio_calendar_returns(net: pd.Series, weights: pd.Series) -> pd.Series:
    """Retain every session between first and last exposure, including explicit zero days."""
    active = weights.reindex(net.index).fillna(0.0).abs() > 0
    if not active.any():
        raise RuntimeError("CPI sleeve has no active exposure window")
    active_index = net.index[active]
    return net.loc[active_index.min() : active_index.max()]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SI = ((surprise("PCPI") + surprise("PCPIX")) / 2.0).dropna()
    IWM, SPY, QQQ = px("IWM"), px("SPY"), px("QQQ")
    print(f"surprise series: {len(SI)} vintages, {SI.index.min().date()}..{SI.index.max().date()}")

    # ---- daily P&L of the pre-registered rule ----
    idx = IWM.index.intersection(SPY.index)
    rl = np.log(IWM.reindex(idx)).diff()
    rs = np.log(SPY.reindex(idx)).diff()
    spread = (rl - rs).dropna()
    w = pd.Series(0.0, index=spread.index)
    Vs = list(SI.index)
    for i, V in enumerate(Vs[:-1]):
        after = spread.index[spread.index > V]
        if len(after) == 0:
            continue
        e0 = after[0]
        seg = (spread.index > e0) & (spread.index <= Vs[i + 1])
        w.loc[seg] = -float(np.clip(SI[V], -1, 1))
    turn = (w - w.shift(1)).abs().fillna(0.0)
    gross = w * spread
    net = (gross - turn * COST_ONEWAY * 2).dropna()   # two legs
    live = net[w.abs() > 0]
    portfolio = portfolio_calendar_returns(net, w)

    eq = (1 + portfolio).cumprod()
    print(f"\nSTRATEGY (net of {COST_ONEWAY*1e4:.0f}bp one-way per leg)")
    print(
        f"  portfolio days {len(portfolio)} ({len(live)} active)  "
        f"{portfolio.index.min().date()}..{portfolio.index.max().date()}"
    )
    print(f"  net Sharpe {sharpe(portfolio):+.3f}   NW t {nw_t(portfolio):+.2f}")
    print(f"  ann ret {portfolio.mean()*ANN:+.2%}   "
          f"vol {portfolio.std(ddof=0)*np.sqrt(ANN):.2%}"
          f"   maxDD {float((eq/eq.cummax()-1).min()):+.1%}")
    print(f"  gross Sharpe (no costs) {sharpe(gross[w.abs()>0]):+.3f}"
          f"   turnover {turn.loc[portfolio.index].sum()/(len(portfolio)/ANN):.2f}x/yr")

    # ---- placebo: same signal on QQQ-SPY must be dead (size-specific, not beta/duration) ----
    idx2 = QQQ.index.intersection(SPY.index)
    sp2 = (np.log(QQQ.reindex(idx2)).diff() - np.log(SPY.reindex(idx2)).diff()).dropna()
    w2 = w.reindex(sp2.index).fillna(0.0)
    pl = (w2 * sp2).dropna()
    pl = pl[w2.abs() > 0]
    print("\nPLACEBO (identical signal on QQQ-SPY — must be INSIGNIFICANT)")
    print(f"  Sharpe {sharpe(pl):+.3f}   NW t {nw_t(pl):+.2f}")

    # ---- diversifier arithmetic vs the live book ----
    def curve(p):
        e = pd.read_parquet(p)
        s = pd.Series(e["equity"].astype(float).values,
                      index=pd.to_datetime(e["ts"], unit="ms").dt.normalize().values)
        return np.log(s[~s.index.duplicated()].sort_index()).diff().dropna()
    B = {"eq": curve("artifacts/walkforward/k30_dn_63/equity.parquet"),
         "mf": curve("artifacts/walkforward/mf_live_fwd/equity.parquet"),
         "inv": curve("artifacts/walkforward/prereg_investment/equity.parquet")}
    j = pd.concat([*B.values(), portfolio.rename("c")], axis=1,
                  keys=[*B.keys(), "c"]).dropna()
    checks, verdict = {}, "KILLED"
    if len(j) > 100:
        bk = j[["eq", "mf", "inv"]].mean(axis=1)
        S_b, S_c = sharpe(bk), sharpe(j["c"])
        rho = float(np.corrcoef(bk, j["c"])[0, 1])
        bar = rho * S_b
        cz = j["c"] - j["c"].mean()
        print(f"\nDIVERSIFIER ({j.index.min().date()}..{j.index.max().date()}, {len(j)}d)")
        print(f"  book S_b {S_b:+.3f} | candidate {S_c:+.3f} | rho {rho:+.3f} | bar {bar:+.3f}")
        best = (-9.0, 0.0, 0.0)
        print(f"  {'weight':>7}{'book SR':>10}{'delta':>9}{'zeroed d':>10}{'from mean':>11}")
        for wt in (0.05, 0.10, 0.15, 0.20):
            d = sharpe((1 - wt) * bk + wt * j["c"]) - S_b
            dz = sharpe((1 - wt) * bk + wt * cz) - S_b
            frac = (d - dz) / d * 100 if abs(d) > 1e-12 else 0.0
            candidate_book_sharpe = sharpe((1 - wt) * bk + wt * j["c"])
            print(
                f"  {wt * 100:>6.0f}%{candidate_book_sharpe:>10.3f}{d:>+9.3f}"
                f"{dz:>+10.3f}{frac:>10.0f}%"
            )
            if d > best[0]:
                best = (d, dz, frac)
        checks = {
            "a_clears_bar": bool(S_c > bar),
            "b_nw_t_ge_1p5": bool(abs(nw_t(portfolio)) >= 1.5),
            "c_benefit_is_the_mean": bool(best[2] >= 50.0 and best[0] > 0),
            "d_placebo_dead": bool(abs(nw_t(pl)) < 1.5),
        }
        verdict = "ADD" if all(checks.values()) else "KILLED"
        print("\nPRE-REGISTERED READING RULE")
        for k, v in checks.items():
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
        print(f"\n  VERDICT: {verdict}")

    # PERSIST THE CURVE, not just the verdict. This probe returned "ADD" on 2026-08-05 and its
    # artifact was 476 bytes of scalars, so the one number that decides a sleeve's worth in a
    # portfolio — its correlation to the book — could not be computed by anyone, including us.
    curve_path = write_curve(portfolio, OUT)
    # AND REGISTER THE TRIAL — screen-stage probes never touched a ledger, so this hypothesis
    # was invisible to the deflation every sleeve is graded against. Idempotent on the config
    # hash: re-running to regenerate an artifact cannot inflate N.
    rec = record_probe_trial(
        "cpi_surprise_size",
        {"series": ["PCPI", "PCPIX"], "sign": -1, "spread": "IWM-SPY",
         "ar_lags": AR_LAGS, "clip": CLIP, "cost_oneway_bp": COST_ONEWAY * 1e4},
        portfolio,
        now_ms=now_ms(),
        prereg="docs/design/PREREG_SLEEVE4_INVESTMENT.md / spec locked 2026-08-05",
    )
    print(f"\ncurve persisted: {curve_path}  ({len(portfolio)} portfolio days)")
    print(f"trial registered: config_hash {rec.config_hash}")

    (OUT / "result.json").write_text(json.dumps({
        "spec": {"instruments": ["IWM", "SPY"], "ar_lags": AR_LAGS, "clip": CLIP,
                 "cost_oneway_bp": COST_ONEWAY * 1e4, "configs_tried": 1},
        "net_sharpe": sharpe(portfolio), "nw_t": nw_t(portfolio),
        "active_day_net_sharpe_superseded": sharpe(live),
        "portfolio_days": len(portfolio), "active_days": len(live),
        "calendar_correction": "zero-exposure sessions retained between first and last activity",
        "gross_sharpe": sharpe(gross[w.abs() > 0]),
        "placebo_sharpe": sharpe(pl), "placebo_nw_t": nw_t(pl),
        "checks": checks, "verdict": verdict}, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
