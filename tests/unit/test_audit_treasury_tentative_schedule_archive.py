from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_treasury_tentative_schedule_archive.py"
    )
)
parse_archive_links = MODULE["parse_archive_links"]
parse_release_date = MODULE["parse_release_date"]
parse_schedule = MODULE["parse_schedule"]
summarize = MODULE["summarize"]
augment_with_wayback = MODULE["augment_with_wayback"]


def test_archive_links_bind_year_and_quarter() -> None:
    raw = b"""
    <h1>Official Remarks on Quarterly Refunding by Calendar Year</h1>
    <div>2025</div><a href="/q4">4th Quarter</a><a href="/q3">3rd Quarter</a>
    <div>2024</div><a href="/old">1st Quarter</a>
    """

    assert parse_archive_links(raw, "https://example.test/archive") == {
        (2025, 4): "https://example.test/q4",
        (2025, 3): "https://example.test/q3",
        (2024, 1): "https://example.test/old",
    }


def test_release_date_selects_article_quarter_not_sidebar_times() -> None:
    raw = b"""
    <time datetime="2026-08-01T12:00:00Z">sidebar</time>
    <time datetime="2023-02-01T13:30:00Z">article</time>
    """

    assert parse_release_date(raw, 2023, 1) == date(2023, 2, 1)


def test_schedule_parser_excludes_frn_and_other_tenors() -> None:
    raw = b"""<?xml version="1.0"?>
    <AuctionCalendar>
      <AuctionCalendarName>May 2020 Refunding Official Calendar</AuctionCalendarName>
      <StartDate>2020-05-06</StartDate><EndDate>2020-10-31</EndDate>
      <AuctionCalendarDate><SecurityTermWeekYear>2-Year</SecurityTermWeekYear>
        <SecurityType>NOTE</SecurityType><TIPS>N</TIPS><FloatingRate>N</FloatingRate>
        <AnnouncementDate>2020-05-21</AnnouncementDate><AuctionDate>2020-05-26</AuctionDate>
        <SettlementDate>2020-06-01</SettlementDate></AuctionCalendarDate>
      <AuctionCalendarDate><SecurityTermWeekYear>2-Year</SecurityTermWeekYear>
        <SecurityType>NOTE</SecurityType><TIPS>N</TIPS><FloatingRate>Y</FloatingRate>
        <AnnouncementDate>2020-05-21</AnnouncementDate><AuctionDate>2020-05-27</AuctionDate>
        <SettlementDate>2020-05-29</SettlementDate></AuctionCalendarDate>
    </AuctionCalendar>"""

    metadata, events = parse_schedule(raw)

    assert metadata["start_date"] == date(2020, 5, 6)
    assert [event["auction_date"] for event in events] == [date(2020, 5, 26)]


def test_missing_historical_quarters_fail_closed(monkeypatch) -> None:
    monkeypatch.setitem(summarize.__globals__, "START_YEAR", 2020)
    monkeypatch.setitem(summarize.__globals__, "END_YEAR", 2020)
    monkeypatch.setitem(
        summarize.__globals__,
        "prior_sessions",
        lambda release_date, auction_date: 12,
    )
    manifest = pd.DataFrame(
        {
            "security_type": ["Note", "Note", "Note"],
            "security_term": ["2-Year", "2-Year", "2-Year"],
            "floating_rate": ["No", "No", "Yes"],
            "auction_date": pd.to_datetime(
                ["2020-02-25", "2020-05-26", "2020-05-26"]
            ),
        }
    )
    documents = [
        {
            "year": 2020,
            "quarter": 2,
            "status": "available",
            "release_date": date(2020, 5, 6),
            "release_page_url": "https://example.test/release",
            "release_page_sha256": "a" * 64,
            "schedule_url": "https://example.test/schedule.xml",
            "schedule_sha256": "b" * 64,
            "schedule_start_date": date(2020, 5, 6),
            "events": [
                {
                    "security_term": "2-Year",
                    "security_type": "NOTE",
                    "auction_date": date(2020, 5, 26),
                    "announcement_date": date(2020, 5, 21),
                    "settlement_date": date(2020, 6, 1),
                }
            ],
        }
    ]

    result, joined = summarize(manifest, documents, "manifest", "archive")

    assert len(joined) == 2
    assert result["schedule_bound_auctions"] == 1
    assert result["schedule_coverage_rate"] == 0.5
    assert result["gates"]["manifest_two_year_auction_dates_unique"] is True
    assert result["gates"]["every_matched_event_supports_ten_prior_sessions"] is True
    assert result["gates"]["every_2013_2025_two_year_auction_schedule_bound"] is False
    assert result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert result["return_hypotheses_spent"] == 0


def test_wayback_proof_combines_without_overwriting_official_metrics() -> None:
    result = {
        "schedule_bound_auctions": 1,
        "gates": {
            "every_2013_2025_two_year_auction_schedule_bound": False,
            "return_data_unopened": True,
            "return_hypotheses_unspent": True,
        },
    }
    joined = pd.DataFrame(
        {
            "auction_date": [date(2020, 2, 25), date(2020, 5, 26)],
            "schedule_sha256": [None, "official"],
        }
    )
    wayback = pd.DataFrame(
        {
            "auction_date": [date(2020, 2, 25)],
            "archive_sha256": ["archive"],
        }
    )
    wayback_result = {
        "source_manifest_sha256": "manifest",
        "events_sha256": "events",
        "cdx_sha256": "cdx",
    }

    combined = augment_with_wayback(
        result,
        joined,
        wayback,
        wayback_result,
        "manifest",
        "events",
        "result",
    )

    assert combined["official_xml_schedule_bound_auctions"] == 1
    assert combined["wayback_ten_session_schedule_bound_auctions"] == 1
    assert combined["combined_schedule_bound_auctions"] == 2
    assert combined["combined_missing_auction_dates"] == []
    assert combined["decision"] == "PASS_TO_RETURN_PREREGISTRATION"


def test_xml_and_pdf_archive_proofs_union_without_double_counting() -> None:
    result = {
        "schedule_bound_auctions": 0,
        "gates": {
            "every_2013_2025_two_year_auction_schedule_bound": False,
            "return_data_unopened": True,
            "return_hypotheses_unspent": True,
        },
    }
    dates = [date(2020, 1, 28), date(2020, 2, 25), date(2020, 3, 24)]
    joined = pd.DataFrame(
        {"auction_date": dates, "schedule_sha256": [None, None, None]}
    )
    xml_events = pd.DataFrame(
        {"auction_date": dates[:2], "archive_sha256": ["xml", "xml"]}
    )
    pdf_events = pd.DataFrame(
        {"auction_date": dates[1:], "archive_sha256": ["pdf", "pdf"]}
    )
    xml_result = {
        "source_manifest_sha256": "manifest",
        "events_sha256": "xml-events",
        "cdx_sha256": "xml-cdx",
    }
    pdf_result = {
        "source_manifest_sha256": "manifest",
        "events_sha256": "pdf-events",
        "cdx_sha256": "pdf-cdx",
    }

    combined = augment_with_wayback(
        result,
        joined,
        xml_events,
        xml_result,
        "manifest",
        "xml-events",
        "xml-result",
        pdf_events,
        pdf_result,
        "pdf-events",
        "pdf-result",
    )

    assert combined["wayback_ten_session_schedule_bound_auctions"] == 2
    assert combined["wayback_pdf_ten_session_schedule_bound_auctions"] == 2
    assert combined["wayback_archive_union_bound_auctions"] == 3
    assert combined["combined_schedule_bound_auctions"] == 3
    assert combined["combined_missing_auction_dates"] == []
