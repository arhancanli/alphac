#!/usr/bin/env python3
"""FX CARRY first-cut screen — does the rate-differential carry premium have a real edge for us?

The companion to fx_trend_screen.py (which came back flat, -0.035). Carry is the *documented* FX
premium: long high-rate currencies, short low-rate ones, collect the interest differential and bet
it isn't fully eaten by spot depreciation. The honest "screen before you build" step for the FX
sleeve's strongest leg.

Mechanics (all expressed in USD-per-1-unit-of-foreign so a price RISE = the long gains):
  - spot vs USD from Yahoo (free, ~10y daily); USDxxx pairs inverted to xxx-in-USD.
  - short rate per currency from FRED's no-key CSV endpoint (fredgraph.csv?id=...). We TRY a list of
    candidate series per currency and keep whichever returns fresh data — robust to FRED's
    discontinued OECD series. Whatever loads is printed so the read is transparent.
  - carry signal_c = rate_c - rate_USD ; cross-sectionally demeaned -> dollar-neutral weights.
  - daily book return = sum_c w_c * (dlog spot_c + carry_c/252), net of cost on weight turnover.

Carry is KNOWN to be negatively skewed (it crashes in risk-off). The test is whether the premium
pays for that crash risk: net Sharpe AND skew together. Standalone — urllib + numpy + pandas only.
Usage: fx_carry_screen.py
"""
# ruff: noqa: E501
from __future__ import annotations

import io
import json
import urllib.request

import numpy as np
import pandas as pd

# currency -> (yahoo pair, invert? so we always end at xxx-in-USD)
FX = {
    "EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False),
    "NZD": ("NZDUSD", False), "JPY": ("USDJPY", True), "CAD": ("USDCAD", True),
    "CHF": ("USDCHF", True), "NOK": ("USDNOK", True), "SEK": ("USDSEK", True),
}
# candidate FRED short-rate series per currency (tried in order; first with fresh data wins).
# mix of 3m-Treasury / interbank / immediate-rate so at least one is current per country.
RATES = {
    "USD": ["DGS3MO", "IR3TIB01USM156N", "IRSTCI01USM156N"],
    "EUR": ["IR3TIB01EZM156N", "IRSTCI01EZM156N", "ECBDFR"],
    "GBP": ["IR3TIB01GBM156N", "IRSTCI01GBM156N", "IUDSOIA"],
    "JPY": ["IR3TIB01JPM156N", "IRSTCI01JPM156N", "INTDSRJPM193N"],
    "AUD": ["IR3TIB01AUM156N", "IRSTCI01AUM156N", "IR3TBB01AUM156N"],
    "CAD": ["IR3TIB01CAM156N", "IRSTCI01CAM156N", "IR3TBB01CAM156N"],
    "CHF": ["IR3TIB01CHM156N", "IRSTCI01CHM156N"],
    "NZD": ["IR3TIB01NZM156N", "IRSTCI01NZM156N"],
    "NOK": ["IR3TIB01NOM156N", "IRSTCI01NOM156N"],
    "SEK": ["IR3TIB01SEM156N", "IRSTCI01SEM156N"],
}
_COST_BPS = 1.5   # FX round-trip, conservative for majors


def _get(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except Exception as e:
        print(f"    fetch failed: {str(e)[:60]}")
        return None


def _yahoo_spot(pair: str, invert: bool) -> pd.Series | None:
    raw = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}=X?range=10y&interval=1d")
    if raw is None:
        return None
    try:
        res = json.loads(raw)["chart"]["result"][0]
        s = pd.Series(res["indicators"]["quote"][0]["close"],
                      index=pd.to_datetime(res["timestamp"], unit="s").date).dropna()
        s = s[~s.index.duplicated(keep="last")]
        return (1.0 / s) if invert else s
    except Exception as e:
        print(f"    parse failed {pair}: {str(e)[:50]}")
        return None


def _fred(series_ids: list[str], ccy: str) -> pd.Series | None:
    """Try each candidate series; keep the first that returns data fresh within ~9 months."""
    for sid in series_ids:
        raw = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
        if raw is None:
            continue
        try:
            df = pd.read_csv(io.BytesIO(raw))
            df.columns = ["date", "val"]
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["val"] = pd.to_numeric(df["val"], errors="coerce")
            s = df.dropna().set_index("date")["val"]
            if len(s) < 24:
                continue
            last = pd.Timestamp(s.index[-1])
            fresh = (pd.Timestamp("2026-06-01") - last).days < 280
            print(f"    {ccy}: {sid}  ({len(s)} obs, last {s.index[-1]}, latest {s.iloc[-1]:.2f}%"
                  f"{'' if fresh else '  STALE->skip'})")
            if fresh:
                return s
        except Exception as e:
            print(f"    {ccy}: {sid} parse failed ({str(e)[:40]})")
    print(f"    {ccy}: NO fresh rate series -> dropped")
    return None


def main() -> int:
    print("=== pulling FX spot (Yahoo) ===")
    spot = {c: _yahoo_spot(p, inv) for c, (p, inv) in FX.items()}
    spot = {c: s for c, s in spot.items() if s is not None and len(s) > 300}
    print(f"  spot loaded: {sorted(spot)}")

    print("=== pulling short rates (FRED, no key) ===")
    rates = {c: _fred(RATES[c], c) for c in (["USD"] + list(spot))}
    if rates.get("USD") is None:
        print("  FATAL: no USD base rate -> cannot compute differentials")
        return 1
    ccys = [c for c in spot if rates.get(c) is not None]
    if len(ccys) < 4:
        print(f"  too few currencies with both spot+rate ({ccys}) -> screen inconclusive")
        return 1
    print(f"  usable currencies: {ccys}")

    # daily panels
    px = pd.DataFrame({c: spot[c] for c in ccys}).sort_index().ffill().dropna(how="all")
    idx = pd.to_datetime(px.index)
    px.index = idx
    # rates: monthly/irregular -> reindex onto daily, ffill (carry is slow; PIT-safe: only past obs)
    usd_r = pd.Series(rates["USD"].values, index=pd.to_datetime(rates["USD"].index)).sort_index()
    rate_df = pd.DataFrame({
        c: pd.Series(rates[c].values, index=pd.to_datetime(rates[c].index)).sort_index()
        for c in ccys
    }).reindex(px.index, method="ffill")
    usd_daily = usd_r.reindex(px.index, method="ffill")
    carry = rate_df.sub(usd_daily, axis=0) / 100.0   # decimal annual differential vs USD

    logpx = np.log(px)
    ret = logpx.diff()
    daily_carry = carry / 252.0
    total_ret = ret.add(daily_carry, fill_value=0.0)  # spot move + accrued carry

    z = carry.sub(carry.mean(axis=1), axis=0)                 # cross-sectional demean -> $-neutral
    w = z.div(z.abs().sum(axis=1), axis=0).fillna(0.0)        # gross-normalized
    gross = (w.shift(1) * total_ret).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    net = (gross - _COST_BPS * 1e-4 * turn).dropna()
    net = net[net.index >= (px.index[0] + pd.Timedelta(days=60))]  # drop warmup

    ann = np.sqrt(252)
    sd = net.std(ddof=1)
    sharpe = float(net.mean() / sd * ann) if sd > 0 else float("nan")
    gsd = (gross.reindex(net.index)).std(ddof=1)
    gsharpe = float(gross.reindex(net.index).mean() / gsd * ann) if gsd > 0 else float("nan")
    vol = float(sd * ann)
    cum = net.cumsum()
    maxdd = float((cum.cummax() - cum).max())
    sk = float(((net - net.mean()) ** 3).mean() / net.std(ddof=0) ** 3)
    ann_turn = float(turn.reindex(net.index).sum() / (len(net) / 252))
    print("\n=== FX CARRY (cross-sectional rate-diff vs USD, dollar-neutral, net of 1.5bp) ===")
    print(f"  window      : {net.index[0].date()} .. {net.index[-1].date()}  ({len(net)} days, {len(ccys)} ccys)")
    print(f"  gross Sharpe: {gsharpe:.3f}")
    print(f"  net Sharpe  : {sharpe:.3f}")
    print(f"  ann vol     : {vol:.3f}")
    print(f"  maxDD (ret) : {maxdd:.3f}")
    print(f"  skew        : {sk:.2f}   (carry is EXPECTED to be negative; question is whether the premium pays for it)")
    print(f"  ann turnover: {ann_turn:.1f}x")
    print("\n  NOTE: crude prototype (raw spot + monthly rates, not the engine's PIT/cost discipline). A real read needs the full gauntlet.")
    print("  Build signal: net Sharpe > ~0.3 AND skew not catastrophic (> ~-1.5) -> FX carry worth the full sleeve build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
