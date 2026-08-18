from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_repurchase_issuance_semantics.py"
    )
)
amendment_replay_audit = MODULE["amendment_replay_audit"]
contamination_inventory = MODULE["contamination_inventory"]
quarterization_audit = MODULE["quarterization_audit"]


def filings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "q1",
                "acceptance_datetime": "2020-05-01T12:00:00Z",
                "form": "10-Q",
            },
            {
                "cik": 1,
                "accession": "q2",
                "acceptance_datetime": "2020-08-01T12:00:00Z",
                "form": "10-Q",
            },
            {
                "cik": 1,
                "accession": "q2a",
                "acceptance_datetime": "2020-08-10T12:00:00Z",
                "form": "10-Q/A",
            },
        ]
    )


def fact(accession: str, period: str, end: str, value: int) -> dict:
    return {
        "cik": 1,
        "accession": accession,
        "tag_family": "repurchase_cash",
        "tag": "PaymentsForRepurchaseOfCommonStock",
        "unit": "USD",
        "value": value,
        "start": "2020-01-01",
        "end": end,
        "fiscal_year": 2020,
        "fiscal_period": period,
    }


def test_amendment_replay_has_a_real_case_and_is_slice_invariant() -> None:
    facts = pd.DataFrame(
        [
            fact("q1", "Q1", "2020-03-31", 10),
            fact("q2", "Q2", "2020-06-30", 30),
            fact("q2a", "Q2", "2020-06-30", 31),
        ]
    )

    result = amendment_replay_audit(facts, filings())

    assert result["amendment_fact_rows_tested"] == 1
    assert result["slice_invariant"] is True
    assert result["slice_invariant_failures"] == []


def test_quarterization_uses_only_known_identical_context_predecessor() -> None:
    facts = pd.DataFrame(
        [fact("q1", "Q1", "2020-03-31", 10), fact("q2", "Q2", "2020-06-30", 30)]
    )

    result = quarterization_audit(facts, filings())

    assert result["eligible_cumulative_facts"] == 1
    assert result["derived_quarters"] == 1
    assert result["failed_closed_facts"] == 0
    assert result["zero_imputations"] == 0


def test_missing_predecessor_fails_closed_without_zero_imputation() -> None:
    facts = pd.DataFrame([fact("q2", "Q2", "2020-06-30", 30)])

    result = quarterization_audit(facts, filings())

    assert result["derived_quarters"] == 0
    assert result["failure_reasons"]["missing_predecessor"] == 1
    assert result["zero_imputations"] == 0
    assert result["accounted_for"] is True


def test_ambiguous_predecessor_fails_closed() -> None:
    facts = pd.DataFrame(
        [
            fact("q1", "Q1", "2020-03-31", 10),
            fact("q1", "Q1", "2020-03-31", 11),
            fact("q2", "Q2", "2020-06-30", 30),
        ]
    )

    result = quarterization_audit(facts, filings())

    assert result["derived_quarters"] == 0
    assert result["failure_reasons"]["ambiguous_predecessor"] == 1


def test_all_contamination_categories_are_explicit_even_when_zero() -> None:
    facts = pd.DataFrame(
        [{"tag_family": "contamination_stock_compensation"}] * 2
    )

    result = contamination_inventory(facts, custom_rows=3)

    assert result["all_categories_reported"] is True
    assert result["fact_rows"]["contamination_stock_compensation"] == 2
    assert result["fact_rows"]["custom_extension"] == 3
    assert result["fact_rows"]["tender_offer"] == 0
