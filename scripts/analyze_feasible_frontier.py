#!/usr/bin/env python3
"""The feasibility frontier for a target book Sharpe: which (s_bar, rho_bar, N) reach it.

WHY THIS EXISTS
---------------
The owner's goal is a book Sharpe of 2.5 at 10% vol, which is ~25% CAGR with ~10% median
worst drawdown, reached via "50 to 200 uncorrelated sleeves". This script establishes, from
the arithmetic alone, that the second half of that sentence CANNOT deliver the first half at
today's per-sleeve quality -- and exactly what would have to change for it to.

THE IDENTITY
------------
    S_book = s_bar * sqrt(N_eff)          N_eff = N / (1 + (N-1) * rho_bar)

N_eff is bounded above by 1/rho_bar, so as N -> infinity:

    S_max = s_bar / sqrt(rho_bar)

That ceiling is the whole story. A target S is unreachable at ANY sleeve count unless

    rho_bar < (s_bar / S)^2

At today's measured s_bar = 0.464, reaching 2.5 demands rho_bar < 0.0344. At an honest
forward rho_bar of 0.05 the ceiling is 2.08, so 2.5 is IMPOSSIBLE -- 200 sleeves gets 1.98
and 10,000 would still get 2.08. Raising s_bar to 0.70 lifts the ceiling to 3.13 and brings
the target inside the feasible set at 34 sleeves.

**Sleeve quality is therefore not a preference over sleeve count. It is a PRECONDITION.**
Below s_bar = S * sqrt(rho_bar) the target is not expensive, it is unreachable, and every
trial spent hunting sleeves before clearing that bar is spent on a goal the arithmetic has
already ruled out (and permanently raises the book's deflation hurdle for nothing).

THE PSD FLOOR (why negative rho_bar does not scale)
--------------------------------------------------
A correlation matrix must stay positive semi-definite, which floors the average pairwise
correlation at -1/(N-1). The book's measured -0.040 is a 3-4 sleeve luxury: at N=4 the floor
is -0.333, but at N=250 it is -0.004. No large book runs on negative average correlation, so
every projection here uses rho_bar >= 0.

Costs nothing in trials: this reads no data and runs no backtest.
Related: scripts/analyze_sleeve_scaling.py, scripts/analyze_target_2p5.py
"""

from __future__ import annotations

import numpy as np

TARGET = 2.5
SEED = 20260806  # fixed: this table is quoted publicly and must reproduce byte-for-byte


def book_sharpe(s_bar: float, rho: float, n: int) -> float:
    """Book Sharpe from per-sleeve Sharpe, average pairwise correlation and sleeve count."""
    n_eff = n / (1 + (n - 1) * rho) if rho > 0 else float(n)
    return s_bar * np.sqrt(n_eff)


def ceiling(s_bar: float, rho: float) -> float:
    """The N -> infinity ceiling. No sleeve count beats this."""
    return float("inf") if rho <= 0 else s_bar / np.sqrt(rho)


def sleeves_required(s_bar: float, rho: float, target: float = TARGET) -> float:
    """Sleeves needed to reach ``target``; inf when the ceiling already sits below it."""
    k = (target / s_bar) ** 2
    if rho <= 0:
        return k
    if k * rho >= 1:
        return float("inf")
    return k * (1 - rho) / (1 - k * rho)


def drawdown_profile(sharpe: float, vol: float, years: int = 20, paths: int = 8000):
    """(median CAGR %, median worst DD %, 5th-pctile worst DD %) under normal iid returns.

    Optimistic by construction: real strategies have fat tails and serial dependence, both of
    which deepen drawdowns. Treat these as a floor on the pain, not an estimate of it.
    """
    rng = np.random.default_rng(SEED)
    r = rng.normal(sharpe * vol / 252, vol / np.sqrt(252), (paths, years * 252))
    eq = np.cumprod(1 + r, axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    cagr = eq[:, -1] ** (1 / years) - 1
    return np.median(cagr) * 100, np.median(dd) * 100, np.percentile(dd, 5) * 100


def main() -> None:
    rhos = (0.02, 0.05, 0.10, 0.15, 0.20)
    s_bars = (0.30, 0.464, 0.60, 0.70, 0.90, 1.10)

    print("=" * 78)
    print("1. THE CEILING.  S_max = s_bar / sqrt(rho_bar), as N -> infinity")
    print("=" * 78)
    print(f"{'s_bar':>7}" + "".join(f"{r:>10.3f}" for r in rhos))
    for s in s_bars:
        print(f"{s:>7.3f}" + "".join(f"{ceiling(s, r):>10.2f}" for r in rhos))

    print()
    print("=" * 78)
    print(f"2. SLEEVES REQUIRED FOR A {TARGET} BOOK   (IMPOSS = unreachable at any N)")
    print("=" * 78)
    cols = (0.0, 0.02, 0.03, 0.05, 0.08, 0.10)
    print(f"{'s_bar':>7}" + "".join(f"{('rho=%.2f' % r):>10}" for r in cols))
    for s in s_bars:
        cells = []
        for r in cols:
            n = sleeves_required(s, r)
            cells.append(f"{'IMPOSS':>10}" if np.isinf(n) else f"{int(np.ceil(n)):>10}")
        print(f"{s:>7.3f}" + "".join(cells))

    print()
    print("=" * 78)
    print("3. WHAT EACH BOOK SHARPE DELIVERS   (vol set so CAGR ~= 25%)")
    print("=" * 78)
    print(f"{'S':>5} {'vol':>7} {'CAGR':>8} {'maxDD med':>11} {'maxDD 1-in-20':>14} {'Calmar':>8}")
    for S in (0.66, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
        vol = min(0.25 / S, 0.30)
        c, d, d5 = drawdown_profile(S, vol)
        print(f"{S:>5.2f} {vol:>6.1%} {c:>7.1f}% {d:>10.1f}% {d5:>13.1f}% {abs(c / d):>8.2f}")

    print()
    print("=" * 78)
    print("4. THE LEVERS, VALUED FROM TODAY  (s_bar=0.464, rho=0.05 honest-forward, N=3)")
    print("=" * 78)
    s0, r0 = 0.464, 0.05
    base = book_sharpe(s0, r0, 3)
    print(f"baseline book Sharpe {base:.2f}\n")
    print(f"{'lever':<46}{'new S':>8}{'gain':>8}")
    for label, s, r, n in [
        ("do nothing (3 sleeves)", s0, r0, 3),
        ("+7 sleeves at TODAY's quality (N=10)", s0, r0, 10),
        ("+47 sleeves at TODAY's quality (N=50)", s0, r0, 50),
        ("+197 sleeves at TODAY's quality (N=200)", s0, r0, 200),
        ("raise s_bar to 0.70, still N=3", 0.70, r0, 3),
        ("raise s_bar to 0.70 AND N=10", 0.70, r0, 10),
        ("raise s_bar to 0.70 AND N=34", 0.70, r0, 34),
        ("raise s_bar to 0.90 AND N=12", 0.90, r0, 12),
        ("halve rho to 0.025, s_bar 0.70, N=34", 0.70, 0.025, 34),
    ]:
        S = book_sharpe(s, r, n)
        print(f"{label:<46}{S:>8.2f}{S - base:>+8.2f}")

    print()
    print(f"THE BINDING RESULT: at s_bar={s0} and rho={r0} the ceiling is "
          f"{ceiling(s0, r0):.2f}.")
    print(f"200 sleeves reaches {book_sharpe(s0, r0, 200):.2f} and infinite sleeves "
          f"reaches {ceiling(s0, r0):.2f}.")
    print(f"Neither reaches {TARGET}. The minimum per-sleeve Sharpe that puts {TARGET} inside")
    print(f"the feasible set at rho={r0} is s_bar = {TARGET} * sqrt({r0}) = "
          f"{TARGET * np.sqrt(r0):.3f}.")
    print("Below that line, breadth is not slow. It is futile.")


if __name__ == "__main__":
    main()
