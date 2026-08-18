from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_repurchase_issuance_feasibility.py"
    )
)
combined_coverage = MODULE["combined_coverage"]
decision_for_gates = MODULE["decision_for_gates"]


def test_combined_coverage_uses_union_without_double_counting() -> None:
    filings = pd.DataFrame(
        [
            {
                "cik": cik,
                "accession": f"a{cik}",
                "report_date": "2020-12-31",
                "acceptance_datetime": "2021-02-01T12:00:00Z",
            }
            for cik in (1, 2, 3)
        ]
    )
    sample = filings[["cik", "accession"]].copy()
    facts = pd.DataFrame(
        [
            {"cik": 1, "accession": "a1", "tag_family": "repurchase_cash"},
            {"cik": 1, "accession": "a1", "tag_family": "issuance_cash"},
            {"cik": 2, "accession": "a2", "tag_family": "repurchase_shares"},
        ]
    )
    predictions = pd.DataFrame(
        [
            {
                "cik": cik,
                "accession": f"a{cik}",
                "parser_version": MODULE["ITEM703_PARSER_VERSION"],
                "has_item703_table": cik in {2, 3},
                "tender_offer_mention": cik == 3,
                "error": None,
            }
            for cik in (1, 2, 3)
        ]
    )

    result = combined_coverage(facts, filings, sample, predictions)

    assert result["sample_issuer_years"] == 3
    assert result["direct_repurchase_issuer_years"] == 2
    assert result["item703_issuer_years"] == 2
    assert result["combined_repurchase_issuer_years"] == 3
    assert result["combined_repurchase_coverage"] == 1.0
    assert result["direct_issuance_issuer_years"] == 1
    assert result["tender_offer_mentions"] == 1


def test_missing_metadata_reduces_denominator_and_is_reported() -> None:
    filings = pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a1",
                "report_date": None,
                "acceptance_datetime": None,
            }
        ]
    )
    sample = filings[["cik", "accession"]].copy()
    facts = pd.DataFrame(columns=["cik", "accession", "tag_family"])
    predictions = pd.DataFrame(
        columns=[
            "cik",
            "accession",
            "parser_version",
            "has_item703_table",
            "tender_offer_mention",
            "error",
        ]
    )

    result = combined_coverage(facts, filings, sample, predictions)

    assert result["sample_issuer_years"] == 0
    assert result["missing_sample_metadata"] == 1
    assert result["combined_repurchase_coverage"] == 0.0


def test_gate_decision_is_fail_closed_and_governance_has_priority() -> None:
    passing = {"return_data_unopened": True, "return_hypotheses_unspent": True}

    assert decision_for_gates(passing) == "PASS_TO_RETURN_PREREGISTRATION"
    assert decision_for_gates(
        {
            "coverage": False,
            "return_data_unopened": True,
            "return_hypotheses_unspent": True,
        }
    ) == "DATA_GATED"
    assert decision_for_gates(
        {"return_data_unopened": False, "return_hypotheses_unspent": True}
    ) == "REJECT_GOVERNANCE"
