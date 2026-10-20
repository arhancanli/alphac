"""Round 5 of the breadth lab (PROTOCOL amendment 11): admission rules compared by a nested check inside the
selection years. Families are chosen on 1998-2002 alone and the netted account runs on 2003-2007, on a panel
cut at 2007-12-31, so nothing after 2007 enters any number.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.nested
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import lab, pods, round4
from research.breadth_lab.effective_bets import weekly_corr
from research.breadth_lab.lab import TARGET_VOL, context, stats
from research.breadth_lab.panel import Panel

HERE = Path(__file__).resolve().parent
CHOOSE = ("1998-01-01", "2002-12-31")
CHECK = ("2003-01-01", "2007-12-31")
HALVES = (("1998-01-01", "2000-06-30"), ("2000-07-01", "2002-12-31"))
END = "2007-12-31"
BAR = 0.3
BAND, EDGE = 0.75, True
RULES = ("bar", "both_halves", "t2", "shrunk", "idea_first", "everything", "bar_52")


def cut_context(end: str = END):
    """The engine's context on a panel that ends on ``end``."""
    p = Panel("search")
    keep = p.dates <= pd.Timestamp(end, tz=p.dates.tz)
    for a in ("total", "overnight", "intraday", "close", "dollar_volume"):
        setattr(p, a, getattr(p, a).loc[keep])
    p.dates = p.dates[keep]
    return context(p)


def family_scores(judged: pd.DataFrame, fam: pd.Series, halves: tuple = HALVES) -> pd.DataFrame:
    """Per family: its book's Sharpe at marginal cost on the choosing years, in each half, and its years of data."""
    rows = {}
    for f, cols in fam.groupby(fam).groups.items():
        b = lab.book(judged[cols].astype("float64"))
        rows[f] = {"sharpe": stats(b).get("sharpe", np.nan), "h1": stats(b.loc[halves[0][0]:halves[0][1]]).get("sharpe", np.nan),
                   "h2": stats(b.loc[halves[1][0]:halves[1][1]]).get("sharpe", np.nan), "years": b.dropna().shape[0] / 252.0}
    return pd.DataFrame(rows).T.astype("float64")


def chosen_by(rule: str, sc: pd.DataFrame, judged: pd.DataFrame, fam: pd.Series, pod_of_signal: dict[str, int]) -> dict[str, float]:
    """The families a rule admits, each with the score that orders it inside its pod."""
    s = sc["sharpe"]
    if rule in ("bar", "bar_52"):
        keep = s >= BAR
    elif rule == "both_halves":
        keep = (s >= BAR) & (sc["h1"] > 0) & (sc["h2"] > 0)
    elif rule == "t2":
        keep = s * np.sqrt(sc["years"]) >= 2.0
    elif rule == "shrunk":
        noise = 1.0 / sc["years"]
        tau2 = max(float(s.var() - noise.mean()), 1e-4)
        s = s.mean() + tau2 / (tau2 + noise) * (s - s.mean())
        keep = s >= BAR
    elif rule == "idea_first":
        pod = pd.Series({f: pod_of_signal[f.split("|")[0]] for f in sc.index})
        good = []
        for p, fs in pod.groupby(pod).groups.items():
            book = pd.DataFrame({f: lab.book(judged[fam.index[fam == f]].astype("float64")) for f in fs}).mean(axis=1)
            if stats(book).get("sharpe", -9.0) >= BAR:
                good.append(p)
        keep = pod.isin(good) & (s > 0)
    elif rule == "everything":
        keep = s.notna()
    else:
        raise ValueError(rule)
    return {f: float(s[f]) for f in sc.index[keep.fillna(False).to_numpy()]}


def main(choose: tuple[str, str] = CHOOSE, check: tuple[str, str] = CHECK, end: str = END, rules: tuple[str, ...] = RULES,
         share: float | None = None, out: str = "round5_nested.json", protocol: str = "PROTOCOL.md amendment 11") -> dict:
    """The nested check; with other windows, the chosen rule's run on 2008-2017 (amendment 11's last step)."""
    from research.breadth_lab.book import MAX_BOOK_LEVERAGE, account
    from research.breadth_lab.netting_law import full_share
    t0 = time.time()
    built = json.loads((pods.OUT / "signs.json").read_text())
    own = {n: pods.sign_on(n, *choose) for n in pods.signals()}
    if share is None:
        share = full_share(choose, own)
    print(f"netted_share_{choose[0][:4]}_{choose[1][:4]}", round(share, 4), flush=True)
    mid = pd.Timestamp(choose[0]) + (pd.Timestamp(choose[1]) - pd.Timestamp(choose[0])) / 2
    halves = ((choose[0], str(mid.date())), (str((mid + pd.Timedelta(days=1)).date()), choose[1]))
    net = pods.candidates(*choose)
    gross = pods.candidates(*choose, tag="gross").reindex(columns=net.columns)
    flip = pd.Series([own[k.split("|")[0]] * built[k.split("|")[0]] for k in net.columns], index=net.columns).astype("float32")
    cost = gross - net
    gross = gross.mul(flip, axis=1)
    net, judged = gross - cost, gross - share * cost
    del cost, gross
    fam = pd.Series([pods.family_of(k) for k in net.columns], index=net.columns)
    sc = family_scores(judged, fam, halves)
    rho = pods.approx_corr(net.resample("W-FRI").sum(min_count=3))
    pod_of_signal = pods.pods_of(net)
    pod = np.array([pod_of_signal[k.split("|")[0]] for k in net.columns])
    position = {k: i for i, k in enumerate(net.columns)}
    new = {f"{n}_s" for n in round4.NEW}
    print("candidates", net.shape[1], "families", len(sc), "pods", int(pod.max()) + 1, f"{time.time() - t0:.0f}s", flush=True)
    selections = {}
    for rule in rules:
        chosen = chosen_by(rule, sc, judged, fam, pod_of_signal)
        if rule == "bar_52":
            chosen = {f: v for f, v in chosen.items() if f.split("|")[0] not in new}
        queues = []
        for p in range(pod.max() + 1):
            fams = sorted((f for f in chosen if pod_of_signal[f.split("|")[0]] == p), key=lambda f: -chosen[f])
            queues.append([position[k] for f in fams for k in fam.index[fam == f]])
        cols = list(net.columns[pods._greedy(queues, rho, pod, np.ones(len(pod), dtype=bool))])
        selections[rule] = cols
        print(rule, "families", len(chosen), "sleeves", len(cols), flush=True)
    standalone = net
    del judged
    c = cut_context(end)
    result = {"protocol": protocol, "chosen_on": f"{choose[0]}..{choose[1]}", "checked_on": f"{check[0]}..{check[1]}",
              "netted_share": round(share, 4), "candidates": int(net.shape[1]), "candidate_families": len(sc), "rules": {}}
    for rule, cols in selections.items():
        if not cols:
            result["rules"][rule] = {"sleeves": 0}
            continue
        pod_s = pd.Series([pod_of_signal[k.split("|")[0]] for k in cols], index=cols)
        books = pd.DataFrame({p: standalone[pod_s.index[pod_s == p]].astype("float64").mean(axis=1) for p in sorted(pod_s.unique())})
        pc = weekly_corr(books).fillna(0.0).to_numpy()
        wpod = pd.Series(1.0 / (1.0 + (pc.sum(axis=1) - 1.0) / max(len(pc) - 1, 1)), index=books.columns)
        wpod = wpod / wpod.sum()
        count = pod_s.value_counts()
        weight = {k: float(wpod[pod_s[k]]) / int(count[pod_s[k]]) for k in cols}
        pos, hedge = pods._positions(c, cols, weight, own)
        net0, _, _ = account(c, pos, hedge)
        target = (TARGET_VOL / (net0.rolling(126, min_periods=63).std() * np.sqrt(252))).clip(upper=MAX_BOOK_LEVERAGE)
        scale = target.where(target.index.isin(c.month_ends)).ffill().shift(2)
        n, g, expo = account(c, pos, hedge, scale, BAND, EDGE)
        n, g = n.where(scale.notna()), g.where(scale.notna())
        result["rules"][rule] = {"families": len({pods.family_of(k) for k in cols}), "sleeves": len(cols), "pods": int(pod_s.nunique()),
                                 "new_signal_sleeves": int(sum(k.split("|")[0] in new for k in cols)),
                                 "chosen_years_net": stats(n.loc[choose[0]:choose[1]]), "check_years_net": stats(n.loc[check[0]:check[1]]),
                                 "check_years_before_costs": stats(g.loc[check[0]:check[1]]), **expo}
        print(f"rule_{rule}", json.dumps(result["rules"][rule]), flush=True)
        del pos, hedge
    result["seconds"] = round(time.time() - t0)
    (HERE / out).write_text(json.dumps(result, indent=1))
    return result


def split_run() -> dict:
    """Amendment 11's last step: the rule with the best 2003-2007 record, chosen on 1998-2007, run on 2008-2017.
    The 1998-2007 netted share for this library and these signs is round 4's (the same computation)."""
    nested = json.loads((HERE / "round5_nested.json").read_text())["rules"]
    best = max(nested, key=lambda r: nested[r].get("check_years_net", {}).get("sharpe", -9.0))
    share = json.loads((HERE / "round4_d_rules.json").read_text())["netted_share_used"]
    print("carried_rule", best, flush=True)
    return main(pods.FIRST, pods.SECOND, pods.SECOND[1], (best,), share, "round5_split.json", "PROTOCOL.md amendment 11 (the chosen rule on 2008-2017)")


if __name__ == "__main__":
    import sys
    split_run() if "--split" in sys.argv else main()
