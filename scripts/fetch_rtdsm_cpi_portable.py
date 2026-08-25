#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "openpyxl==3.1.5",
#   "pandas==3.0.3",
#   "pyarrow==24.0.0",
# ]
# ///
"""Fetch and normalize the public RTDSM CPI vintages without repository data.

This script is intentionally standalone. It may be copied into an empty directory and run with
``uv run --isolated --script``. It writes only to the explicitly supplied output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Final

import pandas as pd

BASE: Final = "https://www.philadelphiafed.org"
SERIES: Final = {
    "PCPI": ("pcpi", "pcpiMvMd.xlsx"),
    "PCPIX": ("pcpix", "pcpixMvMd.xlsx"),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _get(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "alphac-reproduction/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _download_url(variable: str, filename: str) -> str:
    page_url = f"{BASE}/surveys-and-data/real-time-data-research/{variable}"
    page = _get(page_url).decode("utf-8", "ignore")
    match = re.search(rf'href="(/-/media/[^"]*{re.escape(filename)}[^"]*)"', page, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"Official RTDSM link for {filename} was not found at {page_url}")
    return BASE + match.group(1).replace("&amp;", "&")


def _parse_obs_date(value: str) -> pd.Timestamp:
    year, month = value.strip().split(":")
    return pd.Timestamp(int(year), int(month), 1)


def _parse_vintage(value: str, prefix: str) -> pd.Timestamp:
    match = re.fullmatch(r"(\d{2})M(\d{1,2})", value[len(prefix) :])
    if not match:
        raise ValueError(f"Unrecognized monthly vintage column: {value}")
    short_year, month = int(match.group(1)), int(match.group(2))
    year = 1900 + short_year if short_year > 40 else 2000 + short_year
    return pd.Timestamp(year, month, 15)


def _normalize(raw: bytes, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    frame = pd.read_excel(io.BytesIO(raw))
    date_column = frame.columns[0]
    first_vintage = str(frame.columns[1])
    prefix_match = re.match(r"[A-Za-z]+?(?=\d{2}M\d)", first_vintage)
    if not prefix_match:
        raise RuntimeError(f"Could not infer RTDSM prefix from {first_vintage}")
    prefix = prefix_match.group(0)
    columns = [
        column
        for column in frame.columns[1:]
        if re.fullmatch(rf"{re.escape(prefix)}\d{{2}}M\d{{1,2}}", str(column))
    ]
    vintage_dates = {column: _parse_vintage(str(column), prefix) for column in columns}
    columns.sort(key=vintage_dates.get)
    observations = frame[date_column].astype(str).map(_parse_obs_date)
    wide = frame[columns].apply(pd.to_numeric, errors="coerce")
    wide.index = observations
    long = wide.stack().rename("value").reset_index()
    long.columns = ["obs_period", "vintage_col", "value"]
    long["vintage_date"] = long["vintage_col"].map(vintage_dates)
    long = long.drop(columns=["vintage_col"])
    if cutoff is not None:
        long = long[long["vintage_date"] <= cutoff]
    return long.sort_values(["obs_period", "vintage_date"]).reset_index(drop=True)


def _table_content_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.itertuples(index=False):
        line = (
            f"{row.obs_period.date().isoformat()}|{row.vintage_date.date().isoformat()}|"
            f"{float(row.value):.17g}\n"
        )
        digest.update(line.encode())
    return f"sha256:{digest.hexdigest()}"


def build(output: Path, cutoff: pd.Timestamp | None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for name, (variable, filename) in SERIES.items():
        url = _download_url(variable, filename)
        raw = _get(url)
        frame = _normalize(raw, cutoff)
        raw_path = output / filename
        normalized_path = output / f"{name}_vintage_long.parquet"
        raw_path.write_bytes(raw)
        frame.to_parquet(normalized_path, index=False)
        records.append(
            {
                "series": name,
                "official_variable_page": (
                    f"{BASE}/surveys-and-data/real-time-data-research/{variable}"
                ),
                "resolved_download_url": url,
                "raw_file": filename,
                "raw_sha256": _sha256(raw_path),
                "normalized_file": normalized_path.name,
                "normalized_sha256": _sha256(normalized_path),
                "normalized_table_content_hash": _table_content_hash(frame),
                "rows": len(frame),
                "first_vintage": str(frame["vintage_date"].min().date()),
                "last_vintage": str(frame["vintage_date"].max().date()),
                "first_observation": str(frame["obs_period"].min().date()),
                "last_observation": str(frame["obs_period"].max().date()),
            }
        )
    manifest: dict[str, Any] = {
        "schema": "canli.alphac-rtdsm-cpi-portable-fetch.v1",
        "source": "Federal Reserve Bank of Philadelphia RTDSM",
        "vintage_cutoff_inclusive": str(cutoff.date()) if cutoff is not None else None,
        "records": records,
        "raw_redistribution_authorized": False,
        "claim_boundary": (
            "This manifest proves a fresh official-source acquisition and deterministic table "
            "normalization under the recorded environment. It does not grant redistribution "
            "rights and does not reproduce market returns or the AlphaVintage result."
        ),
    }
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["content_hash"] = f"sha256:{_sha256_bytes(body)}"
    (output / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vintage-cutoff", default="2026-07-15")
    arguments = parser.parse_args()
    cutoff = pd.Timestamp(arguments.vintage_cutoff) if arguments.vintage_cutoff else None
    manifest = build(arguments.output.resolve(), cutoff)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
