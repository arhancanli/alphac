"""Industry rotation sleeves for the breadth lab (round 2, PROTOCOL amendment 3): whole Fama-French industries
ranked against each other, where every other stock sleeve ranks stocks inside one industry.

An industry is the equal-weighted portfolio of its eligible names (at least 10). A sleeve is one signal across
all industries: rank-demeaned, gross 1, held as the mean of the last three month-end weights, with each
industry's weight spread equally over its names. Costs, borrow, hedge, scaling and timing as for every
other stock sleeve. Stored like a signal's sleeves, under the one pseudo-industry "ALL".

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.industries
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from research.breadth_lab.lab import BORROW, MIN_NAMES, Ctx, context, hedge_and_scale, stats
from research.breadth_lab.panel import CACHE, Panel

ALL = "ALL"


def industry_returns(c: Ctx) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily equal-weighted return of each industry's names eligible the day before, and their count."""
    elig = c.eligible.shift(1, fill_value=False)
    g = c.bucket.reindex(c.r.columns)
    r = c.r.where(elig)
    ret = r.T.groupby(g).mean().T
    n = elig.astype("float64").T.groupby(g).sum().T
    return ret, n


def _season(ir: pd.DataFrame) -> pd.DataFrame:
    """Heston-Sadka at the industry level: the industry's mean return in the coming calendar month over the
    previous ten years (Keloharju, Linnainmaa and Nyberg find seasonality in industries too)."""
    naive = ir.index.tz_localize(None)
    monthly = (1.0 + ir.fillna(0.0)).groupby(naive.to_period("M")).prod() - 1.0
    lagged = sum(monthly.shift(12 * k - 1) for k in range(1, 11)) / 10.0
    lagged.index = lagged.index.to_timestamp(how="end").normalize().tz_localize("UTC")
    return lagged.reindex(ir.index, method="ffill")


def signals(c: Ctx, ir: pd.DataFrame) -> dict[str, pd.DataFrame]:
    lp = np.log1p(ir.fillna(0.0)).cumsum()
    m = c.market
    cov = ir.mul(m, axis=0).rolling(252, min_periods=126).mean() - ir.rolling(252, min_periods=126).mean().mul(m.rolling(252, min_periods=126).mean(), axis=0)
    var = (m * m).rolling(252, min_periods=126).mean() - m.rolling(252, min_periods=126).mean() ** 2
    return {
        "ind_mom_12_1": lp.shift(21) - lp.shift(252),
        "ind_mom_6_1": lp.shift(21) - lp.shift(126),
        "ind_mom_1m": lp - lp.shift(21),
        "ind_rev_36_12": -(lp.shift(252) - lp.shift(756)),
        "ind_season": _season(ir),
        "ind_lowvol": -ir.rolling(63, min_periods=40).std(),
        "ind_lowbeta": -cov.div(var, axis=0),
    }


def run(mode: str = "search") -> dict:
    t0 = time.time()
    c = context(Panel(mode))
    ir, n = industry_returns(c)
    out_dir = CACHE / mode
    results = {}
    dates = c.month_ends[c.month_ends.isin(c.r.index)]
    g = c.bucket.reindex(c.r.columns)
    for name, sig in signals(c, ir).items():
        rows = []
        for d in dates:
            ok = (n.loc[d] >= MIN_NAMES) & sig.loc[d].notna()
            s = sig.loc[d][ok]
            if len(s) < 10:
                rows.append(pd.Series(dtype="float64", name=d))
                continue
            k = s.rank(pct=True)
            k = (k - k.mean()) / (k - k.mean()).abs().sum()
            members = c.eligible.loc[d] & g.isin(k.index)
            per_name = g[members].map(k) / g[members].map(n.loc[d])
            rows.append(per_name.rename(d))
        w = pd.DataFrame(rows).reindex(columns=c.r.columns).fillna(0.0)
        w = w.rolling(3, min_periods=1).mean()
        w = w.div(w.abs().sum(axis=1).where(lambda x: x > 0), axis=0).fillna(0.0)
        held = w.reindex(c.r.index).ffill().fillna(0.0)
        traded = held.shift(1).fillna(0.0)
        live = held.shift(2).fillna(0.0)
        turnover = (traded - traded.shift(1).fillna(0.0)).abs()
        gross = (live * c.r0).sum(axis=1)
        costs = (turnover * c.cost).sum(axis=1).shift(1).fillna(0.0)
        borrow = live.clip(upper=0.0).abs().sum(axis=1) * BORROW / 252.0
        active = live.abs().sum(axis=1) > 0
        raw = (gross - costs - borrow).where(active).to_frame(ALL)
        pre, lev, beta = hedge_and_scale(c, gross.where(active).to_frame(ALL), parts=True)
        scaled = (raw - beta.mul(c.market, axis=0)) * lev
        sname = f"{name}_s"
        for frame, tag in ((scaled, "net"), (pre, "gross"), (lev, "lev"), (beta, "beta")):
            f = frame.copy()
            f.columns = [f"{sname}|{ALL}"]
            f.astype("float32").to_parquet(out_dir / f"{sname}.{tag}.parquet")
        w.astype("float32").to_parquet(out_dir / f"{sname}.weights.parquet")
        results[sname] = {"sleeves": 1, "net": stats(scaled[ALL]), "before_costs": stats(pre[ALL]).get("sharpe"),
                          "halves_net": [stats(scaled[ALL].loc[a:z]).get("sharpe") for a, z in (("1998-01-01", "2007-12-31"), ("2008-01-01", "2017-12-31"))],
                          "turnover_per_year": round(float(w.diff().abs().sum(axis=1).mean() * 12), 2)}
        print(sname, json.dumps(results[sname]), flush=True)
    print(f"done {time.time() - t0:.0f}s", flush=True)
    return results


if __name__ == "__main__":
    run("search")
