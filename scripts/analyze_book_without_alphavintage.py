"""Measure the book with and without AlphaVintage, and what each does to the target arithmetic.

WHY. AlphaVintage carries a quarter of the book. Its own result artifact records verdict KILLED,
and the production admission evaluator now independently rejects it
(artifacts/analysis/admission_dry_run). Whether it keeps its allocation is the owner's decision,
and the input that decision needs is not a verdict but a MEASUREMENT: what the book's average
pairwise correlation, per-sleeve quality and frontier position look like each way.

Both bases are reported because they differ and the difference matters. Opens no new data,
registers no hypothesis identity, and recommends nothing: 0 trials.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.portfolio.book import SleeveCurve, combine_book

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "book_without_alphavintage" / "result.json"

CURVES = {
    "AlphaForge": "artifacts/walkforward/crypto_carry_wk/equity.parquet",
    "AlphaMax": "artifacts/walkforward/k30_dn_63/equity.parquet",
    "AlphaTrend": "artifacts/walkforward/mf_live_fwd/equity.parquet",
    "AlphaVintage": "artifacts/probe/cpi_surprise_size/equity.parquet",
}
TRADING_DAYS = 252.0
TARGET_N = 14
TARGETS = (2.0, 2.5)


def _curve(name: str, path: Path) -> SleeveCurve:
    frame = pd.read_parquet(path)
    return SleeveCurve(
        name=name,
        ts_ms=[int(v) for v in frame["ts"].to_numpy()],
        equity=[float(v) for v in frame["equity"].to_numpy()],
    )


def _sharpe(values: np.ndarray) -> float:
    deviation = float(np.std(values, ddof=1))
    return float(np.mean(values) / deviation * math.sqrt(TRADING_DAYS)) if deviation else 0.0


def _measure(curves: list[SleeveCurve]) -> dict:
    """Measure through the PRODUCTION combiner, not a pandas join.

    The first version of this script aligned the curves with `pd.DataFrame(...).dropna()`, which
    discards every day on which ANY sleeve is absent -- every weekend for the 24/7 crypto sleeve,
    and every equity holiday. That is the calendar-alignment defect this repository has already
    documented once (a concat/dropna join dropped 36.5% of a sleeve's returns), and it is why the
    naive measurement disagreed with the published figure. `combine_book` aligns to a contiguous
    epoch-day index and treats an absent day as a FLAT day, which is what it is, and computes
    pairwise correlation on days where both sleeves are genuinely active.
    """
    book = combine_book(curves, scheme="equal_risk")
    per_sleeve = {
        name: _sharpe(values[values != 0.0]) for name, values in book.sleeve_returns.items()
    }
    pairs = {f"{a}|{b}": value for (a, b), value in book.corr.items() if not math.isnan(value)}
    s_bar = float(np.mean(list(per_sleeve.values())))
    rho_bar = float(np.mean(list(pairs.values()))) if pairs else float("nan")
    return {
        "sleeves": list(book.names),
        "n": len(book.names),
        "per_sleeve_sharpe": per_sleeve,
        "s_bar": s_bar,
        "pairwise_correlations": pairs,
        "rho_bar": rho_bar,
        "book_sharpe_equal_risk": book.sharpe,
        "book_max_drawdown": book.maxdd,
        "book_vol": book.vol,
        "diversification_ratio": book.diversification_ratio,
        "n_days": book.n_days,
        "projected_book_sharpe_at_14_sleeves": s_bar
        * math.sqrt(TARGET_N / (1.0 + (TARGET_N - 1) * rho_bar)),
        "rho_bar_required_at_14": {
            str(t): ((s_bar**2 * TARGET_N) / t**2 - 1) / (TARGET_N - 1) for t in TARGETS
        },
        "s_bar_required_at_14_at_this_rho": {
            str(t): t / math.sqrt(TARGET_N / (1.0 + (TARGET_N - 1) * rho_bar)) for t in TARGETS
        },
    }


def main() -> int:
    curves = []
    for name, rel in CURVES.items():
        path = REPO / rel
        if not path.exists():
            print(f"missing curve for {name}; refusing to measure a partial book")
            return 1
        curves.append(_curve(name, path))

    with_av = _measure(curves)
    without_av = _measure([c for c in curves if c.name != "AlphaVintage"])
    aligned_days = with_av["n_days"]

    result = {
        "schema": "canli.alphac-book-without-alphavintage.v1",
        "claim_boundary": (
            "A measurement of two allocations on one common window, both reported. Opens no new "
            "data, registers no hypothesis identity, changes no allocation and recommends "
            "nothing. 0 trials."
        ),
        "common_window_days": aligned_days,
        "alignment": (
            "alphaforge.portfolio.book.combine_book, the production path: contiguous epoch-day "
            "index, an absent day treated as FLAT, pairwise correlation on days where both "
            "sleeves are genuinely active."
        ),
        "window_note": (
            "Bounded by the BLESSED research curves, which are frozen by disclosure protocol and "
            "end 2026-06-01 by design. This is not the live record and cannot be extended by "
            "re-running anything."
        ),
        "with_alphavintage": with_av,
        "without_alphavintage": without_av,
        "deltas": {
            "s_bar": without_av["s_bar"] - with_av["s_bar"],
            "rho_bar": without_av["rho_bar"] - with_av["rho_bar"],
            "book_sharpe_equal_risk": (
                without_av["book_sharpe_equal_risk"] - with_av["book_sharpe_equal_risk"]
            ),
            "book_max_drawdown": (
                without_av["book_max_drawdown"] - with_av["book_max_drawdown"]
            ),
            "projected_book_sharpe_at_14_sleeves": (
                without_av["projected_book_sharpe_at_14_sleeves"]
                - with_av["projected_book_sharpe_at_14_sleeves"]
            ),
        },
        "what_this_does_not_settle": (
            "Removing a sleeve raises s_bar mechanically whenever the sleeve is below average, "
            "and that is not evidence the remaining sleeves are better. It also measures both "
            "allocations on the window used to compare them, which is in-sample by construction "
            "for the comparison itself. The drawdown and correlation effects are the parts that "
            "carry information; the s_bar arithmetic is bookkeeping."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  aligned through combine_book: {aligned_days} days")
    for label, book in (("WITH AlphaVintage", with_av), ("WITHOUT", without_av)):
        print(f"\n  {label}  (N={book['n']})")
        print(f"    s_bar {book['s_bar']:+.4f} | rho_bar {book['rho_bar']:+.4f}")
        print(f"    equal-risk book Sharpe {book['book_sharpe_equal_risk']:+.4f} | "
              f"maxDD {book['book_max_drawdown']:+.4f} | "
              f"div ratio {book['diversification_ratio']:.4f}")
        print(f"    projected at 14 sleeves: {book['projected_book_sharpe_at_14_sleeves']:.4f}")
    d = result["deltas"]
    print(f"\n  REMOVING IT: s_bar {d['s_bar']:+.4f} | rho_bar {d['rho_bar']:+.4f} | "
          f"book Sharpe {d['book_sharpe_equal_risk']:+.4f} | maxDD {d['book_max_drawdown']:+.4f}")
    print(f"  projected 14-sleeve book: {d['projected_book_sharpe_at_14_sleeves']:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
