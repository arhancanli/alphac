#!/usr/bin/env python3
"""Crypto VRP (vol-risk-premium) probe — is selling crypto vol a real, decorrelated sleeve?

The thesis: Deribit's DVOL (implied vol) sits systematically ABOVE subsequently-realized vol, so
SELLING vol harvests that gap. The danger: VRP is short the tail — you collect pennies for months,
then a crash (May-21, LUNA, FTX) hands realized vol >> implied and you lose years of premium in days.
So a Sharpe alone is a LIE for this strategy; this probe reports the tail (skew, worst day, max DD)
right next to it, and tests whether timing / a crash filter can dodge the steamroller.

Honest construction (no options in the backtester, so the canonical variance-swap proxy):
  daily short-variance P&L_t = IV_{t-1}^2 / 365   -   r_t^2
i.e. each day you collect the implied daily variance (the premium) and pay the realized (today's
squared return). Calm day -> small gain; crash day -> r_t^2 explodes -> catastrophic loss. That IS
the real VRP payoff, tail included. Costs: the collected IV is haircut by a conservative options
spread (Deribit option bid/ask is wide — the cost that kills naive VRP). All data is LOCAL & FREE
(DVOL from data/deribit/dvol_index, prices from the crypto lake). No Databento credit touched.
"""
# ruff: noqa: E501, E702
from __future__ import annotations

import glob
import math

import numpy as np
import pandas as pd

ANN = 365                  # crypto trades every day
SPLIT = "2023-09-01"       # ~midpoint of the DVOL history -> train/test walk-forward
COST_VOLPTS = 0.03         # conservative 3 vol-point round-trip spread haircut on collected premium
TGT_VOL = 0.10             # vol-target the P&L to 10%/yr so drawdown/worst-day are in real % terms


def _dates(ts: pd.Series) -> pd.Series:
    """Robust ts_open -> tz-naive day (the lake stores tz-aware UTC; the DVOL parquet stores int ms)."""
    dt = pd.to_datetime(ts, unit="ms") if np.issubdtype(np.asarray(ts).dtype, np.integer) else pd.to_datetime(ts)
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_localize(None)
    return dt.dt.floor("D")


def load_dvol(cur: str) -> pd.Series:
    d = pd.read_parquet(f"data/deribit/dvol_index/{cur}.parquet", columns=["ts_open", "close"])
    d["date"] = _dates(d["ts_open"])
    return d.groupby("date")["close"].last() / 100.0  # vol points -> decimal annualized vol


def load_close(sym: str) -> pd.Series:
    fs = glob.glob(f"data/lake/ohlcv_1d/instrument_id=BINANCE:PERP:{sym}/**/*.parquet", recursive=True)
    t = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs]).drop_duplicates("ts_open").sort_values("ts_open")
    t["date"] = _dates(t["ts_open"])
    return t.set_index("date")["close"]


def vrp_pnl(cur: str, sym: str, cost: float = COST_VOLPTS, signal: str = "always", crash_filter: bool = False) -> pd.Series:
    iv = load_dvol(cur)
    px = load_close(sym)
    df = pd.DataFrame({"iv": iv, "px": px}).dropna()
    r = np.log(df["px"] / df["px"].shift(1))
    df = df.assign(r=r).dropna()
    iv, r = df["iv"], df["r"]
    iv_lag = iv.shift(1)                                  # decide on yesterday's implied (no look-ahead)
    rv2 = r ** 2                                          # today's realized daily variance
    iv_net = (iv_lag - cost).clip(lower=0)               # premium net of the options spread
    daily = iv_net ** 2 / ANN - rv2                       # short-variance daily P&L (premium - realized)
    pos = pd.Series(1.0, index=iv.index)
    if signal == "timed":                                # only sell, and size, when implied is rich vs trailing realized
        rv_trail = r.rolling(20).std() * math.sqrt(ANN)
        pos = ((iv_lag - rv_trail) / iv_lag).clip(lower=0.0, upper=1.0).fillna(0.0)
    if crash_filter:                                     # flatten when short-term realized vol is spiking
        rv_fast = r.rolling(5).std() * math.sqrt(ANN)
        rv_slow = r.rolling(60).std() * math.sqrt(ANN)
        pos = pos.where(~(rv_fast > 1.5 * rv_slow), 0.0)
    return (daily * pos.shift(1).fillna(0.0)).dropna()    # position set on prior info too


def vol_target(pnl: pd.Series) -> pd.Series:
    """Scale to TGT_VOL using trailing 60d vol so worst-day / drawdown are in honest % terms."""
    s = (TGT_VOL / math.sqrt(ANN)) / pnl.rolling(60).std().replace(0, np.nan)
    return (pnl * s.clip(upper=5.0).shift(1)).dropna()


def stats(pnl: pd.Series) -> dict:
    e = vol_target(pnl)
    if len(e) < 50 or e.std() == 0:
        return {}
    cum = e.cumsum()
    dd = float((cum - cum.cummax()).min())
    return {
        "sharpe": float(e.mean() / e.std() * math.sqrt(ANN)),
        "skew": float(e.skew()),
        "worst_day_%": float(e.min() * 100),
        "maxDD_%": dd * 100,
        "pos_days_%": float((e > 0).mean() * 100),
    }


def combined(signal: str, crash_filter: bool, cost: float = COST_VOLPTS) -> pd.Series:
    b = vol_target(vrp_pnl("BTC", "BTCUSDT", cost, signal, crash_filter))
    e = vol_target(vrp_pnl("ETH", "ETHUSDT", cost, signal, crash_filter))
    return pd.concat([b, e], axis=1).mean(axis=1).dropna()


def row(label: str, pnl: pd.Series) -> None:
    s = stats(pnl)
    if not s:
        print(f"  {label:34} (insufficient)")
        return
    tr = pnl[pnl.index < SPLIT]; te = pnl[pnl.index >= SPLIT]
    sf = stats(tr).get("sharpe", float("nan")); st = stats(te).get("sharpe", float("nan"))
    print(f"  {label:34} SR {s['sharpe']:+.2f} (tr {sf:+.2f}/te {st:+.2f})  skew {s['skew']:+.1f}  worstday {s['worst_day_%']:+.1f}%  maxDD {s['maxDD_%']:.0f}%  pos {s['pos_days_%']:.0f}%")


def main() -> int:
    iv = load_dvol("BTC")
    print(f"DVOL history: {iv.index[0].date()} .. {iv.index[-1].date()}  ({len(iv)} days)\n")

    print("=== CRYPTO VRP — short variance, daily, net of a 3-vol-point spread ===")
    print("(Sharpe is NOT the whole story for VRP — read skew / worst-day / maxDD right next to it)\n")
    print("BTC + ETH combined sleeve:")
    row("always-short", combined("always", False))
    row("timed (sell only when rich)", combined("timed", False))
    row("always + crash filter", combined("always", True))
    row("timed + crash filter", combined("timed", True))
    print("\nper-leg (always-short):")
    row("BTC", vrp_pnl("BTC", "BTCUSDT"))
    row("ETH", vrp_pnl("ETH", "ETHUSDT"))

    # gross (no spread) to show how much the options spread eats
    print("\ncost sensitivity (always-short combined):")
    for c in (0.0, 0.03, 0.06):
        row(f"spread = {c*100:.0f} vol pts", combined("always", False, cost=c))

    # decorrelation: VRP's tail lands on crypto CRASH days — the same days crypto-carry (AlphaForge) bleeds
    print("\ndecorrelation check (the whole reason to add a sleeve):")
    base = vol_target(vrp_pnl("BTC", "BTCUSDT"))
    btc = load_close("BTCUSDT"); br = np.log(btc / btc.shift(1)).reindex(base.index)
    rho = float(base.corr(br))
    worst = base.nsmallest(10).index
    print(f"  corr(VRP daily P&L, BTC return): {rho:+.2f}")
    print(f"  BTC return on VRP's 10 worst days: mean {br.reindex(worst).mean()*100:+.1f}%  (if strongly negative -> VRP blows up exactly when crypto crashes = NOT decorrelated from the crypto book)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
