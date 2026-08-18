#!/usr/bin/env python3
"""Audit EIA/NOAA/CME source feasibility without requesting market records or returns."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import databento as db
import httpx
import pandas as pd

RAW_DIR: Final = Path("data/raw/natural_gas_storage_weather")
OUT_DIR: Final = Path("artifacts/feasibility/natural_gas_storage_weather")
PROTOCOL: Final = "docs/design/FEASIBILITY_NATURAL_GAS_STORAGE_WEATHER.md"
HISTORY_URL: Final = "https://ir.eia.gov/ngs/ngshistory.xls"
ORIGINAL_URL: Final = "https://ir.eia.gov/ngs/revisions.xls"
CDX_URL: Final = "https://web.archive.org/cdx/search/cdx"
NOAA_ROOT: Final = "https://noaa-gefs-pds.s3.amazonaws.com/"
UA: Final = "Mozilla/5.0 CanliCapitalResearch/1.0 research@canlicapital.com"
START: Final = pd.Timestamp("2017-01-01")
END: Final = pd.Timestamp("2025-12-31")
GEFS_V12_DATE: Final = date(2020, 9, 23)
GEFS_LEGACY_SUBDIR_DATE: Final = date(2018, 7, 27)
RELEASE_PATTERN: Final = re.compile(
    r"Released:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+at\s+"
    r"(\d{1,2}:\d{2}\s+[ap]\.m\.).*?Week\s+Ending\s+"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.I | re.S,
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def fetch(client: httpx.Client, url: str, *, params: dict[str, Any] | None = None) -> bytes:
    error: Exception | None = None
    for attempt in range(5):
        try:
            response = client.get(url, params=params)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise httpx.HTTPStatusError(
                    "retryable source response", request=response.request, response=response
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            error = exc
            time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"request failed after retries: {url}") from error


def cached_fetch(client: httpx.Client, url: str, path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    raw = fetch(client, url)
    atomic_write(path, raw)
    return raw


def expected_periods(history_raw: bytes) -> pd.DataFrame:
    frame = pd.read_excel(
        io.BytesIO(history_raw),
        sheet_name="html_report_history",
        engine="xlrd",
        header=6,
    )
    frame["Week ending"] = pd.to_datetime(frame["Week ending"], errors="coerce")
    frame = frame[frame["Week ending"].between(START, END)].copy()
    return frame[["Week ending", "Total Lower 48"]].rename(
        columns={"Week ending": "period_end", "Total Lower 48": "current_total_bcf"}
    )


def original_periods(original_raw: bytes) -> pd.DataFrame:
    frame = pd.read_excel(
        io.BytesIO(original_raw), sheet_name="original_data", engine="xlrd", header=1
    )
    frame["Week ending"] = pd.to_datetime(frame["Week ending"], errors="coerce")
    frame = frame[frame["Week ending"].between(START, END)].copy()
    return frame[["Week ending", "Total Lower 48", "Explanation"]].rename(
        columns={
            "Week ending": "period_end",
            "Total Lower 48": "original_total_bcf",
            "Explanation": "original_explanation",
        }
    )


def cdx_rows(raw: bytes) -> list[dict[str, str]]:
    payload = json.loads(raw)
    if not payload or payload[0][0] != "timestamp":
        raise ValueError("unexpected Wayback CDX response")
    header = payload[0]
    return [dict(zip(header, row, strict=True)) for row in payload[1:]]


def parse_wngsr_csv(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8-sig", errors="replace")
    match = RELEASE_PATTERN.search(text)
    if match is None:
        raise ValueError("WNGSR release/week-ending header absent")
    release_date = datetime.strptime(match.group(1), "%B %d, %Y").replace(tzinfo=UTC).date()
    period_end = datetime.strptime(match.group(3), "%B %d, %Y").replace(tzinfo=UTC).date()
    total_row = None
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip() == "Total":
            total_row = row
            break
    if total_row is None:
        raise ValueError("WNGSR Total row absent")
    numeric = []
    for value in total_row[1:]:
        cleaned = value.replace(",", "").strip()
        if cleaned and re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
            numeric.append(float(cleaned))
    if len(numeric) < 3:
        raise ValueError("WNGSR Total row has insufficient numeric fields")
    return {
        "release_date": release_date,
        "release_time_text": match.group(2),
        "period_end": period_end,
        "reported_total_bcf": numeric[0],
        "reported_prior_total_bcf": numeric[1],
        "reported_net_change_bcf": numeric[2],
    }


def wayback_manifest(
    client: httpx.Client, cdx: list[dict[str, str]], raw_dir: Path
) -> pd.DataFrame:
    rows = []
    for number, record in enumerate(cdx, 1):
        timestamp = record["timestamp"]
        original = record["original"]
        path = raw_dir / "wayback_wngsr" / f"{timestamp}.csv.gz"
        url = f"https://web.archive.org/web/{timestamp}id_/{original}"
        try:
            if path.exists():
                raw = gzip.decompress(path.read_bytes())
            else:
                raw = fetch(client, url)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
            parsed = parse_wngsr_csv(raw)
            rows.append(
                {
                    **record,
                    **parsed,
                    "capture_url": url,
                    "raw_sha256": sha256_bytes(raw),
                    "error": None,
                }
            )
        except Exception as exc:
            rows.append({**record, "capture_url": url, "error": str(exc)})
        if number % 20 == 0:
            print(f"EIA Wayback captures {number}/{len(cdx)}", flush=True)
    return pd.DataFrame(rows)


def gefs_keys(init_date: date) -> tuple[str, str]:
    stamp = init_date.strftime("%Y%m%d")
    if init_date < GEFS_V12_DATE:
        root = f"gefs.{stamp}/00"
        control_hour = "f024"
        if init_date >= GEFS_LEGACY_SUBDIR_DATE:
            root += "/pgrb2a"
            control_hour = "f24"
        return (
            f"{root}/gec00.t00z.pgrb2a{control_hour}",
            f"{root}/gep20.t00z.pgrb2af168",
        )
    root = f"gefs.{stamp}/00/atmos/pgrb2ap5"
    return (
        f"{root}/gec00.t00z.pgrb2a.0p50.f024",
        f"{root}/gep30.t00z.pgrb2a.0p50.f168",
    )


def noaa_object_audit(periods: pd.Series, workers: int = 16) -> pd.DataFrame:
    requests = []
    for period in pd.to_datetime(periods):
        period_end = period.date()
        init_date = period_end - timedelta(days=6)
        for role, key in zip(
            ("control_f024", "final_member_f168"), gefs_keys(init_date), strict=True
        ):
            requests.append((period_end, init_date, role, key))

    def probe(item: tuple[date, date, str, str]) -> dict[str, Any]:
        period_end, init_date, role, key = item
        try:
            response = httpx.head(NOAA_ROOT + key, timeout=30.0)
            return {
                "period_end": period_end,
                "forecast_init_date": init_date,
                "role": role,
                "object_key": key,
                "status_code": response.status_code,
                "size_bytes": int(response.headers["content-length"])
                if response.status_code == 200
                else None,
                "etag": response.headers.get("etag", "").strip('"') or None,
                "available": response.status_code == 200,
                "error": None,
            }
        except Exception as exc:
            return {
                "period_end": period_end,
                "forecast_init_date": init_date,
                "role": role,
                "object_key": key,
                "available": False,
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(probe, requests))
    return pd.DataFrame(rows).sort_values(["period_end", "role"])


def databento_metadata() -> dict[str, Any]:
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        return {"credential_present": False, "metadata_access": False}
    client = db.Historical(key)
    dataset = "GLBX.MDP3"
    range_info = client.metadata.get_dataset_range(dataset=dataset)
    schemas = client.metadata.list_schemas(dataset=dataset)
    return {
        "credential_present": True,
        "metadata_access": True,
        "dataset": dataset,
        "range": range_info,
        "schemas": schemas,
        "market_records_requested": 0,
    }


def summarize(
    expected: pd.DataFrame,
    original: pd.DataFrame,
    captures: pd.DataFrame,
    noaa: pd.DataFrame,
    cme: dict[str, Any],
    source_hashes: dict[str, str],
) -> dict[str, Any]:
    successful_captures = captures[captures["error"].isna()].copy()
    captured_periods = set(pd.to_datetime(successful_captures["period_end"]).dt.date)
    expected_dates = set(pd.to_datetime(expected["period_end"]).dt.date)
    capture_coverage = len(captured_periods & expected_dates) / len(expected_dates)
    noaa_by_period = noaa.groupby("period_end")["available"].all()
    noaa_coverage = float(noaa_by_period.mean())
    noaa_year = pd.to_datetime(noaa_by_period.index).year
    noaa_coverage_by_year = {
        str(int(year)): float(noaa_by_period[noaa_year == year].mean())
        for year in sorted(set(noaa_year))
    }
    merged = expected.merge(original, on="period_end", how="left", validate="one_to_one")
    original_coverage = float(merged["original_total_bcf"].notna().mean())
    revised_rows = int(
        merged["original_total_bcf"].notna()
        .mul(merged["original_total_bcf"].ne(merged["current_total_bcf"]))
        .sum()
    )
    cme_range = cme.get("range", {})
    cme_start = str(cme_range.get("start", ""))[:10]
    schemas = set(cme.get("schemas", []))
    gates = {
        "at_least_450_unique_expected_eia_periods": len(expected) >= 450
        and not expected["period_end"].duplicated().any(),
        "wayback_first_release_capture_coverage_gte_0_90": capture_coverage >= 0.90,
        "noaa_gefs_endpoint_coverage_gte_0_95": noaa_coverage >= 0.95,
        "cme_metadata_covers_period_with_daily_and_book_schema": bool(
            cme.get("metadata_access")
            and cme_start <= "2017-01-01"
            and "ohlcv-1d" in schemas
            and ({"mbp-1", "bbo-1s", "tbbo"} & schemas)
        ),
        "market_records_unopened": cme.get("market_records_requested", 0) == 0,
        "return_hypotheses_unspent": True,
    }
    return {
        "schema": "canli.feasibility.natural-gas-storage-weather.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "eia_noaa_cme_metadata_no_market_records_no_returns",
        "protocol": PROTOCOL,
        "family_trial_account": "commodity_inventory_weather",
        "prior_family_return_trials": 1,
        "minimum_family_trials_if_returns_open": 2,
        "expected_eia_periods": len(expected),
        "wayback_capture_rows": len(captures),
        "successful_wayback_capture_rows": len(successful_captures),
        "unique_first_release_periods_bound": len(captured_periods & expected_dates),
        "first_release_capture_coverage": capture_coverage,
        "official_original_data_rows": len(original),
        "official_original_data_coverage": original_coverage,
        "original_values_differing_from_current_history": revised_rows,
        "original_data_redesign_note": (
            "EIA revisions.xls original_data covers the panel but was not the frozen first-release "
            "source for this identity; using it requires a new source preregistration."
        ),
        "noaa_object_probes": len(noaa),
        "noaa_periods_with_both_endpoints": int(noaa_by_period.sum()),
        "noaa_endpoint_coverage": noaa_coverage,
        "noaa_endpoint_coverage_by_year": noaa_coverage_by_year,
        "cme_metadata": cme,
        "source_sha256": source_hashes,
        "gates": gates,
        "decision": "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED",
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def run(raw_dir: Path, out_dir: Path, workers: int) -> dict[str, Any]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": UA}, timeout=90.0, follow_redirects=True) as client:
        history_raw = cached_fetch(client, HISTORY_URL, raw_dir / "ngshistory.xls")
        original_raw = cached_fetch(client, ORIGINAL_URL, raw_dir / "revisions.xls")
        cdx_path = raw_dir / "wayback_wngsr_cdx.json"
        if cdx_path.exists():
            cdx_raw = cdx_path.read_bytes()
        else:
            cdx_raw = fetch(
                client,
                CDX_URL,
                params={
                    "url": "https://ir.eia.gov/ngs/wngsr.csv",
                    "from": "2017",
                    "to": "2025",
                    "output": "json",
                    "fl": "timestamp,original,statuscode,digest",
                    "filter": "statuscode:200",
                    "collapse": "timestamp:8",
                },
            )
            atomic_write(cdx_path, cdx_raw)
        expected = expected_periods(history_raw)
        original = original_periods(original_raw)
        captures = wayback_manifest(client, cdx_rows(cdx_raw), raw_dir)
    noaa = noaa_object_audit(expected["period_end"], workers=workers)
    cme = databento_metadata()
    captures.to_parquet(out_dir / "eia_wayback_capture_manifest.parquet", index=False)
    noaa.to_parquet(out_dir / "noaa_gefs_object_audit.parquet", index=False)
    result = summarize(
        expected,
        original,
        captures,
        noaa,
        cme,
        {
            "ngshistory_xls": sha256_bytes(history_raw),
            "revisions_xls": sha256_bytes(original_raw),
            "wayback_cdx": sha256_bytes(cdx_raw),
        },
    )
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    result = run(args.raw_dir, args.out_dir, args.workers)
    return 0 if result["decision"] == "PASS_TO_RETURN_PREREGISTRATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
