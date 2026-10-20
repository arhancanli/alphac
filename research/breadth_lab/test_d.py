"""Variant D's one test (PROTOCOL amendment 13): the design frozen on all search years, run on the years the
search never saw. ``--freeze`` writes frozen_variant_d.json from search years only; the test refuses to run
unless that file's sha256 is the one PROTOCOL.md recorded before the test years were opened.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.test_d --freeze
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.test_d
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import pods, round4
from research.breadth_lab.lab import TARGET_VOL, context, stats
from research.breadth_lab.panel import Panel

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen_variant_d.json"
TEST = ("2018-01-01", "2026-06-18")
FIT = ("1998-01-01", "2007-12-31")


def library() -> list[str]:
    """The 52 signals of rounds 1-2."""
    new = {f"{n}_s" for n in round4.NEW}
    return [n for n in pods.signals() if n not in new]


def _scale(c, pos: pd.DataFrame, hedge: pd.Series) -> pd.Series:
    from research.breadth_lab.book import MAX_BOOK_LEVERAGE, account
    net0, _, _ = account(c, pos, hedge)
    target = (TARGET_VOL / (net0.rolling(126, min_periods=63).std() * np.sqrt(252))).clip(upper=MAX_BOOK_LEVERAGE)
    return target.where(target.index.isin(c.month_ends)).ffill().shift(2)


def freeze() -> dict:
    from research.breadth_lab.book import account
    from research.breadth_lab.netting_law import full_share
    t0 = time.time()
    names = library()
    built = json.loads((pods.OUT / "signs.json").read_text())
    own = {n: pods.sign_on(n, *pods.SEARCH) for n in names}
    share = full_share(pods.SEARCH, own)
    print("netted_share_1998_2017", round(share, 4), flush=True)
    net = pods.candidates(*pods.SEARCH)
    net = net[[k for k in net.columns if k.split("|")[0] in own]]
    gross = pods.candidates(*pods.SEARCH, tag="gross").reindex(columns=net.columns)
    flip = pd.Series([own[k.split("|")[0]] * built[k.split("|")[0]] for k in net.columns], index=net.columns).astype("float32")
    cost = gross - net
    gross = gross.mul(flip, axis=1)
    net, judged = gross - cost, gross - share * cost
    del cost
    a1, _, pods1, _ = pods.admit_families(net, pods.SEARCH, judged, signed=True)
    cols = list(net.columns[a1])
    pod = pd.Series([pods1[k.split("|")[0]] for k in cols], index=cols)
    count = pod.value_counts()
    books = pd.DataFrame({p: judged[pod.index[pod == p]].astype("float64").mean(axis=1) for p in sorted(pod.unique())})
    check = {}
    for lam in pods.SHRINKS:
        w = pods.diversified(books.loc[FIT[0]:FIT[1]], lam)
        check[lam] = stats(pods._scaled(books.fillna(0.0).mul(w, axis=1).sum(axis=1)).loc[pods.SECOND[0]:pods.SECOND[1]]).get("sharpe")
        print(f"validation_shrink_{lam:g}", json.dumps({"run_2008_2017_sharpe": check[lam]}), flush=True)
    shrink = max(check, key=lambda k: check[k])
    wpod = pods.diversified(books, shrink)
    weight = {k: float(wpod[pod[k]]) / int(count[pod[k]]) for k in cols}
    del net, gross, judged
    c = context(Panel("search"))
    pos, hedge = pods._positions(c, cols, weight, own)
    scale = _scale(c, pos, hedge)
    options = {f"{'edge' if e else 'target'}_{b:g}": (b, e) for b, e in pods.BAND_GRID}
    grid = {}
    for key, (band, edge) in options.items():
        n, _, expo = account(c, pos, hedge, scale, band, edge)
        grid[key] = {"search_years_net": stats(n.where(scale.notna())), **expo}
        print(f"grid_{key}", json.dumps(grid[key]), flush=True)
    best = max(grid, key=lambda k: grid[k]["search_years_net"].get("sharpe", -9.0))
    frozen = {"protocol": "PROTOCOL.md amendment 13", "chosen_on": f"{pods.SEARCH[0]}..{pods.SEARCH[1]}", "library": names,
              "signs": own, "netted_share": round(share, 6), "families": len({pods.family_of(k) for k in cols}),
              "pods": int(pod.nunique()), "validation_2008_2017": {str(k): v for k, v in check.items()}, "shrink": shrink,
              "pod_capital": {str(p): round(float(x), 6) for p, x in wpod.items()}, "band_grid_1998_2017": grid,
              "band": {"name": best, "width": options[best][0], "edge": options[best][1]},
              "sleeves": cols, "weights": {k: weight[k] for k in cols}, "seconds": round(time.time() - t0)}
    FROZEN.write_text(json.dumps(frozen, indent=1, sort_keys=True))
    print("frozen", len(cols), "sleeves", "sha256", hashlib.sha256(FROZEN.read_bytes()).hexdigest(), flush=True)
    return frozen


def recorded_sha256() -> str:
    m = re.search(r"frozen_variant_d\.json sha256 ([0-9a-f]{64})", (HERE / "PROTOCOL.md").read_text())
    if not m:
        raise SystemExit("PROTOCOL.md records no frozen variant D: freeze first.")
    return m.group(1)


def main() -> dict:
    from research.breadth_lab.book import account
    sha = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if sha != recorded_sha256():
        raise SystemExit(f"frozen_variant_d.json is {sha}, not the sha256 PROTOCOL.md recorded: refusing to open the test years.")
    f = json.loads(FROZEN.read_text())
    c = context(Panel("test"))
    pos, hedge = pods._positions(c, f["sleeves"], f["weights"], f["signs"])
    scale = _scale(c, pos, hedge)
    n, g, expo = account(c, pos, hedge, scale, float(f["band"]["width"]), bool(f["band"]["edge"]))
    n, g = n.where(scale.notna()), g.where(scale.notna())
    t = n.loc[TEST[0]:TEST[1]]
    out = {"frozen_variant_d_sha256": sha, "sleeves": len(f["sleeves"]), "families": f["families"], "pods": f["pods"],
           "test_years": TEST, "test": stats(t), "test_before_costs": stats(g.loc[TEST[0]:TEST[1]]),
           "by_year": {str(y): stats(x).get("sharpe") for y, x in t.groupby(t.index.year)},
           "search_years_same_code": stats(n.loc[:pods.SEARCH[1]]), **expo}
    n.to_frame("net").to_parquet(pods.OUT / "variant_d_test_net.parquet")
    (HERE / "test_variant_d.json").write_text(json.dumps(out, indent=1))
    print("test", json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    freeze() if a.freeze else main()
