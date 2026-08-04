#!/usr/bin/env python3
"""Build back-adjusted continuous futures series from the raw Databento contracts, into a lake.

From data/lake_fut_db/contracts.parquet (raw individual CME contracts) builds, per root market, a
ratio-back-adjusted continuous series the trend gauntlet can run on:
  - active contract each day = the highest-VOLUME contract (Databento has no OI), rolled MONOTONICALLY
    forward in expiry order (never rolls backward), so the front is always the liquid contract;
  - RATIO back-adjustment at each roll: prices before the roll are scaled by new.close/old.close on the
    roll day, removing the contract-to-contract gap so trend returns are clean (not roll artifacts);
  - dollar-volume FLOORED to $100M (Yahoo/Databento futures volume is in contracts without the
    multiplier, so raw price*volume understates the true ADV; these are all liquid markets).

Writes data/lake_fut_real (OHLCV_1D + a fixed-basket universe) mirroring scripts/mf_etf_load.py so the
existing managed_futures gauntlet runs on it unchanged. Also keeps each root's front+next close for the
carry sleeve (data/lake_fut_real/carry_termstructure.parquet).
"""
# ruff: noqa: E501
from __future__ import annotations

import re
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

SRC = Path("data/lake_fut_db/contracts.parquet")
LAKE, VARD = Path("data/lake_fut_real"), Path("var_fut_real")
_TS = pa.timestamp("ms", tz="UTC")
_VOL_FLOOR = 1e8
_MONTHS = "FGHJKMNQUVXZ"


def _root(sym: str) -> str | None:
    m = re.match(r"^([0-9A-Z]+?)([FGHJKMNQUVXZ])(\d{1,2})$", sym)
    return m.group(1) if m else None


def build_continuous(close: pd.DataFrame, vol: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Ratio-back-adjusted continuous close + the active contract per day (contracts ordered by expiry)."""
    expiry = {c: close[c].last_valid_index() for c in close.columns}
    order = sorted(close.columns, key=lambda c: expiry[c])
    close, vol = close[order], vol[order].fillna(0.0)
    dates = close.index
    cur, active = 0, []
    for d in dates:
        trading = close.loc[d].notna()
        v = vol.loc[d].where(trading, 0.0)
        # standard volume-crossover roll: advance ONE contract at a time when the next is more liquid
        # (or the current has stopped trading) — never jump to a far contract on a volume spike.
        while cur + 1 < len(order):
            c0, c1 = order[cur], order[cur + 1]
            if (not trading[c0] and trading[c1]) or (trading[c1] and v[c1] > v[c0]):
                cur += 1
            else:
                break
        while cur < len(order) - 1 and not trading[order[cur]]:  # guarantee the active trades today
            cur += 1
        active.append(cur)
    # return-stitch: the continuous return each day is the HELD contract's WITHIN-contract return,
    # never spanning a roll or a data gap, so a bad print/roll can't manufacture a fake trend. Daily
    # returns winsorized at +/-25% (a real futures day is never bigger; anything larger is a glitch).
    rets = np.zeros(len(dates))
    for k in range(1, len(dates)):
        if active[k] == active[k - 1]:
            ac = order[active[k]]
            p0, p1 = close.loc[dates[k - 1], ac], close.loc[dates[k], ac]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                rets[k] = np.clip(p1 / p0 - 1.0, -0.25, 0.25)
    price = pd.Series(100.0 * np.cumprod(1.0 + rets), index=dates)
    return price, [order[a] for a in active]


def main() -> int:
    raw = pd.read_parquet(SRC)
    outr = raw[~raw["symbol"].str.contains("-", regex=False)].copy()
    outr["root"] = outr["symbol"].map(_root)
    outr = outr[outr["root"].notna()]
    roots = sorted(outr["root"].unique())
    print(f"{len(outr):,} outright bars, {len(roots)} roots\n")

    now = now_ms()
    VARD.mkdir(parents=True, exist_ok=True)
    writer = LakeWriter(LakePaths(LAKE))
    intervals, carry_rows, n_ok = [], [], 0
    with InstrumentStore(VARD / "ops.sqlite") as store:
        for rank, root in enumerate(roots, start=1):
            sub = outr[outr["root"] == root]
            close = sub.pivot_table(index=sub.index, columns="symbol", values="close")
            vol = sub.pivot_table(index=sub.index, columns="symbol", values="volume")
            if close.shape[1] < 2 or len(close) < 400:
                print(f"  {root}: SKIP (too few contracts/history)")
                continue
            cont, active = build_continuous(close, vol)
            if len(cont) < 400:
                print(f"  {root}: SKIP (continuous too short)")
                continue
            # carry: front vs the NEXT contract (the one after the active in expiry order), per day
            expiry = {c: close[c].last_valid_index() for c in close.columns}
            order = sorted(close.columns, key=lambda c: expiry[c])
            pos = {c: i for i, c in enumerate(order)}
            f0, f1, days = [], [], []
            for d, ac in zip(cont.index, [a for a, dt in zip(active, close.index) if dt in cont.index], strict=False):
                i = pos[ac]
                nxt = order[i + 1] if i + 1 < len(order) and pd.notna(close.loc[d, order[i + 1]]) else None
                f0.append(close.loc[d, ac]); f1.append(close.loc[d, nxt] if nxt else np.nan)
                days.append((expiry[nxt] - expiry[ac]).days if nxt else np.nan)
            carry_rows.append(pd.DataFrame({"date": cont.index, "root": root, "front": f0, "next": f1, "gap_days": days}))

            iid = SymbolMapper.equity_instrument_id(EQUITY_MIC, root.upper())
            df = pd.DataFrame({"c": cont.values}, index=cont.index)
            df["o"] = df["h"] = df["l"] = df["c"]  # daily continuous: use close for OHLC (trend uses close)
            m = len(df)
            ts_open = (df.index.asi8 // 1_000_000).astype("int64")
            tbl = pa.table({
                "instrument_id": pa.array([iid] * m, pa.string()),
                "ts_open": pa.array(ts_open, _TS),
                "open": pa.array(df["o"].to_numpy(), pa.float64()),
                "high": pa.array(df["h"].to_numpy(), pa.float64()),
                "low": pa.array(df["l"].to_numpy(), pa.float64()),
                "close": pa.array(df["c"].to_numpy(), pa.float64()),
                "volume": pa.array(np.full(m, 1e6), pa.float64()),
                "quote_volume": pa.array(np.full(m, _VOL_FLOOR), pa.float64()),
                "n_trades": pa.array([None] * m, pa.int64()),
                "quality_flags": pa.array(np.zeros(m, np.int32), pa.int32()),
                "ingested_at": pa.array([now] * m, _TS),
            })
            writer.write(Dataset.OHLCV_1D, tbl, tf=Timeframe.D1, now=now)
            listed = int(ts_open[0])
            store.upsert(Instrument(
                instrument_id=iid, asset_class=AssetClass.EQUITY, market_type=MarketType.CASH,
                base=root.upper(), quote="USD", tick_size=0.0001, lot_size=1.0,
                min_qty=1.0, min_notional=0.0, contract_multiplier=1.0, can_short=True,
                maker_fee_bps=0.5, taker_fee_bps=1.0, funding_interval_hours=None,
                listed_ts=listed, delisted_ts=None), as_of=now)
            intervals.append({"instrument_id": iid, "effective_from": listed, "effective_to": None, "rank": rank, "reason": "fut"})
            print(f"  {root}: {m} continuous bars  {str(cont.index[0])[:10]}..{str(cont.index[-1])[:10]}")
            n_ok += 1

    uni = pa.table({
        "instrument_id": pa.array([r["instrument_id"] for r in intervals], pa.string()),
        "effective_from": pa.array([r["effective_from"] for r in intervals], _TS),
        "effective_to": pa.array([r["effective_to"] for r in intervals], _TS),
        "rank": pa.array([r["rank"] for r in intervals], pa.int32()),
        "reason": pa.array([r["reason"] for r in intervals], pa.string()),
    })
    UniverseStore(LakePaths(LAKE)).write_intervals(uni, replace=True)
    pd.concat(carry_rows).to_parquet(LAKE / "carry_termstructure.parquet")
    print(f"\nBUILT {n_ok} continuous markets -> {LAKE}  (+ carry term structure)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
