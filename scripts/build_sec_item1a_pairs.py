#!/usr/bin/env python3
"""Build immediate-predecessor Item 1A similarities without reading market data.

Corpus parts can contain retried identities in later files. DuckDB keeps the latest attempt by
part number and streams rows in CIK/acceptance order, avoiding a multi-gigabyte in-memory text
frame. A missing immediate predecessor is never replaced by an older convenient filing.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import PARSER_VERSION, jaccard

PARTS_GLOB: Final = "artifacts/ingest/earnings_narrative_change/item1a_parts/part-*.parquet"
OUT: Final = Path("artifacts/ingest/earnings_narrative_change/item1a_pairs.parquet")
RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/pairs_result.json")
CORPUS_RESULT: Final = Path("artifacts/ingest/earnings_narrative_change/corpus_result.json")
MANIFEST: Final = Path("artifacts/ingest/earnings_narrative_change/filings_manifest.parquet")
PREREG: Final = Path("docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md")
MIN_SECTION_WORDS: Final = 500


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parts_lineage(parts_glob: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    paths = [Path(path) for path in sorted(glob.glob(parts_glob))]
    for path in paths:
        identity = f"{path.name}\0{path.stat().st_size}\0{file_sha256(path)}\n"
        digest.update(identity.encode())
    return len(paths), digest.hexdigest()


def require_complete_corpus(path: Path, parts_glob: str) -> dict:
    if not path.exists():
        raise RuntimeError(f"completed corpus result is missing: {path}")
    result = json.loads(path.read_text())
    if (
        result.get("stage") != "corpus_ingest_no_prices_no_returns"
        or result.get("complete") is not True
        or int(result.get("hypothesis_identities_spent", -1)) != 0
        or result.get("parser_version") != PARSER_VERSION
    ):
        raise RuntimeError(f"corpus is not return-sealed and complete: {path}: {result}")
    part_count, digest = parts_lineage(parts_glob)
    if result.get("part_count") != part_count or result.get("parts_sha256") != digest:
        raise RuntimeError("corpus part lineage does not match the completed corpus result")
    return result


def require_bound_manifest(path: Path, corpus: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"source filing manifest is missing: {path}")
    manifest = pd.read_parquet(
        path,
        columns=["filing_identity", "cik", "accession", "form", "acceptance_datetime"],
    )
    counts = manifest.groupby("cik")["accession"].transform("size")
    eligible_rows = int(counts.ge(2).sum())
    acceptance = pd.to_datetime(manifest["acceptance_datetime"], utc=True, errors="coerce")
    sealed_manifest = corpus.get("source_manifest")
    failures = {
        "missing_corpus_manifest_binding": not isinstance(sealed_manifest, Mapping),
        "corpus_manifest_path_mismatch": not isinstance(sealed_manifest, Mapping)
        or sealed_manifest.get("path") != str(path),
        "corpus_manifest_sha256_mismatch": not isinstance(sealed_manifest, Mapping)
        or sealed_manifest.get("sha256") != file_sha256(path),
        "row_count_mismatch": len(manifest) != int(corpus.get("manifest_rows", -1)),
        "eligible_count_mismatch": eligible_rows
        != int(corpus.get("pair_eligible_manifest_rows", -1)),
        "duplicate_filing_identity": bool(manifest["filing_identity"].duplicated().any()),
        "duplicate_cik_accession": bool(manifest.duplicated(["cik", "accession"]).any()),
        "non_10k_form": bool(manifest["form"].ne("10-K").any()),
        "invalid_acceptance_timestamp": bool(acceptance.isna().any()),
    }
    failed = sorted(name for name, value in failures.items() if value)
    if failed:
        raise RuntimeError(f"source filing manifest failed sealed invariants: {failed}")
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "rows": len(manifest),
        "pair_eligible_rows": eligible_rows,
        "forms": ["10-K"],
        "duplicate_filing_identities": 0,
        "invalid_acceptance_timestamps": 0,
    }


def require_exact_identity_coverage(path: Path, parts_glob: str) -> dict[str, int]:
    """Require the latest corpus identities to equal the pair-eligible manifest set."""
    manifest = pd.read_parquet(path, columns=["filing_identity", "cik", "accession"])
    counts = manifest.groupby("cik")["accession"].transform("size")
    eligible = set(manifest.loc[counts.ge(2), "filing_identity"].astype(str))
    connection = duckdb.connect()
    try:
        corpus_rows = connection.execute(
            """
            WITH attempts AS (
                SELECT filing_identity,
                       CAST(regexp_extract(filename, 'part-([0-9]+)', 1) AS INTEGER) part_no
                FROM read_parquet(?, filename = true)
            ), latest AS (
                SELECT filing_identity, row_number() OVER (
                    PARTITION BY filing_identity ORDER BY part_no DESC
                ) AS attempt_rank
                FROM attempts
            )
            SELECT filing_identity FROM latest WHERE attempt_rank = 1
            """,
            [parts_glob],
        ).fetchall()
    finally:
        connection.close()
    corpus_identities = {str(row[0]) for row in corpus_rows}
    missing = eligible - corpus_identities
    unexpected = corpus_identities - eligible
    if missing or unexpected:
        raise RuntimeError(
            "corpus identities do not exactly match pair-eligible manifest identities: "
            f"missing={len(missing)}, unexpected={len(unexpected)}, "
            f"missing_examples={sorted(missing)[:3]}, "
            f"unexpected_examples={sorted(unexpected)[:3]}"
        )
    return {
        "eligible_manifest_identities": len(eligible),
        "latest_corpus_identities": len(corpus_identities),
        "missing": 0,
        "unexpected": 0,
    }


def valid_section(row: Mapping[str, Any]) -> bool:
    text = row.get("section_text")
    expected_hash = row.get("section_sha256")
    words = int(row.get("section_words") or 0)
    return bool(
        row.get("error") is None
        and row.get("extracted")
        and isinstance(text, str)
        and words >= MIN_SECTION_WORDS
        and len(text.split()) == words
        and isinstance(expected_hash, str)
        and hashlib.sha256(text.encode()).hexdigest() == expected_hash
        and row.get("parser_version") == PARSER_VERSION
    )


def valid_sic(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 4 and value.isdigit()


def pair_rejection_reason(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> str | None:
    if int(previous["cik"]) != int(current["cik"]):
        return "first_filing_for_issuer"
    if not valid_section(previous):
        return "invalid_immediate_predecessor"
    if not valid_section(current):
        return "invalid_current_section"
    if not valid_sic(current.get("sic")):
        return "missing_current_filing_sic"
    previous_acceptance = pd.to_datetime(previous["acceptance_datetime"], utc=True, errors="coerce")
    current_acceptance = pd.to_datetime(current["acceptance_datetime"], utc=True, errors="coerce")
    if pd.isna(previous_acceptance) or pd.isna(current_acceptance):
        return "invalid_acceptance_timestamp"
    if current_acceptance <= previous_acceptance:
        return "non_increasing_acceptance_timestamp"
    return None


def make_pair(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict | None:
    if pair_rejection_reason(previous, current) is not None:
        return None
    return {
        "cik": int(current["cik"]),
        "previous_filing_identity": str(previous["filing_identity"]),
        "current_filing_identity": str(current["filing_identity"]),
        "previous_accession": str(previous["accession"]),
        "current_accession": str(current["accession"]),
        "previous_acceptance": str(previous["acceptance_datetime"]),
        "current_acceptance": str(current["acceptance_datetime"]),
        "previous_section_sha256": str(previous["section_sha256"]),
        "current_section_sha256": str(current["section_sha256"]),
        "previous_section_words": int(previous["section_words"]),
        "current_section_words": int(current["section_words"]),
        "sic": str(current["sic"]),
        "fivegram_jaccard": jaccard(str(previous["section_text"]), str(current["section_text"])),
        "exact_duplicate": previous["section_sha256"] == current["section_sha256"],
        "parser_version": str(current["parser_version"]),
    }


def immediate_pairs(
    rows: Iterable[Mapping[str, Any]], rejection_counts: Counter[str] | None = None
) -> Iterator[dict]:
    previous: Mapping[str, Any] | None = None
    for current in rows:
        if previous is None:
            if rejection_counts is not None:
                rejection_counts["first_filing_for_issuer"] += 1
        else:
            pair = make_pair(previous, current)
            if pair is not None:
                yield pair
            elif rejection_counts is not None:
                reason = pair_rejection_reason(previous, current)
                if reason is None:  # pragma: no cover - deterministic predicate invariant
                    raise RuntimeError("pair eligibility changed within one deterministic pass")
                rejection_counts[reason] += 1
        previous = current


def latest_rows(parts_glob: str, batch_size: int) -> Iterator[dict]:
    """Stream latest attempts in issuer chronology; filename part order defines recency."""
    connection = duckdb.connect()
    try:
        query = """
            WITH attempts AS (
                SELECT *,
                       CAST(regexp_extract(filename, 'part-([0-9]+)', 1) AS INTEGER) part_no
                FROM read_parquet(?, filename = true)
            ), latest AS (
                SELECT *, row_number() OVER (
                    PARTITION BY filing_identity ORDER BY part_no DESC
                ) AS attempt_rank
                FROM attempts
            )
            SELECT filing_identity, cik, accession, acceptance_datetime, sic, parser_version,
                   error, extracted, section_words, section_sha256, section_text
            FROM latest
            WHERE attempt_rank = 1
            ORDER BY cik, acceptance_datetime, accession
        """
        reader = connection.execute(query, [parts_glob]).to_arrow_reader(batch_size)
        for batch in reader:
            columns = batch.to_pydict()
            for index in range(batch.num_rows):
                yield {name: values[index] for name, values in columns.items()}
    finally:
        connection.close()


def run(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    result_path = Path(args.result)
    corpus_result_path = Path(args.corpus_result)
    corpus = require_complete_corpus(corpus_result_path, args.parts_glob)
    manifest_lineage = require_bound_manifest(Path(args.manifest), corpus)
    identity_coverage = require_exact_identity_coverage(Path(args.manifest), args.parts_glob)
    rejection_counts: Counter[str] = Counter()
    pairs = pd.DataFrame(
        immediate_pairs(
            latest_rows(args.parts_glob, args.batch_size),
            rejection_counts,
        )
    )
    if pairs.empty:
        raise RuntimeError("no immediate-predecessor Item 1A pairs were produced")
    adjacency_accounted_rows = len(pairs) + sum(rejection_counts.values())
    if adjacency_accounted_rows != int(corpus["processed_rows"]):
        raise RuntimeError(
            "pair adjacency ledger does not account for every sealed corpus row: "
            f"{adjacency_accounted_rows} != {corpus['processed_rows']}"
        )
    pairs = pairs.sort_values(["current_acceptance", "cik", "current_accession"])
    out.parent.mkdir(parents=True, exist_ok=True)
    pairs.to_parquet(out, index=False, compression="zstd")
    pair_file_sha256 = file_sha256(out)
    acceptance = pd.to_datetime(pairs["current_acceptance"], utc=True, errors="coerce")
    result = {
        "schema": "canli.ingest.sec-10k-item1a-pairs.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "narrative_pairs_no_prices_no_returns",
        "hypothesis_identities_spent": 0,
        "preregistration": str(PREREG),
        "preregistration_sha256": file_sha256(PREREG),
        "parser_version": PARSER_VERSION,
        "source_corpus_result": str(corpus_result_path),
        "source_manifest": manifest_lineage,
        "source_identity_coverage": identity_coverage,
        "source_corpus_parts": int(corpus["part_count"]),
        "source_corpus_parts_sha256": str(corpus["parts_sha256"]),
        "source_processed_rows": int(corpus["processed_rows"]),
        "pair_file_sha256": pair_file_sha256,
        "minimum_section_words": MIN_SECTION_WORDS,
        "pairs": len(pairs),
        "adjacency_attrition": dict(sorted(rejection_counts.items())),
        "adjacency_accounted_rows": adjacency_accounted_rows,
        "unique_ciks": int(pairs["cik"].nunique()),
        "acceptance_start": acceptance.min().isoformat(),
        "acceptance_end": acceptance.max().isoformat(),
        "exact_duplicate_rate": float(pairs["exact_duplicate"].mean()),
        "jaccard": {
            "p05": float(pairs["fivegram_jaccard"].quantile(0.05)),
            "median": float(pairs["fivegram_jaccard"].median()),
            "p95": float(pairs["fivegram_jaccard"].quantile(0.95)),
        },
        "complete": True,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts-glob", default=PARTS_GLOB)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--corpus-result", default=str(CORPUS_RESULT))
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
