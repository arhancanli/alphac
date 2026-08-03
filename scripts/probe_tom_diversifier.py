#!/usr/bin/env python3
"""PROBE — TURN-OF-MONTH AS A DIVERSIFIER, NOT AS A STANDALONE. Spec LOCKED 2026-08-03.

WHY RE-OPEN A KILLED CANDIDATE (the part that must be argued BEFORE any number)
------------------------------------------------------------------------------
`mechflow_tom` was killed at screen with: "net Sharpe 0.27, below buy-and-hold SPY (0.58) and
the screen bar". That reason is WRONG ARITHMETIC for a book. A candidate does not have to beat
the book to improve it. Adding a sleeve with correlation rho to a book of Sharpe S_b improves
the book iff:

        own_SR  >  rho x S_b

With the live book at S_b = 0.64 and a candidate that is in CASH 76% OF DAYS (so rho is small
by construction, maybe 0.10-0.20), the bar is 0.06-0.13. A standalone Sharpe of 0.27 clears
that with room. We screened it on a bar it never needed to clear.

RE-OPENING A KILL IS ALSO HOW PEOPLE FOOL THEMSELVES, so the guards are stated up front:
  * The bar change is ARITHMETIC, not a result. rho x S_b is the textbook condition and it was
    written down (in the reframe) BEFORE this probe was run. It is not a bar invented to let a
    favourite through.
  * The original DSR of 0.035 was deflated across 43 CONFIGS. That penalty is a search penalty.
    This probe runs ONE config, fixed below, with no sweep, no variants, no cell-picking. If it
    fails, it is dead for good and the kill log gets stronger, not weaker.
  * The effect must be REAL, not just uncorrelated. A zero-mean uncorrelated series also lowers
    book vol and thus "improves" naive Sharpe — that is return-stacking, not alpha. The
    mean-zeroed control below is the gate that killed econ-trend and it is mandatory here.

============================== PRE-REGISTERED SPEC ==============================
Locked before any number was computed. One pass, no search-and-pick.

SIGNAL   : the canonical Ariel / Lakonishok-Smidt turn-of-month window — LONG the index on the
           LAST 1 trading day of each month plus the FIRST 3 of the next; FLAT otherwise.
           This is the textbook definition, chosen because it is the standard, NOT because it
           was the best of 43 cells. No parameter is tuned here.
INSTRUMENT: SPY (the deepest, cheapest expression of the flow). QQQ reported as a replication
           check only — it does NOT get to rescue SPY if SPY fails.
COSTS    : 3bp one-way on every position change (2 round trips/month ~= 12bp/yr all-in), which
           is generous-to-pessimistic for SPY.
JUDGED AS: a diversifier. Reported against the live book curve on the COMMON window:
             - own net Sharpe
             - rho to the book, and the implied bar rho x S_b
             - book Sharpe delta at candidate weights 5/10/15/20%
             - the MEAN-ZEROED control at the same weights
             - Newey-West(5) t-stat of the daily in-window mean

PRE-REGISTERED READING RULE (so this cannot be spun):
  ADD  only if ALL of: (a) own_SR > rho x S_b, (b) book Sharpe delta > 0 at a sane weight,
                       (c) the mean-zeroed control gives back MOST of that delta (i.e. the
                           benefit is the MEAN, not the variance), and (d) NW t-stat >= 2.
  Anything else = KILLED, and this time on the correct bar, which makes the kill final.

    uv run python scripts/probe_tom_diversifier.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT = Path("artifacts/probe/tom_diversifier")
ANN = 252
COST_ONEWAY = 0.0003
DAYS_BEFORE = 1      # last N trading days of the month
DAYS_AFTER = 3       # first N trading days of the next month
WEIGHTS = (0.05, 0.10, 0.15, 0.20)


def load_px(sym: str) -> pd.Series:
    fs = glob.glob(f"data/lake_mf/ohlcv_1d/instrument_id=*{sym}USD/**/*.parquet", recursive=True)
    if not fs:
        raise FileNotFoundError(f"no lake data for {sym}")
    d = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs])
    d = d.drop_duplicates("ts_open").sort_values("ts_open")
    s = pd.Series(d["close"].astype(float).values,
                  index=pd.to_datetime(d["ts_open"], unit="ms").dt.normalize().values)
    return s[~s.index.duplicated()].sort_index()


def load_curve(path: str) -> pd.Series:
    eq = pd.read_parquet(path)
    if "ts" in eq.columns:
        s = pd.Series(eq["equity"].astype(float).values,
                      index=pd.to_datetime(eq["ts"], unit="ms").dt.normalize().values)
    else:
        s = eq.iloc[:, -1].astype(float)
    return s[~s.index.duplicated()].sort_index()


def tom_mask(idx: pd.DatetimeIndex) -> pd.Series:
    """True on the last DAYS_BEFORE sessions of a month and the first DAYS_AFTER of the next."""
    df = pd.DataFrame(index=idx)
    ym = pd.Series(idx.year * 12 + idx.month, index=idx)
    rank_from_end = ym.groupby(ym).cumcount(ascending=False)   # 0 = last session of month
    rank_from_start = ym.groupby(ym).cumcount()                # 0 = first session of month
    df["m"] = (rank_from_end < DAYS_BEFORE) | (rank_from_start < DAYS_AFTER)
    return df["m"]


def tom_returns(px: pd.Series) -> pd.Series:
    """Net daily returns of the pre-registered rule. Decide at close t-1, hold day t."""
    r = np.log(px).diff()
    pos = tom_mask(px.index).astype(float).shift(1).fillna(0.0)   # PIT: no same-day lookahead
    turn = (pos - pos.shift(1)).abs().fillna(0.0)
    return (pos * r - turn * COST_ONEWAY).dropna()


def sharpe(r: pd.Series) -> float:
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def nw_t(r: pd.Series, lags: int = 5) -> float:
    """Newey-West t-stat of the mean (autocorrelation-robust)."""
    x = r.values - 0.0
    n = len(x)
    mu = x.mean()
    e = x - mu
    g0 = (e @ e) / n
    var = g0
    for L in range(1, lags + 1):
        gl = (e[L:] @ e[:-L]) / n
        var += 2 * (1 - L / (lags + 1)) * gl
    se = np.sqrt(var / n)
    return float(mu / se) if se > 0 else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    spy, qqq = load_px("SPY"), load_px("QQQ")
    cand = tom_returns(spy)
    cand_qqq = tom_returns(qqq)

    # the live book on its common window (equity + managed futures at their relative weights;
    # the crypto research curve spans a different window, so this is the honest overlap)
    r_eq = np.log(load_curve("artifacts/walkforward/k30_dn_63/equity.parquet")).diff().dropna()
    r_mf = np.log(load_curve("artifacts/walkforward/mf_live_fwd/equity.parquet")).diff().dropna()
    j = pd.concat([r_eq.rename("eq"), r_mf.rename("mf"), cand.rename("tom")], axis=1).dropna()
    book = (0.40 * j["eq"] + 0.20 * j["mf"]) / 0.60
    tom = j["tom"]

    S_b = sharpe(book)
    S_c = sharpe(tom)
    rho = float(np.corrcoef(book, tom)[0, 1])
    bar = rho * S_b

    print("=" * 80)
    print(f"WINDOW {j.index.min().date()} .. {j.index.max().date()}  ({len(j)} common sessions)")
    print("=" * 80)
    print("\nTHE CANDIDATE (one pre-registered config, no sweep)")
    print(f"  in-window days        {int(tom_mask(spy.index).sum())} of {len(spy)} "
          f"({100*tom_mask(spy.index).mean():.1f}% invested, cash otherwise)")
    print(f"  SPY  own net Sharpe   {S_c:+.3f}   NW(5) t-stat {nw_t(tom):+.2f}")
    print(f"  QQQ  replication      {sharpe(cand_qqq):+.3f}   (check only — cannot rescue SPY)")

    print("\nTHE CORRECT BAR (the arithmetic the original kill got wrong)")
    print(f"  book Sharpe S_b       {S_b:+.3f}")
    print(f"  correlation rho       {rho:+.3f}")
    print(f"  bar = rho x S_b       {bar:+.3f}")
    print(f"  own_SR > bar ?        {'YES' if S_c > bar else 'NO'}  ({S_c:+.3f} vs {bar:+.3f})")

    # ---- the decisive test: does the MEAN carry the benefit, or just the variance? ----
    tom_zero = tom - tom.mean()          # strip alpha, keep vol AND correlation structure
    print("\nBOOK IMPACT vs THE MEAN-ZEROED CONTROL")
    print(f"  {'weight':>7}{'book SR':>10}{'delta':>9}{'zeroed SR':>11}{'zeroed d':>10}{'from mean':>11}")
    rows = {}
    for w in WEIGHTS:
        s_add = sharpe((1 - w) * book + w * tom)
        s_zero = sharpe((1 - w) * book + w * tom_zero)
        d, dz = s_add - S_b, s_zero - S_b
        frac = (d - dz) / d * 100 if abs(d) > 1e-12 else 0.0
        rows[f"{w:.2f}"] = {"book_sharpe": s_add, "delta": d, "zeroed_delta": dz,
                            "pct_from_mean": frac}
        print(f"  {w*100:>6.0f}%{s_add:>10.3f}{d:>+9.3f}{s_zero:>11.3f}{dz:>+10.3f}{frac:>10.0f}%")
    print("  READ: 'from mean' is the share of the gain that comes from the candidate's RETURN")
    print("  rather than from merely diluting book vol. Near 0% = return-stacking, not alpha.")

    best_w = max(WEIGHTS, key=lambda w: rows[f"{w:.2f}"]["delta"])
    best = rows[f"{best_w:.2f}"]
    t = nw_t(tom)
    checks = {
        "a_clears_bar": bool(S_c > bar),
        "b_improves_book": bool(best["delta"] > 0),
        "c_benefit_is_the_mean": bool(best["pct_from_mean"] >= 50.0),
        "d_t_stat_ge_2": bool(abs(t) >= 2.0),
    }
    verdict = "ADD" if all(checks.values()) else "KILLED"
    print("\nPRE-REGISTERED READING RULE")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"\n  VERDICT: {verdict}")
    if verdict == "KILLED":
        print("  This kill now stands on the CORRECT bar (rho x S_b), which makes it final —")
        print("  the earlier 'below SPY' reasoning was never the right test.")

    (OUT / "result.json").write_text(json.dumps({
        "window": [str(j.index.min().date()), str(j.index.max().date())], "n_days": len(j),
        "spec": {"days_before": DAYS_BEFORE, "days_after": DAYS_AFTER,
                 "cost_oneway_bp": COST_ONEWAY * 1e4, "configs_tried": 1},
        "own_sharpe": S_c, "qqq_sharpe": sharpe(cand_qqq), "nw_t": t,
        "book_sharpe": S_b, "rho": rho, "bar": bar,
        "weights": rows, "checks": checks, "verdict": verdict,
    }, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
