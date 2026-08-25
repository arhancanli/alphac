#!/usr/bin/env python3
"""Fetch missing crypto-carry funding history from Binance's official public REST API."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
COMPARISON: Final = ROOT / "artifacts/publication/crypto_carry_fresh_input_comparison.json"
PORTABILITY: Final = ROOT / "artifacts/publication/crypto_carry_portability_manifest.json"
OFFICIAL_ENDPOINT: Final = "https://fapi.binance.com/fapi/v1/fundingRate"
PAGE_LIMIT: Final = 1000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_json(url: str, retries: int = 4) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "alphac-portable-research/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, list):
                raise RuntimeError(f"unexpected Binance payload: {payload!r}")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"official funding API failed after {retries} attempts: {last_error}")


def _fetch_pages(
    symbol: str, start_ms: int, end_ms: int, endpoint: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    page_receipts: list[dict[str, Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": PAGE_LIMIT,
            }
        )
        url = f"{endpoint}?{query}"
        page = _request_json(url)
        encoded = _canonical(page)
        page_receipts.append(
            {
                "url": url,
                "rows": len(page),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "payload": page,
            }
        )
        if not page:
            break
        timestamps = [int(row["fundingTime"]) for row in page]
        if timestamps != sorted(set(timestamps)):
            raise RuntimeError(f"non-monotonic or duplicate funding page for {symbol}")
        rows.extend(row for row in page if start_ms <= int(row["fundingTime"]) < end_ms)
        next_cursor = timestamps[-1] + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"funding pagination did not advance for {symbol}")
        cursor = next_cursor
        if len(page) < PAGE_LIMIT:
            break
    deduplicated = {int(row["fundingTime"]): row for row in rows}
    return [deduplicated[key] for key in sorted(deduplicated)], page_receipts


def build(comparison_path: Path, output: Path, endpoint: str) -> dict[str, Any]:
    comparison = json.loads(comparison_path.read_text())
    portability = json.loads(PORTABILITY.read_text())
    if comparison.get("content_hash") != _content_hash(comparison):
        raise RuntimeError("comparison content hash is invalid")
    missing = comparison["missing_funding_archive_objects"]
    if not missing:
        raise RuntimeError("comparison contains no missing funding archives")
    metadata = {row["instrument_id"]: row for row in portability["instrument_metadata"]}
    normalized_records = []
    raw_page_records = []
    for symbol in sorted({row["symbol"] for row in missing}):
        months = sorted(row["month"] for row in missing if row["symbol"] == symbol)
        start = pd.Timestamp(f"{months[0]}-01", tz="UTC")
        end = pd.Timestamp(f"{months[-1]}-01", tz="UTC") + pd.offsets.MonthBegin(1)
        rows, pages = _fetch_pages(
            symbol, int(start.timestamp() * 1000), int(end.timestamp() * 1000), endpoint
        )
        raw_dir = output / "raw" / symbol
        raw_dir.mkdir(parents=True, exist_ok=True)
        for index, page in enumerate(pages, start=1):
            payload = page.pop("payload")
            destination = raw_dir / f"page-{index:03d}.json"
            destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            page["path"] = str(destination)
            raw_page_records.append({"symbol": symbol, **page})
        timestamps = pd.to_datetime([int(row["fundingTime"]) for row in rows], unit="ms", utc=True)
        instrument_id = f"BINANCE:PERP:{symbol}"
        frame = pd.DataFrame(
            {
                "instrument_id": instrument_id,
                "ts_funding": timestamps,
                "rate": [float(row["fundingRate"]) for row in rows],
                "funding_interval_hours": metadata[instrument_id]["funding_interval_hours"],
                "available_at": timestamps + pd.Timedelta(minutes=5),
            }
        )
        destination = output / "normalized/funding" / f"{symbol}.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(destination, index=False)
        normalized_records.append(
            {
                "symbol": symbol,
                "rows": len(frame),
                "first_timestamp": frame["ts_funding"].min().isoformat() if len(frame) else None,
                "last_timestamp": frame["ts_funding"].max().isoformat() if len(frame) else None,
                "sha256": _sha256(destination),
                "path": str(destination),
            }
        )
    passes = all(row["rows"] > 0 for row in normalized_records)
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-funding-api-supplement.v1",
        "author": "Arhan Canli",
        "status": "PASS_OFFICIAL_FUNDING_API_SUPPLEMENT" if passes else "INCOMPLETE_API_SUPPLEMENT",
        "passes": passes,
        "official_endpoint": endpoint,
        "public_endpoint_no_api_key_required": True,
        "comparison_binding": {
            "path": str(comparison_path),
            "sha256": _sha256(comparison_path),
            "content_hash": comparison["content_hash"],
        },
        "missing_archive_objects_addressed": missing,
        "raw_api_pages": raw_page_records,
        "normalized_objects": normalized_records,
        "totals": {
            "symbols": len(normalized_records),
            "api_pages": len(raw_page_records),
            "normalized_rows": sum(row["rows"] for row in normalized_records),
        },
        "funding_availability_rule": "available_at = ts_funding + 5 minutes",
        "strategy_replayed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This receipt preserves and hashes responses from Binance's public funding-history "
            "API for periods absent from the monthly archive. A separate comparison must establish "
            "coverage and equality to the frozen source."
        ),
    }
    document["content_hash"] = _content_hash(document)
    (output / "source_manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=COMPARISON)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--endpoint", default=OFFICIAL_ENDPOINT)
    arguments = parser.parse_args()
    document = build(arguments.comparison.resolve(), arguments.output.resolve(), arguments.endpoint)
    print(json.dumps(document, indent=2, sort_keys=True))
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
