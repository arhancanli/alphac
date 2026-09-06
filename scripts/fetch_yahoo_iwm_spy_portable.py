#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pandas==3.0.3",
#   "pyarrow==24.0.0",
# ]
# ///
"""Reacquire AlphaVintage's adjusted IWM/SPY/QQQ closes without repository data.

Yahoo's terms do not give this project permission to redistribute the downloaded rows. This
standalone recipe therefore supports reviewer-side reacquisition and hash comparison only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

SYMBOLS: Final = ("IWM", "SPY", "QQQ")
ENDPOINT: Final = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def _table_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.itertuples(index=False):
        digest.update(f"{row.date.date().isoformat()}|{float(row.close):.17g}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def _fetch(symbol: str, start: str, end_exclusive: str) -> tuple[str, bytes, pd.DataFrame]:
    query = urllib.parse.urlencode(
        {
            "period1": _epoch(start),
            "period2": _epoch(end_exclusive),
            "interval": "1d",
            "events": "div,splits",
        }
    )
    url = f"{ENDPOINT.format(symbol=symbol)}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    result = json.loads(raw)["chart"]["result"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(result["timestamp"], unit="s", utc=True)
            .tz_localize(None)
            .normalize(),
            "close": adjusted,
        }
    )
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().drop_duplicates("date", keep="last").sort_values("date")
    return url, raw, frame.reset_index(drop=True)


def build(output: Path, start: str, end_exclusive: str) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for symbol in SYMBOLS:
        url, raw, frame = _fetch(symbol, start, end_exclusive)
        raw_path = output / f"{symbol}.chart.json"
        normalized_path = output / f"{symbol}.adjusted_close.parquet"
        raw_path.write_bytes(raw)
        frame.to_parquet(normalized_path, index=False)
        records.append(
            {
                "symbol": symbol,
                "resolved_download_url": url,
                "raw_sha256": _sha256(raw_path),
                "normalized_sha256": _sha256(normalized_path),
                "normalized_table_content_hash": _table_hash(frame),
                "rows": len(frame),
                "first_date": str(frame["date"].min().date()),
                "last_date": str(frame["date"].max().date()),
            }
        )
    document: dict[str, Any] = {
        "schema": "canli.alphac-yahoo-etf-portable-fetch.v1",
        "source": "Yahoo Finance chart service",
        "start_inclusive": start,
        "end_exclusive": end_exclusive,
        "price_semantics": "adjusted close supplied by the source",
        "records": records,
        "raw_redistribution_authorized": False,
        "terms": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
        "claim_boundary": (
            "This manifest supports reviewer-side reacquisition and hash comparison. It does not "
            "grant redistribution rights, guarantee continued endpoint access, or reproduce the "
            "AlphaVintage result."
        ),
    }
    document["content_hash"] = _content_hash(document)
    (output / "source_manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", default="2001-06-27")
    parser.add_argument("--end-exclusive", default="2026-08-22")
    arguments = parser.parse_args()
    print(
        json.dumps(
            build(arguments.output.resolve(), arguments.start, arguments.end_exclusive),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
