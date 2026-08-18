from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "audit_pre_fomc_schedule_lineage.py")
)
parse_annual_schedule = MODULE["parse_annual_schedule"]
summarize = MODULE["summarize"]


def test_old_schedule_parser_handles_cross_month_meeting() -> None:
    raw = b"""<h1>tentative meeting schedule for 2020:</h1>
    January 28-29 March 17-18 April 28-29 June 9-10 July 28-29
    September 15-16 November 4-5 December 15-16 January 26-27, 2021
    For media inquiries"""

    meetings = parse_annual_schedule(raw, 2020)

    assert len(meetings) == 8
    assert meetings[0] == date(2020, 1, 29)
    assert meetings[-1] == date(2020, 12, 16)


def test_modern_schedule_parser_uses_second_day() -> None:
    rows = " ".join(
        f"Tuesday, {month} {first}, and Wednesday, {month} {second}"
        for month, first, second in (
            ("January", 28, 29),
            ("March", 18, 19),
            ("May", 6, 7),
            ("June", 17, 18),
            ("July", 29, 30),
            ("September", 16, 17),
            ("October", 28, 29),
            ("December", 9, 10),
        )
    )
    raw = f"<p>For 2025: {rows} For 2026:</p>".encode()

    meetings = parse_annual_schedule(raw, 2025)

    assert meetings[0] == date(2025, 1, 29)
    assert meetings[-1] == date(2025, 12, 10)


def test_summary_requires_cancelled_slot_and_preserves_zero_return_use(monkeypatch) -> None:
    monkeypatch.setitem(summarize.__globals__, "prior_sessions", lambda *_: 20)
    monkeypatch.setitem(summarize.__globals__, "SCHEDULE_ANNOUNCEMENTS", {2020: "u"})
    completed = pd.DataFrame(
        {"decision_date": pd.to_datetime(["2020-01-29", "2020-04-29"])}
    )
    documents = [
        {
            "target_year": 2020,
            "publication_date": date(2019, 5, 17),
            "url": "u",
            "sha256": "a" * 64,
            "decision_dates": [date(2020, 1, 29), date(2020, 3, 18), date(2020, 4, 29)],
        }
    ]

    result, frame = summarize(
        completed,
        documents,
        b"March 17-18 (cancelled) Meeting - 2020",
        b"For release at 5:00 p.m. EDT",
    )

    assert len(frame) == 3
    assert result["schedule_only_dates"] == ["2020-03-18"]
    assert result["return_hypotheses_spent"] == 0
    assert result["gates"]["only_schedule_without_regular_statement_is_cancelled_2020_meeting"]
