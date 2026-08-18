from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_treasury_wayback_pdf_schedule_lineage.py"
    )
)
parse_schedule_text = MODULE["parse_schedule_text"]
summarize = MODULE["summarize"]


def manifest_for(auction_date: str = "2020-02-25") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_type": ["Note"],
            "security_term": ["2-Year"],
            "floating_rate": ["No"],
            "auction_date": pd.to_datetime([auction_date]),
        }
    )


def capture_for(auction_date: date) -> dict[str, object]:
    return {
        "timestamp": "20200101000000",
        "events": [auction_date],
        "archive_url": "https://example.test/archive.pdf",
        "archive_sha256": "a" * 64,
        "extracted_text_sha256": "b" * 64,
        "pdf_pages": 1,
        "cdx_digest": "digest",
    }


def test_text_parser_uses_second_date_and_excludes_frn() -> None:
    text = """
    2-Year  NOTE  Thursday, February 20, 2020  Tuesday, February 25, 2020  Monday, March 2, 2020
    2-Year FRN    Thursday, February 20, 2020  Wednesday, February 26, 2020  \
Friday, February 28, 2020
    """

    assert parse_schedule_text(text) == [date(2020, 2, 25)]


def test_late_capture_cannot_prove_ten_session_entry(monkeypatch) -> None:
    monkeypatch.setitem(summarize.__globals__, "START", date(2020, 1, 1))
    monkeypatch.setitem(summarize.__globals__, "END", date(2020, 4, 30))
    monkeypatch.setitem(summarize.__globals__, "prior_sessions", lambda *_: 5)

    result, joined = summarize(
        manifest_for(), [capture_for(date(2020, 2, 25))], "manifest", "cdx"
    )

    assert len(joined) == 1
    assert result["ten_session_schedule_bound_auctions"] == 0
    assert result["missing_auction_dates"] == ["2020-02-25"]
    assert result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert result["return_hypotheses_spent"] == 0


def test_unmatched_tentative_date_is_disclosed_and_excluded() -> None:
    result, joined = summarize(
        manifest_for(), [capture_for(date(2020, 2, 26))], "manifest", "cdx"
    )

    assert result["excluded_unmatched_tentative_dates"] == ["2020-02-26"]
    assert result["ten_session_schedule_bound_auctions"] == 0
    assert joined["archive_sha256"].isna().all()
