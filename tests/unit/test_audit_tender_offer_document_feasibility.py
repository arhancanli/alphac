from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_tender_offer_document_feasibility.py"
SPEC = importlib.util.spec_from_file_location("audit_tender_offer_document_feasibility", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_extract_item4_rejects_toc_and_uses_real_section() -> None:
    text = (
        """Item 4. The Solicitation or Recommendation
Item 5. Persons Retained
Item 4. The Solicitation or Recommendation
The Board reviewed the offer. The Board unanimously recommends that stockholders accept the
offer and tender their shares. The offer price is $42.50 in cash per share. """
        + "reason " * 80
        + """
Item 5. Persons/Assets Retained, Employed, Compensated or Used
Other information.
"""
    )
    section = MODULE.extract_item4(text)
    assert section is not None
    assert "42.50" in section
    assert len(section.split()) >= 50


def test_price_candidates_require_cash_context_and_preserve_ambiguity() -> None:
    section = (
        "The offer price is $42.50 in cash per share. Historical prices were $30 per share. "
        "The amended purchase price is $44.00 in cash per share."
    )
    assert MODULE.price_candidates(section) == [42.5, 44.0]


def test_price_candidates_reject_implausible_values() -> None:
    assert MODULE.price_candidates("The offer price is $0.25 in cash per share.") == []
    assert MODULE.price_candidates("The offer price is $1500 in cash per share.") == []


def test_recommendation_conflict_is_unresolved() -> None:
    assert (
        MODULE.recommendation(
            "The Board unanimously recommends that holders accept and tender."
        )
        == "recommend_accept"
    )
    assert (
        MODULE.recommendation("The Board recommends against accepting the offer.")
        == "recommend_reject"
    )
    assert (
        MODULE.recommendation("The Board remains unable to make a recommendation.")
        == "neutral_or_unable"
    )
    assert (
        MODULE.recommendation(
            "The Board recommends holders accept. The Board remains neutral."
        )
        == "unresolved"
    )


def test_frozen_audit_set_is_three_per_year() -> None:
    frame = pd.DataFrame(
        {
            "year": [year for year in range(2016, 2026) for _ in range(10)],
            "sample_rank": [f"{rank:02d}" for _ in range(10) for rank in range(10)],
        }
    ).sort_values(["year", "sample_rank"])
    selected = MODULE.frozen_audit_set(frame)
    assert len(selected) == 30
    assert selected.groupby("year").size().eq(3).all()
