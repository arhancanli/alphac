#!/usr/bin/env python3
"""The strategy-factory math — how 'many uncorrelated strategies' actually moves the combined Sharpe.

The advisor's point (correct): a pod-shop (Millennium/Citadel) does not get fund Sharpe 2-4 from any
brilliant strategy — it gets it from STACKING many modest, uncorrelated ones. The math is exact:

    combined_Sharpe = avg_Sharpe * sqrt( N / (1 + (N-1)*rho) )

So at fixed average skill, the combined Sharpe grows with N (the count of strategies) and SHRINKS with
rho (how correlated they are). The entire game is: more strategies, kept genuinely decorrelated, each
individually deflation-cleared, weighted by skill (not naive equal-risk).

This grounds that formula in OUR real book (measured 2-sleeve forward ~0.70) and projects honestly:
what each realistic next sleeve does, and how many decorrelated sleeves it takes to reach A and beyond.
No fabrication: forward Sharpes are the deflated honest figures (or, for unbuilt sleeves, clearly
labelled assumptions), and the correlation is the thing that makes or breaks it.
"""
# ruff: noqa: E501
from __future__ import annotations

import math


def combined(sharpes: list[float], rho: float) -> float:
    """Combined Sharpe of N equal-skill-ish sleeves at average pairwise correlation rho.
    Uses the average forward Sharpe in the closed-form; exact for equal Sharpes, a fair approx otherwise."""
    n = len(sharpes)
    if n == 0:
        return 0.0
    avg = sum(sharpes) / n
    return avg * math.sqrt(n / (1.0 + (n - 1) * rho))


def main() -> int:
    print("=== THE STRATEGY-FACTORY MATH (combined Sharpe = avg x sqrt(N/(1+(N-1)rho))) ===\n")

    # 1) where we ARE, grounded in the measured 2-sleeve book (forward ~0.70)
    print("OUR BOOK TODAY (measured): 2 sleeves, forward combined ~0.70")
    print("  AlphaForge crypto-carry fwd ~0.30  |  AlphaMax equity-momentum fwd ~0.50")
    print("  (they combine ABOVE their average because they're ~uncorrelated/slightly negative)\n")

    # 2) the honest roadmap of REAL next sleeves (forward Sharpes; unbuilt ones are labelled)
    roadmap = [
        ("AlphaForge  crypto carry",     0.30, "LIVE"),
        ("AlphaMax    equity momentum",  0.50, "LIVE"),
        ("AlphaTrend  futures trend",    0.45, "needs $270 futures data"),
        ("AlphaCarry  futures carry",    0.40, "needs $270 futures data (same buy)"),
        ("AlphaVol    options VRP",      0.45, "Deribit data accruing -> ~2027"),
        ("AlphaFX     FX carry/trend",   0.35, "future, needs FX data"),
        ("Alpha7      e.g. equity value/seasonality", 0.35, "future research"),
        ("Alpha8      e.g. cross-asset reversal",     0.35, "future research"),
    ]
    print("HONEST ROADMAP — combined forward Sharpe as decorrelated sleeves stack (rho assumed 0.15):")
    rho = 0.15
    sh: list[float] = []
    for name, s, status in roadmap:
        sh.append(s)
        c = combined(sh, rho)
        grade = "A*" if c >= 1.8 else "A" if c >= 1.0 else "B+" if c >= 0.8 else "B"
        print(f"  +{name:34} fwd {s:.2f}  -> combined {c:.2f}  [{grade}]   ({status})")
    print()

    # 3) the correlation sensitivity — WHY 'decorrelated' is the whole game
    print("WHY DECORRELATION IS EVERYTHING (8 sleeves at avg fwd 0.40, varying rho):")
    eight = [0.40] * 8
    for r in (0.0, 0.10, 0.20, 0.35, 0.55):
        print(f"  rho {r:.2f}: combined {combined(eight, r):.2f}   {'<- correlated sleeves add almost nothing' if r >= 0.35 else ''}")
    print()

    # 4) what it takes to reach the targets (avg fwd 0.40, rho 0.15)
    print("HOW MANY DECORRELATED SLEEVES TO HIT EACH GRADE (avg fwd 0.40, rho 0.15):")
    for target, label in ((0.80, "B+"), (1.00, "A"), (1.30, "A/A+"), (1.80, "A*/S")):
        n = 1
        while combined([0.40] * n, 0.15) < target and n < 200:
            n += 1
        print(f"  {label:5} (combined {target:.2f}):  ~{n} decorrelated, deflation-cleared sleeves")
    print()

    print("THE HONEST CEILING FOR US: rho is never really 0.15 in a crisis (it spikes toward 0.5-0.9),")
    print("and genuinely-decorrelated deflation-clearing sleeves are RARE + each needs data. Realistic")
    print("multi-year target with disciplined execution = A-territory (~1.0-1.3), NOT Millennium's 2-4")
    print("(they have hundreds of PMs, prime leverage, co-location). The path is real; the ceiling is real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
