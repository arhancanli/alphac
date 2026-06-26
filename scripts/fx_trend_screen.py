#!/usr/bin/env python3
"""FX TREND first-cut screen — does cross-sectional currency trend have a real edge for us?

The honest "screen before you build" step for the FX sleeve (the prototype, NOT yet engine-
integrated). Pulls ~16 FX majors/crosses from Yahoo (free, ~10y daily), computes 12-1 trend per
pair, builds a dollar-neutral long-top / short-bottom book net of a realistic FX round-trip cost,
and reports the net Sharpe + skew. If the signal is there at this crude level, it's worth the full
sleeve build (carry + value + the gauntlet); if it's flat net of cost, we've learned that cheaply.
Standalone — uses only urllib + numpy + pandas. Usage: fx_trend_screen.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import urllib.request

import numpy as np
import pandas as pd

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
         "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF", "EURAUD", "USDNOK", "USDSEK", "USDMXN"]
_COST_BPS = 1.5   # FX round-trip is tight; majors ~0.5-2bp. conservative.
_LOOKBACK, _SKIP = 252, 21  # 12-1 trend


def _yahoo(pair: str) -> pd.Series | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}=X?range=10y&interval=1d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
        s = pd.Series(close, index=pd.to_datetime(ts, unit="s").date, name=pair).dropna()
        return s[~s.index.duplicated(keep="last")]
    except Exception as e:
        print(f"  {pair}: fetch failed ({str(e)[:50]})")
        return None


def main() -> int:
    cols = {p: _yahoo(p) for p in PAIRS}
    cols = {p: s for p, s in cols.items() if s is not None and len(s) > _LOOKBACK + 60}
    px = pd.DataFrame(cols).sort_index().ffill().dropna(how="all")
    print(f"FX panel: {px.shape[1]} pairs, {len(px)} days, {px.index[0]}..{px.index[-1]}")

    logpx = np.log(px)
    # 12-1 trend per pair (USD-base sign is arbitrary across pairs, so this is a CS-ranked book)
    signal = logpx.shift(_SKIP) - logpx.shift(_LOOKBACK)
    z = signal.sub(signal.mean(axis=1), axis=0)  # cross-sectional demean -> dollar-neutral
    w = z.div(z.abs().sum(axis=1), axis=0).fillna(0.0)  # gross-normalized weights
    ret = np.log(px).diff()
    gross = (w.shift(1) * ret).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - _COST_BPS * 1e-4 * turn).dropna()
    net = net.iloc[_LOOKBACK:]  # drop warmup

    ann = np.sqrt(252)
    sharpe = float(net.mean() / net.std(ddof=1) * ann) if net.std(ddof=1) > 0 else float("nan")
    vol = float(net.std(ddof=1) * ann)
    cum = net.cumsum()
    maxdd = float((cum.cummax() - cum).max())
    sk = float(((net - net.mean()) ** 3).mean() / net.std(ddof=0) ** 3)
    print("\n=== FX TREND (cross-sectional 12-1, dollar-neutral, net of 1.5bp cost) ===")
    print(f"  net Sharpe : {sharpe:.3f}")
    print(f"  ann vol    : {vol:.3f}")
    print(f"  maxDD (ret): {maxdd:.3f}")
    print(f"  skew       : {sk:.2f}   (FX trend should NOT be deeply negative — unlike carry)")
    print(f"  ann turnover: {float(turn.iloc[_LOOKBACK:].sum()/ (len(net)/252)):.1f}x")
    print("\n  NOTE: crude prototype, raw price (not the engine's PIT/cost discipline). A real read needs the full gauntlet.")
    print("  If Sharpe > ~0.3 and skew is not catastrophic, FX TREND is worth the full sleeve build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
