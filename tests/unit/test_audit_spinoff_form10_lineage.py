from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_spinoff_form10_lineage.py"
SPEC = importlib.util.spec_from_file_location("audit_spinoff_form10_lineage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def master_index(rows: list[str]) -> bytes:
    header = "CIK|Company Name|Form Type|Date Filed|Filename\n" + "-" * 80 + "\n"
    return ("SEC header\n" + header + "\n".join(rows) + "\n").encode("latin-1")


def test_parser_retains_only_form10_12b_lineage() -> None:
    raw = master_index(
        [
            "123|Child Corp|10-12B|2020-01-02|edgar/data/123/0000000123-20-000001.txt",
            "123|Child Corp|10-12B/A|2020-02-03|edgar/data/123/0000000123-20-000002.txt",
            "456|Other Corp|10-K|2020-02-04|edgar/data/456/0000000456-20-000003.txt",
        ]
    )
    frame = MODULE.parse_master_index(raw, year=2020, quarter=1)

    assert frame["form"].tolist() == ["10-12B", "10-12B/A"]
    assert frame["accession"].tolist() == [
        "0000000123-20-000001",
        "0000000123-20-000002",
    ]
    assert frame["is_initial_registration"].tolist() == [True, False]


def test_parser_preserves_missing_accession_for_fail_closed_gate() -> None:
    raw = master_index(["123|Child Corp|10-12B|2020-01-02|edgar/data/123/bad-name.txt"])
    frame = MODULE.parse_master_index(raw, year=2020, quarter=1)
    assert pd.isna(frame.iloc[0]["accession"])


def test_summary_passes_complete_source_lineage() -> None:
    source_rows = [
        {
            "year": year,
            "quarter": quarter,
            "sha256": "a" * 64,
            "parse_error": None,
        }
        for year in range(2016, 2026)
        for quarter in range(1, 5)
    ]
    filing_rows = []
    for year in range(2016, 2026):
        for number in range(5):
            accession = f"{year:010d}-{year % 100:02d}-{number:06d}"
            filing_rows.append(
                {
                    "source_year": year,
                    "source_quarter": 1,
                    "cik": year * 100 + number,
                    "company_name": f"Child {year} {number}",
                    "form": "10-12B",
                    "filing_date": f"{year}-01-{number + 1:02d}",
                    "archive_filename": f"edgar/data/{year}/{accession}.txt",
                    "accession": accession,
                    "is_initial_registration": True,
                }
            )
    result = MODULE.summarize(pd.DataFrame(filing_rows), pd.DataFrame(source_rows))

    assert result["decision"] == "PASS_TO_DOCUMENT_SCHEMA_AUDIT"
    assert result["quarter_indexes"] == 40
    assert result["initial_10_12b_registrations"] == 50
    assert result["market_data_opened"] is False
    assert result["return_hypotheses_spent"] == 0
