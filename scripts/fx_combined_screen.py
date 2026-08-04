#!/usr/bin/env python3
"""FX COMBINED screen — the decisive read: carry + trend together, the real FX construction.

Carry alone (fx_carry_screen) = 0.20 Sharpe / -2.76 skew; trend alone (fx_trend_screen) = flat.
But the professional FX book runs them TOGETHER: trend is negatively correlated to carry and is
supposed to cut carry's left tail (it shorts the currencies that are crashing). This pulls data
once and reports four books so we see the whole picture in one shot:
  1. carry-only        2. trend-only        3. 50/50 z-blend        4. trend-overlaid carry
If even the blend can't clear ~0.3 Sharpe with a non-catastrophic skew, FX is honestly not worth a
full sleeve this decade and we pivot to managed-futures. urllib + numpy + pandas only.
"""
# ruff: noqa: E501
from __future__ import annotations

import io
import json
import urllib.request

import numpy as np
import pandas as pd

FX = {
    "EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False),
    "NZD": ("NZDUSD", False), "JPY": ("USDJPY", True), "CAD": ("USDCAD", True),
    "CHF": ("USDCHF", True), "NOK": ("USDNOK", True), "SEK": ("USDSEK", True),
}
RATES = {
    "USD": ["DGS3MO"], "EUR": ["IR3TIB01EZM156N"], "GBP": ["IR3TIB01GBM156N"],
    "JPY": ["IR3TIB01JPM156N"], "AUD": ["IR3TIB01AUM156N"], "CAD": ["IR3TIB01CAM156N"],
    "CHF": ["IR3TIB01CHM156N"], "NZD": ["IR3TIB01NZM156N"], "NOK": ["IR3TIB01NOM156N"],
    "SEK": ["IR3TIB01SEM156N"],
}
_COST_BPS = 1.5
_LB, _SKIP = 252, 21


def _get(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except Exception:
        return None


def _spot(pair: str, invert: bool) -> pd.Series | None:
    raw = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}=X?range=10y&interval=1d")
    if raw is None:
        return None
    try:
        res = json.loads(raw)["chart"]["result"][0]
        s = pd.Series(res["indicators"]["quote"][0]["close"],
                      index=pd.to_datetime(res["timestamp"], unit="s").date).dropna()
        s = s[~s.index.duplicated(keep="last")]
        return (1.0 / s) if invert else s
    except Exception:
        return None


def _fred(sid: str) -> pd.Series | None:
    raw = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
    if raw is None:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = ["date", "val"]
        df["date"] = pd.to_datetime(df["date"])
        df["val"] = pd.to_numeric(df["val"], errors="coerce")
        return df.dropna().set_index("date")["val"]
    except Exception:
        return None


def _book(signal: pd.DataFrame, total_ret: pd.DataFrame, idx0) -> dict:
    z = signal.sub(signal.mean(axis=1), axis=0)
    w = z.div(z.abs().sum(axis=1), axis=0).fillna(0.0)
    gross = (w.shift(1) * total_ret).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - _COST_BPS * 1e-4 * turn).dropna()
    net = net[net.index >= idx0]
    ann = np.sqrt(252)
    sd = net.std(ddof=1)
    cum = net.cumsum()
    return {
        "sharpe": float(net.mean() / sd * ann) if sd > 0 else float("nan"),
        "vol": float(sd * ann),
        "maxdd": float((cum.cummax() - cum).max()),
        "skew": float(((net - net.mean()) ** 3).mean() / net.std(ddof=0) ** 3),
        "turn": float(turn.reindex(net.index).sum() / (len(net) / 252)),
        "net": net,
    }


def main() -> int:
    spot = {c: _spot(p, inv) for c, (p, inv) in FX.items()}
    spot = {c: s for c, s in spot.items() if s is not None and len(s) > 300}
    usd = _fred(RATES["USD"][0])
    rates = {c: _fred(RATES[c][0]) for c in spot}
    ccys = [c for c in spot if rates.get(c) is not None and len(rates[c]) > 24]
    print(f"FX combined: {len(ccys)} ccys {ccys}")

    px = pd.DataFrame({c: spot[c] for c in ccys}).sort_index().ffill().dropna(how="all")
    px.index = pd.to_datetime(px.index)
    rate_df = pd.DataFrame({c: rates[c].sort_index() for c in ccys}).reindex(px.index, method="ffill")
    usd_d = usd.sort_index().reindex(px.index, method="ffill")
    carry = rate_df.sub(usd_d, axis=0) / 100.0

    logpx = np.log(px)
    ret = logpx.diff()
    total_ret = ret.add(carry / 252.0, fill_value=0.0)
    trend = logpx.shift(_SKIP) - logpx.shift(_LB)
    idx0 = px.index[0] + pd.Timedelta(days=300)

    # cross-sectional z-scores for blending
    def zc(df):
        m = df.sub(df.mean(axis=1), axis=0)
        return m.div(m.std(axis=1).replace(0, np.nan), axis=0)
    z_carry, z_trend = zc(carry), zc(trend)
    blend = (z_carry + z_trend) / 2.0
    # trend-overlay: take carry, but zero any position trend strongly opposes (opposite sign + |z|>0.5)
    overlay = carry.where(~((np.sign(z_carry) != np.sign(z_trend)) & (z_trend.abs() > 0.5)), 0.0)

    books = {
        "carry-only ": _book(carry, total_ret, idx0),
        "trend-only ": _book(trend, total_ret, idx0),
        "50/50 blend": _book(blend, total_ret, idx0),
        "trend-overlay carry": _book(overlay, total_ret, idx0),
    }
    print(f"window {px.index[0].date()}..{px.index[-1].date()}, net of {_COST_BPS}bp\n")
    print(f"  {'book':22} {'netSharpe':>10} {'vol':>7} {'maxDD':>7} {'skew':>7} {'turn':>7}")
    for name, b in books.items():
        print(f"  {name:22} {b['sharpe']:>10.3f} {b['vol']:>7.3f} {b['maxdd']:>7.3f} {b['skew']:>7.2f} {b['turn']:>6.1f}x")
    # correlation of carry vs trend net returns (is trend a real hedge?)
    cc = books["carry-only "]["net"].align(books["trend-only "]["net"], join="inner")
    rho = float(np.corrcoef(cc[0], cc[1])[0, 1])
    print(f"\n  corr(carry, trend) net returns: {rho:+.2f}   (negative = trend hedges carry's crashes)")
    print("\n  VERDICT BAR: best book net Sharpe > ~0.3 AND skew > ~-1.5 -> FX sleeve worth building.")
    print("  Else: FX is a weak-decade null for us -> pivot breadth to managed-futures (data buy).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
