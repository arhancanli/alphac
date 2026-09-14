#!/usr/bin/env python3
"""Extract the 10-K Item 7 (MD&A) corpus from the filings already cached on disk. No returns.

WHY. The earnings-narrative-change pre-registration locked its first identity to Item 1A and
reserved the candidate's second and final budgeted identity for the MD&A variant under a new
pre-registration. The v2 full-evidence reservation needs a probability-of-backtest-overfitting
matrix, and a matrix needs at least two counted columns, so the MD&A identity is what lets the
family be decided at all rather than closing INCOMPLETE. Every 10-K document the Item 1A corpus
read is cached under data/raw/sec_10k_narrative (82,491 documents, 16 GB, gzip); this script
re-parses those bytes for Item 7 and never touches the network. Same manifest, same parser
version, same eligibility rule (issuers with at least two filings), same part layout, so
scripts/build_sec_item1a_pairs.py builds the Item 7 pairs unchanged.

Reads no prices, computes no return, spends no hypothesis identity.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import (
    PARSER_VERSION,
    extract_sections,
    html_to_text,
    sha256_bytes,
    sha256_text,
)
from download_sec_10k_item1a import (
    completed_identities,
    file_sha256,
    parse_sic,
    parts_lineage,
    write_part,
)

MANIFEST: Final = Path("artifacts/ingest/earnings_narrative_change/filings_manifest.parquet")
RAW_DIR: Final = Path("data/raw/sec_10k_narrative")
OUT_DIR: Final = Path("artifacts/ingest/earnings_narrative_change/item7_parts")
RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/item7_corpus_result.json")
SECTION: Final = "mda"
SCHEMA: Final = "canli.ingest.sec-10k-item7-corpus.v1"
PREREG: Final = "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE_MDNA.md"


def _read_cached(path: Path) -> bytes:
    with gzip.open(path, "rb") as handle:
        return handle.read()


def process_cached_filing(args: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """One filing from the on-disk cache; a missing cache entry is an error row, never a fetch."""
    raw_dir_text, filing = args
    raw_dir = Path(raw_dir_text)
    accession = str(filing["accession"])
    cache_key = f"{int(filing['cik'])}_{accession}"
    index_path = raw_dir / "index" / f"{cache_key}.html.gz"
    document_path = raw_dir / "documents" / f"{cache_key}.html.gz"
    base: dict[str, Any] = {
        **filing,
        "parser_version": PARSER_VERSION,
        "section": SECTION,
        "index_cache_path": str(index_path),
        "document_cache_path": str(document_path),
    }
    try:
        if not document_path.is_file() or not index_path.is_file():
            raise FileNotFoundError(f"not cached: {cache_key}")
        index_raw = _read_cached(index_path)
        document_raw = _read_cached(document_path)
        text = html_to_text(document_raw)
        section = extract_sections(text, "10-K").get(SECTION)
        return {
            **base,
            "sic": parse_sic(index_raw),
            "index_sha256": sha256_bytes(index_raw),
            "index_bytes": len(index_raw),
            "index_from_cache": True,
            "document_sha256": sha256_bytes(document_raw),
            "document_bytes": len(document_raw),
            "document_from_cache": True,
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


def summarize(out_dir: Path, manifest_path: Path, manifest_rows: int, eligible_rows: int) -> dict:
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
    parser_complete = int(frame["parser_version"].eq(PARSER_VERSION).sum()) if processed else 0
    part_count, parts_sha256 = parts_lineage(out_dir)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "corpus_ingest_no_prices_no_returns",
        "section": SECTION,
        "hypothesis_identities_spent": 0,
        "preregistration": PREREG,
        "parser_version": PARSER_VERSION,
        "source_manifest": {"path": str(manifest_path), "sha256": file_sha256(manifest_path)},
        "source_cache": str(RAW_DIR),
        "network_reads": 0,
        "manifest_rows": manifest_rows,
        "pair_eligible_manifest_rows": eligible_rows,
        "processed_rows": processed,
        "successful_downloads": successful,
        "download_rate": successful / processed if processed else 0.0,
        "item7_extracted": extracted,
        "item7_extraction_rate": extracted / successful if successful else 0.0,
        "sic_complete": sic_complete,
        "sic_missing_at_source": successful - sic_complete,
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

    records = [(str(raw_dir), row) for row in pending.to_dict("records")]
    buffer: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for number, row in enumerate(pool.map(process_cached_filing, records, chunksize=8), 1):
            buffer.append(row)
            if len(buffer) >= args.batch_size:
                write_part(out_dir, next_part, buffer)
                next_part += 1
                buffer = []
            if number % 500 == 0 or number == len(records):
                print(
                    f"filings {number}/{len(records)} pending | completed before run "
                    f"{len(complete)} | {datetime.now(UTC).strftime('%H:%M:%SZ')}",
                    flush=True,
                )
        if buffer:
            write_part(out_dir, next_part, buffer)

    result = summarize(out_dir, manifest_path, len(manifest), len(eligible))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--max-filings", type=int)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({k: v for k, v in result.items() if k != "source_manifest"}, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
