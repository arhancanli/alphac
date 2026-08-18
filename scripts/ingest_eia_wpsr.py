#!/usr/bin/env python3
"""Ingest first-release EIA WPSR Table 4 inventory vintages from the dated archive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Final

import pandas as pd

ARCHIVE_INDEX: Final[str] = "https://www.eia.gov/petroleum/supply/weekly/archive/"
RAW_DIR: Final[Path] = Path("data/raw/eia_wpsr")
OUT_DIR: Final[Path] = Path("data/lake_inventory_releases")
USER_AGENT: Final[str] = "Canli Capital Research arhancanli@icloud.com"
TARGETS: Final[dict[str, str]] = {
    "Commercial (Excluding SPR)": "USO",
    "Total Motor Gasoline": "UGA",
}
LINK_RE: Final[re.Pattern[str]] = re.compile(
    r'(?:https://www\.eia\.gov/petroleum/supply/weekly/)?'
    r'archive/(?P<year>\d{4})/(?P<stamp>\d{4}_\d{2}_\d{2})/'
    r'wpsr_(?P=stamp)\.(?:php|html)'
)


def fetch(url: str, *, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from error


def discover_releases(html: str) -> list[tuple[date, str]]:
    releases: dict[date, str] = {}
    for match in LINK_RE.finditer(html):
        released = pd.Timestamp(match.group("stamp").replace("_", "-")).date()
        folder = f"{match.group('year')}/{match.group('stamp')}"
        releases[released] = f"{ARCHIVE_INDEX}{folder}/csv/table4.csv"
    return sorted(releases.items())


def _number(raw: str) -> float:
    return float(raw.replace(",", "").strip())


def parse_table4(
    payload: bytes,
    *,
    release_date: date,
    source_url: str,
    source_sha256: str,
) -> list[dict[str, object]]:
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig", errors="replace"))))
    if not rows or len(rows[0]) < 4:
        raise ValueError(f"{release_date}: malformed Table 4 header")
    period_end = pd.to_datetime(rows[0][1], format="%m/%d/%y").date()
    previous_end = pd.to_datetime(rows[0][2], format="%m/%d/%y").date()
    if not period_end < release_date or not previous_end < period_end:
        raise ValueError(f"{release_date}: impossible report chronology")

    found: dict[str, list[str]] = {row[0].strip(): row for row in rows[1:] if row}
    output: list[dict[str, object]] = []
    for label, proxy in TARGETS.items():
        if label not in found:
            raise ValueError(f"{release_date}: missing required row {label!r}")
        row = found[label]
        current, previous, change = (_number(row[1]), _number(row[2]), _number(row[3]))
        if abs((current - previous) - change) > 0.002:
            raise ValueError(f"{release_date}: {label} difference does not reconcile")
        output.append(
            {
                "release_date": pd.Timestamp(release_date),
                "period_end": pd.Timestamp(period_end),
                "previous_period_end": pd.Timestamp(previous_end),
                "product": label,
                "proxy": proxy,
                "stock_million_barrels": current,
                "previous_stock_million_barrels": previous,
                "change_million_barrels": change,
                "source_url": source_url,
                "source_sha256": source_sha256,
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2011-08-01")
    parser.add_argument("--end", default=str(pd.Timestamp.now(tz="UTC").date()))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pace-seconds", type=float, default=0.10)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_payload = fetch(ARCHIVE_INDEX)
    releases = discover_releases(index_payload.decode("utf-8", errors="replace"))
    start, end = pd.Timestamp(args.start).date(), pd.Timestamp(args.end).date()
    releases = [(released, url) for released, url in releases if start <= released <= end]
    if args.limit is not None:
        releases = releases[: args.limit]
    if not releases:
        raise SystemExit("no EIA WPSR releases found in requested interval")

    records: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    for number, (released, url) in enumerate(releases, start=1):
        path = RAW_DIR / f"{released.isoformat()}_table4.csv"
        if path.exists():
            payload = path.read_bytes()
        else:
            payload = fetch(url)
            path.write_bytes(payload)
            time.sleep(max(args.pace_seconds, 0.0))
        digest = hashlib.sha256(payload).hexdigest()
        try:
            parsed = parse_table4(
                payload,
                release_date=released,
                source_url=url,
                source_sha256=digest,
            )
            status = "accepted"
            reason = None
        except ValueError as exc:
            # A source contradiction cannot be interpreted in the strategy's favour. Quarantine
            # both products for the release, retain provenance, and leave the portfolio flat.
            parsed = []
            status = "rejected"
            reason = str(exc)
            rejected.append({"release_date": released.isoformat(), "reason": reason})
        records.extend(parsed)
        files.append(
            {
                "release_date": released.isoformat(),
                "url": url,
                "path": str(path),
                "sha256": digest,
                "rows": len(parsed),
                "status": status,
                "reason": reason,
            }
        )
        if number % 100 == 0 or number == len(releases):
            print(f"processed {number:,}/{len(releases):,} release vintages", flush=True)

    frame = pd.DataFrame(records).sort_values(["release_date", "product"])
    if frame.duplicated(["release_date", "product"]).any():
        raise SystemExit("duplicate release/product rows")
    frame.to_parquet(OUT_DIR / "events.parquet", index=False)
    manifest = {
        "schema": "canli.eia-wpsr-vintage-manifest.v1",
        "archive_index": ARCHIVE_INDEX,
        "archive_index_sha256": hashlib.sha256(index_payload).hexdigest(),
        "start": str(frame["release_date"].min().date()),
        "end": str(frame["release_date"].max().date()),
        "discovered_releases": len(releases),
        "accepted_releases": int(frame["release_date"].nunique()),
        "rejected_releases": len(rejected),
        "rejections": rejected,
        "rows": len(frame),
        "products": sorted(frame["product"].unique()),
        "files": files,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    main()
