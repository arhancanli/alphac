from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_treasury_auction_identity_timing.py"
)
SPEC = spec_from_file_location("audit_treasury_auction_identity_timing", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def frame(lead_days: list[int]) -> pd.DataFrame:
    auction_dates = pd.to_datetime(["2020-01-20"] * len(lead_days))
    return pd.DataFrame(
        {
            "security_type": ["Note"] * len(lead_days),
            "security_term": ["2-Year"] * len(lead_days),
            "floating_rate": ["No"] * len(lead_days),
            "auction_date": auction_dates,
            "announcement_date": [
                date - pd.Timedelta(days=lead)
                for date, lead in zip(auction_dates, lead_days, strict=True)
            ],
        }
    )


def test_formal_notice_fails_published_ten_session_identity(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_TWO_YEAR_EVENTS", 2)
    result = MODULE.summarize(frame([5, 7]), "abc")

    assert result["two_year_note_auctions"] == 2
    assert result["formal_announcements_with_at_least_ten_calendar_days"] == 0
    assert result["gates"]["formal_notice_supports_published_ten_session_entry"] is False
    assert result["decision"] == "CALENDAR_LINEAGE_REQUIRED"
    assert result["return_hypotheses_spent"] == 0


def test_ten_day_formal_notice_still_requires_tentative_archive(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_TWO_YEAR_EVENTS", 2)
    result = MODULE.summarize(frame([10, 12]), "abc")

    assert result["gates"]["formal_notice_supports_published_ten_session_entry"] is True
    assert result["gates"]["point_in_time_tentative_schedule_archive_sealed"] is False
    assert result["decision"] == "CALENDAR_LINEAGE_REQUIRED"


def test_non_two_year_events_are_excluded(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_TWO_YEAR_EVENTS", 1)
    data = frame([5])
    other = data.assign(security_term="5-Year")
    result = MODULE.summarize(pd.concat([data, other], ignore_index=True), "abc")

    assert result["two_year_note_auctions"] == 1


def test_two_year_floating_rate_notes_are_excluded(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_TWO_YEAR_EVENTS", 1)
    fixed = frame([5])
    floating = fixed.assign(floating_rate="Yes")
    result = MODULE.summarize(pd.concat([fixed, floating], ignore_index=True), "abc")

    assert result["two_year_note_auctions"] == 1
