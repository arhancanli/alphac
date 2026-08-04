#!/usr/bin/env python3
"""FX trend-overlay-carry ROBUSTNESS — is the 0.32 Sharpe real or did I cherry-pick the knob?

The honest gate before committing days to engine integration. The combined screen found
trend-overlay carry = 0.32 Sharpe / -0.15 skew, but I hand-picked the overlay threshold (0.5) and
the cost (1.5bp). This stress-tests all of that:
  A. overlay-threshold sweep   (did 0.5 just happen to be the lucky knob?)
  B. cost sensitivity          (survives realistic FX costs?)
  C. sub-period stability      (works in BOTH halves of the decade, or one lucky stretch?)
  D. leave-one-currency-out    (one currency carrying the whole thing = fragile)
If it survives all four -> real, build it. If it craters on any -> it was an artifact.
urllib + numpy + pandas only.
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
RATES = {"USD": "DGS3MO", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N",
         "JPY": "IR3TIB01JPM156N", "AUD": "IR3TIB01AUM156N", "CAD": "IR3TIB01CAM156N",
         "CHF": "IR3TIB01CHM156N", "NZD": "IR3TIB01NZM156N", "NOK": "IR3TIB01NOM156N",
         "SEK": "IR3TIB01SEM156N"}
_LB, _SKIP = 252, 21


def _get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except Exception:
        return None


def _spot(pair, invert):
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


def _fred(sid):
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


def _stats(net):
    ann = np.sqrt(252)
    sd = net.std(ddof=1)
    cum = net.cumsum()
    return (float(net.mean() / sd * ann) if sd > 0 else float("nan"),
            float((cum.cummax() - cum).max()),
            float(((net - net.mean()) ** 3).mean() / net.std(ddof=0) ** 3))


def overlay_net(carry, z_carry, z_trend, total_ret, idx0, thr, cost_bps, ccys=None):
    if ccys is not None:
        carry, z_carry, z_trend, total_ret = (df[ccys] for df in (carry, z_carry, z_trend, total_ret))
    sig = carry.where(~((np.sign(z_carry) != np.sign(z_trend)) & (z_trend.abs() > thr)), 0.0)
    z = sig.sub(sig.mean(axis=1), axis=0)
    w = z.div(z.abs().sum(axis=1), axis=0).fillna(0.0)
    gross = (w.shift(1) * total_ret).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - cost_bps * 1e-4 * turn).dropna()
    return net[net.index >= idx0]


def main():
    spot = {c: _spot(p, inv) for c, (p, inv) in FX.items()}
    spot = {c: s for c, s in spot.items() if s is not None and len(s) > 300}
    usd = _fred(RATES["USD"])
    rates = {c: _fred(RATES[c]) for c in spot}
    ccys = [c for c in spot if rates.get(c) is not None and len(rates[c]) > 24]
    px = pd.DataFrame({c: spot[c] for c in ccys}).sort_index().ffill().dropna(how="all")
    px.index = pd.to_datetime(px.index)
    rate_df = pd.DataFrame({c: rates[c].sort_index() for c in ccys}).reindex(px.index, method="ffill")
    usd_d = usd.sort_index().reindex(px.index, method="ffill")
    carry = rate_df.sub(usd_d, axis=0) / 100.0
    logpx = np.log(px)
    total_ret = logpx.diff().add(carry / 252.0, fill_value=0.0)
    trend = logpx.shift(_SKIP) - logpx.shift(_LB)

    def zc(df):
        m = df.sub(df.mean(axis=1), axis=0)
        return m.div(m.std(axis=1).replace(0, np.nan), axis=0)
    z_carry, z_trend = zc(carry), zc(trend)
    idx0 = px.index[0] + pd.Timedelta(days=300)
    print(f"FX robustness: {len(ccys)} ccys, {px.index[0].date()}..{px.index[-1].date()}\n")

    print("A. overlay-threshold sweep (cost 1.5bp) — is 0.5 special?")
    print(f"   {'thr':>5} {'netSharpe':>10} {'maxDD':>7} {'skew':>7}")
    for thr in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]:
        s, dd, sk = _stats(overlay_net(carry, z_carry, z_trend, total_ret, idx0, thr, 1.5))
        print(f"   {thr:>5.2f} {s:>10.3f} {dd:>7.3f} {sk:>7.2f}")

    print("\nB. cost sensitivity (thr=0.5)")
    print(f"   {'bp':>5} {'netSharpe':>10}")
    for cb in [1.5, 3.0, 5.0, 8.0]:
        s, _, _ = _stats(overlay_net(carry, z_carry, z_trend, total_ret, idx0, 0.5, cb))
        print(f"   {cb:>5.1f} {s:>10.3f}")

    print("\nC. sub-period stability (thr=0.5, 1.5bp)")
    net = overlay_net(carry, z_carry, z_trend, total_ret, idx0, 0.5, 1.5)
    mid = net.index[len(net) // 2]
    for lbl, seg in [("first half", net[net.index < mid]), ("second half", net[net.index >= mid])]:
        s, dd, sk = _stats(seg)
        print(f"   {lbl:12} {seg.index[0].date()}..{seg.index[-1].date()}  Sharpe {s:>6.3f}  skew {sk:>6.2f}")

    print("\nD. leave-one-currency-out (thr=0.5, 1.5bp) — is one ccy carrying it?")
    print(f"   {'dropped':>8} {'netSharpe':>10}")
    base_s, _, _ = _stats(net)
    print(f"   {'(none)':>8} {base_s:>10.3f}")
    for c in ccys:
        keep = [x for x in ccys if x != c]
        s, _, _ = _stats(overlay_net(carry, z_carry, z_trend, total_ret, idx0, 0.5, 1.5, ccys=keep))
        print(f"   {c:>8} {s:>10.3f}")

    print("\n  READ: robust if threshold sweep stays >~0.25 across the plateau, survives 3-5bp,")
    print("  BOTH half-periods positive, and no single currency drop collapses it. Else fragile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
