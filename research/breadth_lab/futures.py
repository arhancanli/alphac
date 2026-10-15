"""Futures sleeves for the breadth lab (round 2, PROTOCOL amendment 3): one sleeve per CME market and signal.

Databento daily bars of individual CME contracts (data/lake_fut_db/contracts.parquet). CME symbols carry one
year digit, so a contract is a symbol and Databento id, split wherever its bars stop for more than 60 days,
and its expiry year is the first year with that digit whose contract month is not before its last bar.
Each market's series holds its highest-volume contract (rolling forward only, chosen two days earlier) and
earns that contract's own close-to-close return, so a roll leaves no price gap; the roll itself is charged.

A sleeve's exposure is its signal (between -1 and 1) times 10% over the market's trailing volatility, capped
at 10x notional. Decided at a close, traded at the next close, earning from the close after, as for stocks.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.futures --build
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.futures
"""

from __future__ import annotations

import argparse
import json

import duckdb
import numpy as np
import pandas as pd

from research.breadth_lab.lab import stats
from research.breadth_lab.panel import ALPHAFORGE, CACHE

SRC = ALPHAFORGE / "data" / "lake_fut_db" / "contracts.parquet"
SEARCH_END = pd.Timestamp("2017-12-31")
MONTHS = "FGHJKMNQUVXZ"
CLASSES = {
    "equity": ["ES", "NQ", "YM", "EMD", "RTY", "NKD"],
    "rates": ["ZT", "ZF", "ZN", "ZB", "UB", "TN", "ZQ"],
    "currency": ["6E", "6C", "6J", "6B", "6A", "6S", "6N"],
    "energy": ["CL", "NG", "HO", "RB"],
    "metals": ["GC", "SI", "HG", "PL", "PA"],
    "grains": ["ZC", "ZS", "ZW", "ZM", "ZL", "ZO"],
    "livestock": ["HE", "LE", "GF"],
}
CLASS_OF = {r: c for c, roots in CLASSES.items() for r in roots}
COMMODITY = {"energy", "metals", "grains", "livestock"}
THIN = {"HE", "LE", "GF", "ZO", "PA", "PL", "NKD", "RTY"}
TARGET_VOL, MAX_EXPOSURE = 0.10, 10.0
OUT = CACHE / "futures"


def one_way_cost(root: str) -> float:
    if root in THIN:
        return 0.0010
    return 0.0005 if CLASS_OF[root] in COMMODITY else 0.0002


def contracts() -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"""SELECT symbol, instrument_id AS iid, epoch_ms(ts_event) AS t, close, volume
                         FROM read_parquet('{SRC}')
                         WHERE regexp_matches(symbol, '^[A-Z0-9]{{1,3}}[FGHJKMNQUVXZ][0-9]{{1,2}}$')""").df()
    x = df["symbol"].str.extract(r"^([A-Z0-9]{1,3}?)([FGHJKMNQUVXZ])([0-9]{1,2})$")
    df["root"], df["month"], df["ydig"] = x[0], x[1].map(MONTHS.index) + 1, x[2]
    df = df[df["root"].isin(list(CLASS_OF)) & (df["close"] > 0)].copy()
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    df = df[df["day"].dt.dayofweek < 5].sort_values(["symbol", "iid", "day"])
    gap = df.groupby(["symbol", "iid"])["day"].diff() > pd.Timedelta(days=60)
    df["run"] = gap.groupby([df["symbol"], df["iid"]]).cumsum()
    last = df.groupby(["symbol", "iid", "run"])["day"].transform("max")
    ly, lm = last.dt.year.to_numpy(), last.dt.month.to_numpy()
    month = df["month"].to_numpy()
    y = ly - ly % 10 + df["ydig"].str[-1].astype(int).to_numpy()
    y = np.where(y * 12 + month < ly * 12 + lm, y + 10, y)
    two = df["ydig"].str.len().to_numpy() == 2
    y = np.where(two, 2000 + pd.to_numeric(df["ydig"]).to_numpy(), y)
    df["expiry"] = y * 100 + month
    return df.sort_values("volume").drop_duplicates(["root", "expiry", "day"], keep="last")


def continuous(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """One market: the held contract's return, roll flags, and carry from the curve."""
    exp = close.columns.to_numpy()
    c = close.to_numpy()
    has = ~np.isnan(c)
    vol = np.where(has, volume.fillna(0.0).to_numpy(), -1.0)
    cf = close.ffill(limit=5).to_numpy()
    n = len(close)
    active = np.full(n, -1)
    cur = -1
    for i in range(n):
        if has[i].any():
            j = int(np.argmax(vol[i]))
            cur = j if (cur < 0 or j > cur) else cur
        active[i] = cur
    held = np.r_[[-1, -1], active[:-2]]
    ret = np.full(n, np.nan)
    for i in range(1, n):
        h = held[i]
        if h >= 0 and not np.isnan(cf[i - 1, h]) and not np.isnan(cf[i, h]):
            ret[i] = cf[i, h] / cf[i - 1, h] - 1.0
    roll = np.r_[False, (held[1:] != held[:-1]) & (held[:-1] >= 0)]
    carry_next, carry_12 = np.full(n, np.nan), np.full(n, np.nan)
    months = (exp // 100) * 12 + exp % 100
    for i in range(n):
        a = active[i]
        if a < 0 or not has[i, a]:
            continue
        later = np.flatnonzero(has[i, a + 1:]) + a + 1
        if len(later):
            k = later[0]
            carry_next[i] = np.log(c[i, a] / c[i, k]) * 12.0 / (months[k] - months[a])
            far = later[np.abs(months[later] - months[a] - 12) <= 1]
            if len(far):
                k = far[0]
                carry_12[i] = np.log(c[i, a] / c[i, k]) * 12.0 / (months[k] - months[a])
    held_exp = np.where(held >= 0, exp[held.clip(0)], 0)
    return pd.DataFrame({"ret": ret, "roll": roll, "carry_next": carry_next, "carry_12": carry_12,
                         "held_expiry": held_exp, "volume": np.where(held >= 0, np.nan_to_num(volume.to_numpy()[np.arange(n), held.clip(0)]), np.nan)},
                        index=close.index)


def build() -> None:
    df = contracts()
    days = pd.DatetimeIndex(sorted(df["day"].unique()))
    frames = {}
    for root, g in df.groupby("root"):
        close = g.pivot(index="day", columns="expiry", values="close").reindex(days).sort_index(axis=1)
        volume = g.pivot(index="day", columns="expiry", values="volume").reindex(days).sort_index(axis=1)
        frames[root] = continuous(close, volume)
    OUT.mkdir(parents=True, exist_ok=True)
    for field in ("ret", "roll", "carry_next", "carry_12", "held_expiry", "volume"):
        pd.DataFrame({r: f[field] for r, f in frames.items()}).to_parquet(OUT / f"{field}.parquet")
    ret = pd.DataFrame({r: f["ret"] for r, f in frames.items()})
    print(json.dumps({"markets": len(frames), "days": len(days), "first": str(days[0].date()), "last": str(days[-1].date()),
                      "annual_vol": {r: round(float(ret[r].std() * np.sqrt(252)), 3) for r in ret.columns},
                      "rolls_per_year": {r: round(float(frames[r]["roll"].sum() / (len(days) / 252)), 1) for r in frames}}))


def load(mode: str = "search") -> dict[str, pd.DataFrame]:
    w = {f: pd.read_parquet(OUT / f"{f}.parquet") for f in ("ret", "roll", "carry_next", "carry_12")}
    if mode == "search":
        w = {k: v.loc[:SEARCH_END] for k, v in w.items()}
    return w


def _week_ends(index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("W")).transform("max") == s


def _month_ends(index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("M")).transform("max") == s


def signals(w: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Each signal between -1 and 1 per market, sampled on its rebalance days and held between them."""
    r = w["ret"]
    sd = r.rolling(63, min_periods=40).std()
    logp = np.log1p(r.fillna(0.0)).cumsum().where(sd.notna())
    week, month = _week_ends(r.index), _month_ends(r.index)
    out = {}
    for L in (21, 63, 126, 252):
        z = (logp - logp.shift(L)) / (sd * np.sqrt(L))
        out[f"trend_{L}"] = z.clip(-1, 1).where(week).ffill()
    z126 = (logp - logp.shift(126)) / (sd * np.sqrt(126))
    z252 = (logp - logp.shift(252)) / (sd * np.sqrt(252))
    out["trend_252_monthly"] = z252.clip(-1, 1).where(month).ffill()
    out["trend_blend"] = ((z126 + z252) / 2.0).clip(-1, 1).where(week).ffill()
    out["trend_blend_monthly"] = ((z126 + z252) / 2.0).clip(-1, 1).where(month).ffill()
    out["tsmom_sign_252"] = np.sign(logp - logp.shift(252)).where(month).ffill()
    carry = pd.DataFrame({m: (w["carry_12"][m] if CLASS_OF[m] in COMMODITY else w["carry_next"][m]) for m in r.columns})
    carry = carry.rolling(21, min_periods=10).mean()
    out["carry"] = (carry / (sd * np.sqrt(252))).clip(-1, 1).where(month).ffill()
    # Cross-sectional momentum inside each asset class: 12-month return skipping the last month, ranked.
    mom = (logp.shift(21) - logp.shift(252))
    xs = pd.DataFrame(np.nan, index=r.index, columns=r.columns)
    for cls, roots in CLASSES.items():
        cols = [m for m in roots if m in r.columns]
        rk = mom[cols].rank(axis=1, pct=True)
        n = mom[cols].notna().sum(axis=1)
        xs[cols] = (rk.sub(rk.mean(axis=1), axis=0) * 2.0).where(n >= 3, np.nan)
    out["xsmom"] = xs.where(month).ffill()
    return out


def exposures(w: dict[str, pd.DataFrame], sig: pd.DataFrame) -> pd.DataFrame:
    r = w["ret"]
    vol = r.rolling(63, min_periods=40).std() * np.sqrt(252)
    scale = (TARGET_VOL / vol).clip(upper=MAX_EXPOSURE)
    return (sig * scale.where(sig.notna())).fillna(0.0)


def pnl(w: dict[str, pd.DataFrame], e: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Net and before-cost daily P&L per market for an exposure frame decided at each close."""
    r = w["ret"].fillna(0.0)
    held = e.shift(2).fillna(0.0)
    traded = (e.shift(1) - e.shift(2)).abs().fillna(0.0)
    c = pd.Series({m: one_way_cost(m) for m in r.columns})
    cost = traded.mul(c, axis=1) + w["roll"].astype(float).fillna(0.0) * 2.0 * held.abs().mul(c, axis=1)
    gross = held * r
    return gross - cost, gross


def sleeves(w: dict[str, pd.DataFrame]) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    out = {}
    for name, sig in signals(w).items():
        e = exposures(w, sig)
        net, gross = pnl(w, e)
        out[name] = (net.where(sig.shift(2).notna()), gross.where(sig.shift(2).notna()), e)
    return out


def book(w: dict[str, pd.DataFrame], chosen: dict[str, int], scale_to: float = TARGET_VOL) -> dict:
    """The netted block: every chosen signal's exposures summed per market (each signal counted once per
    market it trades), trades and rolls charged on the netted exposure, scaled to 10% at month ends."""
    sigs = signals(w)
    total, n = None, 0
    for name, sign in chosen.items():
        e = exposures(w, sigs[name]) * sign
        total = e if total is None else total.add(e, fill_value=0.0)
        n += int((sigs[name].notna().sum() > 0).sum())
    net, gross = pnl(w, total)
    live = (total.shift(2).abs().sum(axis=1) > 0)  # days the book holds anything; a flat start is not low risk
    bn, bg = net.sum(axis=1).where(live), gross.sum(axis=1).where(live)
    vol = bg.rolling(126, min_periods=63).std() * np.sqrt(252)
    month = _month_ends(bg.index)
    k = (scale_to / vol).where(month).ffill().shift(2)
    k = k.clip(upper=20.0)
    return {"net": bn * k, "gross": bg * k, "sleeves": n}


def correlation(frames: list[pd.DataFrame]) -> dict:
    x = pd.concat(frames, axis=1)
    x = x.loc[:, x.notna().sum() >= 200]
    weekly = x.resample("W").sum(min_count=3)
    cm = weekly.corr(min_periods=52).to_numpy()
    off = cm[~np.eye(len(cm), dtype=bool)]
    rho = float(np.nanmean(off))
    n = len(cm)
    return {"sleeves": n, "avg_pairwise_corr_weekly": round(rho, 3), "n_eff_from_avg": round(n / (1 + (n - 1) * rho), 1) if n else None}


def search_report() -> None:
    w = load("search")
    sl = sleeves(w)
    halves = (("2010-06-01", "2013-12-31"), ("2014-01-01", "2017-12-31"))
    rows = {}
    for name, (net, gross, _) in sl.items():
        b = book(w, {name: 1})
        rows[name] = {"book_net": stats(b["net"].dropna()), "book_before_costs": stats(b["gross"].dropna()).get("sharpe"),
                      "halves_net": [stats(b["net"].loc[a:z].dropna()).get("sharpe") for a, z in halves],
                      "mean_sleeve_sharpe_net": round(float(np.nanmean([stats(net[m].dropna()).get("sharpe") or np.nan for m in net.columns])), 3),
                      **correlation([net])}
        print(name, json.dumps(rows[name]), flush=True)
    all_names = {k: 1 for k in sl}
    b = book(w, all_names)
    print("all_signals", json.dumps({"book_net": stats(b["net"].dropna()), "book_before_costs": stats(b["gross"].dropna()).get("sharpe"),
                                     "halves_net": [stats(b["net"].loc[a:z].dropna()).get("sharpe") for a, z in halves],
                                     **correlation([v[0] for v in sl.values()])}), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    if a.build:
        build()
    else:
        search_report()
