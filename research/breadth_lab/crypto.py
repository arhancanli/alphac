"""Crypto sleeves for the breadth lab: one cash-and-carry sleeve per coin (long Binance spot, short the
same coin's perpetual, collect funding), on only while that coin's recent funding pays.

Daily UTC closes from hourly bars; funding summed per UTC day by settlement time. A decision at a day's
close trades at the next close and earns from the close after (one day to trade), as for stocks.
Search mode cuts everything after 2022-12-31 (protocol amendment 1).

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.crypto --build
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.crypto
"""

from __future__ import annotations

import argparse
import json

import duckdb
import numpy as np
import pandas as pd

from research.breadth_lab.lab import stats
from research.breadth_lab.panel import ALPHAFORGE, CACHE

SPOT = ALPHAFORGE / "data" / "lake_spot" / "ohlcv"
PERP = ALPHAFORGE / "data" / "lake" / "ohlcv"
FUNDING = ALPHAFORGE / "data" / "lake" / "funding"
SEARCH_END = pd.Timestamp("2022-12-31", tz="UTC")
TARGET_VOL, MAX_LEVERAGE = 0.10, 2.0


def build() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    daily = """SELECT split_part(instrument_id, ':', 3) AS coin, CAST(date_trunc('day', ts_open) AS DATE) AS day,
                      arg_max(close, ts_open) AS close, sum(quote_volume) AS qv, count(*) AS bars
               FROM read_parquet('{path}/*/*/*.parquet') GROUP BY 1, 2"""
    spot = con.execute(daily.format(path=SPOT)).df()
    perp = con.execute(daily.format(path=PERP).replace("FROM read_parquet", "FROM read_parquet").replace("GROUP BY", "WHERE instrument_id LIKE 'BINANCE:PERP:%' GROUP BY")).df()
    fund = con.execute(f"""SELECT split_part(instrument_id, ':', 3) AS coin, CAST(date_trunc('day', ts_funding) AS DATE) AS day,
                                  sum(rate) AS funding, count(*) AS settlements
                           FROM read_parquet('{FUNDING}/*/*/*.parquet') GROUP BY 1, 2""").df()
    out = CACHE / "crypto"
    out.mkdir(parents=True, exist_ok=True)
    for name, f in (("spot", spot), ("perp", perp), ("funding", fund)):
        f["day"] = pd.to_datetime(f["day"], utc=True)
        f.to_parquet(out / f"{name}.parquet")
    print(json.dumps({"spot_coins": int(spot.coin.nunique()), "perp_coins": int(perp.coin.nunique()), "funding_coins": int(fund.coin.nunique()),
                      "spot_rows": len(spot), "perp_rows": len(perp), "funding_rows": len(fund)}))


def load(mode: str = "search") -> dict[str, pd.DataFrame]:
    d = CACHE / "crypto"
    wide = {}
    for name, col in (("spot", "close"), ("perp", "close"), ("funding", "funding")):
        f = pd.read_parquet(d / f"{name}.parquet")
        if name != "funding":
            f = f[f["bars"] >= 20]  # a day with most of its hours
            wide[f"{name}_qv"] = f.pivot(index="day", columns="coin", values="qv")
        wide[name] = f.pivot(index="day", columns="coin", values=col)
    coins = wide["spot"].columns.intersection(wide["perp"].columns).intersection(wide["funding"].columns)
    days = pd.date_range(wide["perp"].index.min(), wide["perp"].index.max(), freq="D", tz="UTC")
    if mode == "search":
        days = days[days <= SEARCH_END]
    return {k: v.reindex(index=days, columns=coins) for k, v in wide.items()}


def sleeves(w: dict[str, pd.DataFrame], lookback: int = 7, threshold: float = 0.0, cost_major: float = 0.0015,
            cost_minor: float = 0.0030, min_perp_qv: float = 2e7) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Per-coin daily return (net, before costs) at TARGET_VOL, and the on/off state."""
    rs, rp, f = w["spot"].pct_change(fill_method=None), w["perp"].pct_change(fill_method=None), w["funding"].fillna(0.0)
    liquid = w["perp_qv"].rolling(30, min_periods=20).median() >= min_perp_qv
    signal = (f.rolling(lookback, min_periods=lookback).mean() > threshold) & liquid & w["spot"].notna() & w["perp"].notna()
    on = signal.astype(float).shift(2).fillna(0.0)               # decide at the close, trade next close, earn after
    carry = (rs - rp).fillna(0.0) + f                              # long spot, short perp, funding received
    gross = on * carry
    switches = on.diff().abs().fillna(on)
    big = w["perp_qv"].rolling(30, min_periods=20).median() >= 2e8
    cost = switches * np.where(big, cost_major, cost_minor) * 2.0  # both legs
    net = gross - cost
    vol = gross.where(on > 0).rolling(90, min_periods=30).std() * np.sqrt(365)
    lev = (TARGET_VOL / vol.shift(1)).clip(upper=MAX_LEVERAGE).ffill().fillna(0.0)
    active = on > 0
    return (net * lev).where(active), (gross * lev).where(active), on


def summary(net: pd.DataFrame, gross: pd.DataFrame, on: pd.DataFrame) -> dict:
    used = net.columns[net.notna().sum() >= 60]
    net, gross = net[used], gross[used]
    book_net = net.mean(axis=1)
    book_gross = gross.mean(axis=1)
    weekly = net.resample("W").sum(min_count=3)
    cm = weekly.corr(min_periods=26).to_numpy()
    off = cm[~np.eye(len(cm), dtype=bool)]
    ann = lambda x: stats(x, periods=365)  # noqa: E731  (crypto trades every day)
    return {"coins_with_a_sleeve": int(len(used)), "avg_coins_on": round(float((on[used] > 0).sum(axis=1).mean()), 1),
            "avg_pairwise_corr_weekly": round(float(np.nanmean(off)), 3),
            "book_net_equal_weight": ann(book_net.dropna()), "book_before_costs": ann(book_gross.dropna()).get("sharpe")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    if a.build:
        build()
    else:
        w = load("search")
        for lb, th in ((7, 0.0), (7, 0.0001), (30, 0.0), (3, 0.0003)):
            n, g, on = sleeves(w, lookback=lb, threshold=th)
            print(json.dumps({"lookback": lb, "threshold_per_day": th, **summary(n, g, on)}), flush=True)
