from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "audit_treasury_calendar_revisions.py")
)
summarize = MODULE["summarize"]


def test_revision_audit_classifies_changed_late_post_and_missing(monkeypatch) -> None:
    monkeypatch.setitem(
        summarize.__globals__,
        "prior_sessions",
        lambda publication, auction: max((auction - publication).days, 0),
    )
    auction_dates = pd.to_datetime(
        ["2020-01-20", "2020-02-20", "2020-03-20", "2020-04-20"]
    )
    manifest = pd.DataFrame(
        {
            "security_type": ["Note"] * 4,
            "security_term": ["2-Year"] * 4,
            "floating_rate": ["No"] * 4,
            "auction_date": auction_dates,
            "announcement_date": pd.to_datetime(
                ["2020-01-18", "2020-02-18", "2020-03-18", "2020-04-18"]
            ),
        }
    )
    evidence = pd.DataFrame(
        {
            "source": ["archived_pdf", "archived_xml", "archived_pdf"],
            "capture_date": pd.to_datetime(
                ["2020-01-01", "2020-02-15", "2020-03-21"]
            ),
            "tentative_auction_date": pd.to_datetime(
                ["2020-01-21", "2020-02-20", "2020-03-20"]
            ),
        }
    )

    result = summarize(
        manifest, evidence, [value.date() for value in auction_dates]
    )

    assert result["classifications"] == {
        "TENTATIVE_DATE_CHANGED": 1,
        "EXACT_DATE_ONLY_LATE_CAPTURE": 1,
        "EXACT_DATE_ONLY_POST_EVENT_CAPTURE": 1,
        "NO_CAPTURED_MONTH_SCHEDULE": 1,
    }
    assert result["decision"] == "IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED"
    assert result["return_hypotheses_spent"] == 0
