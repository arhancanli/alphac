from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_treasury_wayback_schedule_lineage.py"
    )
)
parse_cdx = MODULE["parse_cdx"]
parse_schedule = MODULE["parse_schedule"]
summarize = MODULE["summarize"]


def test_cdx_schema_and_schedule_parser_exclude_frn() -> None:
    captures = parse_cdx(
        b'[["timestamp","original","digest"],["20200101000000","u","d"]]'
    )
    raw = b"""<AuctionCalendar><StartDate>2020-01-01</StartDate>
    <EndDate>2020-06-30</EndDate>
    <AuctionCalendarDate><SecurityTermWeekYear>2-Year</SecurityTermWeekYear>
    <SecurityType>NOTE</SecurityType><FloatingRate>N</FloatingRate>
    <AuctionDate>2020-02-25</AuctionDate></AuctionCalendarDate>
    <AuctionCalendarDate><SecurityTermWeekYear>2-Year</SecurityTermWeekYear>
    <SecurityType>NOTE</SecurityType><FloatingRate>Y</FloatingRate>
    <AuctionDate>2020-02-26</AuctionDate></AuctionCalendarDate></AuctionCalendar>"""

    start, end, events = parse_schedule(raw)

    assert captures[0]["timestamp"] == "20200101000000"
    assert (start, end) == (date(2020, 1, 1), date(2020, 6, 30))
    assert events == [date(2020, 2, 25)]


def test_late_capture_cannot_prove_ten_session_entry(monkeypatch) -> None:
    monkeypatch.setitem(summarize.__globals__, "START", date(2020, 1, 1))
    monkeypatch.setitem(summarize.__globals__, "END", date(2020, 4, 30))
    monkeypatch.setitem(
        summarize.__globals__,
        "prior_sessions",
        lambda capture_date, auction_date: 5,
    )
    manifest = pd.DataFrame(
        {
            "security_type": ["Note"],
            "security_term": ["2-Year"],
            "floating_rate": ["No"],
            "auction_date": pd.to_datetime(["2020-02-25"]),
        }
    )
    captures = [
        {
            "timestamp": "20200218000000",
            "schedule_start_date": date(2020, 1, 1),
            "schedule_end_date": date(2020, 6, 30),
            "events": [date(2020, 2, 25)],
            "archive_url": "https://example.test/archive",
            "archive_sha256": "a" * 64,
            "cdx_digest": "digest",
        }
    ]

    result, joined = summarize(manifest, captures, "manifest", "cdx")

    assert len(joined) == 1
    assert result["ten_session_schedule_bound_auctions"] == 0
    assert result["missing_auction_dates"] == ["2020-02-25"]
    assert result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert result["return_hypotheses_spent"] == 0
