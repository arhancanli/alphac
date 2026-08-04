#!/usr/bin/env python3
"""PROBE — CAGR, LEVERAGE, AND WHETHER MARKET-NEUTRAL IS THE RIGHT SHAPE. 2026-08-03.

Three questions the owner asked before committing real capital, answered with arithmetic
rather than opinion:

  Q1  Can we raise CAGR rather than Sharpe?
  Q2  Is market-neutral the best shape for RETURNS?
  Q3  What does leverage actually buy, and what does it cost?

THE IDENTITY THAT GOVERNS ALL THREE (state it before any result, so nothing looks like a
discovery that is really just algebra):

        CAGR  ~=  Sharpe x vol  -  vol^2/2        [the second term is compounding drag]

Sharpe is the only term that is *earned*. Vol is a DIAL — you can set it wherever you like
with leverage. So "increase CAGR" is not an alpha question at all; it is a risk question,
and the honest framing is: at a GIVEN Sharpe, what drawdown are you willing to hold to reach
a given CAGR? Leverage multiplies the numerator and the denominator together.

THE DANGER THIS PROBE EXISTS TO QUANTIFY: levering an edge you are UNCERTAIN about. Our own
published forward is Sharpe 0.3-0.9 "with a real chance of ~0 in year one", and the deflated
Sharpe ratio at the current trial count is 0.00 — i.e. we cannot statistically distinguish
this book's edge from luck. Kelly sizing assumes you KNOW mu. When mu is uncertain and you
size as if you knew it, leverage does not amplify an edge, it amplifies an error.

Also included, unrequested but decisive: the honest benchmark. If a market-neutral book
returns less than buy-and-hold SPY at similar Sharpe, the owner deserves to see that
comparison before committing money, not after.

    uv run python scripts/probe_returns_leverage.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT = Path("artifacts/probe/returns_leverage")
ANN = 252


def load_curve(path: str) -> pd.Series:
    eq = pd.read_parquet(path)
    if "ts" in eq.columns:
        s = pd.Series(eq["equity"].astype(float).values,
                      index=pd.to_datetime(eq["ts"], unit="ms").dt.normalize().values)
    else:
        s = eq.iloc[:, -1].astype(float)
    return s[~s.index.duplicated()].sort_index()


def spy() -> pd.Series:
    fs = glob.glob("data/lake_mf/ohlcv_1d/instrument_id=*SPYUSD/**/*.parquet", recursive=True)
    d = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs])
    d = d.drop_duplicates("ts_open").sort_values("ts_open")
    return pd.Series(d["close"].astype(float).values,
                     index=pd.to_datetime(d["ts_open"], unit="ms").dt.normalize().values)


def stats(r: pd.Series, lev: float = 1.0) -> dict:
    r = r.dropna() * lev
    if len(r) < 100:
        return {}
    sd = r.std(ddof=0)
    eq = (1.0 + r).cumprod()
    yrs = len(r) / ANN
    # ruin = equity ever touching -100% on a levered path (the term Kelly ignores at your peril)
    ruined = bool((eq <= 0).any())
    return {
        "sharpe": float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0,
        "cagr_pct": float((eq.iloc[-1] ** (1 / yrs) - 1) * 100) if eq.iloc[-1] > 0 else -100.0,
        "vol_pct": float(sd * np.sqrt(ANN) * 100),
        "max_dd_pct": float((eq / eq.cummax() - 1).min() * 100),
        "worst_day_pct": float(r.min() * 100),
        "ruined": ruined,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # the book's research curve = the three sleeves as actually validated
    eq_c = load_curve("artifacts/walkforward/k30_dn_63/equity.parquet")
    r_eq = np.log(eq_c).diff().dropna()
    mf_c = load_curve("artifacts/walkforward/mf_live_fwd/equity.parquet")
    r_mf = np.log(mf_c).diff().dropna()
    s = spy()
    r_spy = np.log(s).diff().dropna()

    # book = 40/40/20 with crypto proxied out (crypto research curve is a different window);
    # use the two equity/MF sleeves at their relative weights, which is the honest overlap.
    j = pd.concat([r_eq.rename("eq"), r_mf.rename("mf"), r_spy.rename("spy")], axis=1).dropna()
    book = (0.40 * j["eq"] + 0.20 * j["mf"]) / 0.60          # renormalised to the overlap
    print("=" * 78)
    print(f"WINDOW {j.index.min().date()} .. {j.index.max().date()}  ({len(j)} common sessions)")
    print("=" * 78)

    print("\nQ2 — IS MARKET-NEUTRAL THE BEST SHAPE FOR RETURNS? (the honest benchmark)")
    print(f"  {'':<26}{'Sharpe':>8}{'CAGR%':>9}{'vol%':>8}{'maxDD%':>9}{'worst day%':>12}")
    for label, r in (("ALPHAC book (neutral)", book), ("SPY buy-and-hold", j["spy"])):
        st = stats(r)
        print(f"  {label:<26}{st['sharpe']:>8.2f}{st['cagr_pct']:>9.2f}{st['vol_pct']:>8.1f}"
              f"{st['max_dd_pct']:>9.1f}{st['worst_day_pct']:>12.2f}")
    print("  READ: neutral books trade CAGR for drawdown. SPY usually wins on CAGR and loses")
    print("  badly on drawdown. Which you want is a RISK CHOICE, not an alpha question.")

    print("\nQ1+Q3 — WHAT LEVERAGE ACTUALLY BUYS (same edge, dial turned up)")
    print(f"  {'leverage':<10}{'Sharpe':>8}{'CAGR%':>9}{'vol%':>8}{'maxDD%':>9}{'worst day%':>12}{'ruin':>7}")
    base = stats(book)
    for lev in (1, 2, 3, 5, 8):
        st = stats(book, lev)
        print(f"  {lev}x{'':<8}{st['sharpe']:>8.2f}{st['cagr_pct']:>9.2f}{st['vol_pct']:>8.1f}"
              f"{st['max_dd_pct']:>9.1f}{st['worst_day_pct']:>12.2f}{str(st['ruined']):>7}")
    print("  READ: Sharpe is IDENTICAL at every row — leverage cannot create edge. CAGR and")
    print("  drawdown scale together until compounding drag turns CAGR back down.")

    # the crisis-inclusive reality: our published worst case is -15% to -18%, not the
    # backtest window's max_dd, so show what leverage does to THAT.
    print("\n  CRISIS-INCLUSIVE (our published honest worst case is -15% to -18% UNLEVERED):")
    for lev in (1, 2, 3, 5):
        print(f"    {lev}x -> a -15% to -18% crisis becomes {-15*lev:.0f}% to {-18*lev:.0f}%"
              + ("   <-- ACCOUNT DESTROYED" if 18 * lev >= 100 else ""))

    print("\n  THE UNCERTAINTY PROBLEM (why Kelly is the wrong tool here):")
    mu, sd = base["cagr_pct"] / 100, base["vol_pct"] / 100
    print(f"    measured: mu {mu*100:+.2f}%/yr, vol {sd*100:.1f}%  -> naive full-Kelly f* = mu/vol^2 = {mu/sd**2:.1f}x")
    print("    BUT Kelly assumes mu is KNOWN. Our deflated Sharpe is 0.00 at the current trial")
    print("    count and the published forward explicitly allows ~0 in year one. If true mu is")
    print("    zero, every leverage row above has the same expected return (zero) and strictly")
    print("    worse drawdowns. Sizing on an unproven mu is how leveraged funds die.")

    import json
    (OUT / "result.json").write_text(json.dumps({
        "window": [str(j.index.min().date()), str(j.index.max().date())],
        "book": base, "spy": stats(j["spy"]),
        "leverage": {f"{l}x": stats(book, l) for l in (1, 2, 3, 5, 8)},
    }, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
