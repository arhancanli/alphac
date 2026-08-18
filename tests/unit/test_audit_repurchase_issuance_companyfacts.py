from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_repurchase_issuance_companyfacts.py"
    )
)
coverage_metrics = MODULE["coverage_metrics"]
wilson_lower = MODULE["wilson_lower"]


def test_coverage_uses_filing_denominators_and_unique_issuer_years() -> None:
    filings = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "form": "10-K",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-02-01T12:00:00Z",
            },
            {
                "cik": 1,
                "accession": "b",
                "form": "10-K/A",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-03-01T12:00:00Z",
            },
            {
                "cik": 2,
                "accession": "c",
                "form": "10-K",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-02-01T12:00:00Z",
            },
        ]
    )
    facts = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "tag_family": "repurchase_cash",
                "tag": "PaymentsForRepurchaseOfCommonStock",
                "unit": "USD",
                "start": "2020-01-01",
                "end": "2020-12-31",
                "form": "10-K",
            },
            {
                "cik": 1,
                "accession": "b",
                "tag_family": "issuance_cash",
                "tag": "ProceedsFromIssuanceOfCommonStock",
                "unit": "USD",
                "start": "2020-01-01",
                "end": "2020-12-31",
                "form": "10-K/A",
            },
        ]
    )

    result = coverage_metrics(facts, filings)

    assert result["periodic_filings"] == 3
    assert result["issuer_years"] == 2
    assert result["direct_repurchase_issuer_years"] == 1
    assert result["direct_repurchase_coverage"] == 0.5
    assert result["direct_issuance_coverage"] == 0.5
    assert result["accession_join_rate"] == 1.0
    assert result["context_complete_rate"] == 1.0


def test_unjoined_and_missing_duration_context_fail_rates() -> None:
    filings = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "form": "10-K",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-02-01T12:00:00Z",
            }
        ]
    )
    facts = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "missing",
                "tag_family": "repurchase_cash",
                "tag": "PaymentsForRepurchaseOfCommonStock",
                "unit": "USD",
                "start": None,
                "end": "2020-12-31",
                "form": "10-K",
            }
        ]
    )

    result = coverage_metrics(facts, filings)

    assert result["accession_join_rate"] == 0.0
    assert result["context_complete_rate"] == 0.0
    assert result["unjoined_accessions"] == ["missing"]


def test_wilson_lower_is_fail_closed_for_empty_sample() -> None:
    assert wilson_lower(0, 0) == 0.0
    assert 0.0 < wilson_lower(70, 100) < 0.70


def test_contamination_facts_are_counted_but_never_direct_issuance() -> None:
    filings = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "form": "10-K",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-02-01T12:00:00Z",
            }
        ]
    )
    facts = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "tag_family": "contamination_stock_compensation",
                "tag": "ProceedsFromStockOptionsExercised",
                "unit": "USD",
                "start": "2020-01-01",
                "end": "2020-12-31",
                "form": "10-K",
            }
        ]
    )

    result = coverage_metrics(facts, filings)

    assert result["direct_issuance_issuer_years"] == 0
    assert result["tag_family_rows"] == {"contamination_stock_compensation": 1}
    assert result["tag_family_issuer_years"] == {
        "contamination_stock_compensation": 1
    }
