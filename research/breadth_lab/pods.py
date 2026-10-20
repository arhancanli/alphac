"""Round 3 of the breadth lab (PROTOCOL amendment 4): pods and flexible, correlation-first admission.

Every overlapping-portfolio stock signal of rounds 1-2 is built in four cell schemes (the 48
industries, each industry's larger and smaller names, and Sharadar's 150 industries). Signals are
grouped into pods (one idea each); sleeves are admitted when they pay for themselves and barely
move with what is already admitted; a central layer weights the pods and can brake a falling one.
Search years only.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.pods --build
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.pods --select
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import lab, round2
from research.breadth_lab.effective_bets import idea_clusters, participation, weekly_corr
from research.breadth_lab.lab import TARGET_VOL, Ctx, context, hedge_and_scale, sleeve_returns, smoothed, stats
from research.breadth_lab.panel import CACHE, Panel

HERE = Path(__file__).resolve().parent
OUT = CACHE / "pods"
SCHEMES = ("ind48", "ind48xL", "ind48xS", "ind150")
MIN_CELL = 6
NEAR_DUP = 0.5
BOOK_CORR = 0.05
MIN_WEEKS = 104
POD_JOIN = 0.5
BRAKE_HALF, BRAKE_FLAT = 0.05, 0.075
SEARCH = ("1998-01-01", "2017-12-31")
FIRST = ("1998-01-01", "2007-12-31")
SECOND = ("2008-01-01", "2017-12-31")


def signals() -> list[str]:
    round2.register()
    return sorted(n for n in lab.SIGNALS if n.endswith("_s"))


def signal_sign(name: str) -> int:
    """Round 1's rule: sign each signal by its search-year book Sharpe before costs (48 industries)."""
    gross = pd.read_parquet(CACHE / "search" / f"{name}.gross.parquet").astype("float64")
    return 1 if stats(lab.book(gross)).get("sharpe", 0.0) >= 0 else -1


def cell_weights(c: Ctx, signal: pd.DataFrame, dates: pd.DatetimeIndex, half: str | None) -> pd.DataFrame:
    """Rank-demeaned, gross-1 weights inside each cell; a half keeps an industry's larger or smaller names."""
    rows = []
    for d in dates:
        s = signal.loc[d].where(c.eligible.loc[d]).dropna()
        g = c.bucket.reindex(s.index)
        s, g = s[g.notna()], g[g.notna()]
        if half is not None and not s.empty:
            adv = c.adv.loc[d, s.index]
            med = adv.groupby(g).transform("median")
            keep = (adv >= med) if half == "L" else (adv < med)
            s, g = s[keep], g[keep]
        n = g.map(g.value_counts())
        s, g = s[n >= MIN_CELL], g[n >= MIN_CELL]
        if s.empty:
            rows.append(pd.Series(dtype="float64", name=d))
            continue
        x = s.groupby(g).rank(pct=True)
        x = x - x.groupby(g).transform("mean")
        x = x / x.abs().groupby(g).transform("sum")
        rows.append(x.rename(d))
    return pd.DataFrame(rows).reindex(columns=c.r.columns).fillna(0.0)


def build(only: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    c = context(Panel("search"))
    print(f"context {time.time() - t0:.0f}s", flush=True)
    cells = {"ind48": (c, None), "ind48xL": (c, "L"), "ind48xS": (c, "S"),
             "ind150": (dataclasses.replace(c, bucket=c.p.meta["industry"]), None)}
    signs = {}
    for name in signals():
        if only and name not in only:
            continue
        todo = [k for k in SCHEMES if not (OUT / f"{name}.{k}.net.parquet").exists()]
        if not todo:
            continue
        t1 = time.time()
        fn, freq = lab.SIGNALS[name]
        signs[name] = signal_sign(name)
        sig = fn(c) * signs[name]
        dates = c.month_ends if freq == "M" else c.week_ends
        dates = dates[dates.isin(c.r.index)]
        for scheme in todo:
            cc, half = cells[scheme]
            w = smoothed(cc, cell_weights(cc, sig, dates, half), lab.SMOOTH.get(name, 1))
            raw = sleeve_returns(cc, w)
            pre, lev, beta = hedge_and_scale(cc, sleeve_returns(cc, w, before_costs=True), parts=True)
            net = (raw - beta.mul(cc.market, axis=0)) * lev
            net.columns = [f"{name}|{scheme}|{b}" for b in net.columns]
            net.astype("float32").to_parquet(OUT / f"{name}.{scheme}.net.parquet")
        print(name, signs[name], f"{time.time() - t1:.0f}s", flush=True)
    path = OUT / "signs.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**merged, **signs}, indent=1, sort_keys=True))


# ---- admission -------------------------------------------------------------------------------------

def candidates(a: str, z: str) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in sorted(OUT.glob("*.net.parquet"))]
    x = pd.concat(frames, axis=1).astype("float32").loc[a:z]
    return x.loc[:, x.notna().sum() >= 756]


def approx_corr(weekly: pd.DataFrame) -> np.ndarray:
    """Pairwise weekly correlation from each column's own mean and spread; pairs under MIN_WEEKS shared weeks are 0."""
    v = weekly.to_numpy(dtype="float64")
    m = ~np.isnan(v)
    z = (v - np.nanmean(v, axis=0)) / np.nanstd(v, axis=0)
    z = np.where(m, z, 0.0).astype("float32")
    mf = m.astype("float32")
    shared = mf.T @ mf
    rho = (z.T @ z) / np.maximum(shared, 1.0)
    rho[shared < MIN_WEEKS] = 0.0
    np.fill_diagonal(rho, 1.0)
    return np.clip(rho, -1.0, 1.0)


def pods_of(sleeves: pd.DataFrame) -> dict[str, int]:
    """Signals joined while their 48-industry books correlate POD_JOIN or more; one pod per idea."""
    family = {s.split("|")[0] for s in sleeves.columns}
    books = pd.DataFrame({f: sleeves[[k for k in sleeves.columns if k.startswith(f"{f}|ind48|")]].mean(axis=1)
                          for f in sorted(family)})
    groups = idea_clusters(weekly_corr(books), POD_JOIN)
    return {f: i for i, g in enumerate(groups) for f in g}


def admit(sleeves: pd.DataFrame) -> tuple[list[int], np.ndarray, dict[str, int]]:
    sharpe = (sleeves.mean() / sleeves.std() * np.sqrt(252)).to_numpy()
    rho = approx_corr(sleeves.resample("W-FRI").sum(min_count=3))
    pod_of_signal = pods_of(sleeves)
    pod = np.array([pod_of_signal[k.split("|")[0]] for k in sleeves.columns])
    queues = [list(np.flatnonzero(pod == p)[np.argsort(-sharpe[pod == p])]) for p in range(pod.max() + 1)]
    return _greedy(queues, rho, pod, sharpe > 0), rho, pod_of_signal


def _greedy(queues: list[list[int]], rho: np.ndarray, pod: np.ndarray, eligible: np.ndarray) -> list[int]:
    """Pods in turn; a sleeve joins unless it is ineligible, near-duplicates its pod or moves with the book."""
    sum_rho = np.zeros(len(pod))
    max_pod = np.zeros(len(pod))
    admitted: list[int] = []
    while any(queues):
        for q in queues:
            if not q:
                continue
            i = q.pop(0)
            if not eligible[i] or max_pod[i] >= NEAR_DUP:
                continue
            if admitted and sum_rho[i] / len(admitted) >= BOOK_CORR:
                continue
            admitted.append(i)
            sum_rho += rho[:, i]
            same = pod == pod[i]
            max_pod[same] = np.maximum(max_pod[same], np.abs(rho[same, i]))
    return admitted


# ---- variant B (amendment 5): judge the family, keep all of its sleeves ------------------------------

FAMILY_BAR = 0.3


def family_of(col: str) -> str:
    name, scheme, _ = col.split("|", 2)
    return f"{name}|{scheme}"


def sign_on(name: str, a: str, z: str) -> int:
    gross = pd.read_parquet(CACHE / "search" / f"{name}.gross.parquet").astype("float64").loc[a:z]
    return 1 if stats(lab.book(gross)).get("sharpe", 0.0) >= 0 else -1


def admit_families(sleeves: pd.DataFrame, years: tuple[str, str]) -> tuple[list[int], np.ndarray, dict[str, int], dict[str, float]]:
    built = json.loads((OUT / "signs.json").read_text())
    fam = pd.Series([family_of(k) for k in sleeves.columns], index=sleeves.columns)
    agrees = {n: sign_on(n, *years) == built[n] for n in {f.split("|")[0] for f in fam}}
    chosen: dict[str, float] = {}
    for f, cols in fam.groupby(fam).groups.items():
        if not agrees[f.split("|")[0]]:
            continue
        sharpe = stats(lab.book(sleeves[cols].astype("float64"))).get("sharpe")
        if sharpe is not None and sharpe >= FAMILY_BAR:
            chosen[f] = sharpe
    rho = approx_corr(sleeves.resample("W-FRI").sum(min_count=3))
    pod_of_signal = pods_of(sleeves)
    pod = np.array([pod_of_signal[k.split("|")[0]] for k in sleeves.columns])
    position = {k: i for i, k in enumerate(sleeves.columns)}
    queues = []
    for p in range(pod.max() + 1):
        fams = sorted((f for f in chosen if pod_of_signal[f.split("|")[0]] == p), key=lambda f: -chosen[f])
        queues.append([position[k] for f in fams for k in fam.index[fam == f]])
    return _greedy(queues, rho, pod, np.ones(len(pod), dtype=bool)), rho, pod_of_signal, chosen


def select_families() -> dict:
    t0 = time.time()
    full = candidates(*SEARCH)
    a, rho, pods, chosen = admit_families(full, SEARCH)
    result = {"protocol": "PROTOCOL.md amendment 5 (variant B: family admission)", "years": f"{SEARCH[0]}..{SEARCH[1]}",
              "families_admitted": len(chosen), "search_chosen_on_same_years": summarize(full, a, rho, pods)}
    print("search", json.dumps({k: v for k, v in result["search_chosen_on_same_years"].items() if k != "pod_members"}), flush=True)
    first = candidates(*FIRST)
    a1, _, pods1, chosen1 = admit_families(first, FIRST)
    second = candidates(*SECOND)
    cols = [k for k in first.columns[a1] if k in second.columns]
    pod2 = pd.Series([pods1[k.split("|")[0]] for k in cols], index=cols)
    sharpe2 = second[cols].mean() / second[cols].std() * np.sqrt(252)
    result["split"] = {"chosen_on": f"{FIRST[0]}..{FIRST[1]}", "families_admitted_on_first": len(chosen1),
                       "admitted_on_first": len(a1), "held_into_second": len(cols),
                       "second_half_avg_sleeve_sharpe": round(float(sharpe2.mean()), 3),
                       "second_half_book": stats(central_book(second[cols], pod2, False)),
                       "second_half_book_with_pod_brake": stats(central_book(second[cols], pod2, True))}
    print("split", json.dumps(result["split"]), flush=True)
    result["seconds"] = round(time.time() - t0)
    (HERE / "round3b_result.json").write_text(json.dumps(result, indent=1))
    return result


def central_book(sleeves: pd.DataFrame, pod: pd.Series, brake: bool) -> pd.Series:
    """Equal weight inside a pod, pods by 1 / (1 + average correlation with the others), scaled to target."""
    books = pd.DataFrame({p: sleeves[pod.index[pod == p]].mean(axis=1) for p in sorted(pod.unique())})
    pc = weekly_corr(books).fillna(0.0).to_numpy()
    k = pc.shape[0]
    avg_other = (pc.sum(axis=1) - 1.0) / max(k - 1, 1)
    w = pd.Series(1.0 / (1.0 + avg_other), index=books.columns)
    vol = books.rolling(126, min_periods=63).std() * np.sqrt(252)
    scaled = books * (TARGET_VOL / vol.shift(1))
    active = scaled.notna().mul(w, axis=1).sum(axis=1).replace(0.0, np.nan)
    plain = scaled.fillna(0.0).mul(w, axis=1).sum(axis=1) / active
    # Sized from the plain book (capped like a sleeve), so a brake cuts exposure instead of being
    # levered back to the target by the scaling.
    rvol = plain.rolling(126, min_periods=63).std() * np.sqrt(252)
    lev = (TARGET_VOL / rvol.shift(1)).clip(upper=lab.MAX_LEVERAGE)
    raw = plain
    if brake:
        equity = (1.0 + scaled.fillna(0.0)).cumprod()
        dd = (equity / equity.cummax() - 1.0).shift(1)
        mult = pd.DataFrame(np.where(dd <= -BRAKE_FLAT, 0.0, np.where(dd <= -BRAKE_HALF, 0.5, 1.0)), index=dd.index, columns=dd.columns)
        raw = (scaled * mult).fillna(0.0).mul(w, axis=1).sum(axis=1) / active
    return (raw * lev).dropna()


def summarize(sleeves: pd.DataFrame, admitted: list[int], rho: np.ndarray, pod_of_signal: dict[str, int]) -> dict:
    cols = sleeves.columns[admitted]
    sub = rho[np.ix_(admitted, admitted)]
    n = len(admitted)
    pod = pd.Series([pod_of_signal[k.split("|")[0]] for k in cols], index=cols)
    books = pd.DataFrame({p: sleeves[pod.index[pod == p]].mean(axis=1) for p in sorted(pod.unique())})
    plain, braked = central_book(sleeves[cols], pod, False), central_book(sleeves[cols], pod, True)
    members = {}
    for f, p in pod_of_signal.items():
        members.setdefault(str(p), []).append(f)
    return {
        "candidates": int(sleeves.shape[1]),
        "admitted": n,
        "admitted_by_scheme": {s: int(sum(f"|{s}|" in k for k in cols)) for s in SCHEMES},
        "avg_pairwise_corr_admitted": round(float((sub.sum() - n) / max(n * (n - 1), 1)), 4),
        "effective_bets_sleeves": round(float(n * n / np.square(sub).sum()), 1),
        "pods": int(pod.nunique()),
        "effective_bets_pods": round(participation(weekly_corr(books).to_numpy()), 1),
        "book": stats(plain),
        "book_with_pod_brake": stats(braked),
        "sleeves_per_pod": {str(p): int((pod == p).sum()) for p in sorted(pod.unique())},
        "pod_members": members,
    }


def select() -> dict:
    t0 = time.time()
    full = candidates(*SEARCH)
    admitted, rho, pods = admit(full)
    result = {"protocol": "PROTOCOL.md amendment 4", "years": f"{SEARCH[0]}..{SEARCH[1]}",
              "search": summarize(full, admitted, rho, pods)}
    (OUT / "admitted_search.json").write_text(json.dumps([full.columns[i] for i in admitted]))
    print("search", json.dumps({k: v for k, v in result["search"].items() if k != "pod_members"}), flush=True)
    first = candidates(*FIRST)
    a1, rho1, pods1 = admit(first)
    second = candidates(*SECOND)
    cols = [k for k in first.columns[a1] if k in second.columns]
    pod2 = pd.Series([pods1[k.split("|")[0]] for k in cols], index=cols)
    result["split"] = {"chosen_on": f"{FIRST[0]}..{FIRST[1]}", "admitted_on_first": len(a1),
                       "held_into_second": len(cols), "second_half_book": stats(central_book(second[cols], pod2, False)),
                       "second_half_book_with_pod_brake": stats(central_book(second[cols], pod2, True))}
    print("split", json.dumps(result["split"]), flush=True)
    result["seconds"] = round(time.time() - t0)
    (HERE / "round3_result.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--select", action="store_true")
    ap.add_argument("--families", action="store_true", help="variant B (amendment 5)")
    ap.add_argument("--only", default=None, help="comma list of signals to build")
    a = ap.parse_args()
    if a.build:
        build(a.only.split(",") if a.only else None)
    if a.select:
        select()
    if a.families:
        select_families()
