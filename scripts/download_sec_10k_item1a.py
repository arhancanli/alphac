#!/usr/bin/env python3
"""Download and extract the preregistered 10-K Item 1A corpus, without opening returns.

Raw SEC responses are retained as deterministic gzip streams. Extracted rows are written in
bounded Parquet parts, making the multi-hour official-source ingest safe to stop and resume.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import (
    PARSER_VERSION,
    extract_sections,
    html_to_text,
    sha256_bytes,
    sha256_text,
)
from build_sec_10k_manifest import SecClient

MANIFEST: Final = Path("artifacts/ingest/earnings_narrative_change/filings_manifest.parquet")
RAW_DIR: Final = Path("data/raw/sec_10k_narrative")
OUT_DIR: Final = Path("artifacts/ingest/earnings_narrative_change/item1a_parts")
RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/corpus_result.json")
SIC_PATTERN: Final = re.compile(r"(?:[?&]|&amp;)SIC=(\d{4})\b", re.IGNORECASE)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parts_lineage(out_dir: Path) -> tuple[int, str]:
    """Bind a corpus result to exact immutable part names, sizes, and bytes."""
    digest = hashlib.sha256()
    paths = sorted(out_dir.glob("part-*.parquet"))
    for path in paths:
        identity = f"{path.name}\0{path.stat().st_size}\0{file_sha256(path)}\n"
        digest.update(identity.encode())
    return len(paths), digest.hexdigest()


def parse_sic(index_html: bytes) -> str | None:
    match = SIC_PATTERN.search(index_html.decode("utf-8", errors="replace"))
    return match.group(1) if match else None


def gzip_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    temporary.replace(path)


def gzip_read(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def cached_response(client: SecClient, url: str, path: Path) -> tuple[bytes, bool]:
    if path.exists():
        try:
            return gzip_read(path), True
        except (EOFError, OSError):
            path.unlink()
    raw = client.get_bytes(url)
    gzip_write(path, raw)
    return raw, False


def process_filing(client: SecClient, raw_dir: Path, filing: dict) -> dict:
    accession = str(filing["accession"])
    cache_key = f"{int(filing['cik'])}_{accession}"
    index_path = raw_dir / "index" / f"{cache_key}.html.gz"
    document_path = raw_dir / "documents" / f"{cache_key}.html.gz"
    base = {
        **filing,
        "parser_version": PARSER_VERSION,
        "index_cache_path": str(index_path),
        "document_cache_path": str(document_path),
    }
    try:
        index_raw, index_cached = cached_response(client, str(filing["index_url"]), index_path)
        document_raw, document_cached = cached_response(
            client, str(filing["document_url"]), document_path
        )
        text = html_to_text(document_raw)
        section = extract_sections(text, "10-K").get("risk_factors")
        return {
            **base,
            "sic": parse_sic(index_raw),
            "index_sha256": sha256_bytes(index_raw),
            "index_bytes": len(index_raw),
            "index_from_cache": index_cached,
            "document_sha256": sha256_bytes(document_raw),
            "document_bytes": len(document_raw),
            "document_from_cache": document_cached,
            "document_words": len(text.split()),
            "extracted": section is not None,
            "section_words": len(section.split()) if section else 0,
            "section_sha256": sha256_text(section) if section else None,
            "section_text": section,
            "error": None,
        }
    except Exception as error:
        return {
            **base,
            "sic": None,
            "index_sha256": None,
            "index_bytes": 0,
            "index_from_cache": index_path.exists(),
            "document_sha256": None,
            "document_bytes": 0,
            "document_from_cache": document_path.exists(),
            "document_words": 0,
            "extracted": False,
            "section_words": 0,
            "section_sha256": None,
            "section_text": None,
            "error": str(error),
        }


def completed_identities(out_dir: Path) -> set[str]:
    complete: set[str] = set()
    for path in sorted(out_dir.glob("part-*.parquet")):
        frame = pd.read_parquet(path, columns=["filing_identity", "parser_version", "sic", "error"])
        sealed = (
            frame["error"].isna()
            & frame["parser_version"].eq(PARSER_VERSION)
        )
        complete.update(frame.loc[sealed, "filing_identity"].astype(str))
    return complete


def write_part(out_dir: Path, part_number: int, rows: list[dict]) -> Path:
    path = out_dir / f"part-{part_number:05d}.parquet"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite completed corpus part: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows).to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)
    return path


def summarize(
    out_dir: Path, manifest_path: Path, manifest_rows: int, eligible_rows: int
) -> dict:
    summaries = []
    for path in sorted(out_dir.glob("part-*.parquet")):
        summaries.append(
            pd.read_parquet(
                path,
                columns=[
                    "accession",
                    "cik",
                    "parser_version",
                    "extracted",
                    "sic",
                    "error",
                    "section_words",
                ],
            )
        )
    frame = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    if len(frame):
        frame = frame.drop_duplicates(["cik", "accession"], keep="last")
    processed = len(frame)
    successful = int(frame["error"].isna().sum()) if processed else 0
    extracted = int(frame["extracted"].sum()) if processed else 0
    sic_complete = int(frame["sic"].notna().sum()) if processed else 0
    sic_missing_at_source = successful - sic_complete
    parser_complete = int(frame["parser_version"].eq(PARSER_VERSION).sum()) if processed else 0
    part_count, parts_sha256 = parts_lineage(out_dir)
    return {
        "schema": "canli.ingest.sec-10k-item1a-corpus.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "corpus_ingest_no_prices_no_returns",
        "hypothesis_identities_spent": 0,
        "preregistration": "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "parser_version": PARSER_VERSION,
        "source_manifest": {
            "path": str(manifest_path),
            "sha256": file_sha256(manifest_path),
        },
        "manifest_rows": manifest_rows,
        "pair_eligible_manifest_rows": eligible_rows,
        "processed_rows": processed,
        "successful_downloads": successful,
        "download_rate": successful / processed if processed else 0.0,
        "item1a_extracted": extracted,
        "item1a_extraction_rate": extracted / successful if successful else 0.0,
        "sic_complete": sic_complete,
        "sic_missing_at_source": sic_missing_at_source,
        "sic_rate": sic_complete / successful if successful else 0.0,
        "current_parser_rows": parser_complete,
        "median_section_words": float(frame["section_words"].median()) if processed else 0.0,
        "unique_ciks": int(frame["cik"].nunique()) if processed else 0,
        "part_count": part_count,
        "parts_sha256": parts_sha256,
        "complete": (
            processed == eligible_rows
            and successful == eligible_rows
            and parser_complete == successful
        ),
    }


def run(args: argparse.Namespace) -> dict:
    manifest_path = Path(args.manifest)
    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    result_path = Path(args.result)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = pd.read_parquet(manifest_path)
    counts = manifest.groupby("cik")["accession"].transform("size")
    eligible = manifest[counts.ge(2)].sort_values(["cik", "acceptance_datetime"]).copy()
    if args.max_filings is not None:
        eligible = eligible.head(args.max_filings)
    complete = completed_identities(out_dir)
    pending = eligible[~eligible["filing_identity"].astype(str).isin(complete)]
    existing_parts = sorted(out_dir.glob("part-*.parquet"))
    next_part = int(existing_parts[-1].stem.split("-")[-1]) + 1 if existing_parts else 0

    client = SecClient(raw_dir / "network_metadata_cache")
    buffer: list[dict] = []
    try:
        records = pending.to_dict("records")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = pool.map(lambda row: process_filing(client, raw_dir, row), records)
            for number, row in enumerate(results, 1):
                buffer.append(row)
                if len(buffer) >= args.batch_size:
                    write_part(out_dir, next_part, buffer)
                    next_part += 1
                    buffer = []
                if number % 100 == 0 or number == len(records):
                    print(
                        f"filings {number}/{len(records)} pending | "
                        f"completed before run {len(complete)}",
                        flush=True,
                    )
            if buffer:
                write_part(out_dir, next_part, buffer)
    finally:
        client.close()

    result = summarize(out_dir, manifest_path, len(manifest), len(eligible))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--max-filings", type=int)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
