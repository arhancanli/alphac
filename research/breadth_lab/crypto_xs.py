"""Crypto cross-section for the breadth lab (round 2, PROTOCOL amendment 3): Binance perpetuals ranked against
each other inside liquidity tiers, dollar neutral, so the block does not depend on the level of funding.

A sleeve is one signal inside one tier (tiers by 30-day median quote volume among eligible coins: the top
quarter, the next quarter, and so on; at least 8 coins). Weights are rank-demeaned and gross 1, set at week
ends and held as the mean of the last two weeks' weights. A long pays the funding a short receives. Decided
at a UTC close, traded at the next close, earning from the close after. Each sleeve is hedged with the BTC
perpetual at a trailing beta and scaled to 10% volatility; costs one way 15 bp for coins trading $200M a
day, 30 bp below, and 5 bp on the hedge. Search 2020-01-01 to 2022-12-31.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.crypto_xs
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.breadth_lab.lab import stats
from research.breadth_lab.panel import CACHE

SEARCH_END = pd.Timestamp("2022-12-31", tz="UTC")
TARGET_VOL, MAX_LEVERAGE, MIN_COINS, TIERS = 0.10, 5.0, 8, 4
MIN_QV, BIG_QV = 2e7, 2e8
HEDGE_COST = 0.0005
HALVES = (("2020-01-01", "2021-06-30"), ("2021-07-01", "2022-12-31"))


def load(mode: str = "search") -> dict[str, pd.DataFrame]:
    d = CACHE / "crypto"
    perp = pd.read_parquet(d / "perp.parquet")
    perp = perp[perp["bars"] >= 20]
    spot = pd.read_parquet(d / "spot.parquet")
    spot = spot[spot["bars"] >= 20]
    fund = pd.read_parquet(d / "funding.parquet")
    w = {"close": perp.pivot(index="day", columns="coin", values="close"), "qv": perp.pivot(index="day", columns="coin", values="qv"),
         "funding": fund.pivot(index="day", columns="coin", values="funding"), "spot": spot.pivot(index="day", columns="coin", values="close")}
    days = pd.date_range(w["close"].index.min(), w["close"].index.max(), freq="D", tz="UTC")
    if mode == "search":
        days = days[days <= SEARCH_END]
    coins = w["close"].columns
    return {k: v.reindex(index=days, columns=coins) for k, v in w.items()}


def inputs(w: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    r = w["close"].pct_change(fill_method=None)
    f = w["funding"].fillna(0.0)
    liq = w["qv"].rolling(30, min_periods=20).median()
    eligible = (liq >= MIN_QV) & w["close"].notna()
    long_ret = (r - f).where(r.notna())          # what a long earns: price change less the funding it pays
    btc = long_ret["BTCUSDT"].fillna(0.0)
    return {"r": r, "long_ret": long_ret, "liq": liq, "eligible": eligible, "btc": btc,
            "cost": pd.DataFrame(np.where(liq >= BIG_QV, 0.0015, 0.0030), index=r.index, columns=r.columns)}


def signals(w: dict[str, pd.DataFrame], x: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    r, lr = x["r"], x["long_ret"]
    lp = np.log1p(r.fillna(0.0)).cumsum()
    btc = x["btc"]
    cov = lr.mul(btc, axis=0).rolling(90, min_periods=60).mean() - lr.rolling(90, min_periods=60).mean().mul(btc.rolling(90, min_periods=60).mean(), axis=0)
    var = (btc * btc).rolling(90, min_periods=60).mean() - btc.rolling(90, min_periods=60).mean() ** 2
    premium = np.log(w["close"] / w["spot"])
    return {
        "mom_7": lp - lp.shift(7),
        "mom_30": lp - lp.shift(30),
        "mom_90": lp.shift(7) - lp.shift(90),
        "funding_low": -w["funding"].rolling(7, min_periods=5).mean(),
        "lowvol_30": -r.rolling(30, min_periods=20).std(),
        "lowbeta_90": -cov.div(var, axis=0),
        "max_7": -r.rolling(7, min_periods=5).max(),
        "vol_shock": np.log(w["qv"].rolling(7, min_periods=5).mean() / w["qv"].rolling(90, min_periods=60).mean()),
        "premium_low": -premium.rolling(7, min_periods=5).mean(),
        "small": -np.log(x["liq"]),
    }


def tier_weights(x: dict[str, pd.DataFrame], sig: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[int, pd.DataFrame]:
    """Rank-demeaned gross-1 weights per liquidity tier at each date."""
    out = {t: [] for t in range(TIERS)}
    for d in dates:
        ok = x["eligible"].loc[d] & sig.loc[d].notna()
        s, lq = sig.loc[d][ok], x["liq"].loc[d][ok]
        tier = np.floor(lq.rank(pct=True, ascending=False).clip(upper=0.999999) * TIERS).astype(int)
        for t in range(TIERS):
            st = s[tier == t]
            if len(st) < MIN_COINS:
                out[t].append(pd.Series(dtype="float64", name=d))
                continue
            k = st.rank(pct=True)
            k = k - k.mean()
            out[t].append((k / k.abs().sum()).rename(d))
    return {t: pd.DataFrame(rows).reindex(columns=x["r"].columns).fillna(0.0) for t, rows in out.items()}


def sleeve(x: dict[str, pd.DataFrame], wr: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    """One sleeve: net and before-cost returns at 10% volatility, its leverage and hedge ratio, and its daily weights."""
    w = wr.rolling(2, min_periods=1).mean()
    w = w.div(w.abs().sum(axis=1).where(lambda s: s > 0), axis=0).fillna(0.0)
    held = w.reindex(x["r"].index).ffill().fillna(0.0)
    live = held.shift(2).fillna(0.0)
    traded = (held.shift(1) - held.shift(2)).abs().fillna(0.0)
    lr = x["long_ret"].fillna(0.0)
    raw_gross = (live * lr).sum(axis=1)
    raw_cost = (traded * x["cost"]).sum(axis=1)
    active = live.abs().sum(axis=1) > 0
    btc = x["btc"]
    g = raw_gross.where(active)
    beta = (g.mul(btc).rolling(90, min_periods=45).mean() - g.rolling(90, min_periods=45).mean() * btc.rolling(90, min_periods=45).mean()) / (
        (btc * btc).rolling(90, min_periods=45).mean() - btc.rolling(90, min_periods=45).mean() ** 2)
    beta = beta.shift(1)
    hedged_gross = g - beta * btc
    vol = hedged_gross.rolling(90, min_periods=45).std() * np.sqrt(365)
    lev = (TARGET_VOL / vol.shift(1)).clip(upper=MAX_LEVERAGE)
    gross = hedged_gross * lev
    net = (g - raw_cost - beta * btc - (beta.diff().abs() * HEDGE_COST).fillna(0.0)) * lev
    return net, gross, lev, beta, w


def run(mode: str = "search") -> dict:
    w = load(mode)
    x = inputs(w)
    week_ends = x["r"].index[x["r"].index.dayofweek == 6]
    results, frames = {}, {}
    for name, sig in signals(w, x).items():
        tw = tier_weights(x, sig, week_ends)
        nets, grosses = {}, {}
        for t, wr in tw.items():
            if wr.abs().sum().sum() == 0:
                continue
            net, gross, lev, beta, wd = sleeve(x, wr)
            nets[t], grosses[t] = net, gross
            frames[(name, t)] = (wd, lev, beta)
        n, g = pd.DataFrame(nets), pd.DataFrame(grosses)
        bn, bg = n.mean(axis=1), g.mean(axis=1)
        results[name] = {"sleeves": n.shape[1], "book_net": stats(bn, periods=365), "book_before_costs": stats(bg, periods=365).get("sharpe"),
                         "halves_net": [stats(bn.loc[a:z], periods=365).get("sharpe") for a, z in HALVES],
                         "tier_net": {str(t): stats(n[t], periods=365).get("sharpe") for t in n.columns},
                         "avg_corr_weekly": round(float(np.nanmean(n.resample("W").sum(min_count=3).corr().to_numpy()[~np.eye(n.shape[1], dtype=bool)])), 3) if n.shape[1] > 1 else None}
        print(name, json.dumps(results[name]), flush=True)
    return results


if __name__ == "__main__":
    run("search")
