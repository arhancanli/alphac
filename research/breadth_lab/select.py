"""Selection rules for the combined book, compared on the search years.

Every rule is judged twice: on all search years, and as a split inside them (choose on 1998-2007, score
on 2008-2017), because a rule that only works on the years it chose from is the failure this lab
exists to catch.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.select
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from research.breadth_lab import book as bk
from research.breadth_lab.lab import SIGNALS, context, stats
from research.breadth_lab.panel import CACHE, Panel

FIRST = ("1998-01-01", "2007-12-31")
SECOND = ("2008-01-01", "2017-12-31")


VARIANTS = [s for s in SIGNALS if not s.endswith("_s")]


def sleeve_frame(mode: str, tag: str) -> pd.DataFrame:
    frames = [pd.read_parquet(CACHE / mode / f"{s}.{tag}.parquet") for s in VARIANTS]
    return pd.concat(frames, axis=1).astype("float64")


def sharpe(x: pd.DataFrame) -> pd.Series:
    return x.mean() / x.std() * np.sqrt(252)


def choose(gross: pd.DataFrame, net: pd.DataFrame, rule: dict) -> list[tuple[str, str, int]]:
    """A rule picks signs per signal and then sleeves, from the frames it is given (one period)."""
    by_signal = {s: [c for c in gross.columns if c.startswith(s + "|")] for s in VARIANTS}
    book_pre = {s: sharpe(gross[cols].mean(axis=1).to_frame()).iloc[0] for s, cols in by_signal.items()}
    out = []
    for s, cols in by_signal.items():
        sign = 1 if book_pre[s] >= 0 else -1
        if rule.get("no_flip") and sign < 0:
            continue
        if abs(book_pre[s]) < rule.get("min_signal_pre", 0.0):
            continue
        if s in rule.get("exclude", ()):
            continue
        sr = sharpe(sign * gross[cols])
        for c in cols:
            if rule.get("sleeve_positive") and not (sr[c] > 0):
                continue
            out.append((s, c.split("|", 1)[1], sign))
    return out


RULES = {
    "all_signals_signed": {},
    "all_signals_no_flip": {"no_flip": True},
    "signals_pre_0.3": {"min_signal_pre": 0.3},
    "signals_pre_0.5": {"min_signal_pre": 0.5},
    "signals_pre_0.5_no_flip": {"min_signal_pre": 0.5, "no_flip": True},
    "signals_pre_0.3_positive_sleeves": {"min_signal_pre": 0.3, "sleeve_positive": True},
    "signals_pre_0.5_no_weekly": {"min_signal_pre": 0.5, "exclude": ("rev_1w",)},
}


def main(variants: str = "base", rules: list[str] | None = None, tag: str = "") -> None:
    global VARIANTS
    VARIANTS = [s for s in SIGNALS if s.endswith("_s") == (variants == "smoothed")] if variants != "both" else list(SIGNALS)
    t0 = time.time()
    c = context(Panel("search"))
    gross, net = sleeve_frame("search", "gross"), sleeve_frame("search", "net")
    print(f"{gross.shape[1]} sleeves loaded ({time.time() - t0:.0f}s)", flush=True)
    results = {}
    for name, rule in RULES.items():
        if rules and name not in rules:
            continue
        full = choose(gross, net, rule)
        b = bk.book(c, "search", full)
        first = choose(gross.loc[FIRST[0]:FIRST[1]], net.loc[FIRST[0]:FIRST[1]], rule)
        b1 = bk.book(c, "search", first)
        out_of_half = stats(b1["_net"].loc[SECOND[0]:SECOND[1]])
        results[name] = {"sleeves": len(full), "signals": len({s for s, _, _ in full}), "net": b["net"], "before_costs": b["before_costs"].get("sharpe"),
                         "gross_exposure": b["mean_gross_exposure"], "turnover": b["turnover_per_year"], "cost_per_year": b["cost_per_year"],
                         "chosen_on_first_half_scored_on_second": out_of_half, "sleeves_chosen_on_first_half": len(first)}
        print(name, json.dumps(results[name]), flush=True)
    (CACHE / "search" / f"selection_rules{tag}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="base", choices=["base", "smoothed", "both"])
    ap.add_argument("--rules", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    main(a.variants, a.rules.split(",") if a.rules else None, a.tag)
