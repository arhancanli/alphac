from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_spinoff_document_schema.py"
SPEC = importlib.util.spec_from_file_location("audit_spinoff_document_schema", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_frozen_sample_is_hash_ranked_and_year_bounded() -> None:
    rows = []
    for year, count in ((2024, 12), (2025, 8)):
        for number in range(count):
            rows.append(
                {
                    "cik": year * 100 + number,
                    "accession": f"{year:010d}-{year % 100:02d}-{number:06d}",
                    "form": "10-12B",
                    "filing_date": f"{year}-01-01",
                }
            )
    sample = MODULE.frozen_sample(pd.DataFrame(rows))
    assert len(sample) == 18
    assert sample.groupby("year").size().to_dict() == {2024: 10, 2025: 8}


def test_parse_index_page_requires_exact_form_document() -> None:
    raw = b"""
    <div class="infoHead">Accepted</div><div class="info">2024-01-02 16:31:22</div>
    <table><tr><td>1</td><td><a href="child.htm">child.htm</a></td>
    <td>Registration statement</td><td>10-12B</td><td>100</td></tr></table>
    """
    accepted, href = MODULE.parse_index_page(raw)
    assert accepted == "2024-01-02 16:31:22"
    assert href == "child.htm"


def test_fixed_evidence_patterns_do_not_require_prices() -> None:
    text = (
        "The separation and distribution agreement provides for a pro rata distribution to "
        "stockholders of Parent. One share of Child common stock will be issued for every "
        "three shares held on the record date. The distribution date will follow."
    )
    assert MODULE.SEPARATION_DISTRIBUTION_PATTERN.search(text)
    assert MODULE.PRO_RATA_PATTERN.search(text)
    assert MODULE.RATIO_PATTERN.search(text)
    assert MODULE.RECORD_DATE_PATTERN.search(text)
    assert MODULE.DISTRIBUTION_DATE_PATTERN.search(text)
