#!/usr/bin/env python3
"""MANAGED-FUTURES TREND screen — the real breadth lever, prototyped on FREE ETF proxies.

Existing-data factors are tapped (null/marginal) and FX is a fragile null. The one breadth lever
left is managed-futures trend: time-series momentum (TSMOM) across a diversified basket of rates +
commodities + equity-index + FX. It's the most-documented systematic premium there is (40+yr of CTA
evidence), it has POSITIVE skew (long convexity — makes money in crises), and ~0 equity beta. But
it needs a ~$270/yr futures-data buy. So we do the FX discipline: screen on free ETF proxies FIRST.
If trend-on-a-diversified-basket is robustly positive-Sharpe / positive-skew / low-equity-beta here,
the data buy is justified and we build it. If weak, we learned it for free.

Construction = canonical Moskowitz-Ooi-Pedersen TSMOM, deliberately NOT knob-tuned (the FX lesson):
  - signal_i = mean over horizons {63,126,252} of sign(logP_t - logP_{t-h})   (multi-horizon, robust)
  - vol-scale each leg to equal risk (inverse 60d realized vol), then equal-weight the basket
  - net of 3bp ETF round-trip on turnover
Report net Sharpe, skew (expect POSITIVE — the opposite of carry), and correlation to SPY (expect ~0).
urllib + numpy + pandas only.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import urllib.request

import numpy as np
import pandas as pd

# diversified basket across 4 asset classes (liquid ETFs, long clean Yahoo history)
BASKET = {
    "equity": ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    "rates":  ["IEF", "TLT", "SHY"],
    "commod": ["GLD", "SLV", "USO", "DBC", "DBA", "UNG"],
    "fx":     ["UUP", "FXE", "FXY"],
}
ALL = [t for v in BASKET.values() for t in v]
_HORIZONS = [63, 126, 252]
_VOLWIN = 60
_COST_BPS = 3.0
_TGT_LEG_VOL = 0.10  # per-leg annual vol target before equal-weighting


def _close(ticker: str) -> pd.Series | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=20y&interval=1d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.loads(r.read())["chart"]["result"][0]
        # adjusted close if available (handles distributions) else raw close
        q = res["indicators"]["quote"][0]["close"]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") if "adjclose" in res["indicators"] else None
        vals = adj if adj is not None else q
        s = pd.Series(vals, index=pd.to_datetime(res["timestamp"], unit="s").date).dropna()
        return s[~s.index.duplicated(keep="last")]
    except Exception as e:
        print(f"  {ticker}: fetch failed ({str(e)[:40]})")
        return None


def _stats(net):
    ann = np.sqrt(252)
    sd = net.std(ddof=1)
    cum = net.cumsum()
    return {
        "sharpe": float(net.mean() / sd * ann) if sd > 0 else float("nan"),
        "vol": float(sd * ann),
        "maxdd": float((cum.cummax() - cum).max()),
        "skew": float(((net - net.mean()) ** 3).mean() / net.std(ddof=0) ** 3),
    }


def tsmom_book(px: pd.DataFrame, cols, cost_bps=_COST_BPS):
    logpx = np.log(px[cols])
    ret = logpx.diff()
    # multi-horizon sign signal in [-1,1]
    sig = sum(np.sign(logpx - logpx.shift(h)) for h in _HORIZONS) / len(_HORIZONS)
    vol = ret.rolling(_VOLWIN).std() * np.sqrt(252)
    lever = (_TGT_LEG_VOL / vol).clip(upper=5.0)            # inverse-vol scaling, capped
    w = (sig * lever).fillna(0.0)
    w = w.div(len(cols))                                    # equal-weight the basket
    gross = (w.shift(1) * ret).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - cost_bps * 1e-4 * turn).dropna()
    return net, turn


def main():
    print(f"=== pulling {len(ALL)} ETF proxies (Yahoo, 20y) ===")
    closes = {t: _close(t) for t in ALL}
    closes = {t: s for t, s in closes.items() if s is not None and len(s) > 300}
    px = pd.DataFrame(closes).sort_index()
    px.index = pd.to_datetime(px.index)
    px = px.ffill().dropna(how="all")
    have = list(px.columns)
    print(f"  loaded {len(have)}: {have}")
    # require ~5y common history for the full-basket book
    px_full = px.dropna()
    spy_ret = np.log(px["SPY"]).diff() if "SPY" in px else None

    print(f"\n=== MANAGED-FUTURES TSMOM (multi-horizon, vol-scaled, net {_COST_BPS}bp) ===")
    print(f"  {'book':16} {'window':24} {'netSharpe':>10} {'vol':>6} {'maxDD':>7} {'skew':>7} {'corrSPY':>8}")
    # full diversified basket (common-history window)
    results = {}
    for name, cols in [("FULL basket", have)] + [(f"{k} only", [c for c in v if c in have]) for k, v in BASKET.items()]:
        cols = [c for c in cols if c in have]
        if len(cols) < 2:
            continue
        net, _ = tsmom_book(px, cols)
        net = net[net.index >= (net.index[0] + pd.Timedelta(days=300))]
        st = _stats(net)
        corr = ""
        if spy_ret is not None:
            a, b = net.align(spy_ret, join="inner")
            corr = f"{float(np.corrcoef(a, b)[0,1]):+.2f}"
        results[name] = (net, st)
        print(f"  {name:16} {str(net.index[0].date())+'..'+str(net.index[-1].date()):24} "
              f"{st['sharpe']:>10.3f} {st['vol']:>6.3f} {st['maxdd']:>7.3f} {st['skew']:>7.2f} {corr:>8}")

    # robustness on the FULL basket: cost + sub-period (the FX lesson — stress before believing)
    net_full = results["FULL basket"][0]
    print("\n  cost sensitivity (FULL basket):")
    for cb in [3.0, 6.0, 10.0]:
        net, _ = tsmom_book(px, have, cost_bps=cb)
        net = net[net.index >= (net.index[0] + pd.Timedelta(days=300))]
        print(f"    {cb:>4.1f}bp -> Sharpe {_stats(net)['sharpe']:>6.3f}")
    mid = net_full.index[len(net_full) // 2]
    for lbl, seg in [("first half", net_full[net_full.index < mid]), ("second half", net_full[net_full.index >= mid])]:
        st = _stats(seg)
        print(f"    {lbl:11} {seg.index[0].date()}..{seg.index[-1].date()}  Sharpe {st['sharpe']:>6.3f}  skew {st['skew']:>6.2f}")

    print("\n  BUILD BAR: FULL-basket net Sharpe > ~0.4, skew POSITIVE (or >~-0.5), corrSPY ~0, both halves +,")
    print("  survives 6bp -> managed-futures sleeve justifies the ~$270/yr futures-data buy. Else reconsider.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
