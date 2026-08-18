#!/usr/bin/env python3
"""Audit global Schedule 13D target lineage without opening documents or returns."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import sha256_bytes
from build_sec_10k_manifest import SecClient

OUT: Final = Path("artifacts/feasibility/active_ownership_13d")
RAW: Final = Path("data/raw/sec_active_ownership_13d")
TICKERS: Final = Path(
    "artifacts/ingest/earnings_narrative_change/issuer_ticker_history.parquet"
)
PROTOCOL: Final = "docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D.md"
PARSER_VERSION: Final = "sec-13d-header-v2"
START_YEAR: Final = 2010
END_YEAR: Final = 2025
ACCESSION_PATTERN: Final = re.compile(r"(\d{10}-\d{2}-\d{6})\.txt$")
ACCEPTANCE_PATTERN: Final = re.compile(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", re.I)
CIK_PATTERN: Final = re.compile(r"<(?:CIK|CENTRAL-INDEX-KEY)>\s*0*(\d+)", re.I)


def deterministic_gzip(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))


def read_or_fetch(client: SecClient, url: str, path: Path, delay: float) -> tuple[bytes, bool]:
    if path.exists():
        return gzip.decompress(path.read_bytes()), True
    raw = client.get_bytes(url)
    deterministic_gzip(path, raw)
    if delay > 0:
        time.sleep(delay)
    return raw, False


def parse_master_index(raw: bytes, year: int, quarter: int) -> list[dict]:
    lines = raw.decode("latin-1", errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if line.startswith("CIK|")), None)
    if header is None:
        raise ValueError(f"missing pipe header in {year} Q{quarter}")
    rows: list[dict] = []
    for line in lines[header + 1 :]:
        fields = line.split("|")
        if len(fields) != 5:
            continue
        filer_cik, company_name, form, filing_date, filename = fields
        if form != "SC 13D":
            continue
        match = ACCESSION_PATTERN.search(filename)
        if not match:
            continue
        accession = match.group(1)
        rows.append(
            {
                "year": year,
                "quarter": quarter,
                "index_filer_cik": int(filer_cik),
                "index_company_name": company_name,
                "form": form,
                "filing_date": filing_date,
                "accession": accession,
                "index_filename": filename,
                "header_url": (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{int(filer_cik)}/{accession.replace('-', '')}/{accession}.hdr.sgml"
                ),
            }
        )
    return rows


def section(text: str, name: str) -> str | None:
    pattern = re.compile(
        rf"<{re.escape(name)}>\s*(.*?)(?=\n\s*<(?:SUBJECT-COMPANY|FILED-BY|REPORTING-OWNER|"
        rf"ISSUER|SERIES|OWNER-DATA)>|\Z)",
        re.I | re.S,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def parse_header(raw: bytes) -> dict:
    text = raw.decode("latin-1", errors="replace")
    accepted = ACCEPTANCE_PATTERN.search(text)
    subject = section(text, "SUBJECT-COMPANY")
    filed_by = section(text, "FILED-BY") or section(text, "REPORTING-OWNER")
    subject_cik = CIK_PATTERN.search(subject or "")
    filed_by_cik = CIK_PATTERN.search(filed_by or "")
    return {
        "acceptance_datetime": accepted.group(1) if accepted else None,
        "subject_cik": int(subject_cik.group(1)) if subject_cik else None,
        "filed_by_cik": int(filed_by_cik.group(1)) if filed_by_cik else None,
    }


def locked_sample(frame: pd.DataFrame, per_year: int = 10) -> pd.DataFrame:
    sample = frame.copy()
    sample["sample_rank"] = sample.apply(
        lambda row: hashlib.sha256(
            f"{int(row['year'])}|{int(row['index_filer_cik'])}|{row['accession']}".encode()
        ).hexdigest(),
        axis=1,
    )
    return (
        sample.sort_values(["year", "sample_rank", "accession"])
        .groupby("year", group_keys=False)
        .head(per_year)
        .reset_index(drop=True)
    )


def ticker_matches(rows: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    history = tickers.copy()
    history["firstpricedate"] = pd.to_datetime(history["firstpricedate"], errors="coerce")
    history["lastpricedate"] = pd.to_datetime(history["lastpricedate"], errors="coerce")
    grouped = dict(iter(history.groupby("cik", sort=False)))
    out = rows.copy()
    counts: list[int] = []
    names: list[str | None] = []
    for record in out.to_dict("records"):
        cik = record.get("subject_cik")
        filing_date = pd.Timestamp(record["filing_date"])
        candidates = grouped.get(cik, pd.DataFrame())
        if len(candidates):
            candidates = candidates[
                candidates["firstpricedate"].le(filing_date)
                & candidates["lastpricedate"].ge(filing_date)
            ].drop_duplicates(["permaticker"])
        counts.append(len(candidates))
        names.append(str(candidates.iloc[0]["ticker"]) if len(candidates) == 1 else None)
    out["ticker_match_count"] = counts
    out["ticker"] = names
    return out


def run(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    raw_dir = Path(args.raw)
    out.mkdir(parents=True, exist_ok=True)
    client = SecClient(raw_dir / "network_metadata_cache")
    index_rows: list[dict] = []
    index_failures: list[dict] = []
    try:
        for year in range(args.start_year, args.end_year + 1):
            for quarter in range(1, 5):
                url = (
                    f"https://www.sec.gov/Archives/edgar/full-index/{year}/"
                    f"QTR{quarter}/master.idx"
                )
                path = raw_dir / "indexes" / f"{year}-Q{quarter}.idx.gz"
                try:
                    raw, _ = read_or_fetch(client, url, path, args.uncached_delay)
                    index_rows.extend(parse_master_index(raw, year, quarter))
                except Exception as error:
                    index_failures.append(
                        {"year": year, "quarter": quarter, "url": url, "error": str(error)}
                    )
            print(f"13D quarterly indexes through {year}", flush=True)

        index_frame = pd.DataFrame(index_rows)
        source_duplicate_accessions = int(index_frame["accession"].duplicated().sum())
        filings = index_frame.drop_duplicates("accession", keep="first")
        filings.to_parquet(out / "initial_13d_index.parquet", index=False, compression="zstd")
        sample = locked_sample(filings, args.sample_per_year)
        sample.to_csv(out / "locked_header_sample.csv", index=False)
        headers: list[dict] = []
        for index, record in enumerate(sample.to_dict("records"), 1):
            path = raw_dir / "headers" / f"{record['accession']}.hdr.sgml.gz"
            try:
                raw, cached = read_or_fetch(
                    client, str(record["header_url"]), path, args.uncached_delay
                )
                headers.append(
                    {
                        **record,
                        **parse_header(raw),
                        "parser_version": PARSER_VERSION,
                        "header_cache_path": str(path),
                        "header_sha256": sha256_bytes(raw),
                        "header_bytes": len(raw),
                        "header_from_cache": cached,
                        "error": None,
                    }
                )
            except Exception as error:
                headers.append({**record, "error": str(error)})
            if index % 20 == 0 or index == len(sample):
                print(f"13D headers {index}/{len(sample)}", flush=True)
    finally:
        client.close()

    header_frame = pd.DataFrame(headers)
    header_frame = ticker_matches(header_frame, pd.read_parquet(args.tickers))
    header_frame.to_parquet(out / "header_audit.parquet", index=False, compression="zstd")
    annual = filings.groupby("year").size() if len(filings) else pd.Series(dtype=int)
    successful = header_frame["error"].isna()
    lineage = successful & header_frame[
        ["acceptance_datetime", "subject_cik", "filed_by_cik"]
    ].notna().all(axis=1)
    filer_match = lineage & header_frame["filed_by_cik"].eq(header_frame["index_filer_cik"])
    ticker_unique = lineage & header_frame["ticker_match_count"].eq(1)
    gates = {
        "quarterly_indexes_64_of_64": len(index_failures) == 0,
        "every_year_at_least_100_initial_filings": all(
            int(annual.get(year, 0)) >= 100 for year in range(args.start_year, args.end_year + 1)
        ),
        "duplicate_accessions_zero_after_assembly": not filings["accession"].duplicated().any(),
        "headers_160_of_160": int(successful.sum()) == len(sample) == 160,
        "header_lineage_rate_gte_0_98": float(lineage.mean()) >= 0.98,
        "filed_by_matches_index_rate_gte_0_98": (
            float(filer_match[lineage].mean()) >= 0.98 if lineage.any() else False
        ),
        "unique_contemporaneous_ticker_rate_gte_0_80": (
            float(ticker_unique[lineage].mean()) >= 0.80 if lineage.any() else False
        ),
    }
    result = {
        "schema": "canli.feasibility.active-ownership-13d-metadata.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_metadata_feasibility_no_documents_no_returns",
        "protocol": PROTOCOL,
        "hypothesis_identities_spent": 0,
        "period": {"start_year": args.start_year, "end_year": args.end_year},
        "quarterly_indexes_expected": 64,
        "quarterly_index_failures": index_failures,
        "initial_13d_filings": len(filings),
        "source_duplicate_accessions": source_duplicate_accessions,
        "initial_13d_by_year": {
            str(year): int(annual.get(year, 0))
            for year in range(args.start_year, args.end_year + 1)
        },
        "locked_header_sample": len(sample),
        "successful_headers": int(successful.sum()),
        "header_lineage_rate": float(lineage.mean()),
        "filed_by_index_match_rate": float(filer_match[lineage].mean()) if lineage.any() else 0.0,
        "unique_contemporaneous_ticker_rate": (
            float(ticker_unique[lineage].mean()) if lineage.any() else 0.0
        ),
        "gates": gates,
        "decision": "PASS_TO_DOCUMENT_FEASIBILITY" if all(gates.values()) else "DATA_GATED",
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--tickers", default=str(TICKERS))
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--sample-per-year", type=int, default=10)
    parser.add_argument("--uncached-delay", type=float, default=0.8)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
