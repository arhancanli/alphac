#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 1: Alpaca (IEX feed) 1-minute history feasibility. READ-ONLY keys.

What this answers (free, $0):
  1. How far back does Alpaca's historical 1-min bar API (basic plan = IEX feed) go,
     per symbol (SPY QQQ TQQQ SQQQ SOXL)?  (limit=1, sort=asc from 2000 -> exact first bar)
  2. Coverage/quality for two sample weeks (2019-05-06.. and 2024-05-06..):
     bars per session, % of regular-session minutes with a bar, % of the LAST 30 MINUTES
     (15:30-16:00 ET) with a bar, volume share of the last 30 min.
  3. How noisy IEX minute closes are vs official daily closes. lake_mf dailies are Yahoo
     ADJUSTED closes, so the honest comparison is (a) close-to-close DAILY RETURNS
     (adjustment factor is constant between ex-div dates; the sample weeks contain no
     SPY/QQQ ex-div) and (b) level residual after ONE per-symbol-week scale factor k
     (median official/iex), reported in bps.

Writes (NEW paths only):
  data/research/intraday_probe/lake/alpaca_1min/{SYM}_{week}.parquet   raw pulled bars
  artifacts/sweep/intraday_feasibility/alpaca_report.json              the numbers

Usage:  uv run python scripts/probe_intraday_alpaca.py
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import os
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
LAKE_OUT = _ROOT / "data" / "research" / "intraday_probe" / "lake" / "alpaca_1min"
ART_OUT = _ROOT / "artifacts" / "sweep" / "intraday_feasibility"
LAKE_MF = _ROOT / "data" / "lake_mf"
LAKE_OUT.mkdir(parents=True, exist_ok=True)
ART_OUT.mkdir(parents=True, exist_ok=True)

DATA_URL = "https://data.alpaca.markets"
SYMBOLS = ["SPY", "QQQ", "TQQQ", "SQQQ", "SOXL"]
WEEKS = {
    "2019w": ("2019-05-06", "2019-05-11"),  # requested; empirically BEFORE history start -> documents the limit
    "2021w": ("2021-05-03", "2021-05-08"),  # early-history quality sample (history starts 2020-07-27)
    "2024w": ("2024-05-06", "2024-05-11"),
}
OFFICIAL_OVERLAP = ["SPY", "QQQ"]  # symbols with official (adjusted) dailies in lake_mf


def _keys() -> dict[str, str]:
    env = Path.home() / ".config" / "alphaforge" / "alpaca.env"
    kv = {}
    for line in env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    return {
        "APCA-API-KEY-ID": kv["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": kv["APCA_API_SECRET_KEY"],
    }


HEADERS = _keys()


def get_bars(symbol: str, start: str, end: str, limit: int = 10000, sort: str = "asc") -> pd.DataFrame:
    """Pull 1-min IEX bars, paginated. Times returned in UTC."""
    rows = []
    token = None
    with httpx.Client(timeout=30) as cli:
        while True:
            params = {
                "timeframe": "1Min", "start": start, "end": end, "limit": limit,
                "adjustment": "raw", "feed": "iex", "sort": sort,
            }
            if token:
                params["page_token"] = token
            r = cli.get(f"{DATA_URL}/v2/stocks/{symbol}/bars", params=params, headers=HEADERS)
            if r.status_code == 429:
                time.sleep(10)
                continue
            r.raise_for_status()
            js = r.json()
            rows.extend(js.get("bars") or [])
            token = js.get("next_page_token")
            if not token or limit == 1:
                break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trades", "vw": "vwap"})


def earliest_bar(symbol: str) -> str | None:
    df = get_bars(symbol, "2000-01-01", "2026-12-31", limit=1, sort="asc")
    return None if df.empty else str(df["t"].iloc[0])


def _load_official(sym: str) -> pd.Series:
    fs = sorted(glob.glob(str(LAKE_MF / f"ohlcv_1d/instrument_id=XUSE:CASH:{sym}USD/**/*.parquet"), recursive=True))
    if not fs:
        return pd.Series(dtype=float)
    df = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs]).sort_values("ts_open").drop_duplicates("ts_open")
    idx = pd.to_datetime(df["ts_open"]).dt.tz_localize(None).dt.normalize()
    return pd.Series(df["close"].to_numpy(float), index=idx)


def week_quality(df: pd.DataFrame) -> dict:
    """Coverage stats over regular sessions (09:30-16:00 ET)."""
    et = df["t"].dt.tz_convert("America/New_York")
    d = df.assign(et=et, day=et.dt.date, hm=et.dt.hour * 60 + et.dt.minute)
    reg = d[(d["hm"] >= 570) & (d["hm"] < 960)]  # 09:30 <= t < 16:00
    out = {"sessions": int(reg["day"].nunique())}
    per, last30_cov, last30_volshare, close_bar_1559 = [], [], [], []
    for _, g in reg.groupby("day"):
        per.append(len(g))
        l30 = g[g["hm"] >= 930]  # 15:30..15:59
        last30_cov.append(len(l30) / 30.0)
        vol = g["volume"].sum()
        last30_volshare.append(float(l30["volume"].sum() / vol) if vol > 0 else np.nan)
        close_bar_1559.append(bool((g["hm"] == 959).any()))
    out.update({
        "bars_per_session_median": float(np.median(per)) if per else 0.0,
        "bars_per_session_min": int(min(per)) if per else 0,
        "session_minute_coverage_median": round(float(np.median(per)) / 390.0, 4) if per else 0.0,
        "last30min_minute_coverage_median": round(float(np.median(last30_cov)), 4) if last30_cov else 0.0,
        "last30min_minute_coverage_min": round(float(min(last30_cov)), 4) if last30_cov else 0.0,
        "last30min_volume_share_median": round(float(np.nanmedian(last30_volshare)), 4) if last30_volshare else None,
        "final_minute_bar_present_days": int(sum(close_bar_1559)),
        "total_bars_incl_extended": int(len(df)),
    })
    return out


def iex_daily_close(df: pd.DataFrame) -> pd.Series:
    """Last minute-bar close in [15:55, 16:00) ET per session (the 'IEX close' proxy)."""
    et = df["t"].dt.tz_convert("America/New_York")
    d = df.assign(et=et, day=pd.to_datetime(et.dt.date), hm=et.dt.hour * 60 + et.dt.minute)
    d = d[(d["hm"] >= 955) & (d["hm"] < 960)]
    if d.empty:
        return pd.Series(dtype=float)
    last = d.sort_values("et").groupby("day").tail(1)
    return pd.Series(last["close"].to_numpy(float), index=pd.DatetimeIndex(last["day"]))


def tracking_error(sym: str, week_bars: pd.DataFrame) -> dict | None:
    off = _load_official(sym)
    if off.empty:
        return None
    iex = iex_daily_close(week_bars)
    if len(iex) < 3:
        return {"note": "too few IEX closes"}
    common = iex.index.intersection(off.index)
    if len(common) < 3:
        return {"note": "no official-daily overlap"}
    i, o = iex[common], off[common]
    # (a) close-to-close daily returns (immune to the constant adjustment factor)
    ri, ro = i.pct_change().dropna(), o.pct_change().dropna()
    ret_diff_bps = ((ri - ro).abs() * 1e4).dropna()
    # (b) level residual after one per-week scale factor
    k = float((o / i).median())
    lvl_bps = ((o / (i * k) - 1.0).abs() * 1e4)
    return {
        "days_compared": int(len(common)),
        "ret_absdiff_bps_median": round(float(ret_diff_bps.median()), 2),
        "ret_absdiff_bps_max": round(float(ret_diff_bps.max()), 2),
        "level_resid_bps_median": round(float(lvl_bps.median()), 2),
        "level_resid_bps_max": round(float(lvl_bps.max()), 2),
        "scale_factor_official_over_iex": round(k, 6),
    }


def main() -> int:
    report: dict = {"probe": "alpaca_iex_1min_feasibility", "feed": "iex", "plan": "basic/free",
                    "generated_utc": pd.Timestamp.utcnow().isoformat()}

    print("== earliest available 1-min bar per symbol (feed=iex) ==")
    report["earliest_bar"] = {}
    for s in SYMBOLS:
        try:
            eb = earliest_bar(s)
        except httpx.HTTPStatusError as e:
            eb = f"HTTP {e.response.status_code}: {e.response.text[:120]}"
        report["earliest_bar"][s] = eb
        print(f"  {s:5s}: {eb}")

    report["weeks"] = {}
    for wk, (a, b) in WEEKS.items():
        report["weeks"][wk] = {}
        for s in SYMBOLS:
            try:
                df = get_bars(s, a, b)
            except httpx.HTTPStatusError as e:
                report["weeks"][wk][s] = {"error": f"HTTP {e.response.status_code}: {e.response.text[:120]}"}
                continue
            if df.empty:
                report["weeks"][wk][s] = {"error": "no bars returned"}
                print(f"  {wk} {s}: NO BARS")
                continue
            df.to_parquet(LAKE_OUT / f"{s}_{wk}.parquet", index=False)
            q = week_quality(df)
            te = tracking_error(s, df) if s in OFFICIAL_OVERLAP else None
            report["weeks"][wk][s] = {"quality": q, "tracking_vs_official": te}
            print(f"  {wk} {s:5s}: bars/sess(med)={q['bars_per_session_median']:.0f} "
                  f"cov={q['session_minute_coverage_median']:.0%} last30cov={q['last30min_minute_coverage_median']:.0%} "
                  f"{'te(ret med bps)=' + str(te['ret_absdiff_bps_median']) if te and 'ret_absdiff_bps_median' in te else ''}")

    report["notes"] = [
        "lake_mf dailies are Yahoo ADJUSTED closes -> tracking is return-based + scale-normalized level; sample weeks have no SPY/QQQ ex-div.",
        "IEX venue is ~2-3% of consolidated volume; no official closing auction print on this feed.",
        "TQQQ/SQQQ/SOXL have no official dailies on disk; only coverage stats reported for them.",
    ]
    (ART_OUT / "alpaca_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nreport -> {ART_OUT / 'alpaca_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
