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

from research.breadth_lab import lab, round2, round4
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
    """The library: every overlapping-portfolio signal of rounds 1-2 and, from amendment 10, round 4."""
    round2.register()
    round4.register()
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
        todo = [k for k in SCHEMES if not all((OUT / f"{name}.{k}.{t}.parquet").exists() for t in ("net", "gross"))]
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
            for frame, tag in ((net, "net"), (pre, "gross")):
                frame.columns = [f"{name}|{scheme}|{b}" for b in frame.columns]
                frame.astype("float32").to_parquet(OUT / f"{name}.{scheme}.{tag}.parquet")
        print(name, signs[name], f"{time.time() - t1:.0f}s", flush=True)
    path = OUT / "signs.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**merged, **signs}, indent=1, sort_keys=True))


# ---- admission -------------------------------------------------------------------------------------

def candidates(a: str, z: str, tag: str = "net") -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in sorted(OUT.glob(f"*.{tag}.parquet"))]
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


def admit_families(sleeves: pd.DataFrame, years: tuple[str, str], judged: pd.DataFrame | None = None, signed: bool = False) -> tuple[list[int], np.ndarray, dict[str, int], dict[str, float]]:
    """Variant B; with ``judged`` (variant C, amendment 8) families are judged on those returns instead.
    ``signed`` (variant D, amendment 9): the sleeves already carry their selection-year sign, so none is left out."""
    judged = sleeves if judged is None else judged
    built = json.loads((OUT / "signs.json").read_text())
    fam = pd.Series([family_of(k) for k in sleeves.columns], index=sleeves.columns)
    agrees = {n: signed or sign_on(n, *years) == built[n] for n in {f.split("|")[0] for f in fam}}
    chosen: dict[str, float] = {}
    for f, cols in fam.groupby(fam).groups.items():
        if not agrees[f.split("|")[0]]:
            continue
        sharpe = stats(lab.book(judged[cols].astype("float64"))).get("sharpe")
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


# ---- amendment 6: variant B's split selection traded as one netted account --------------------------

def netted_split(bands: tuple[float, ...] = (0.0, 1.5), variant: str = "B") -> dict:
    from research.breadth_lab.book import MAX_BOOK_LEVERAGE, account
    t0 = time.time()
    first = candidates(*FIRST)
    judged, share = None, None
    if variant == "C":
        from research.breadth_lab.netting_law import full_share
        share = full_share(FIRST)
        gross = candidates(*FIRST, tag="gross").reindex(columns=first.columns)
        judged = gross - share * (gross - first)
        print("netted_share_1998_2007", round(share, 4), flush=True)
    a1, _, pods1, chosen1 = admit_families(first, FIRST, judged)
    cols = list(first.columns[a1])
    pod = pd.Series([pods1[k.split("|")[0]] for k in cols], index=cols)
    books = pd.DataFrame({p: first[pod.index[pod == p]].mean(axis=1) for p in sorted(pod.unique())})
    pc = weekly_corr(books).fillna(0.0).to_numpy()
    k = pc.shape[0]
    wpod = pd.Series(1.0 / (1.0 + (pc.sum(axis=1) - 1.0) / max(k - 1, 1)), index=books.columns)
    wpod = wpod / wpod.sum()
    count = pod.value_counts()
    weight = {col: float(wpod[pod[col]]) / int(count[pod[col]]) for col in cols}
    del first
    signals()
    c = context(Panel("search"))
    pos, hedge = _positions(c, cols, weight, json.loads((OUT / "signs.json").read_text()))
    net0, _, _ = account(c, pos, hedge)
    vol = net0.rolling(126, min_periods=63).std() * np.sqrt(252)
    target = (TARGET_VOL / vol).clip(upper=MAX_BOOK_LEVERAGE)
    scale = target.where(target.index.isin(c.month_ends)).ffill().shift(2)
    result = {"protocol": "PROTOCOL.md amendment 6" if variant == "B" else "PROTOCOL.md amendment 8 (variant C)",
              "chosen_on": f"{FIRST[0]}..{FIRST[1]}", "sleeves": len(cols), "families": len({family_of(k) for k in cols}),
              "pods": int(pod.nunique()), "netted_share_used": share}
    for band in bands:
        net, gross, expo = account(c, pos, hedge, scale, band)
        net, gross = net.where(scale.notna()), gross.where(scale.notna())
        result[f"band_{band:g}"] = {"second_half_net": stats(net.loc[SECOND[0]:SECOND[1]]),
                                    "second_half_before_costs": stats(gross.loc[SECOND[0]:SECOND[1]]),
                                    "first_half_net": stats(net.loc[FIRST[0]:FIRST[1]]), **expo}
        print(f"band_{band:g}", json.dumps(result[f"band_{band:g}"]), flush=True)
    result["seconds"] = round(time.time() - t0)
    (HERE / ("round3c_netted.json" if variant == "B" else "round3e_netted_variant_c.json")).write_text(json.dumps(result, indent=1))
    return result


def _positions(c: Ctx, cols: list[str], weight: dict[str, float], signs: dict[str, int]) -> tuple[pd.DataFrame, pd.Series]:
    """The sleeves summed into one account: each sleeve's stock positions (cell weights times its own leverage)
    and market hedge at its weight, every signal at the sign given."""
    cells = {"ind48": (c, None), "ind48xL": (c, "L"), "ind48xS": (c, "S"),
             "ind150": (dataclasses.replace(c, bucket=c.p.meta["industry"]), None)}
    pos = np.zeros(c.r.shape)
    hedge = np.zeros(len(c.r))
    families: dict[str, list[str]] = {}
    for col in cols:
        families.setdefault(family_of(col), []).append(col)
    for fam, members in families.items():
        name, scheme = fam.split("|")
        fn, freq = lab.SIGNALS[name]
        sig = fn(c) * signs[name]
        dates = c.month_ends if freq == "M" else c.week_ends
        dates = dates[dates.isin(c.r.index)]
        cc, half = cells[scheme]
        wr = smoothed(cc, cell_weights(cc, sig, dates, half), lab.SMOOTH.get(name, 1))
        _, lev, beta = hedge_and_scale(cc, sleeve_returns(cc, wr, before_costs=True), parts=True)
        w = wr.reindex(c.r.index).ffill().fillna(0.0).shift(2).fillna(0.0)
        # As book.py: leverage and hedge ratio move only when the sleeve rebalances.
        on = pd.Series(np.nan, index=c.r.index)
        on.loc[wr.index] = 1.0
        lev, beta = (f.reindex(c.r.index).where(on.notna(), axis=0).ffill().shift(2).fillna(0.0) for f in (lev, beta))
        bucket = cc.bucket.reindex(c.r.columns)
        for col in members:
            cell = col.split("|", 2)[2]
            if cell not in lev.columns:
                continue
            idx = np.flatnonzero((bucket == cell).to_numpy())
            size = lev[cell].to_numpy() * weight[col]
            pos[:, idx] += w.iloc[:, idx].to_numpy() * size[:, None]
            hedge -= beta[cell].to_numpy() * size
        print(fam, len(members), flush=True)
    return pd.DataFrame(pos, index=c.r.index, columns=c.r.columns), pd.Series(hedge, index=c.r.index)


# ---- variant D (amendment 9): selection-year signs, pods weighted for diversification, the band's edge ---

SHRINKS = (0.75, 0.5, 0.25)
VALIDATION = (("1998-01-01", "2002-12-31"), ("2003-01-01", "2007-12-31"))
BAND_GRID = ((1.0, False), (1.5, False), (2.0, False), (0.25, True), (0.5, True), (0.75, True), (1.0, True))


def diversified(books: pd.DataFrame, shrink: float) -> pd.Series:
    """Capital per pod for the most diversified book, inverse(Sigma) x 1 (every sleeve expected to earn the same
    Sharpe), with the pods' weekly correlations shrunk toward zero; long only, summing to one."""
    vol = books.std().to_numpy()
    if np.isnan(vol).any():
        raise ValueError("a pod has no record in the fitting years")
    rho = (1.0 - shrink) * weekly_corr(books).fillna(0.0).to_numpy() + shrink * np.eye(len(vol))
    w = np.clip(np.linalg.solve(np.outer(vol, vol) * rho, np.ones(len(vol))), 0.0, None)
    return pd.Series(w / w.sum(), index=books.columns)


def as_ideas(books: pd.DataFrame, shrink: float) -> pd.Series:
    """Capital per pod when every pod (idea) is expected to earn the same Sharpe (amendment 10): inverse(R) x 1 / sigma,
    with the pods' weekly correlations shrunk toward zero; long only, summing to one."""
    vol = books.std().to_numpy()
    if np.isnan(vol).any():
        raise ValueError("a pod has no record in the fitting years")
    rho = (1.0 - shrink) * weekly_corr(books).fillna(0.0).to_numpy() + shrink * np.eye(len(vol))
    w = np.clip(np.linalg.solve(rho, np.ones(len(vol))) / vol, 0.0, None)
    return pd.Series(w / w.sum(), index=books.columns)


def _scaled(raw: pd.Series) -> pd.Series:
    """A book scaled to the target with its trailing volatility, lagged a day, from its first live day."""
    raw = raw.where(raw != 0)
    return raw * (TARGET_VOL / (raw.rolling(126, min_periods=63).std() * np.sqrt(252)).shift(1))


def netted_d(weighting: str = "sleeves", share: float | None = None, ablations: bool = True,
             out: str = "round3f_variant_d.json", tag: str = "d") -> dict:
    """Variant D, chosen on 1998-2007 and run once on 2008-2017, with its two ablations. ``weighting="ideas"``
    and the other options serve round 4 (amendment 10): pods weighted as ideas, one netted share for two books."""
    from research.breadth_lab.book import MAX_BOOK_LEVERAGE, account
    from research.breadth_lab.netting_law import full_share
    t0 = time.time()
    built = json.loads((OUT / "signs.json").read_text())
    own = {n: sign_on(n, *FIRST) for n in signals()}
    if share is None:
        share = full_share(FIRST, own)
        print("netted_share_1998_2007", round(share, 4), flush=True)
    first = candidates(*FIRST)
    gross = candidates(*FIRST, tag="gross").reindex(columns=first.columns)
    flip = pd.Series([own[k.split("|")[0]] * built[k.split("|")[0]] for k in first.columns], index=first.columns).astype("float32")
    cost = gross - first
    gross = gross.mul(flip, axis=1)
    net, judged = gross - cost, gross - share * cost
    del first, cost
    a1, _, pods1, _ = admit_families(net, FIRST, judged, signed=True)
    cols = list(net.columns[a1])
    pod = pd.Series([pods1[k.split("|")[0]] for k in cols], index=cols)
    count = pod.value_counts()
    books = pd.DataFrame({p: judged[pod.index[pod == p]].astype("float64").mean(axis=1) for p in sorted(pod.unique())})
    fit, run = VALIDATION
    weigh, shrinks = (as_ideas, (1.0, *SHRINKS)) if weighting == "ideas" else (diversified, SHRINKS)
    check = {}
    for lam in shrinks:
        w = weigh(books.loc[fit[0]:fit[1]], lam)
        check[lam] = stats(_scaled(books.fillna(0.0).mul(w, axis=1).sum(axis=1)).loc[run[0]:run[1]]).get("sharpe")
        print(f"{tag}_validation_shrink_{lam:g}", json.dumps({"run_2003_2007_sharpe": check[lam]}), flush=True)
    shrink = max(check, key=lambda k: check[k])
    wpod = weigh(books, shrink)
    standalone = pd.DataFrame({p: net[pod.index[pod == p]].astype("float64").mean(axis=1) for p in sorted(pod.unique())})
    pc = weekly_corr(standalone).fillna(0.0).to_numpy()
    wc = pd.Series(1.0 / (1.0 + (pc.sum(axis=1) - 1.0) / max(len(pc) - 1, 1)), index=standalone.columns)
    wc = wc / wc.sum()
    del net, gross, judged
    signals()
    c = context(Panel("search"))

    def build_account(wp: pd.Series) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        weight = {col: float(wp[pod[col]]) / int(count[pod[col]]) for col in cols}
        pos, hedge = _positions(c, cols, weight, own)
        net0, _, _ = account(c, pos, hedge)
        target = (TARGET_VOL / (net0.rolling(126, min_periods=63).std() * np.sqrt(252))).clip(upper=MAX_BOOK_LEVERAGE)
        return pos, hedge, target.where(target.index.isin(c.month_ends)).ffill().shift(2)

    def report(pos: pd.DataFrame, hedge: pd.Series, scale: pd.Series, band: float, edge: bool) -> dict:
        net, gross, expo = account(c, pos, hedge, scale, band, edge)
        net, gross = net.where(scale.notna()), gross.where(scale.notna())
        return {"second_half_net": stats(net.loc[SECOND[0]:SECOND[1]]), "second_half_before_costs": stats(gross.loc[SECOND[0]:SECOND[1]]),
                "first_half_net": stats(net.loc[FIRST[0]:FIRST[1]]), **expo, "_net": net}

    pos, hedge, scale = build_account(wpod)
    # The band is chosen on the selection years alone: the account is run on 1998-2007 only.
    a, z = FIRST
    cw = dataclasses.replace(c, r=c.r.loc[a:z], r0=c.r0.loc[a:z], market=c.market.loc[a:z], cost=c.cost.loc[a:z])
    options = {f"{'edge' if e else 'target'}_{b:g}": (b, e) for b, e in BAND_GRID}
    grid = {}
    for key, (band, edge) in options.items():
        n1, _, expo = account(cw, pos.loc[a:z], hedge.loc[a:z], scale.loc[a:z], band, edge)
        grid[key] = {"first_half_net": stats(n1.where(scale.loc[a:z].notna())), **expo}
        print(f"{tag}_grid_{key}", json.dumps(grid[key]), flush=True)
    best = max(grid, key=lambda k: grid[k]["first_half_net"].get("sharpe", -9.0))
    band, edge = options[best]
    members = {}
    for k in cols:
        members.setdefault(str(pod[k]), set()).add(k.split("|")[0])
    new = {f"{n}_s" for n in round4.NEW}
    result = {"protocol": "PROTOCOL.md amendment 9 (variant D)" if tag == "d" else f"PROTOCOL.md amendment 10 ({tag})",
              "weighting": weighting, "chosen_on": f"{FIRST[0]}..{FIRST[1]}", "sleeves": len(cols),
              "families": len({family_of(k) for k in cols}), "pods": int(pod.nunique()), "netted_share_used": round(share, 4),
              "signals_flipped_to_selection_sign": sorted(n for n in own if own[n] != built[n]),
              "validation_2003_2007": {str(k): v for k, v in check.items()}, "shrink": shrink,
              "pod_capital": {str(p): round(float(x), 4) for p, x in wpod.items()},
              "pod_capital_variant_c_rule": {str(p): round(float(x), 4) for p, x in wc.items()},
              "band_grid_1998_2007": grid, "band": best,
              "pods_detail": {p: {"sleeves": int((pod.astype(str) == p).sum()), "signals": sorted(v), "round4_signals": sorted(v & new)}
                              for p, v in members.items()}}
    d = report(pos, hedge, scale, band, edge)
    d.pop("_net").to_frame("net").to_parquet(OUT / ("variant_d_net.parquet" if tag == "d" else f"{tag}_net.parquet"))
    result[tag] = d
    print(tag, json.dumps(d), flush=True)
    if ablations:
        result["ablation_round1_band"] = {k: v for k, v in report(pos, hedge, scale, 1.5, False).items() if k != "_net"}
        print("ablation_round1_band", json.dumps(result["ablation_round1_band"]), flush=True)
        del pos, hedge
        pos, hedge, scale = build_account(wc)
        result["ablation_variant_c_pod_weights"] = {k: v for k, v in report(pos, hedge, scale, band, edge).items() if k != "_net"}
        print("ablation_variant_c_pod_weights", json.dumps(result["ablation_variant_c_pod_weights"]), flush=True)
    result["seconds"] = round(time.time() - t0)
    (HERE / out).write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--select", action="store_true")
    ap.add_argument("--families", action="store_true", help="variant B (amendment 5)")
    ap.add_argument("--netted", action="store_true", help="variant B traded as one netted account (amendment 6)")
    ap.add_argument("--netted-c", action="store_true", help="variant C: marginal netted cost admission (amendment 8)")
    ap.add_argument("--netted-d", action="store_true", help="variant D: selection-year signs, diversified pods, the band's edge (amendment 9)")
    ap.add_argument("--only", default=None, help="comma list of signals to build")
    a = ap.parse_args()
    if a.build:
        build(a.only.split(",") if a.only else None)
    if a.select:
        select()
    if a.families:
        select_families()
    if a.netted:
        netted_split()
    if a.netted_c:
        netted_split(variant="C")
    if a.netted_d:
        netted_d()
