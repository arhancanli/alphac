#!/usr/bin/env python3
"""Ingest Binance spot 1h klines from the public archive into their own lake, data/lake_spot.

WHY. AlphaForge v2 (the cash-and-carry redesign, owner 2026-09-23) would short a perpetual and
hold the same coin on spot, so price moves cancel and the funding remains. The main lake holds
funding for every archived USDT perpetual since 2020 but no spot prices. This fetches them.

WHY A SEPARATE LAKE. data/lake is read by code that lists every instrument it holds; spot rows
there could reach a perpetual universe that does not filter on market type. A separate root, the
lake_sharadar pattern, keeps the crypto sleeve's inputs exactly as they are.

WHAT IT DOES NOT DO. It opens no returns and registers no hypothesis: data only. Which coins a
strategy may trade is the preregistration's decision, not this script's, so it fetches spot for
every perpetual symbol the archive lists that also has a spot archive.

Resumable: a (symbol, month) already written is skipped unless --refresh. Months the archive does
not have (before listing, after delisting) are recorded as gaps, never invented. A month whose
archive file fails the client's validation (on 2026-09-24, EDUUSDT 2026-06 carried a duplicate
open_time) is recorded as rejected with the reason and written nowhere: one bad vendor file
stopped the whole run once, and repairing it by picking one of two rows would be inventing.

    uv run python scripts/ingest_binance_spot_archive.py [--symbols BTCUSDT,ETHUSDT] \
        [--start 2020-01] [--end 2026-08] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from alphaforge.core.errors import DataGapError, SchemaError  # noqa: E402
from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.core.types import MarketType  # noqa: E402
from alphaforge.data.schemas import Dataset  # noqa: E402
from alphaforge.data.sources.vision import BinanceVisionClient  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.writer import LakeWriter  # noqa: E402

LAKE = REPO / "data" / "lake_spot"
PROGRESS = LAKE / "_ingest" / "progress.json"
DELAY_S = 0.1  # politeness on a public bucket


def months(start: str, end: str) -> list[tuple[int, int]]:
    y, m = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _load_progress(path: Path) -> dict[str, Any]:
    if path.is_file():
        return dict(json.loads(path.read_text()))
    return {"done": {}, "gaps": {}, "rejected": {}}


def _save_progress(path: Path, progress: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def ingest(
    symbols: list[str],
    month_list: list[tuple[int, int]],
    *,
    spot: BinanceVisionClient,
    writer: LakeWriter,
    progress_path: Path,
    refresh: bool = False,
) -> dict[str, int]:
    """Fetch and write every (symbol, month); returns counts of written, gap and skipped files."""
    progress = _load_progress(progress_path)
    progress.setdefault("rejected", {})
    counts = {"written": 0, "rows": 0, "gaps": 0, "rejected": 0, "skipped": 0}
    for symbol in symbols:
        done = set(progress["done"].get(symbol, []))
        gaps = set(progress["gaps"].get(symbol, []))
        rejected: dict[str, str] = dict(progress["rejected"].get(symbol, {}))
        for year, month in month_list:
            key = f"{year:04d}-{month:02d}"
            if not refresh and (key in done or key in gaps or key in rejected):
                counts["skipped"] += 1
                continue
            try:
                table = spot.fetch_ohlcv_month(symbol, year, month)
            except DataGapError:
                gaps.add(key)
                counts["gaps"] += 1
                continue
            except SchemaError as exc:
                rejected[key] = str(exc)
                counts["rejected"] += 1
                continue
            if table.num_rows:
                writer.write(Dataset.OHLCV, table, tf=Timeframe.H1)
                counts["rows"] += table.num_rows
            done.add(key)
            counts["written"] += 1
        progress["done"][symbol] = sorted(done)
        progress["gaps"][symbol] = sorted(gaps)
        if rejected:
            progress["rejected"][symbol] = dict(sorted(rejected.items()))
        _save_progress(progress_path, progress)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", help="comma-separated; default: every archived USDT perp")
    parser.add_argument("--start", default="2020-01")
    today = dt.datetime.now(dt.UTC).date()
    last_month = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    parser.add_argument("--end", default=last_month, help="last complete month (default)")
    parser.add_argument("--limit", type=int, help="only the first N symbols (smoke runs)")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    args = parser.parse_args()

    perp = BinanceVisionClient(delay_s=DELAY_S)
    spot = BinanceVisionClient(delay_s=DELAY_S, market=MarketType.SPOT)
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        spot_symbols = set(spot.list_symbols())
        symbols = [s for s in perp.list_symbols() if s in spot_symbols]
    if args.limit:
        symbols = symbols[: args.limit]
    month_list = months(args.start, args.end)
    print(f"{len(symbols)} symbols x {len(month_list)} months -> {LAKE.relative_to(REPO)}")
    if args.dry_run:
        print(", ".join(symbols[:40]) + (" ..." if len(symbols) > 40 else ""))
        return 0
    counts = ingest(
        symbols,
        month_list,
        spot=spot,
        writer=LakeWriter(LakePaths(LAKE)),
        progress_path=PROGRESS,
        refresh=args.refresh,
    )
    print(f"done: {counts}")
    if not (args.symbols or args.limit):
        # A full default run that returned: every archived symbol was fetched, gapped or
        # rejected. Readers (the cash-and-carry readiness audit) gate on this, never on a count.
        progress = _load_progress(PROGRESS)
        progress["complete"] = {
            "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "symbols": len(symbols),
            "end_month": args.end,
        }
        _save_progress(PROGRESS, progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
