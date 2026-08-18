from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_active_ownership_13d_metadata.py"
SPEC = importlib.util.spec_from_file_location("audit_active_ownership_13d_metadata", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_master_index_uses_exact_initial_form() -> None:
    raw = b"""Description\nCIK|Company Name|Form Type|Date Filed|Filename
123|Reporter A|SC 13D|2020-01-02|edgar/data/123/0000000123-20-000001.txt
123|Reporter A|SC 13D/A|2020-01-03|edgar/data/123/0000000123-20-000002.txt
124|Reporter B|SC 13G|2020-01-04|edgar/data/124/0000000124-20-000003.txt
"""
    rows = MODULE.parse_master_index(raw, 2020, 1)
    assert [row["accession"] for row in rows] == ["0000000123-20-000001"]


def test_parse_header_separates_subject_and_filer() -> None:
    raw = b"""<ACCEPTANCE-DATETIME>20200102123456
<SUBJECT-COMPANY>
<COMPANY-DATA>
<CIK>0000009999
<FILED-BY>
<COMPANY-DATA>
<CIK>0000000123
"""
    parsed = MODULE.parse_header(raw)
    assert parsed == {
        "acceptance_datetime": "20200102123456",
        "subject_cik": 9999,
        "filed_by_cik": 123,
    }


def test_locked_sample_is_deterministic_and_ten_per_year() -> None:
    frame = pd.DataFrame(
        [
            {
                "year": year,
                "index_filer_cik": index + 1,
                "accession": f"{index:010d}-20-000001",
            }
            for year in (2020, 2021)
            for index in range(20)
        ]
    )
    left = MODULE.locked_sample(frame)
    right = MODULE.locked_sample(frame.sample(frac=1, random_state=9))
    assert left["accession"].tolist() == right["accession"].tolist()
    assert left.groupby("year").size().eq(10).all()


def test_ticker_mapping_uses_filing_date_interval() -> None:
    rows = pd.DataFrame(
        [
            {"subject_cik": 10, "filing_date": "2020-06-01"},
            {"subject_cik": 10, "filing_date": "2022-06-01"},
        ]
    )
    tickers = pd.DataFrame(
        [
            {
                "cik": 10,
                "permaticker": 1,
                "ticker": "OLD",
                "firstpricedate": "2010-01-01",
                "lastpricedate": "2020-12-31",
            },
            {
                "cik": 10,
                "permaticker": 2,
                "ticker": "NEW",
                "firstpricedate": "2021-01-01",
                "lastpricedate": "2025-12-31",
            },
        ]
    )
    mapped = MODULE.ticker_matches(rows, tickers)
    assert mapped["ticker"].tolist() == ["OLD", "NEW"]
    assert mapped["ticker_match_count"].tolist() == [1, 1]
