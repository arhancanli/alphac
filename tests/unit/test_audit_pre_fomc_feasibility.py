from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "audit_pre_fomc_under_test", _ROOT / "scripts" / "audit_pre_fomc_feasibility.py"
)
assert _SPEC and _SPEC.loader
AUDIT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(AUDIT)


def test_historical_parser_keeps_meetings_and_excludes_conference_calls() -> None:
    page = """
    <h5 class="panel-heading panel-heading--shaded">January 26-27 Meeting - 2016</h5>
    <p><a href="/newsevents/pressreleases/monetary20160127a.htm">Statement</a></p>
    <h5 class="panel-heading panel-heading--shaded">March 2 (unscheduled) Meeting - 2020</h5>
    <p><a href="/newsevents/pressreleases/monetary20200303a.htm">Statement</a></p>
    """
    rows = AUDIT.parse_historical_scheduled(page, "official")
    assert [row["decision_date"] for row in rows] == ["2016-01-27"]


def test_current_parser_deduplicates_pdf_adjacent_html_and_bounds_years() -> None:
    page = """
    <a href="/newsevents/pressreleases/monetary20250129a.htm">HTML</a>
    <a href="/newsevents/pressreleases/monetary20250129a.htm">HTML duplicate</a>
    <a href="/newsevents/pressreleases/monetary20260128a.htm">future outside audit</a>
    """
    rows = AUDIT.parse_current_completed(page, "official")
    assert len(rows) == 1
    assert rows[0]["decision_date"] == "2025-01-29"


def test_current_parser_excludes_notation_votes() -> None:
    page = """
    <div class="fomc-meeting__date">22 (notation vote)</div>
    <a href="/newsevents/pressreleases/monetary20250822a.htm">Strategy statement</a>
    """
    assert AUDIT.parse_current_completed(page, "official") == []


def test_release_time_parser_accepts_est_and_edt_metadata() -> None:
    for zone in ("EST", "EDT"):
        text = AUDIT.parse_release_time(
            f'<p class="releaseTime"> For release at 2:00 p.m. {zone} </p>'
        )
        assert text == f"For release at 2:00 p.m. {zone}"


def test_release_time_parser_fails_closed_when_absent() -> None:
    assert AUDIT.parse_release_time("<p>statement body</p>") is None
