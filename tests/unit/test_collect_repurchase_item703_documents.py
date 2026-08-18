from __future__ import annotations

import gzip
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "collect_repurchase_item703_documents.py"
    )
)
completed_accessions = MODULE["completed_accessions"]
gzip_read = MODULE["gzip_read"]
gzip_write = MODULE["gzip_write"]
summarize = MODULE["summarize"]
write_part = MODULE["write_part"]


def test_gzip_cache_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.gz"
    second = tmp_path / "second.gz"
    gzip_write(first, b"filing")
    gzip_write(second, b"filing")

    assert first.read_bytes() == second.read_bytes()
    assert gzip_read(first) == b"filing"
    assert gzip.decompress(first.read_bytes()) == b"filing"


def test_completed_accessions_requires_current_success(tmp_path: Path) -> None:
    base = {
        "cik": 1,
        "filing_year": 2020,
        "form": "10-K",
        "document_url": "https://example.test/doc.htm",
        "raw_cache_path": "doc.gz",
        "raw_sha256": "a" * 64,
        "raw_bytes": 100,
        "raw_from_cache": False,
    }
    write_part(
        tmp_path,
        0,
        [
            {
                **base,
                "accession": "a",
                "collector_version": MODULE["COLLECTOR_VERSION"],
                "error": None,
            },
            {
                **base,
                "accession": "b",
                "collector_version": "old",
                "error": None,
            },
            {
                **base,
                "accession": "c",
                "collector_version": MODULE["COLLECTOR_VERSION"],
                "error": "failure",
            },
        ],
    )

    assert completed_accessions(tmp_path) == {"a"}
    assert len(pd.read_parquet(tmp_path / "status-00000.parquet")) == 3


def test_summary_requires_exact_manifest_identity_set(tmp_path: Path) -> None:
    base = {
        "cik": 1,
        "filing_year": 2020,
        "form": "10-K",
        "document_url": "https://example.test/doc.htm",
        "collector_version": MODULE["COLLECTOR_VERSION"],
        "raw_cache_path": "doc.gz",
        "raw_sha256": "a" * 64,
        "raw_bytes": 100,
        "raw_from_cache": False,
        "error": None,
    }
    write_part(
        tmp_path,
        0,
        [{**base, "accession": "expected"}, {**base, "accession": "unexpected"}],
    )

    result = summarize(
        tmp_path,
        {"expected", "missing"},
        {"content_hash": "sealed", "document_manifest_sha256": "manifest"},
    )

    assert result["complete"] is False
    assert result["missing_accessions"] == ["missing"]
    assert result["unexpected_accessions"] == ["unexpected"]
