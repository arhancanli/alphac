#!/usr/bin/env python3
"""ANALYSIS — the book the PRE-REGISTERED runs already form, and how close it is to the objective.

WHY THIS IS THE MOST VALUABLE THING ON THE SHELF. Eight runs in artifacts/walkforward/ are
`prereg_*`: pre-registered, direction-locked, parameters-locked before the holdout was read, with
20 to 26 years of history each. That matters for one specific reason.

Deflated Sharpe punishes a result for the number of trials it was SELECTED from. The live sleeves
carry the full union of 228 hypothesis identities, which is why not one of them clears the 0.95
portfolio-maturity standard. A pre-registered, direction-locked candidate was not selected from
anything: N=1, and the hurdle collapses from a multiple-testing deflation to the ordinary significance bar,
`SR >= 1.96/sqrt(T)` -- about 0.43 on 21 years against roughly 1.17 for the mined sleeves.

So these eight are the strongest evidence this project owns, and they have never been combined
and measured as a book. This does that.

WHAT THIS IS NOT.
  * Not a new hypothesis. Every run already exists and is already in the ledger; this reads their
    curves and combines them. The ledger is asserted unmoved before and after.
  * Not evidence any of them should be deployed. Being pre-registered says the SEARCH was honest,
    not that the edge is real. A pre-registered null is still a null and is reported as one.
  * Not a licence to pick the best subset. Choosing a favourable combination out of eight curves
    IS selection, even when each input was pre-registered, so the all-in book is reported FIRST
    and any subset is labelled as selected.

ALIGNMENT. Uses `alphaforge.portfolio.book.combine_book`, the live path, which unions calendar
days and computes pairwise correlation only on days where BOTH sleeves are genuinely active. A
naive concat/dropna across a 24/7 crypto sleeve and business-day equity sleeves silently discards
a third of the sample; that trap is documented in this repo and is not re-entered here.

    uv run python scripts/analyze_prereg_book.py
"""

# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import math
import sys
from itertools import combinations
from pathlib import Path

import duckdb
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.portfolio.book import SleeveCurve, combine_book  # noqa: E402

OUT_DIR = _ROOT / "artifacts" / "analysis" / "prereg_book"
LEDGER = _ROOT / "var" / "experiments.jsonl"
TARGET_N = 14
TARGETS = tuple(
    json.loads((_ROOT / "config/sleeve_admission_contract.json").read_text())["objective"][
        "portfolio_sharpe_target"
    ]
)


def load(name: str, path: str) -> SleeveCurve:
    df = duckdb.connect().execute(f"SELECT ts, equity FROM read_parquet('{path}') ORDER BY ts").df()
    return SleeveCurve(
        name=name, ts_ms=df.ts.astype("int64").tolist(), equity=df.equity.astype(float).tolist()
    )


def prereg_hurdle(n_obs: int, trading_days: int = 252) -> float:
    """Ordinary two-sided 5% significance bar for a SINGLE pre-registered strategy.

    `SR_ann >= 1.96 / sqrt(years)`. This is NOT a deflated Sharpe: deflation corrects for the
    number of trials a result was SELECTED from, and a direction-locked pre-registration selected
    from one. It is the right bar here and the wrong bar for anything mined.
    """
    years = n_obs / trading_days
    return 1.96 / math.sqrt(years) if years > 0 else float("inf")


def main() -> int:
    before = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0

    paths = sorted(glob.glob(str(_ROOT / "artifacts/walkforward/prereg_*/equity.parquet")))
    curves = [load(Path(p).parent.name.replace("prereg_", ""), p) for p in paths]
    if len(curves) < 2:
        raise SystemExit("ABORT: fewer than two prereg curves found")

    print("=" * 100)
    print(f"  THE PRE-REGISTERED BOOK — {len(curves)} runs, N=1 selection each")
    print("=" * 100)

    # ---- standalone, each on its OWN full history (the honest per-sleeve view) -------------
    print("\n[1] STANDALONE, each on its own full history")
    print(f"    {'sleeve':<20}{'days':>7}{'years':>7}{'Sharpe':>9}{'prereg bar':>12}   clears?")
    standalone = {}
    for c in curves:
        eq = np.asarray(c.equity, dtype=float)
        r = eq[1:] / eq[:-1] - 1.0
        r = r[np.isfinite(r)]
        sd = float(np.std(r, ddof=1))
        sr = float(np.mean(r) / sd * math.sqrt(252)) if sd > 1e-12 else 0.0
        bar = prereg_hurdle(r.size)
        standalone[c.name] = {
            "days": int(r.size),
            "sharpe_ann": sr,
            "prereg_bar": bar,
            "clears": bool(sr >= bar),
        }
        print(
            f"    {c.name:<20}{r.size:>7}{r.size / 252:>7.1f}{sr:>9.3f}{bar:>12.3f}   {'YES' if sr >= bar else 'no'}"
        )

    cleared = [n for n, v in standalone.items() if v["clears"]]
    print(
        f"\n    {len(cleared)} of {len(curves)} clear their own pre-registration bar: {', '.join(cleared) or 'none'}"
    )

    # ---- the ALL-IN book, reported first so no subset can be presented as the headline -----
    print("\n[2] THE ALL-IN BOOK (every prereg run, no selection)")
    book = combine_book(curves, scheme="equal_risk")
    corr_vals = [v for v in book.corr.values() if np.isfinite(v)]
    rho_bar = float(np.mean(corr_vals)) if corr_vals else float("nan")
    print(f"    sleeves {len(curves)}   common days {book.n_days}   book Sharpe {book.sharpe:+.4f}")
    print(f"    rho_bar {rho_bar:+.4f}   diversification ratio {book.diversification_ratio:.3f}")
    print(
        f"    max drawdown {book.maxdd:+.2%}   decorrelated ceiling sqrt(sum SR^2) {book.sharpe_theory_uncorr:.3f}"
    )

    print("\n    pairwise correlations:")
    for (left_name, right_name), v in sorted(
        book.corr.items(), key=lambda kv: -abs(kv[1]) if np.isfinite(kv[1]) else 0
    ):
        print(f"      {left_name:<18} x {right_name:<18} {v:+.4f}")

    # ---- what this rho_bar implies at the objective's sleeve count -------------------------
    print(f"\n[3] WHAT THIS rho_bar IMPLIES AT N={TARGET_N}")
    s_bar = float(np.mean([standalone[c.name]["sharpe_ann"] for c in curves]))
    print(f"    s_bar across these runs: {s_bar:.4f}")
    for label, rho in (("all-in prereg book", rho_bar), ("live 4-sleeve book", 0.0260)):
        if rho <= -1.0 / (TARGET_N - 1):
            print(f"    {label:<22} rho_bar {rho:+.4f} is below the PSD floor at N={TARGET_N}")
            continue
        n_eff = TARGET_N / (1.0 + (TARGET_N - 1) * rho)
        print(
            f"    {label:<22} rho_bar {rho:+.4f} -> N_eff {n_eff:5.2f} -> book {s_bar * math.sqrt(n_eff):.3f} at s_bar {s_bar:.3f}"
        )
    for t in TARGETS:
        req = (TARGET_N * s_bar * s_bar / (t * t) - 1.0) / (TARGET_N - 1)
        print(f"    to reach {t} at N={TARGET_N} with this s_bar, rho_bar must be <= {req:+.4f}")

    # ---- best pair/triple, EXPLICITLY labelled as selection --------------------------------
    print("\n[4] BEST SUBSETS — labelled as SELECTION, not as a result")
    print("    Reported only to show where the diversification actually lives. Choosing the best")
    print("    subset of eight curves is selection even when every input was pre-registered, so")
    print("    these numbers carry a selection cost that the all-in book above does not.")
    subsets = []
    for k in (2, 3, 4):
        best = None
        for combo in combinations(curves, k):
            subset_book = combine_book(list(combo), scheme="equal_risk")
            if subset_book.n_days < 252:
                continue
            if best is None or subset_book.sharpe > best[1].sharpe:
                best = ([c.name for c in combo], subset_book)
        if best:
            names, subset_book = best
            cv = [v for v in subset_book.corr.values() if np.isfinite(v)]
            subsets.append(
                {
                    "k": k,
                    "sleeves": names,
                    "sharpe": subset_book.sharpe,
                    "rho_bar": float(np.mean(cv)) if cv else None,
                    "days": subset_book.n_days,
                }
            )
            print(
                f"    best {k}: {', '.join(names):<52} Sharpe {subset_book.sharpe:+.3f}  rho_bar {np.mean(cv):+.4f}  ({subset_book.n_days}d)"
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(
        json.dumps(
            {
                "standalone": standalone,
                "cleared_own_prereg_bar": cleared,
                "all_in_book": {
                    "n_sleeves": len(curves),
                    "n_days": book.n_days,
                    "sharpe": book.sharpe,
                    "rho_bar": rho_bar,
                    "maxdd": book.maxdd,
                    "diversification_ratio": book.diversification_ratio,
                    "decorrelated_ceiling": book.sharpe_theory_uncorr,
                    "pairwise": {f"{a}|{b}": v for (a, b), v in book.corr.items()},
                },
                "s_bar": s_bar,
                "best_subsets_SELECTED": subsets,
                "claim_boundary": (
                    "Reads existing pre-registered curves and combines them. No hypothesis "
                    "registered, no return opened, 0 trials. Pre-registration means the search "
                    "was honest, not that the edge is real. Subset numbers carry a selection "
                    "cost the all-in book does not."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    after = sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")
    print(f"\n    ledger unmoved ({after}); 0 hypotheses consumed")
    print(f"    written: {OUT_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
