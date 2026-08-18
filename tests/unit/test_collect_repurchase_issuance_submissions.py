from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "collect_repurchase_issuance_submissions.py"
    )
)
periodic_filings = MODULE["periodic_filings"]
completed_ciks = MODULE["completed_ciks"]
summarize = MODULE["summarize"]
write_parts = MODULE["write_parts"]


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "accessionNumber": [
                "0000000001-20-000001",
                "0000000001-20-000002",
                "0000000001-20-000003",
                "bad",
            ],
            "filingDate": ["2020-02-01", "2020-03-01", "2020-04-01", "2020-05-01"],
            "reportDate": ["2019-12-31"] * 4,
            "acceptanceDateTime": [
                "20200201120000",
                "20200301120000",
                "20200401120000",
                "20200501120000",
            ],
            "form": ["10-K", "10-K/A", "8-K", "10-Q"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
        }
    )


def test_periodic_filings_preserves_amendments_and_rejects_bad_rows() -> None:
    rows = periodic_filings(1, [frame()])

    assert [row["form"] for row in rows] == ["10-K", "10-K/A"]
    assert [row["accession"] for row in rows] == [
        "0000000001-20-000001",
        "0000000001-20-000002",
    ]


def test_empty_filing_batch_still_writes_auditable_parts(tmp_path: Path) -> None:
    status = {
        "cik": 1,
        "parser_version": MODULE["PARSER_VERSION"],
        "source_pages": 1,
        "source_pages_sha256": "a" * 64,
        "periodic_filings": 0,
        "error": None,
    }

    write_parts(tmp_path, 0, [status], [])

    assert (tmp_path / "issuer-status-00000.parquet").is_file()
    assert (tmp_path / "filings-00000.parquet").is_file()
    assert completed_ciks(tmp_path) == {1}


def test_summary_requires_exact_manifest_cik_set(tmp_path: Path) -> None:
    statuses = [
        {
            "cik": cik,
            "parser_version": MODULE["PARSER_VERSION"],
            "source_pages": 1,
            "source_pages_sha256": "a" * 64,
            "periodic_filings": 0,
            "error": None,
        }
        for cik in (1, 3)
    ]
    write_parts(tmp_path, 0, statuses, [])

    result = summarize(
        tmp_path,
        {1, 2},
        {"content_hash": "sealed", "sample_sha256": "manifest"},
    )

    assert result["complete"] is False
    assert result["missing_ciks"] == [2]
    assert result["unexpected_ciks"] == [3]
