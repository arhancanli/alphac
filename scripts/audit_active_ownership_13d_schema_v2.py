#!/usr/bin/env python3
"""Run the schema-aware v2 Schedule 13D metadata audit without documents or returns."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_active_ownership_13d_metadata import (
    PARSER_VERSION,
    parse_header,
    read_or_fetch,
    ticker_matches,
)
from audit_sec_filing_text_feasibility import sha256_bytes
from build_sec_10k_manifest import SecClient

RAW: Final = Path("data/raw/sec_active_ownership_13d")
OUT: Final = Path("artifacts/feasibility/active_ownership_13d_schema_v2")
TICKERS: Final = Path(
    "artifacts/ingest/earnings_narrative_change/issuer_ticker_history.parquet"
)
PROTOCOL: Final = "docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D_SCHEMA_V2.md"
FORMS: Final = {"SC 13D", "SCHEDULE 13D"}
ACCESSION_PATTERN: Final = re.compile(r"(\d{10}-\d{2}-\d{6})\.txt$")


def parse_index(raw: bytes, year: int, quarter: int) -> list[dict]:
    lines = raw.decode("latin-1", errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if line.startswith("CIK|")), None)
    if header is None:
        raise ValueError(f"missing pipe header in {year} Q{quarter}")
    rows: list[dict] = []
    for line in lines[header + 1 :]:
        fields = line.split("|")
        if len(fields) != 5 or fields[2] not in FORMS:
            continue
        filer_cik, company_name, form, filing_date, filename = fields
        match = ACCESSION_PATTERN.search(filename)
        if not match:
            continue
        parts = filename.split("/")
        if len(parts) < 4 or not parts[2].isdigit():
            continue
        rows.append(
            {
                "year": year,
                "quarter": quarter,
                "associated_cik": int(filer_cik),
                "index_company_name": company_name,
                "form": form,
                "filing_date": filing_date,
                "accession": match.group(1),
                "index_filename": filename,
                "archive_cik": int(parts[2]),
            }
        )
    return rows


def accession_table(rows: pd.DataFrame) -> pd.DataFrame:
    grouped: list[dict] = []
    for accession, frame in rows.groupby("accession", sort=True):
        first = frame.sort_values(["year", "quarter", "associated_cik"]).iloc[0]
        grouped.append(
            {
                "year": int(first["year"]),
                "quarter": int(first["quarter"]),
                "filing_date": str(first["filing_date"]),
                "form": str(first["form"]),
                "accession": accession,
                "index_filename": str(first["index_filename"]),
                "archive_cik": int(first["archive_cik"]),
                "associated_ciks": sorted(set(frame["associated_cik"].astype(int))),
                "association_count": int(frame["associated_cik"].nunique()),
            }
        )
    return pd.DataFrame(grouped)


def locked_sample(frame: pd.DataFrame, per_year: int = 50) -> pd.DataFrame:
    sample = frame.copy()
    sample["sample_rank"] = sample.apply(
        lambda row: hashlib.sha256(f"{int(row['year'])}|{row['accession']}".encode()).hexdigest(),
        axis=1,
    )
    return (
        sample.sort_values(["year", "sample_rank", "accession"])
        .groupby("year", group_keys=False)
        .head(per_year)
        .reset_index(drop=True)
    )


def wilson_lower(successes: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = proportion + z**2 / (2 * total)
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2))
    return (centre - margin) / denominator


def run(args: argparse.Namespace) -> dict:
    raw_dir = Path(args.raw)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    index_failures: list[dict] = []
    for year in range(args.start_year, args.end_year + 1):
        for quarter in range(1, 5):
            path = raw_dir / "indexes" / f"{year}-Q{quarter}.idx.gz"
            try:
                rows.extend(parse_index(gzip.decompress(path.read_bytes()), year, quarter))
            except Exception as error:
                index_failures.append(
                    {"year": year, "quarter": quarter, "path": str(path), "error": str(error)}
                )
    filings = accession_table(pd.DataFrame(rows))
    filings.to_parquet(out / "initial_13d_accessions.parquet", index=False, compression="zstd")
    sample = locked_sample(filings, args.sample_per_year)
    sample.to_csv(out / "locked_header_sample.csv", index=False)

    client = SecClient(raw_dir / "network_metadata_cache")
    headers: list[dict] = []
    try:
        for index, record in enumerate(sample.to_dict("records"), 1):
            accession = str(record["accession"])
            path = raw_dir / "headers" / f"{accession}.hdr.sgml.gz"
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(record['archive_cik'])}/{accession.replace('-', '')}/{accession}.hdr.sgml"
            )
            try:
                raw, cached = read_or_fetch(client, url, path, args.uncached_delay)
                parsed = parse_header(raw)
                associated = set(record["associated_ciks"])
                headers.append(
                    {
                        **record,
                        **parsed,
                        "both_header_ciks_in_association_set": bool(
                            parsed["subject_cik"] in associated
                            and parsed["filed_by_cik"] in associated
                        ),
                        "parser_version": PARSER_VERSION,
                        "header_url": url,
                        "header_cache_path": str(path),
                        "header_sha256": sha256_bytes(raw),
                        "header_bytes": len(raw),
                        "header_from_cache": cached,
                        "error": None,
                    }
                )
            except Exception as error:
                headers.append({**record, "error": str(error)})
            if index % 50 == 0 or index == len(sample):
                print(f"13D v2 headers {index}/{len(sample)}", flush=True)
    finally:
        client.close()

    audited = ticker_matches(pd.DataFrame(headers), pd.read_parquet(args.tickers))
    audited.to_parquet(out / "header_audit.parquet", index=False, compression="zstd")
    annual = filings.groupby("year").size()
    successful = audited["error"].isna()
    lineage = successful & audited[
        ["acceptance_datetime", "subject_cik", "filed_by_cik"]
    ].notna().all(axis=1)
    association = lineage & audited["both_header_ciks_in_association_set"].fillna(False)
    unique = lineage & audited["ticker_match_count"].eq(1)
    unique_by_year = audited[unique].groupby("year").size()
    unique_total = int(unique.sum())
    lineage_total = int(lineage.sum())
    lower = wilson_lower(unique_total, lineage_total)
    expected_sample = (args.end_year - args.start_year + 1) * args.sample_per_year
    gates = {
        "quarterly_indexes_64_of_64": len(index_failures) == 0,
        "every_year_at_least_100_initial_accessions": all(
            int(annual.get(year, 0)) >= 100 for year in range(args.start_year, args.end_year + 1)
        ),
        "sample_800_and_50_per_year": bool(
            len(sample) == expected_sample == 800
            and sample.groupby("year").size().eq(50).all()
        ),
        "headers_800_of_800": int(successful.sum()) == len(sample) == 800,
        "header_lineage_rate_gte_0_98": float(lineage.mean()) >= 0.98,
        "header_ciks_in_association_set_rate_gte_0_98": (
            float(association[lineage].mean()) >= 0.98 if lineage.any() else False
        ),
        "at_least_10_unique_tickers_every_year": all(
            int(unique_by_year.get(year, 0)) >= 10
            for year in range(args.start_year, args.end_year + 1)
        ),
        "ticker_mapping_wilson_lower_gt_0_20": lower > 0.20,
    }
    result = {
        "schema": "canli.feasibility.active-ownership-13d-schema-v2.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_metadata_feasibility_no_documents_no_returns",
        "protocol": PROTOCOL,
        "hypothesis_identities_spent": 0,
        "forms": sorted(FORMS),
        "quarterly_index_failures": index_failures,
        "unique_initial_accessions": len(filings),
        "initial_accessions_by_year": {
            str(year): int(annual.get(year, 0))
            for year in range(args.start_year, args.end_year + 1)
        },
        "locked_header_sample": len(sample),
        "successful_headers": int(successful.sum()),
        "header_lineage_rate": float(lineage.mean()),
        "header_cik_association_rate": (
            float(association[lineage].mean()) if lineage.any() else 0.0
        ),
        "unique_ticker_matches": unique_total,
        "unique_ticker_mapping_rate": unique_total / lineage_total if lineage_total else 0.0,
        "unique_ticker_wilson_95_lower": lower,
        "unique_ticker_matches_by_year": {
            str(year): int(unique_by_year.get(year, 0))
            for year in range(args.start_year, args.end_year + 1)
        },
        "gates": gates,
        "decision": "PASS_TO_DOCUMENT_FEASIBILITY" if all(gates.values()) else "DATA_GATED",
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--tickers", default=str(TICKERS))
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--sample-per-year", type=int, default=50)
    parser.add_argument("--uncached-delay", type=float, default=0.8)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
