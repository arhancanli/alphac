"""Effective independent bets: how many distinct ideas a book of sleeves really holds.

Book Sharpe grows with the square root of independent bets, not of sleeves, so every sleeve count is
reported beside these numbers (LONG_TERM_PLAN, rule 1: count ideas, not sleeves). Three levels:

- sleeves: the participation ratio of the sleeve correlation matrix;
- families: each family's sleeves averaged into one book, then the same ratio across family books;
- ideas: families joined while their books correlate at or above a threshold (average linkage).

The participation ratio (sum of eigenvalues)^2 / sum of squared eigenvalues equals n for n uncorrelated
series and 1 for n copies of one series. Flipping a series' sign leaves it unchanged, so short and long
versions of an idea count once.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.effective_bets --mode search
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = HERE.parents[1] / "var" / "breadth_lab"


def participation(cm: np.ndarray) -> float:
    filled = np.nan_to_num(cm, nan=0.0)
    np.fill_diagonal(filled, 1.0)
    eig = np.clip(np.linalg.eigvalsh(filled), 0, None)
    return float(eig.sum() ** 2 / (eig ** 2).sum())


def weekly_corr(returns: pd.DataFrame, min_weeks: int = 104) -> pd.DataFrame:
    weekly = returns.resample("W-FRI").sum(min_count=3)
    return weekly.corr(min_periods=min_weeks)


def idea_clusters(cm: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Average-linkage clusters on |correlation|: two groups merge while their mean |corr| is >= threshold."""
    a = cm.abs().fillna(0.0).to_numpy()
    groups = [[i] for i in range(len(cm))]
    while len(groups) > 1:
        best, pair = -1.0, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                link = float(a[np.ix_(groups[i], groups[j])].mean())
                if link > best:
                    best, pair = link, (i, j)
        if best < threshold:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    names = list(cm.columns)
    return sorted(([names[k] for k in g] for g in groups), key=len, reverse=True)


def report(sleeves: pd.DataFrame, family_of: dict[str, str], threshold: float = 0.5) -> dict:
    families = sorted(set(family_of[c] for c in sleeves.columns))
    books = pd.DataFrame({f: sleeves[[c for c in sleeves.columns if family_of[c] == f]].mean(axis=1, skipna=True)
                          for f in families})
    sleeve_cm = weekly_corr(sleeves)
    book_cm = weekly_corr(books)
    off = book_cm.to_numpy()[~np.eye(len(families), dtype=bool)]
    clusters = idea_clusters(book_cm, threshold)
    return {
        "sleeves": int(sleeves.shape[1]),
        "families": len(families),
        "effective_bets_sleeves": round(participation(sleeve_cm.to_numpy()), 1),
        "effective_bets_families": round(participation(book_cm.to_numpy()), 1),
        "family_avg_abs_corr": round(float(np.nanmean(np.abs(off))), 3) if off.size else None,
        "ideas": len(clusters),
        "idea_threshold_abs_corr": threshold,
        "idea_members": clusters,
    }


def stock_sleeves(mode: str) -> tuple[pd.DataFrame, dict[str, str]]:
    frozen = json.loads((HERE / "frozen_selection.json").read_text())
    signals = sorted(frozen["stocks"]["signals"])
    missing = [s for s in signals if not (CACHE / mode / f"{s}.net.parquet").exists()]
    if missing:
        raise SystemExit(f"no {mode} sleeve returns for {missing}")
    sleeves = pd.concat([pd.read_parquet(CACHE / mode / f"{s}.net.parquet") for s in signals], axis=1).astype("float64")
    return sleeves, {c: c.split("|", 1)[0] for c in sleeves.columns}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="search", choices=["search", "test"])
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--out")
    a = ap.parse_args()
    sleeves, family_of = stock_sleeves(a.mode)
    out = {"block": "stocks", "mode": a.mode, "families_are": "signals (frozen selection)",
           **report(sleeves, family_of, a.threshold)}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
