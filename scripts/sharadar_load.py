"""Load Sharadar bulk-export zips (data/sharadar_raw/) into the AlphaForge lake.

The deep+wide survivorship-free equity backfill (the data investment). Maps the four
Sharadar tables to the canonical lake schemas, reusing the existing equity machinery.

  SEP     -> OHLCV_1D. Prices stored UNADJUSTED (raw) so the repo's own PIT split/div
             adjustment runs: raw = adjusted * (closeunadj/close); close_raw = closeunadj.
             quote_volume = close*volume (= true dollar volume, split-invariant) for ranking.
             A liquidity gate (median daily $vol >= --min-dollar) keeps the tradable
             survivorship-free universe (delisted-but-once-liquid names INCLUDED), not 16k
             micro-caps -> bounds the lake partition count. SEP defines the final universe.
  TICKERS -> InstrumentStore SCD2 for the kept set (listed_ts=firstpricedate,
             delisted_ts=lastpricedate if isdelisted; survivorship-free).
  SF1 ARQ -> FUNDAMENTALS. available_at = datekey (SEC FILING date = PIT); ARQ = as-reported.
  ACTIONS -> CORPORATE_ACTIONS (split/adrratiosplit -> ratio; dividend -> cash_amount).

Columns mapped BY NAME from each CSV header. Idempotent (LakeWriter + SCD2 upsert).

    uv run python scripts/sharadar_load.py                      # full load
    uv run python scripts/sharadar_load.py --limit-tickers 40   # smoke test
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.config.settings import load_settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.symbols import EQUITY_MIC, SymbolMapper
from alphaforge.core.time import Timeframe, now_ms
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter

RAW = Path("data/sharadar_raw")
_MS_DAY = 86_400_000
_TS = pa.timestamp("ms", tz="UTC")
_EQ_TICK, _EQ_LOT, _EQ_FEE_BPS = 0.01, 1.0, 1.0
_COMMON = ("Domestic Common Stock", "Domestic Common Stock Primary Class", "ADR Common Stock")


def _inner_csv(name: str) -> tuple[zipfile.ZipFile, str]:
    z = zipfile.ZipFile(RAW / f"{name}.zip")
    return z, next(n for n in z.namelist() if n.endswith(".csv"))


def _read_zip_csv(name: str, **kw: object) -> pd.DataFrame:
    z, inner = _inner_csv(name)
    with z.open(inner) as fh:
        return pd.read_csv(fh, **kw)  # type: ignore[arg-type]


def _canon(ticker: str) -> str:
    # Canonicalize dotted/dashed class & preferred tickers (BRK.B -> BRKB, SACH-PA -> SACHPA)
    # so they build a valid equity id; matches SymbolMapper's documented guidance.
    return str(ticker).upper().replace(".", "").replace("-", "")


def _eid(ticker: str) -> str:
    return SymbolMapper.equity_instrument_id(EQUITY_MIC, _canon(ticker))


def _ids_vec(tickers: pd.Series) -> pd.Series:
    canon = tickers.str.upper().str.replace(".", "", regex=False).str.replace("-", "", regex=False)
    return f"{EQUITY_MIC}:{MarketType.CASH.name}:" + canon + "USD"


def _ms_vec(dates: pd.Series) -> np.ndarray:
    # Force millisecond resolution explicitly (pandas 2.x may parse date-only strings at
    # second/ns resolution; a naive .astype('int64')//1e6 then silently mis-scales -> 1970).
    naive = pd.to_datetime(dates, utc=True).dt.tz_localize(None)
    return naive.to_numpy().astype("datetime64[ms]").astype("int64")


def _to_ms(date_str: object) -> int | None:
    if date_str is None or (isinstance(date_str, float) and pd.isna(date_str)):
        return None
    d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    return int(d.timestamp() * 1000)


def _candidates() -> pd.DataFrame:
    """Common-stock tickers from TICKERS (price-able, not USD-suffixed)."""
    tk = _read_zip_csv("TICKERS")
    tk = tk[(tk["table"] == "SEP") & tk["category"].isin(_COMMON) & tk["firstpricedate"].notna()]
    tk = tk[~tk["ticker"].astype(str).str.upper().str.endswith("USD")]
    return tk.copy()


def load_sep(writer: LakeWriter, candidates: set[str], now: int, *, min_dollar: float,
             limit_tickers: int | None, chunk: int = 5_000_000) -> set[str]:
    """Stream SEP, filter to candidates, gate by liquidity, write UNADJUSTED OHLCV_1D."""
    cols = ["ticker", "date", "open", "high", "low", "close", "volume", "closeunadj"]
    z, inner = _inner_csv("SEP")
    parts: list[pd.DataFrame] = []
    with z.open(inner) as fh:
        for ch in pd.read_csv(fh, usecols=cols, chunksize=chunk):  # type: ignore[arg-type]
            ch = ch[ch["ticker"].astype(str).str.upper().isin(candidates)]
            ch = ch[(ch["close"] > 0) & (ch["closeunadj"] > 0)]
            if len(ch):
                parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    del parts
    df["ratio"] = df["closeunadj"] / df["close"]  # adjusted -> raw
    df["dollar"] = df["close"] * df["volume"]  # split-invariant dollar volume
    med = df.groupby("ticker")["dollar"].median()
    keep = set(med[med >= min_dollar].index.astype(str).str.upper())
    if limit_tickers:
        keep = set(sorted(keep)[:limit_tickers])
    df = df[df["ticker"].astype(str).str.upper().isin(keep)]
    df["tu"] = df["ticker"].astype(str).str.upper()
    df["ts_open"] = _ms_vec(df["date"])
    df["o"] = df["open"] * df["ratio"]
    df["h"] = df["high"] * df["ratio"]
    df["l"] = df["low"] * df["ratio"]
    n_written = 0
    for tu, g in df.groupby("tu"):
        g = g.sort_values("ts_open")
        m = len(g)
        tbl = pa.table({
            "instrument_id": pa.array([_eid(tu)] * m, pa.string()),
            "ts_open": pa.array(g["ts_open"].to_numpy(), _TS),
            "open": pa.array(g["o"].to_numpy(), pa.float64()),
            "high": pa.array(g["h"].to_numpy(), pa.float64()),
            "low": pa.array(g["l"].to_numpy(), pa.float64()),
            "close": pa.array(g["closeunadj"].to_numpy(), pa.float64()),
            "volume": pa.array(g["volume"].to_numpy(), pa.float64()),
            "quote_volume": pa.array(g["dollar"].to_numpy(), pa.float64()),
            "n_trades": pa.array([None] * m, pa.int64()),
            "quality_flags": pa.array(np.zeros(m, np.int32), pa.int32()),
            "ingested_at": pa.array([now] * m, _TS),
        })
        writer.write(Dataset.OHLCV_1D, tbl, tf=Timeframe.D1, now=now)
        n_written += m
    print(f"SEP: kept {len(keep)} liquid tickers (median $vol>={min_dollar:,.0f}); "
          f"wrote {n_written:,} bars", flush=True)
    return keep


def load_instruments(store: InstrumentStore, cand: pd.DataFrame, keep: set[str], now: int) -> None:
    n = 0
    for _, r in cand[cand["ticker"].astype(str).str.upper().isin(keep)].iterrows():
        t = str(r["ticker"]).upper()
        listed = _to_ms(r["firstpricedate"])
        if listed is None:
            continue
        delisted = _to_ms(r["lastpricedate"]) if str(r.get("isdelisted", "N")) == "Y" else None
        if delisted is not None and delisted <= listed:
            delisted = listed + _MS_DAY
        store.upsert(Instrument(
            instrument_id=_eid(t), asset_class=AssetClass.EQUITY, market_type=MarketType.CASH,
            base=_canon(t), quote="USD", tick_size=_EQ_TICK, lot_size=_EQ_LOT, min_qty=_EQ_LOT,
            min_notional=0.0, contract_multiplier=1.0, can_short=True,
            maker_fee_bps=_EQ_FEE_BPS, taker_fee_bps=_EQ_FEE_BPS, funding_interval_hours=None,
            listed_ts=listed, delisted_ts=delisted), as_of=now)
        n += 1
    print(f"TICKERS: upserted {n} instruments", flush=True)


def load_sf1(writer: LakeWriter, keep: set[str], now: int) -> None:
    df = _read_zip_csv("SF1")
    df = df[(df["dimension"] == "ARQ") & df["ticker"].astype(str).str.upper().isin(keep)]
    df = df.dropna(subset=["reportperiod", "datekey"])
    pe = _ms_vec(df["reportperiod"])
    ak = _ms_vec(df["datekey"])
    dts = pd.to_datetime(df["reportperiod"], utc=True)
    fp = ("Q" + ((dts.dt.month - 1) // 3 + 1).astype(str)).to_numpy()
    fy = dts.dt.year.astype("int32").to_numpy()

    def col(src: str) -> pa.Array:
        return pa.array(pd.to_numeric(df[src], errors="coerce").to_numpy(), pa.float64())

    tbl = pa.table({
        "instrument_id": pa.array(_ids_vec(df["ticker"]).to_numpy(), pa.string()),
        "period_end": pa.array(pe, _TS), "available_at": pa.array(ak, _TS),
        "fiscal_period": pa.array(fp, pa.string()), "fiscal_year": pa.array(fy, pa.int32()),
        "revenues": col("revenue"), "cost_of_revenue": col("cor"), "gross_profit": col("gp"),
        "operating_income": col("opinc"), "net_income": col("netinc"), "equity": col("equity"),
        "assets": col("assets"), "diluted_shares": col("shareswadil"),
        "ingested_at": pa.array([now] * len(df), _TS),
    })
    writer.write(Dataset.FUNDAMENTALS, tbl, now=now)
    print(f"SF1: wrote {tbl.num_rows:,} ARQ fundamental rows", flush=True)


def load_actions(writer: LakeWriter, keep: set[str], now: int) -> None:
    df = _read_zip_csv("ACTIONS")
    df = df[df["action"].isin(["split", "dividend", "adrratiosplit"])
            & df["ticker"].astype(str).str.upper().isin(keep)].dropna(subset=["date", "value"])
    is_split = df["action"].isin(["split", "adrratiosplit"]).to_numpy()
    t = _ms_vec(df["date"])
    val = pd.to_numeric(df["value"], errors="coerce").to_numpy()
    tbl = pa.table({
        "instrument_id": pa.array(_ids_vec(df["ticker"]).to_numpy(), pa.string()),
        "action_type": pa.array(np.where(is_split, "split", "dividend"), pa.string()),
        "ex_date": pa.array(t, _TS), "available_at": pa.array(t, _TS),
        "ratio": pa.array(np.where(is_split, val, 1.0), pa.float64()),
        "cash_amount": pa.array(np.where(is_split, np.nan, val), pa.float64()),
        "ingested_at": pa.array([now] * len(df), _TS),
    })
    writer.write(Dataset.CORPORATE_ACTIONS, tbl, now=now)
    print(f"ACTIONS: wrote {tbl.num_rows:,} rows ({int(is_split.sum()):,} splits)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-dollar", type=float, default=500_000.0, help="median daily $vol gate")
    ap.add_argument("--limit-tickers", type=int, default=None, help="cap kept tickers (smoke test)")
    ap.add_argument("--lake-dir", type=str, default=None, help="override lake dir (testing)")
    ap.add_argument("--var-dir", type=str, default=None, help="override var dir (testing)")
    args = ap.parse_args()
    settings = load_settings()
    now = now_ms()
    lake_dir = Path(args.lake_dir) if args.lake_dir else settings.paths.lake_dir
    var_dir = Path(args.var_dir) if args.var_dir else settings.paths.var_dir
    var_dir.mkdir(parents=True, exist_ok=True)
    writer = LakeWriter(LakePaths(lake_dir))
    cand_df = _candidates()
    cand = set(cand_df["ticker"].astype(str).str.upper())
    print(f"candidates: {len(cand)} common-stock tickers", flush=True)
    keep = load_sep(writer, cand, now, min_dollar=args.min_dollar, limit_tickers=args.limit_tickers)
    with InstrumentStore(var_dir / "ops.sqlite") as store:
        load_instruments(store, cand_df, keep, now)
    load_sf1(writer, keep, now)
    load_actions(writer, keep, now)
    print("LOAD COMPLETE", flush=True)


if __name__ == "__main__":
    main()
