"""Load the managed-futures ETF basket into a dedicated AlphaForge research lake.

The data step for the managed-futures TREND sleeve (the screen found net Sharpe 0.73, two-decade
stable, negative equity beta — see scripts/managed_futures_screen.py). ETFs ARE equities, so this
reuses the equity machinery verbatim; it just points at its own lake (data/lake_mf, var_mf) so it
coexists with crypto + the Sharadar equity lake.

Source = Yahoo daily, ADJUSTED (total-return: ratio = adjclose/close applied to OHL, close=adjclose)
so bond/equity-ETF dividends are included and NO corporate-action rows are needed — the engine then
uses the prices verbatim (no actions => no further adjustment). Research-lake only; the LIVE loop
would price these off Alpaca. Mirrors scripts/sharadar_load.py's lake/instrument/universe writes.

  uv run python scripts/mf_etf_load.py            # load the basket
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.symbols import EQUITY_MIC, SymbolMapper
from alphaforge.core.time import Timeframe, now_ms
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore

_TS = pa.timestamp("ms", tz="UTC")
_EQ_TICK, _EQ_LOT, _EQ_FEE_BPS = 0.01, 1.0, 1.0

# The diversified managed-futures basket (4 asset classes via liquid ETF proxies). The screen
# showed the FULL basket (0.73) beats every single asset class — diversification is the edge, so
# keep all four legs. USO/UNG carry futures roll-bleed; the trend book SHORTS them in their
# downtrends (it profits from the bleed) so they stay in the research basket.
BASKET = ["SPY", "QQQ", "IWM", "EFA", "EEM",    # equity index
          "IEF", "TLT", "SHY",                  # rates / Treasuries
          "GLD", "SLV", "USO", "DBC", "DBA", "UNG",  # commodities
          "UUP", "FXE", "FXY"]                   # FX


def _eid(ticker: str) -> str:
    return SymbolMapper.equity_instrument_id(EQUITY_MIC, ticker.upper())


def _yahoo_ohlcv(ticker: str) -> pd.DataFrame | None:
    """Daily ADJUSTED OHLCV from Yahoo. ratio=adjclose/close applied to OHL; close=adjclose."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=25y&interval=1d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read())["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"]["adjclose"][0]["adjclose"]
        df = pd.DataFrame({
            "ts": res["timestamp"], "open": q["open"], "high": q["high"],
            "low": q["low"], "close": q["close"], "adjclose": adj, "volume": q["volume"],
        }).dropna(subset=["open", "high", "low", "close", "adjclose"])
        # finite + positive (the backtest's BarView rejects non-finite OHLC)
        for c in ("open", "high", "low", "close", "adjclose"):
            df = df[np.isfinite(df[c]) & (df[c] > 0)]
        # ts -> UTC-midnight of the bar date (the equity D1 ts_open convention, matches sharadar)
        dt = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None).dt.normalize()
        df["ts_open"] = dt.to_numpy().astype("datetime64[ms]").astype("int64")
        df = df.drop_duplicates(subset="ts_open", keep="last").sort_values("ts_open")
        ratio = df["adjclose"] / df["close"]
        df["o"] = df["open"] * ratio
        df["h"] = df["high"] * ratio
        df["l"] = df["low"] * ratio
        df["c"] = df["adjclose"]
        df["vol"] = df["volume"].where(np.isfinite(df["volume"]) & (df["volume"] >= 0.0), 0.0)
        df["dollar"] = df["c"] * df["vol"]
        return df
    except Exception as e:
        print(f"  {ticker}: fetch failed ({str(e)[:60]})", flush=True)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake-dir", default="data/lake_mf")
    ap.add_argument("--var-dir", default="var_mf")
    args = ap.parse_args()
    now = now_ms()
    lake_dir, var_dir = Path(args.lake_dir), Path(args.var_dir)
    var_dir.mkdir(parents=True, exist_ok=True)
    writer = LakeWriter(LakePaths(lake_dir))

    intervals: list[dict] = []
    n_ok = 0
    # MF_EXTRA_TICKERS lets a RESEARCH run widen the basket (into a separate --lake-dir) without
    # touching the live 17-ETF BASKET. Default (no env var) = the unchanged 17.
    extra = [t.strip().upper() for t in os.environ.get("MF_EXTRA_TICKERS", "").split(",") if t.strip()]
    # MF_BASKET_OVERRIDE fully REPLACES the basket (e.g. a futures-only research run). Yahoo futures
    # are TICKER=F (ES=F, KC=F); we fetch with the =F ticker but store the clean symbol (ES, KC).
    override = [t.strip().upper() for t in os.environ.get("MF_BASKET_OVERRIDE", "").split(",") if t.strip()]
    basket = override if override else BASKET + [t for t in extra if t not in BASKET]
    # Yahoo futures volume is in CONTRACTS without the multiplier, so price*volume hugely understates
    # the true dollar ADV and the impact cost model spuriously rejects these (genuinely liquid) markets.
    # MF_VOLUME_FLOOR floors the dollar-volume to a conservative-real level for a futures research run.
    vol_floor = float(os.environ.get("MF_VOLUME_FLOOR", "0") or 0)
    with InstrumentStore(var_dir / "ops.sqlite") as store:
        for rank, ticker in enumerate(basket, start=1):
            df = _yahoo_ohlcv(ticker)
            if df is None or len(df) < 400:  # need >252 + warmup for the slow trend leg
                print(f"  {ticker}: SKIP (insufficient history)", flush=True)
                continue
            sym = ticker.split("=")[0]  # ES=F -> ES (the clean instrument symbol)
            iid = _eid(sym)
            m = len(df)
            tbl = pa.table({
                "instrument_id": pa.array([iid] * m, pa.string()),
                "ts_open": pa.array(df["ts_open"].to_numpy(), _TS),
                "open": pa.array(df["o"].to_numpy(), pa.float64()),
                "high": pa.array(df["h"].to_numpy(), pa.float64()),
                "low": pa.array(df["l"].to_numpy(), pa.float64()),
                "close": pa.array(df["c"].to_numpy(), pa.float64()),
                "volume": pa.array(df["vol"].to_numpy(), pa.float64()),
                "quote_volume": pa.array(np.maximum(df["dollar"].to_numpy(), vol_floor), pa.float64()),
                "n_trades": pa.array([None] * m, pa.int64()),
                "quality_flags": pa.array(np.zeros(m, np.int32), pa.int32()),
                "ingested_at": pa.array([now] * m, _TS),
            })
            writer.write(Dataset.OHLCV_1D, tbl, tf=Timeframe.D1, now=now)
            listed = int(df["ts_open"].iloc[0])
            store.upsert(Instrument(
                instrument_id=iid, asset_class=AssetClass.EQUITY, market_type=MarketType.CASH,
                base=sym.upper(), quote="USD", tick_size=_EQ_TICK, lot_size=_EQ_LOT,
                min_qty=_EQ_LOT, min_notional=0.0, contract_multiplier=1.0, can_short=True,
                maker_fee_bps=_EQ_FEE_BPS, taker_fee_bps=_EQ_FEE_BPS, funding_interval_hours=None,
                listed_ts=listed, delisted_ts=None), as_of=now)
            # fixed-basket membership: member from first bar, never leaves (effective_to=null)
            intervals.append({"instrument_id": iid, "effective_from": listed,
                              "effective_to": None, "rank": rank, "reason": "mf_basket"})
            print(f"  {ticker}: {m} bars  {df['ts_open'].iloc[0]}..{df['ts_open'].iloc[-1]}", flush=True)
            n_ok += 1

    uni = pa.table({
        "instrument_id": pa.array([r["instrument_id"] for r in intervals], pa.string()),
        "effective_from": pa.array([r["effective_from"] for r in intervals], _TS),
        "effective_to": pa.array([r["effective_to"] for r in intervals], _TS),
        "rank": pa.array([r["rank"] for r in intervals], pa.int32()),
        "reason": pa.array([r["reason"] for r in intervals], pa.string()),
    })
    UniverseStore(LakePaths(lake_dir)).write_intervals(uni, replace=True)
    print(f"LOAD COMPLETE: {n_ok}/{len(BASKET)} ETFs, fixed-basket universe written", flush=True)


if __name__ == "__main__":
    main()
