"""The netting law (PROTOCOL amendment 7): how much of what sleeves pay one by one an account pays.

Each round-3 candidate sleeve's stock positions (its cell weights times its own leverage, held
between rebalances) are sampled weekly. For random sets of K sleeves at equal weight, the summed
standalone cost is compared with the cost of trading the summed positions as one account. Costs
only, search years only; nothing is selected.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.netting_law
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import lab, pods
from research.breadth_lab.lab import context, hedge_and_scale, sleeve_returns, smoothed
from research.breadth_lab.panel import Panel

HERE = Path(__file__).resolve().parent
KS = (10, 30, 100, 300, 1000, 3000)
REPEATS = {10: 20, 30: 20, 100: 20, 300: 5, 1000: 5, 3000: 2}
SEED = 20261020


def sleeve_positions(years: tuple[str, str] = pods.SEARCH) -> tuple[list[str], list[np.ndarray], list[np.ndarray], np.ndarray, int]:
    """Per sleeve: the column indices of its names and its weekly positions in them; weekly cost per name."""
    keep = set(pods.candidates(*years).columns)
    pods.signals()
    c = context(Panel("search"))
    weeks = c.week_ends[c.week_ends.isin(c.r.index)]
    weeks = weeks[(weeks >= pd.Timestamp(years[0], tz=weeks.tz)) & (weeks <= pd.Timestamp(years[1], tz=weeks.tz))]
    cost = c.cost.reindex(weeks).to_numpy(dtype="float32")
    cells = {"ind48": (c, None), "ind48xL": (c, "L"), "ind48xS": (c, "S"),
             "ind150": (dataclasses.replace(c, bucket=c.p.meta["industry"]), None)}
    signs = json.loads((pods.OUT / "signs.json").read_text())
    names: list[str] = []
    index: list[np.ndarray] = []
    held: list[np.ndarray] = []
    for name in pods.signals():
        fn, freq = lab.SIGNALS[name]
        sig = fn(c) * signs[name]
        dates = c.month_ends if freq == "M" else c.week_ends
        dates = dates[dates.isin(c.r.index)]
        for scheme in pods.SCHEMES:
            cc, half = cells[scheme]
            wr = smoothed(cc, pods.cell_weights(cc, sig, dates, half), lab.SMOOTH.get(name, 1))
            _, lev, _ = hedge_and_scale(cc, sleeve_returns(cc, wr, before_costs=True), parts=True)
            on = pd.Series(np.nan, index=c.r.index)
            on.loc[wr.index] = 1.0
            lev = lev.reindex(c.r.index).where(on.notna(), axis=0).ffill().reindex(weeks).fillna(0.0)
            w = wr.reindex(c.r.index).ffill().reindex(weeks).fillna(0.0)
            bucket = cc.bucket.reindex(c.r.columns)
            for cell in lev.columns:
                col = f"{name}|{scheme}|{cell}"
                if col not in keep:
                    continue
                idx = np.flatnonzero((bucket == cell).to_numpy())
                pos = w.iloc[:, idx].to_numpy() * lev[cell].to_numpy()[:, None]
                # Only the names the sleeve ever held, at half precision: costs need no more.
                nz = np.flatnonzero(np.abs(pos).sum(axis=0) > 0)
                names.append(col)
                index.append(idx[nz])
                held.append(pos[:, nz].astype("float16"))
        print(name, len(names), flush=True)
    return names, index, held, cost, c.r.shape[1]


def costs(members: np.ndarray, index: list[np.ndarray], held: list[np.ndarray], cost: np.ndarray, width: int) -> tuple[float, float]:
    """Annual cost of the K sleeves paid one by one, and paid as one account, at weight 1/K each."""
    k = len(members)
    account = np.zeros((cost.shape[0], width), dtype="float32")
    alone = 0.0
    for i in members:
        p = held[i].astype("float32") / k
        alone += float((np.abs(np.diff(p, axis=0)) * cost[1:, index[i]]).sum())
        account[:, index[i]] += p
    netted = float((np.abs(np.diff(account, axis=0)) * cost[1:]).sum())
    years = (cost.shape[0] - 1) / 52.0
    return alone / years, netted / years


def full_share(years: tuple[str, str]) -> float:
    """The netted share for all candidate sleeves with three years of data in ``years`` (one draw)."""
    names, index, held, cost, width = sleeve_positions(years)
    alone, netted = costs(np.arange(len(names)), index, held, cost, width)
    return netted / alone


def main() -> None:
    t0 = time.time()
    names, index, held, cost, width = sleeve_positions()
    n = len(names)
    rng = np.random.default_rng(SEED)
    rows = []
    for k in (*KS, n):
        for _ in range(REPEATS.get(k, 1)):
            members = rng.choice(n, size=k, replace=False) if k < n else np.arange(n)
            alone, netted = costs(members, index, held, cost, width)
            rows.append({"k": int(k), "alone_per_year": alone, "netted_per_year": netted, "netted_share": netted / alone})
        sub = [r for r in rows if r["k"] == k]
        print(k, json.dumps({"netted_share_mean": round(float(np.mean([r["netted_share"] for r in sub])), 4),
                             "alone_per_year": round(float(np.mean([r["alone_per_year"] for r in sub])), 4),
                             "netted_per_year": round(float(np.mean([r["netted_per_year"] for r in sub])), 4)}), flush=True)
    by_k = pd.DataFrame(rows).groupby("k")["netted_share"].mean()
    slope = float(np.polyfit(np.log(by_k.index.to_numpy(dtype=float)), np.log(by_k.to_numpy()), 1)[0])
    result = {"protocol": "PROTOCOL.md amendment 7", "sleeves": n, "years": f"{pods.SEARCH[0]}..{pods.SEARCH[1]}",
              "netted_share_by_k": {str(k): round(float(v), 4) for k, v in by_k.items()},
              "slope_log_share_on_log_k": round(slope, 3), "draws": rows, "seconds": round(time.time() - t0)}
    (HERE / "netting_law.json").write_text(json.dumps(result, indent=1))
    print("law", json.dumps({k: v for k, v in result.items() if k != "draws"}), flush=True)


if __name__ == "__main__":
    main()
