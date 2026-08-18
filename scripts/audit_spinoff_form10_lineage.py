#!/usr/bin/env python3
"""Build a hash-bound Form 10 candidate lineage without opening prices or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

START_YEAR: Final = 2016
END_YEAR: Final = 2025
RAW_DIR: Final = Path("data/raw/spin_off_dislocation/full_index")
OUT_DIR: Final = Path("artifacts/feasibility/spin_off_dislocation")
PROTOCOL: Final = "docs/design/FEASIBILITY_SPIN_OFF_DISLOCATION.md"
UA: Final = "Canli Capital quantitative research research@canlicapital.com"
INDEX_URL: Final = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx"
ACCESSION_PATTERN: Final = re.compile(r"(\d{10}-\d{2}-\d{6})\.txt$")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def parse_master_index(raw: bytes, *, year: int, quarter: int) -> pd.DataFrame:
    text = raw.decode("latin-1")
    marker = "CIK|Company Name|Form Type|Date Filed|Filename"
    if marker not in text:
        raise ValueError(f"SEC master index header absent for {year} Q{quarter}")
    body = text.split(marker, 1)[1]
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line or line.startswith("-"):
            continue
        fields = line.split("|")
        if len(fields) != 5:
            continue
        cik, company_name, form, filing_date, filename = fields
        if form not in {"10-12B", "10-12B/A"}:
            continue
        match = ACCESSION_PATTERN.search(filename)
        rows.append(
            {
                "source_year": year,
                "source_quarter": quarter,
                "cik": int(cik),
                "company_name": company_name.strip(),
                "form": form,
                "filing_date": filing_date,
                "archive_filename": filename,
                "accession": match.group(1) if match else None,
                "is_initial_registration": form == "10-12B",
            }
        )
    return pd.DataFrame(rows)


def fetch_index(client: httpx.Client, url: str) -> bytes:
    error: Exception | None = None
    for attempt in range(5):
        try:
            response = client.get(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise httpx.HTTPStatusError(
                    "retryable SEC response", request=response.request, response=response
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            error = exc
            time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"SEC full-index request failed after retries: {url}") from error


def summarize(filings: pd.DataFrame, sources: pd.DataFrame) -> dict[str, Any]:
    initial = filings[filings["is_initial_registration"]]
    annual_initial = initial.groupby(pd.to_datetime(initial["filing_date"]).dt.year).size()
    gates = {
        "exactly_40_quarter_indexes_hash_bound": len(sources) == 40
        and bool(sources["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()),
        "all_quarter_indexes_parsed": bool(sources["parse_error"].isna().all()),
        "all_retained_rows_have_canonical_accessions": bool(
            filings["accession"].str.fullmatch(r"\d{10}-\d{2}-\d{6}").all()
        ),
        "filing_identities_unique": not filings.duplicated(["cik", "accession"]).any(),
        "each_year_has_initial_registration": set(annual_initial.index)
        == set(range(START_YEAR, END_YEAR + 1)),
        "at_least_50_initial_registrations": len(initial) >= 50,
        "market_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    return {
        "schema": "canli.feasibility.spin-off-form10-lineage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "sec_full_index_lineage_no_documents_no_prices_no_returns",
        "protocol": PROTOCOL,
        "period": [START_YEAR, END_YEAR],
        "quarter_indexes": len(sources),
        "retained_form_rows": len(filings),
        "initial_10_12b_registrations": len(initial),
        "amendment_10_12b_a_rows": int((filings["form"] == "10-12B/A").sum()),
        "unique_ciks": int(filings["cik"].nunique()),
        "initial_registrations_by_year": {
            str(int(year)): int(count) for year, count in annual_initial.items()
        },
        "source_manifest_sha256": sha256_bytes(
            sources.sort_values(["year", "quarter"])
            .to_json(orient="records", date_format="iso")
            .encode()
        ),
        "filings_manifest_sha256": sha256_bytes(
            filings.sort_values(["filing_date", "cik", "accession"])
            .to_json(orient="records", date_format="iso")
            .encode()
        ),
        "gates": gates,
        "decision": (
            "PASS_TO_DOCUMENT_SCHEMA_AUDIT" if all(gates.values()) else "SOURCE_LINEAGE_REQUIRED"
        ),
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def run(raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_rows = []
    filing_frames = []
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, timeout=60.0
    ) as client:
        for year in range(START_YEAR, END_YEAR + 1):
            for quarter in range(1, 5):
                url = INDEX_URL.format(year=year, quarter=quarter)
                path = raw_dir / f"{year}-Q{quarter}-master.idx"
                raw = path.read_bytes() if path.exists() else fetch_index(client, url)
                if not path.exists():
                    atomic_write(path, raw)
                    time.sleep(0.15)
                error = None
                try:
                    frame = parse_master_index(raw, year=year, quarter=quarter)
                    filing_frames.append(frame)
                except Exception as exc:
                    error = str(exc)
                    frame = pd.DataFrame()
                source_rows.append(
                    {
                        "year": year,
                        "quarter": quarter,
                        "url": url,
                        "cache_path": str(path),
                        "bytes": len(raw),
                        "sha256": sha256_bytes(raw),
                        "retained_rows": len(frame),
                        "parse_error": error,
                    }
                )
    sources = pd.DataFrame(source_rows).sort_values(["year", "quarter"])
    filings = pd.concat(filing_frames, ignore_index=True) if filing_frames else pd.DataFrame()
    if not filings.empty:
        filings = filings.drop_duplicates().sort_values(["filing_date", "cik", "accession"])
    sources.to_parquet(out_dir / "quarter_sources.parquet", index=False)
    filings.to_parquet(out_dir / "form10_filings.parquet", index=False)
    result = summarize(filings, sources)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    result = run(args.raw_dir, args.out_dir)
    return 0 if result["decision"] == "PASS_TO_DOCUMENT_SCHEMA_AUDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
