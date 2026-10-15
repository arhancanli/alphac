"""Daily stock panel for the breadth lab: total, overnight and intraday returns, prices, dollar volume,
industry and sector, built once from the Sharadar lake and cached under var/breadth_lab/.

Returns use the reader's corrected corporate actions: on an ex-date with split ratio k (new shares
per old) and cash dividend d per new share, the holder of one old share earns k * (close + d) /
previous close - 1. Search mode cuts every array at the last search date, so no later return
exists in memory.

    PYTHONPATH=src ~/alphaforge/.venv/bin/python -m research.breadth_lab.panel --build
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader

ALPHAFORGE = Path.home() / "alphaforge"
LAKE = ALPHAFORGE / "data" / "lake_sharadar"
TICKERS_ZIP = ALPHAFORGE / "data" / "sharadar_raw" / "TICKERS.zip"
CACHE = Path(__file__).resolve().parents[2] / "var" / "breadth_lab"

SEARCH_END = pd.Timestamp("2017-12-31", tz="UTC")
TEST_START = pd.Timestamp("2018-01-01", tz="UTC")
CATEGORIES = {
    "Domestic Common Stock", "Domestic Common Stock Primary Class", "Domestic Common Stock Secondary Class",
    "ADR Common Stock", "ADR Common Stock Primary Class", "ADR Common Stock Secondary Class",
}


def ticker_of(instrument_id: str) -> str:
    return instrument_id.split(":")[-1].removesuffix("USD")


def tickers() -> pd.DataFrame:
    with zipfile.ZipFile(TICKERS_ZIP) as z, z.open(z.namelist()[0]) as f:
        t = pd.read_csv(f, low_memory=False)
    t = t[(t["table"] == "SEP") & t["category"].isin(CATEGORIES)]
    return t.drop_duplicates("ticker", keep="last").set_index("ticker")[["famaindustry", "sector", "industry", "category"]]


def build() -> Path:
    t0 = time.time()
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    bars = con.execute(
        f"""SELECT instrument_id, epoch_ms(ts_open) AS t, open, close, volume
            FROM read_parquet('{LAKE}/ohlcv_1d/*/*/data.parquet')
            WHERE close > 0"""
    ).df()
    meta = tickers()
    bars["ticker"] = bars["instrument_id"].map(ticker_of)
    bars = bars[bars["ticker"].isin(meta.index)]
    ids = sorted(bars["instrument_id"].unique())
    print(f"bars {len(bars):,} rows, {len(ids):,} common stocks and ADRs ({time.time() - t0:.0f}s)")

    reader = PITDataReader(LakePaths(LAKE))
    lo, hi = int(bars["t"].min()), int(bars["t"].max()) + 86_400_000
    acts = reader.corporate_actions(ids, start=lo, end=hi, as_of=hi + 400 * 86_400_000).to_pandas()
    print(f"corporate actions {len(acts):,} (corrections sha256 {reader.corrections_sha256})")

    wide = {c: bars.pivot(index="t", columns="instrument_id", values=c).sort_index() for c in ("open", "close", "volume")}
    dates = wide["close"].index.to_numpy()
    cols = wide["close"].columns
    k = pd.DataFrame(1.0, index=dates, columns=cols)
    d = pd.DataFrame(0.0, index=dates, columns=cols)
    pos = pd.Index(dates)
    for row in acts.itertuples(index=False):
        if row.instrument_id not in cols:
            continue
        i = pos.searchsorted(int(pd.Timestamp(row.ex_date).value // 1_000_000))
        if i >= len(dates):
            continue
        if row.action_type == "split" and np.isfinite(row.ratio) and row.ratio > 0:
            k.iat[i, cols.get_loc(row.instrument_id)] *= row.ratio
        elif row.action_type == "dividend" and np.isfinite(row.cash_amount):
            d.iat[i, cols.get_loc(row.instrument_id)] += row.cash_amount

    close, opn, vol = wide["close"], wide["open"], wide["volume"]
    prev = close.shift(1)
    total = k * (close + d) / prev - 1.0
    overnight = k * (opn + d) / prev - 1.0
    intraday = close / opn - 1.0
    # A bar after a gap in trading is not a one-day return: drop it rather than book a multi-day move as one day.
    gap = close.notna() & prev.isna()
    for r in (total, overnight):
        r[gap] = np.nan
    # Isolated bad prints: a jump of more than 150% that reverses by more than 60% the next day.
    spike = (total > 1.5) & (total.shift(-1) < -0.6)
    for r in (total, overnight, intraday):
        r[spike | spike.shift(1, fill_value=False)] = np.nan

    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / "panel.npz"
    np.savez(
        out,
        dates=dates.astype("int64"), ids=np.array(cols, dtype=str),
        total=total.to_numpy(np.float32), overnight=overnight.to_numpy(np.float32), intraday=intraday.to_numpy(np.float32),
        close=close.to_numpy(np.float32), dollar_volume=(close * vol).to_numpy(np.float32),
        split_events=(k != 1.0).to_numpy(), dividend_events=(d != 0.0).to_numpy(),
    )
    m = meta.reindex([ticker_of(c) for c in cols])
    m.index = cols
    m.to_parquet(CACHE / "meta.parquet")
    (CACHE / "panel.json").write_text(json.dumps({
        "built_at": pd.Timestamp.now(tz="UTC").isoformat(), "rows": int(len(bars)), "instruments": len(cols),
        "first": str(pd.Timestamp(dates[0], unit="ms")), "last": str(pd.Timestamp(dates[-1], unit="ms")),
        "corporate_actions": int(len(acts)), "corrections_sha256": reader.corrections_sha256,
        "spikes_removed": int(spike.to_numpy().sum()),
    }, indent=1))
    print(f"panel {len(dates):,} days x {len(cols):,} names -> {out} ({time.time() - t0:.0f}s)")
    return out


class Panel:
    """The cached arrays as DataFrames. ``mode='search'`` cuts everything after the last search date."""

    def __init__(self, mode: str = "search") -> None:
        if mode not in ("search", "test"):
            raise ValueError(mode)
        z = np.load(CACHE / "panel.npz")
        idx = pd.to_datetime(z["dates"], unit="ms", utc=True)
        keep = idx <= SEARCH_END if mode == "search" else np.ones(len(idx), bool)
        self.mode, self.dates, self.ids = mode, idx[keep], pd.Index(z["ids"])
        frame = lambda a: pd.DataFrame(a[keep], index=self.dates, columns=self.ids)  # noqa: E731
        self.total, self.overnight, self.intraday = frame(z["total"]), frame(z["overnight"]), frame(z["intraday"])
        self.close, self.dollar_volume = frame(z["close"]), frame(z["dollar_volume"])
        self.meta = pd.read_parquet(CACHE / "meta.parquet").reindex(self.ids)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--build", action="store_true")
    if p.parse_args().build:
        build()
