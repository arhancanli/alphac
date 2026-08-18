#!/usr/bin/env python3
"""Audit a frozen Form 10 document sample without opening prices or returns."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import PARSER_VERSION, html_to_text, sha256_bytes

LINEAGE: Final = Path("artifacts/feasibility/spin_off_dislocation/form10_filings.parquet")
RAW_DIR: Final = Path("data/raw/spin_off_dislocation/document_schema")
OUT_DIR: Final = Path("artifacts/feasibility/spin_off_dislocation")
PROTOCOL: Final = "docs/design/FEASIBILITY_SPIN_OFF_DOCUMENT_SCHEMA.md"
UA: Final = "Canli Capital quantitative research research@canlicapital.com"
ROW_PATTERN: Final = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
HREF_PATTERN: Final = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
TAG_PATTERN: Final = re.compile(r"<[^>]+>")
ACCEPTED_PATTERN: Final = re.compile(
    r"Accepted\s*</div>\s*<div[^>]*class=[\"']info[\"'][^>]*>\s*([^<]+)", re.I | re.S
)
SPIN_PATTERN: Final = re.compile(r"\bspin(?:\s|-)?off\b", re.I)
SEPARATION_DISTRIBUTION_PATTERN: Final = re.compile(
    r"\bseparation\s+and\s+distribution(?:\s+agreement)?\b", re.I
)
PRO_RATA_PATTERN: Final = re.compile(
    r"(?:\bpro\s+rata\b.{0,220}\bdistribut|\bdistribut.{0,220}"
    r"\b(?:holders|stockholders)\s+of\b)",
    re.I | re.S,
)
RATIO_PATTERN: Final = re.compile(
    r"\b(?:one|[0-9]+(?:\.[0-9]+)?)\s+shares?\b.{0,180}\b(?:for\s+every|for\s+each)\b",
    re.I | re.S,
)
RECORD_DATE_PATTERN: Final = re.compile(r"\brecord\s+date\b", re.I)
DISTRIBUTION_DATE_PATTERN: Final = re.compile(r"\bdistribution\s+date\b", re.I)


def frozen_sample(lineage: pd.DataFrame) -> pd.DataFrame:
    initial = lineage[lineage["form"] == "10-12B"].copy()
    initial["year"] = pd.to_datetime(initial["filing_date"]).dt.year
    initial["sample_hash"] = initial.apply(
        lambda row: hashlib.sha256(f"{row['cik']}|{row['accession']}".encode()).hexdigest(),
        axis=1,
    )
    sample = (
        initial.sort_values(["year", "sample_hash", "cik", "accession"])
        .groupby("year", group_keys=False)
        .head(10)
        .reset_index(drop=True)
    )
    return sample


def filing_index_url(archive_filename: str) -> str:
    if not archive_filename.endswith(".txt"):
        raise ValueError(f"unexpected SEC archive filename: {archive_filename}")
    stem = archive_filename[:-4]
    return f"https://www.sec.gov/Archives/{stem}-index.html"


def visible_text(fragment: str) -> str:
    return " ".join(html.unescape(TAG_PATTERN.sub(" ", fragment)).split())


def parse_index_page(raw: bytes, *, expected_form: str = "10-12B") -> tuple[str, str]:
    text = raw.decode("utf-8", errors="replace")
    accepted = ACCEPTED_PATTERN.search(text)
    if accepted is None:
        raise ValueError("SEC filing index has no accepted timestamp")
    candidates = []
    for row in ROW_PATTERN.findall(text):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
        cell_text = [visible_text(cell) for cell in cells]
        if expected_form not in cell_text:
            continue
        href = HREF_PATTERN.search(row)
        if href is not None:
            candidates.append(href.group(1))
    if len(candidates) != 1:
        raise ValueError(
            f"expected one primary {expected_form} document link, found {len(candidates)}"
        )
    return " ".join(accepted.group(1).split()), candidates[0]


def fetch(client: httpx.Client, url: str) -> bytes:
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
    raise RuntimeError(f"SEC filing request failed after retries: {url}") from error


def read_or_fetch(client: httpx.Client, url: str, path: Path) -> tuple[bytes, bool]:
    if path.exists():
        return gzip.decompress(path.read_bytes()), True
    raw = fetch(client, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    return raw, False


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    successful = frame["error"].isna()
    explicit = frame["spin_language"].fillna(False) | frame[
        "separation_distribution_language"
    ].fillna(False)
    gates = {
        "exactly_98_frozen_filings": len(frame) == 98,
        "all_filing_indexes_and_exact_primary_links": bool(successful.all())
        and bool(frame["primary_document_url"].notna().all()),
        "all_acceptance_timestamps": bool(frame["acceptance_datetime"].notna().all()),
        "all_primary_documents_hash_bound": bool(
            frame["primary_document_sha256"].fillna("").str.fullmatch(r"[0-9a-f]{64}").all()
        ),
        "explicit_spin_or_separation_language_rate_gte_0_50": float(explicit.mean()) >= 0.50,
        "pro_rata_distribution_language_rate_gte_0_30": float(
            frame["pro_rata_distribution_language"].fillna(False).mean()
        )
        >= 0.30,
        "market_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    return {
        "schema": "canli.feasibility.spin-off-document-schema.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_initial_form10_document_schema_no_prices_no_returns",
        "protocol": PROTOCOL,
        "parser_version": PARSER_VERSION,
        "sample_rows": len(frame),
        "successful_rows": int(successful.sum()),
        "explicit_spin_or_separation_language": int(explicit.sum()),
        "explicit_spin_or_separation_language_rate": float(explicit.mean()),
        "pro_rata_distribution_language": int(
            frame["pro_rata_distribution_language"].fillna(False).sum()
        ),
        "pro_rata_distribution_language_rate": float(
            frame["pro_rata_distribution_language"].fillna(False).mean()
        ),
        "ratio_mentions": int(frame["ratio_mention"].fillna(False).sum()),
        "record_date_mentions": int(frame["record_date_mention"].fillna(False).sum()),
        "distribution_date_mentions": int(
            frame["distribution_date_mention"].fillna(False).sum()
        ),
        "gates": gates,
        "decision": "PASS_TO_AMENDMENT_CHAIN_AUDIT" if all(gates.values()) else "DATA_GATED",
        "market_data_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def run(lineage_path: Path, raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    sample = frozen_sample(pd.read_parquet(lineage_path))
    rows = []
    out_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        for number, record in enumerate(sample.to_dict("records"), 1):
            accession = str(record["accession"])
            index_url = filing_index_url(str(record["archive_filename"]))
            index_path = raw_dir / "indexes" / f"{accession}.html.gz"
            try:
                index_raw, index_cached = read_or_fetch(client, index_url, index_path)
                accepted, document_href = parse_index_page(index_raw)
                document_url = urljoin(index_url, document_href)
                suffix = Path(document_href).suffix or ".html"
                document_path = raw_dir / "documents" / f"{accession}{suffix}.gz"
                document_raw, document_cached = read_or_fetch(
                    client, document_url, document_path
                )
                text = html_to_text(document_raw)
                rows.append(
                    {
                        **record,
                        "index_url": index_url,
                        "index_sha256": sha256_bytes(index_raw),
                        "index_from_cache": index_cached,
                        "acceptance_datetime": accepted,
                        "primary_document_url": document_url,
                        "primary_document_sha256": sha256_bytes(document_raw),
                        "primary_document_bytes": len(document_raw),
                        "primary_document_words": len(text.split()),
                        "primary_document_from_cache": document_cached,
                        "spin_language": bool(SPIN_PATTERN.search(text)),
                        "separation_distribution_language": bool(
                            SEPARATION_DISTRIBUTION_PATTERN.search(text)
                        ),
                        "pro_rata_distribution_language": bool(PRO_RATA_PATTERN.search(text)),
                        "ratio_mention": bool(RATIO_PATTERN.search(text)),
                        "record_date_mention": bool(RECORD_DATE_PATTERN.search(text)),
                        "distribution_date_mention": bool(
                            DISTRIBUTION_DATE_PATTERN.search(text)
                        ),
                        "error": None,
                    }
                )
            except Exception as exc:
                rows.append({**record, "index_url": index_url, "error": str(exc)})
            if number % 10 == 0 or number == len(sample):
                print(f"spin-off documents {number}/{len(sample)}", flush=True)
            time.sleep(0.13)
    frame = pd.DataFrame(rows)
    frame.to_parquet(out_dir / "initial_document_schema.parquet", index=False)
    result = summarize(frame)
    (out_dir / "document_schema_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", type=Path, default=LINEAGE)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    result = run(args.lineage, args.raw_dir, args.out_dir)
    return 0 if result["decision"] == "PASS_TO_AMENDMENT_CHAIN_AUDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
