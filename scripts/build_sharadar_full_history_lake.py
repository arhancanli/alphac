#!/usr/bin/env python3
"""Build a survivorship-inclusive Sharadar lake from the raw SEP and ACTIONS archives.

WHY. ``data/lake_sharadar`` holds 8,436 instruments; Sharadar's SEP ticker table holds 21,859,
15,573 of them delisted. The narrative-change calibration (2026-09-14) found 43 percent of a
2007 cohort's mapped issuers had no lake partition at all, every one a delisted name. A run on
that lake would be survivor-only, which the pre-registration forbids ("survivorship-inclusive
Sharadar SEP"). This builds ``data/lake_sharadar_full`` with every SEP ticker, in the lake's own
layout and schema, so the same PIT reader and the same adjustment kernel serve it.

CONVENTIONS, mirrored from the base lake and documented here so nobody has to infer them again:

- prices are RAW (unadjusted): ``close`` is SEP ``closeunadj``; ``open``, ``high`` and ``low``
  are SEP's split-adjusted fields scaled by ``closeunadj / close``; ``volume`` is SEP volume as
  delivered; ``quote_volume`` is SEP ``close * volume``; ``n_trades`` is null; ``quality_flags``
  is 0.
- corporate actions carry the VENDOR factor: a split stores ``ACTIONS.value`` as ``ratio``
  (new shares per old; the kernel divides pre-ex prices by it), ``cash_amount`` null; a dividend
  stores ``ratio`` 1.0 and ``ACTIONS.value`` as ``cash_amount`` (vendor basis, see the sealed
  dividend-basis audit); ``available_at`` equals ``ex_date``; ``adrratiosplit`` and every other
  action type are not executable and are not written.
- instrument ids are ``XUSE:CASH:<TICKER>USD``; dotted class tickers keep their dot.

The build is resumable per ticker, spends no hypothesis identity, opens no strategy, and writes
a content-hashed receipt binding the three archives.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.data.schemas import Dataset  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.writer import LakeWriter  # noqa: E402

RAW = REPO / "data" / "sharadar_raw"
SEP_ZIP = RAW / "SEP.zip"
ACTIONS_ZIP = RAW / "ACTIONS.zip"
TICKERS_ZIP = RAW / "TICKERS.zip"
OUT_LAKE = REPO / "data" / "lake_sharadar_full"
RECEIPT = REPO / "artifacts" / "audit" / "sharadar_full_history_lake_build.json"
EXECUTABLE_ACTIONS = ("split", "dividend")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "content_hash"}
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def instrument_id(ticker: str) -> str:
    return f"XUSE:CASH:{ticker.strip().upper()}USD"


def extract_csv(archive: Path, target_dir: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"{archive} must hold exactly one CSV, holds {names}")
        return Path(zf.extract(names[0], target_dir))


def partition_sep_by_ticker(sep_csv: Path, parts_dir: Path) -> int:
    """One parquet file per ticker, out of core, in the raw-price convention."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=6")
    con.execute(
        f"""
        COPY (
            SELECT
                ticker,
                CAST(date AS DATE) AS date,
                open * (closeunadj / NULLIF(close, 0)) AS open_raw,
                high * (closeunadj / NULLIF(close, 0)) AS high_raw,
                low * (closeunadj / NULLIF(close, 0)) AS low_raw,
                closeunadj AS close_raw,
                volume,
                close * volume AS quote_volume
            FROM read_csv('{sep_csv}', header=true,
                          columns={{'ticker':'VARCHAR','date':'VARCHAR','open':'DOUBLE',
                                   'high':'DOUBLE','low':'DOUBLE','close':'DOUBLE',
                                   'volume':'DOUBLE','closeadj':'DOUBLE','closeunadj':'DOUBLE',
                                   'lastupdated':'VARCHAR'}})
            WHERE closeunadj IS NOT NULL AND closeunadj > 0 AND close IS NOT NULL AND close > 0
        ) TO '{parts_dir}' (FORMAT PARQUET, PARTITION_BY (ticker), OVERWRITE_OR_IGNORE)
        """
    )
    count = con.execute(f"SELECT count(*) FROM read_parquet('{parts_dir}/*/*.parquet')").fetchone()
    con.close()
    return int(count[0]) if count else 0


def bars_table(frame: pd.DataFrame, iid: str, ingested_ms: int) -> pa.Table:
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    ts = (
        (pd.to_datetime(frame["date"], utc=True) - pd.Timestamp(0, tz="UTC"))
        // pd.Timedelta(milliseconds=1)
    ).astype("int64")
    n = len(frame)
    return pa.table(
        {
            "instrument_id": pa.array([iid] * n, type=pa.string()),
            "ts_open": pa.array(ts.to_list(), type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(frame["open_raw"].to_numpy(dtype="float64"), type=pa.float64()),
            "high": pa.array(frame["high_raw"].to_numpy(dtype="float64"), type=pa.float64()),
            "low": pa.array(frame["low_raw"].to_numpy(dtype="float64"), type=pa.float64()),
            "close": pa.array(frame["close_raw"].to_numpy(dtype="float64"), type=pa.float64()),
            "volume": pa.array(frame["volume"].to_numpy(dtype="float64"), type=pa.float64()),
            "quote_volume": pa.array(
                frame["quote_volume"].to_numpy(dtype="float64"), type=pa.float64()
            ),
            "n_trades": pa.array([None] * n, type=pa.int64()),
            "quality_flags": pa.array([0] * n, type=pa.int32()),
            "ingested_at": pa.array([ingested_ms] * n, type=pa.timestamp("ms", tz="UTC")),
        }
    )


def actions_table(frame: pd.DataFrame, ingested_ms: int) -> pa.Table:
    ex = (
        (pd.to_datetime(frame["date"], utc=True) - pd.Timestamp(0, tz="UTC"))
        // pd.Timedelta(milliseconds=1)
    ).astype("int64")
    is_split = frame["action"] == "split"
    value = pd.to_numeric(frame["value"], errors="coerce")
    ratio = value.where(is_split, 1.0).astype("float64")
    cash = value.where(~is_split, float("nan")).astype("float64")
    n = len(frame)
    return pa.table(
        {
            "instrument_id": pa.array(
                frame["instrument_id"].astype(str).to_list(), type=pa.string()
            ),
            "action_type": pa.array(frame["action"].astype(str).to_list(), type=pa.string()),
            "ex_date": pa.array(ex.to_list(), type=pa.timestamp("ms", tz="UTC")),
            "available_at": pa.array(ex.to_list(), type=pa.timestamp("ms", tz="UTC")),
            "ratio": pa.array(ratio.to_numpy(), type=pa.float64()),
            "cash_amount": pa.array(cash.to_numpy(), type=pa.float64()),
            "ingested_at": pa.array([ingested_ms] * n, type=pa.timestamp("ms", tz="UTC")),
        }
    )


def build(*, out_lake: Path, workdir: Path, limit: int | None) -> dict[str, Any]:
    t0 = time.time()
    ingested_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    sep_csv = extract_csv(SEP_ZIP, workdir)
    parts_dir = workdir / "sep_by_ticker"
    rows = partition_sep_by_ticker(sep_csv, parts_dir)
    print(f"SEP partitioned by ticker: {rows} rows in {time.time() - t0:.0f}s", flush=True)
    writer = LakeWriter(LakePaths(out_lake))
    tickers = sorted(p.name.split("=", 1)[1] for p in parts_dir.iterdir() if p.is_dir())
    if limit is not None:
        tickers = tickers[:limit]
    written = 0
    bars_written = 0
    skipped: list[str] = []
    for k, ticker in enumerate(tickers):
        iid = instrument_id(ticker)
        if "/" in ticker or "=" in ticker or not ticker:
            skipped.append(ticker)
            continue
        files = sorted((parts_dir / f"ticker={ticker}").glob("*.parquet"))
        frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        frame = frame[frame["close_raw"] > 0]
        if frame.empty:
            skipped.append(ticker)
            continue
        stats = writer.write(Dataset.OHLCV_1D, bars_table(frame, iid, ingested_ms), tf=Timeframe.D1)
        bars_written += stats.rows_written
        written += 1
        if k % 1000 == 0:
            print(
                f"  {k}/{len(tickers)} tickers, {bars_written} bars, {time.time() - t0:.0f}s",
                flush=True,
            )
    actions_csv = extract_csv(ACTIONS_ZIP, workdir)
    raw_actions = pd.read_csv(actions_csv, usecols=["date", "action", "ticker", "value"])
    executable = raw_actions[raw_actions["action"].isin(EXECUTABLE_ACTIONS)].copy()
    executable["ticker"] = executable["ticker"].astype(str).str.strip().str.upper()
    executable = executable[executable["ticker"].isin({t.upper() for t in tickers})]
    executable["instrument_id"] = executable["ticker"].map(instrument_id)
    executable = executable[pd.to_numeric(executable["value"], errors="coerce").notna()]
    action_rows = 0
    for _iid, group in executable.groupby("instrument_id", sort=True):
        stats = writer.write(Dataset.CORPORATE_ACTIONS, actions_table(group, ingested_ms))
        action_rows += stats.rows_written
    receipt: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-full-history-lake-build.v1",
        "author": "Arhan Canli",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "lake": str(out_lake.relative_to(REPO)) if out_lake.is_relative_to(REPO) else str(out_lake),
        "sources": {
            "SEP.zip": _sha256(SEP_ZIP),
            "ACTIONS.zip": _sha256(ACTIONS_ZIP),
            "TICKERS.zip": _sha256(TICKERS_ZIP),
        },
        "sep_rows_read": rows,
        "tickers_in_sep": len(tickers),
        "instruments_written": written,
        "bars_written": bars_written,
        "corporate_action_rows_written": action_rows,
        "skipped_tickers": skipped,
        "conventions": {
            "prices": "raw (SEP closeunadj; open/high/low scaled by closeunadj/close)",
            "split_ratio": "vendor ACTIONS.value, new shares per old; the kernel divides",
            "dividend_cash_amount": (
                "vendor ACTIONS.value (vendor share basis, quarantined by the sealed "
                "dividend-basis audit; consumers use split-only adjustment)"
            ),
            "available_at": "equals ex_date",
            "executable_action_types": list(EXECUTABLE_ACTIONS),
        },
        "elapsed_seconds": round(time.time() - t0, 1),
        "claim_boundary": (
            "A data lake build. It opens no strategy, spends no hypothesis identity and "
            "repairs nothing in the base lake."
        ),
    }
    receipt["content_hash"] = _content_hash(receipt)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT_LAKE)
    ap.add_argument("--limit", type=int, default=None, help="tickers, for a smoke build")
    ap.add_argument("--workdir", type=Path, default=None)
    args = ap.parse_args(argv)
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="sharadar_full_"))
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        receipt = build(out_lake=args.out, workdir=workdir, limit=args.limit)
    finally:
        if args.workdir is None:
            shutil.rmtree(workdir, ignore_errors=True)
    print(
        f"lake {receipt['lake']}: {receipt['instruments_written']} instruments, "
        f"{receipt['bars_written']} bars, {receipt['corporate_action_rows_written']} actions, "
        f"{receipt['elapsed_seconds']}s -> {RECEIPT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
