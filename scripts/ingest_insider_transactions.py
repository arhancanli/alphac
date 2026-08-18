#!/usr/bin/env python3
"""Ingest the official SEC Form 3/4/5 flat files for the insider-cluster probe.

The source is the SEC DERA Insider Transactions Data Sets, not a scraped aggregator. Raw
quarterly ZIPs are cached and SHA-256 hashed; normalized qualifying transactions are written one
Parquet file per quarter. No API key is required. Automated requests identify Canli Capital and
remain far below the SEC's published 10 requests/second fair-access ceiling.

Only NON-DERIVATIVE open-market purchases reported on original Form 4 filings survive:
transaction code P, acquired code A, positive shares and price, and a reporting person identified
as an officer or director. Form 4/A amendments are excluded rather than guessed into their
original records because the flat file does not provide a reliable amended-accession foreign key.

Run a bounded OOS ingest first:
    uv run python scripts/ingest_insider_transactions.py --start-year 2016
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import pandas as pd

RAW_DIR: Final[Path] = Path("data/raw/sec_form345")
OUT_DIR: Final[Path] = Path("data/lake_insider")
DEFAULT_USER_AGENT: Final[str] = "Canli Capital Research arhancanli@icloud.com"
URL_TEMPLATES: Final[tuple[str, ...]] = (
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{year}q{quarter}_form345.zip",
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{quarter}_form345.zip",
)


@dataclass(frozen=True)
class QuarterResult:
    year: int
    quarter: int
    source_url: str
    source_sha256: str
    source_bytes: int
    submission_rows: int
    transaction_rows: int
    owner_rows: int
    qualifying_rows: int
    output_path: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(
    year: int,
    quarter: int,
    *,
    user_agent: str,
    pause: float = 0.25,
) -> tuple[bytes, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{year}q{quarter}_form345.zip"
    url_record = RAW_DIR / f"{year}q{quarter}_source.txt"
    if cache.exists():
        source = url_record.read_text().strip() if url_record.exists() else "cached"
        return cache.read_bytes(), source

    errors: list[str] = []
    for template in URL_TEMPLATES:
        url = template.format(year=year, quarter=quarter)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
            if not zipfile.is_zipfile(io.BytesIO(payload)):
                raise ValueError("response was not a ZIP archive")
            cache.write_bytes(payload)
            url_record.write_text(url + "\n")
            time.sleep(pause)
            return payload, url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("SEC quarter unavailable:\n" + "\n".join(errors))


def _read_tsv(
    archive: zipfile.ZipFile,
    name: str,
    columns: list[str],
    *,
    optional: tuple[str, ...] = (),
) -> pd.DataFrame:
    with archive.open(name) as fh:
        header = pd.read_csv(fh, sep="\t", nrows=0).columns
    missing_required = set(columns) - set(header) - set(optional)
    if missing_required:
        raise ValueError(f"{name} missing required SEC columns: {sorted(missing_required)}")
    present = [column for column in columns if column in header]
    with archive.open(name) as fh:
        frame = pd.read_csv(fh, sep="\t", usecols=present, dtype=str, low_memory=False)
    for column in optional:
        if column not in frame:
            frame[column] = pd.NA
    return frame


def normalize_quarter(payload: bytes) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return one row per qualifying accession / owner / non-derivative transaction."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        submissions = _read_tsv(
            archive,
            "SUBMISSION.tsv",
            [
                "ACCESSION_NUMBER",
                "FILING_DATE",
                "DOCUMENT_TYPE",
                "ISSUERCIK",
                "ISSUERNAME",
                "ISSUERTRADINGSYMBOL",
                "AFF10B5ONE",
            ],
            optional=("AFF10B5ONE",),
        )
        transactions = _read_tsv(
            archive,
            "NONDERIV_TRANS.tsv",
            [
                "ACCESSION_NUMBER",
                "NONDERIV_TRANS_SK",
                "TRANS_DATE",
                "TRANS_CODE",
                "TRANS_SHARES",
                "TRANS_PRICEPERSHARE",
                "TRANS_ACQUIRED_DISP_CD",
                "DIRECT_INDIRECT_OWNERSHIP",
            ],
        )
        owners = _read_tsv(
            archive,
            "REPORTINGOWNER.tsv",
            [
                "ACCESSION_NUMBER",
                "RPTOWNERCIK",
                "RPTOWNERNAME",
                "RPTOWNER_RELATIONSHIP",
                "RPTOWNER_TITLE",
            ],
        )

    counts = {
        "submission_rows": len(submissions),
        "transaction_rows": len(transactions),
        "owner_rows": len(owners),
    }

    # Original Form 4 only. Amendments are excluded: a heuristic replacement would be worse than
    # omission because it could duplicate a purchase and manufacture a two-insider cluster.
    submissions = submissions[submissions["DOCUMENT_TYPE"].str.strip().eq("4")].copy()
    relationship = owners["RPTOWNER_RELATIONSHIP"].fillna("")
    owners = owners[relationship.str.contains(r"Officer|Director", case=False, regex=True)].copy()
    transactions = transactions[
        transactions["TRANS_CODE"].str.strip().eq("P")
        & transactions["TRANS_ACQUIRED_DISP_CD"].str.strip().eq("A")
    ].copy()
    transactions["shares"] = pd.to_numeric(transactions["TRANS_SHARES"], errors="coerce")
    transactions["price"] = pd.to_numeric(transactions["TRANS_PRICEPERSHARE"], errors="coerce")
    transactions = transactions[(transactions["shares"] > 0) & (transactions["price"] > 0)]
    transactions["purchase_value_usd"] = transactions["shares"] * transactions["price"]

    merged = submissions.merge(
        transactions,
        on="ACCESSION_NUMBER",
        how="inner",
        validate="one_to_many",
    )
    merged = merged.merge(owners, on="ACCESSION_NUMBER", how="inner", validate="many_to_many")
    merged = merged.drop_duplicates(["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "RPTOWNERCIK"])
    merged["filing_date"] = pd.to_datetime(
        merged["FILING_DATE"], format="%d-%b-%Y", errors="coerce"
    )
    merged["transaction_date"] = pd.to_datetime(
        merged["TRANS_DATE"], format="%d-%b-%Y", errors="coerce"
    )
    merged = merged.dropna(subset=["filing_date", "transaction_date", "ISSUERCIK", "RPTOWNERCIK"])

    renamed = merged.rename(
        columns={
            "ACCESSION_NUMBER": "accession_number",
            "NONDERIV_TRANS_SK": "transaction_key",
            "ISSUERCIK": "issuer_cik",
            "ISSUERNAME": "issuer_name",
            "ISSUERTRADINGSYMBOL": "ticker",
            "RPTOWNERCIK": "owner_cik",
            "RPTOWNERNAME": "owner_name",
            "RPTOWNER_RELATIONSHIP": "owner_relationship",
            "RPTOWNER_TITLE": "owner_title",
            "DIRECT_INDIRECT_OWNERSHIP": "direct_or_indirect",
            "AFF10B5ONE": "aff10b5one",
        }
    )
    columns = [
        "accession_number",
        "transaction_key",
        "filing_date",
        "transaction_date",
        "issuer_cik",
        "issuer_name",
        "ticker",
        "owner_cik",
        "owner_name",
        "owner_relationship",
        "owner_title",
        "shares",
        "price",
        "purchase_value_usd",
        "direct_or_indirect",
        "aff10b5one",
    ]
    return renamed[columns].sort_values(["filing_date", "issuer_cik", "owner_cik"]), counts


def ingest_quarter(year: int, quarter: int, *, user_agent: str) -> QuarterResult:
    payload, url = _download(year, quarter, user_agent=user_agent)
    normalized, counts = normalize_quarter(payload)
    quarter_dir = OUT_DIR / f"year={year}" / f"quarter={quarter}"
    quarter_dir.mkdir(parents=True, exist_ok=True)
    output = quarter_dir / "events.parquet"
    normalized.to_parquet(output, index=False)
    return QuarterResult(
        year=year,
        quarter=quarter,
        source_url=url,
        source_sha256=_sha256(payload),
        source_bytes=len(payload),
        qualifying_rows=len(normalized),
        output_path=str(output),
        **counts,
    )


def quarters(start_year: int, end_year: int, end_quarter: int) -> list[tuple[int, int]]:
    return [
        (year, quarter)
        for year in range(start_year, end_year + 1)
        for quarter in range(1, 5)
        if year < end_year or quarter <= end_quarter
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2006)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--end-quarter", type=int, choices=(1, 2, 3, 4), default=2)
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)

    results: list[QuarterResult] = []
    for year, quarter in quarters(args.start_year, args.end_year, args.end_quarter):
        result = ingest_quarter(year, quarter, user_agent=user_agent)
        results.append(result)
        print(f"{year} Q{quarter}: {result.qualifying_rows:,} qualifying rows")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "canli.sec-insider-lake.v1",
        "source": "SEC DERA Insider Transactions Data Sets",
        "source_page": (
            "https://www.sec.gov/data-research/sec-markets-data/"
            "insider-transactions-data-sets"
        ),
        "selection": (
            "original Form 4; non-derivative code P; acquired; officer/director; "
            "positive shares and price"
        ),
        "amendment_policy": "Form 4/A excluded rather than heuristically joined",
        "quarters": [asdict(result) for result in results],
        "total_qualifying_rows": sum(result.qualifying_rows for result in results),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT_DIR / 'manifest.json'} ({manifest['total_qualifying_rows']:,} rows)")


if __name__ == "__main__":
    main()
