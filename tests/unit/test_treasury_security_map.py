import pytest

from alphaforge.validation.treasury_security_map import classify, issued_candidate


def note(**changes):
    r = {
        "cusip": "A",
        "floating_rate": "No",
        "inflation_index_security": "No",
        "security_type": "Note",
        "security_term": "10-Year",
        "original_security_term": "10-Year",
        "reopening": "No",
        "announcemt_date": "2020-01-02",
        "auction_date": "2020-01-09",
        "issue_date": "2020-01-15",
        "maturity_date": "2030-01-15",
    }
    return dict(r, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"inflation_index_security": "Yes"},
        {"inflation_index_security": "null"},
        {"floating_rate": "Yes"},
        {"reopening": "Yes"},
    ],
)
def test_excludes_tips_unknown_frn_and_reopening(changes):
    assert classify(note(**changes)) is None


def test_unissued_cannot_replace_existing_benchmark():
    old = note(
        cusip="OLD",
        auction_date="2019-10-09",
        announcemt_date="2019-10-02",
        issue_date="2019-10-15",
    )
    assert issued_candidate([old, note()], "2020-01-10", "note_10y")["cusip"] == "OLD"
    assert issued_candidate([old, note()], "2020-01-15", "note_10y")["cusip"] == "A"


def test_bill_uses_current_26_week_term_even_when_reopened():
    r = note(
        security_type="Bill",
        security_term="26-Week",
        original_security_term="52-Week",
        reopening="Yes",
    )
    assert classify(r) == "bill_6m"


def test_ambiguous_mapping_refuses():
    with pytest.raises(ValueError, match="ambiguous"):
        issued_candidate([note(), note(cusip="B")], "2020-01-16", "note_10y")


def test_no_future_or_matured_candidate():
    for day in ("2020-01-02", "2030-01-15"):
        with pytest.raises(ValueError, match="no_issued"):
            issued_candidate([note()], day, "note_10y")


def test_invalid_chronology_refuses():
    with pytest.raises(ValueError, match="chronology"):
        issued_candidate([note(issue_date="2020-01-01")], "2020-01-16", "note_10y")
