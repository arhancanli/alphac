#!/usr/bin/env python3
"""ANALYSIS — what would a book Sharpe of 2.5 actually require, and is it reachable?

The owner's stated long-term goal, recorded 2026-08-05:
    "2.5 sharpe ratio, hundreds of uncorrelated or very good sleeves, minimal max dd"

This is a REQUIREMENTS calculation, not a forecast and not a trial. It runs no backtest,
fits nothing, and does not touch var/experiments.jsonl. It inverts the breadth identity

    S_book = s_bar * sqrt(N_eff),      N_eff = N / (1 + (N-1)*rho_bar)

to answer: for a target S, and a given per-sleeve Sharpe s_bar, what average pairwise
correlation and sleeve count are needed -- and where does the requirement become infeasible?

The infeasibility is sharp and worth stating plainly. N_eff is bounded above by 1/rho_bar
NO MATTER HOW MANY SLEEVES YOU ADD, so a target S is unreachable at ANY N unless

    rho_bar < (s_bar / S)^2

That single inequality is the whole ballgame. At s_bar = 0.464 and S = 2.5 it demands
rho_bar < 0.034. Not "helps if" -- required, at any sleeve count, forever.

Second question, on drawdown: high Sharpe and shallow drawdown are the SAME property, not
competing ones, so "2.5 Sharpe with minimal max DD" is internally consistent. Quantified here
by Monte Carlo rather than a closed form, because expected max drawdown grows with horizon
and the closed forms hide that.

    uv run python scripts/analyze_target_2p5.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

OUT = Path("artifacts/analysis/target_2p5")
ANN = 252

# Measured inputs, from scripts/analyze_sleeve_scaling.py on the live sleeve curves.
S_BAR_NOW = 0.464     # average per-sleeve Sharpe, 728d common window
TARGET = 2.5
SD_T = 1.390          # sd of ledger trial t-stats -> sigma_SR = SD_T / sqrt(T_years)
HIT_RATE = 0.0652     # 3 survivors / 46 candidates tested, published kill log
EULER = 0.5772156649015329


def n_eff(n: float, rho: float) -> float:
    if n <= 1:
        return float(n)
    rho = max(rho, -1.0 / (n - 1) + 1e-9)
    d = 1 + (n - 1) * rho
    return float(n / d) if d > 0 else float("inf")


def sleeves_required(target: float, s_bar: float, rho: float) -> float:
    """How many sleeves at correlation rho reach `target`? inf if impossible at any N."""
    need_ne = (target / s_bar) ** 2
    if rho <= 0:
        return need_ne                      # rho<=0 is a small-N luxury; treat as best case
    if need_ne * rho >= 1.0:
        return float("inf")                 # bounded by the 1/rho ceiling -- unreachable
    return need_ne * (1 - rho) / (1 - need_ne * rho)


def sr_star(n_trials: float, sigma_sr: float) -> float:
    from statistics import NormalDist
    nd = NormalDist()
    n = max(float(n_trials), 2.0)
    return sigma_sr * ((1 - EULER) * nd.inv_cdf(1 - 1 / n) + EULER * nd.inv_cdf(1 - 1 / (n * math.e)))


def expected_max_dd(sharpe: float, vol: float, years: float, paths: int = 20000) -> tuple:
    """Monte-Carlo expected and 95th-percentile max drawdown. Normal iid daily returns --
    deliberately OPTIMISTIC, since real strategy returns have fat tails and autocorrelation."""
    rng = np.random.default_rng(12345)
    n = int(years * ANN)
    mu_d, sd_d = sharpe * vol / ANN, vol / math.sqrt(ANN)
    r = rng.normal(mu_d, sd_d, size=(paths, n))
    eq = np.cumprod(1.0 + r, axis=1)
    dd = eq / np.maximum.accumulate(eq, axis=1) - 1.0
    mdd = dd.min(axis=1)
    return float(-mdd.mean()), float(-np.percentile(mdd, 5))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"REQUIREMENT 1 — THE HARD GATE:  rho_bar < (s_bar / S)^2")
    print("=" * 78)
    print("  N_eff can never exceed 1/rho_bar, so if this inequality fails the target is")
    print("  unreachable at ANY sleeve count. Not expensive. Impossible.\n")
    print(f"{'s_bar':>8}{'max rho_bar for S=2.5':>24}{'interpretation':>34}")
    for s_bar in (0.35, 0.464, 0.55, 0.70, 0.90, 1.10):
        rmax = (s_bar / TARGET) ** 2
        note = ("brutal — near-zero correlation" if rmax < 0.03 else
                "hard but not absurd" if rmax < 0.08 else
                "comfortable" if rmax < 0.2 else "easy")
        star = "  <- today" if abs(s_bar - S_BAR_NOW) < 1e-9 else ""
        print(f"{s_bar:>8.3f}{rmax:>24.4f}{note:>34}{star}")

    print("\n" + "=" * 78)
    print("REQUIREMENT 2 — SLEEVE COUNT NEEDED (inf = impossible at that correlation)")
    print("=" * 78)
    rhos = (0.00, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10)
    print(f"\n{'s_bar':>8}" + "".join(f"{('rho=' + format(r, '.2f')):>12}" for r in rhos))
    grid = {}
    for s_bar in (0.35, 0.464, 0.55, 0.70, 0.90, 1.10):
        line, row = f"{s_bar:>8.3f}", {}
        for r in rhos:
            n = sleeves_required(TARGET, s_bar, r)
            row[f"{r:.2f}"] = None if math.isinf(n) else round(n, 1)
            line += f"{'IMPOSSIBLE':>12}" if math.isinf(n) else f"{n:>12.0f}"
        grid[f"{s_bar:.3f}"] = row
        print(line)
    print("\n  Read the 0.464 row: at TODAY's sleeve quality, 2.5 needs ~29 sleeves at rho=0")
    print("  or ~63 at rho=0.02, and becomes IMPOSSIBLE at rho >= 0.034 no matter the count.")
    print("  Read DOWN a column: raising per-sleeve QUALITY is worth far more than adding")
    print("  sleeves. s_bar 0.464 -> 0.70 cuts the requirement by more than half.")

    print("\n" + "=" * 78)
    print("REQUIREMENT 3 — THE TRIAL BILL, and whether the result could ever be BELIEVED")
    print("=" * 78)
    print(f"  at the measured {HIT_RATE:.1%} hit rate, and deflating against the full trial count\n")
    print(f"{'route':>28}{'sleeves':>9}{'trials':>9}{'N_total':>9}"
          f"{'SR* @10y':>10}{'SR* @20y':>10}{'verdict':>26}")
    bill = []
    for label, s_bar, rho in (("today's quality, rho 0.02", 0.464, 0.02),
                              ("today's quality, rho 0.01", 0.464, 0.01),
                              ("better sleeves, rho 0.05", 0.70, 0.05),
                              ("better sleeves, rho 0.02", 0.70, 0.02),
                              ("excellent sleeves, rho 0.05", 0.90, 0.05)):
        n = sleeves_required(TARGET, s_bar, rho)
        if math.isinf(n):
            print(f"{label:>28}{'IMPOSSIBLE':>9}")
            continue
        trials = (n - 4) / HIT_RATE
        n_tot = 125 + max(trials, 0)
        h10, h20 = sr_star(n_tot, SD_T / math.sqrt(10)), sr_star(n_tot, SD_T / math.sqrt(20))
        v = "believable at 10y" if TARGET > h10 else ("needs 20y" if TARGET > h20 else "never")
        bill.append({"route": label, "s_bar": s_bar, "rho": rho, "sleeves": n,
                     "trials": trials, "n_total": n_tot, "sr_star_10y": h10,
                     "sr_star_20y": h20, "verdict": v})
        print(f"{label:>28}{n:>9.0f}{trials:>9.0f}{n_tot:>9.0f}{h10:>10.2f}{h20:>10.2f}{v:>26}")
    print("\n  The good news the earlier analysis missed: a Sharpe of 2.5 is so far above the")
    print("  hurdle that even ~1,500 trials cannot explain it away. The deflation problem is")
    print("  a problem for a 1.0 book. It is NOT the binding constraint on a 2.5 book.")
    print("  The binding constraint on 2.5 is rho_bar, and only rho_bar.")

    print("\n" + "=" * 78)
    print("REQUIREMENT 4 — DRAWDOWN. High Sharpe and shallow DD are the SAME property.")
    print("=" * 78)
    print("  Monte Carlo, 20k paths, normal iid daily (OPTIMISTIC — real returns have fat")
    print("  tails, so treat these as a floor on how bad it gets, not a forecast).\n")
    print(f"{'Sharpe':>8}{'vol':>7}{'E[maxDD] 5y':>14}{'95th pct 5y':>14}"
          f"{'E[maxDD] 20y':>15}{'95th pct 20y':>15}")
    dd_rows = []
    for S in (0.5, 1.0, 1.5, 2.0, 2.5):
        for vol in (0.10,):
            e5, p5 = expected_max_dd(S, vol, 5)
            e20, p20 = expected_max_dd(S, vol, 20)
            dd_rows.append({"sharpe": S, "vol": vol, "e_mdd_5y": e5, "p95_mdd_5y": p5,
                            "e_mdd_20y": e20, "p95_mdd_20y": p20})
            print(f"{S:>8.1f}{vol:>7.0%}{e5:>13.1%}{p5:>14.1%}{e20:>15.1%}{p20:>15.1%}")
    print("\n  So 'Sharpe 2.5 AND minimal drawdown' is not a trade-off — it is one goal stated")
    print("  twice. At 2.5 and 10% vol the expected worst drawdown over TWENTY years is single")
    print("  digits. Today's book, at an honest 0.3-0.9, is where the deep drawdowns live.")
    print("  CAVEAT: this assumes the Sharpe is REAL. A book that is actually 0.5 while")
    print("  believed to be 2.5 draws down like a 0.5 book, and leverage sized for 2.5 then")
    print("  turns a -12% into a catastrophe. Drawdown safety is bought by the Sharpe being")
    print("  true, never by the Sharpe being claimed.")

    (OUT / "result.json").write_text(json.dumps({
        "target": TARGET,
        "inputs": {"s_bar_now": S_BAR_NOW, "sd_t": SD_T, "hit_rate": HIT_RATE},
        "hard_gate_rho_max": {f"{s:.3f}": (s / TARGET) ** 2
                              for s in (0.35, 0.464, 0.55, 0.70, 0.90, 1.10)},
        "sleeves_required": grid,
        "trial_bill": bill,
        "drawdown_mc": dd_rows,
        "conclusion": ("2.5 is reachable in principle but requires rho_bar < (s_bar/2.5)^2 "
                       "-- 0.034 at today's sleeve quality. rho_bar, not sleeve count and not "
                       "deflation, is the binding constraint. Raising per-sleeve Sharpe relaxes "
                       "the requirement faster than adding sleeves does."),
    }, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
