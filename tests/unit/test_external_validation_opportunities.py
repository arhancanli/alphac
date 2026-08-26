from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/seal_external_validation_opportunities.py"
SPEC = importlib.util.spec_from_file_location("external_validation_opportunities_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_external_validation_audit_fails_closed() -> None:
    payload = MODULE.build()
    assert payload["schema"] == MODULE.SCHEMA
    assert payload["content_hash"] == _content_hash(payload)
    assert payload["decision"] == "NO_EXTERNAL_ACTION_AUTHORIZED_ELIGIBILITY_FACTS_REMAIN"
    assert payload["verified_on"] == "2026-08-26"
    assert payload["counts"] == {
        "opportunities": 6,
        "registered": 0,
        "submitted": 0,
        "awarded": 0,
        "registration_authorized": 0,
        "exact_future_deadlines": 2,
    }
    assert len(payload["owner_facts_required"]) == 6
    assert len(payload["opportunity_shortlist"]) == 6
    assert payload["opportunity_shortlist"][0].startswith(
        "1. Regeneron ISEF 2027 through an affiliated fair"
    )
    assert all(row["registration_authorized"] is False for row in payload["opportunities"])
    assert all(row["entry_claimed"] is False for row in payload["opportunities"])
    assert all(row["source_checked_on"] == "2026-08-26" for row in payload["opportunities"])
    assert all(row["unknowns"] for row in payload["opportunities"])
    assert all(
        url.startswith("https://")
        for row in payload["opportunities"]
        for url in row["official_sources"]
    )


def test_high_priority_rules_preserve_verified_constraints() -> None:
    rows = {row["id"]: row for row in MODULE.build()["opportunities"]}
    isef = rows["regeneron_isef_2027"]
    assert isef["eligibility"]["research_window"].endswith("no work before 2026-01-01")
    assert "may not initially write" in isef["ai_boundary"]
    assert isef["global_calendar"] == {
        "last_affiliated_fair_date": "2027-04-12",
        "abstract_rewrite_deadline": "2027-04-16",
        "isef_event": {"starts": "2027-05-08", "ends": "2027-05-14"},
    }
    assert isef["affiliated_fair_directory_query"] == {
        "directory_cycle": "2025-2026",
        "country": "United Arab Emirates",
        "fair_type": "ISEF",
        "result": "NO_FAIRS_MATCH_YOUR_SEARCH_CRITERIA",
        "result_count": 0,
        "checked_on": "2026-08-26",
        "interpretation": (
            "This establishes only that the current public directory lists no UAE ISEF fair. "
            "It does not establish the 2026-2027 network, which the Society says is populated "
            "as fairs complete annual affiliation."
        ),
    }

    wharton = rows["wharton_investment_2026_2027"]
    assert wharton["eligibility"]["team_size"] == "4-6 students from the same school"
    assert wharton["eligibility"]["team_leader"] == (
        "at least 16 years old at the start of the competition"
    )
    assert wharton["eligibility"]["registration_actor"] == "advisor, not student"
    assert "may not submit AI-generated work as their own" in wharton["ai_boundary"]
    assert wharton["exact_deadline"] == "2026-09-11T17:00:00-04:00"
    assert wharton["competition_calendar"] == {
        "registered_team_instructions": "2026-09-15",
        "competition_begins": "2026-09-28",
        "official_team_roster": "2026-10-09T17:00:00-04:00",
        "investment_policy_statement": "2026-11-06T17:00:00-05:00",
        "final_report_and_school_documentation": "2026-12-04T17:00:00-05:00",
    }

    diamond = rows["diamond_challenge_2027"]
    assert diamond["window_opens"] == "2026-09-16"
    assert diamond["exact_deadline"] == "2027-01-14T17:00:00-05:00"
    assert diamond["competition_calendar"]["summit"] == {
        "starts": "2027-04-29",
        "ends": "2027-04-30",
    }

    emirates = rows["emirates_young_scientist_next_cycle"]
    assert emirates["eligibility"]["individual"] == "UAE nationals only"
    assert "at most one non-UAE national" in emirates["eligibility"]["group"]

    nyas = rows["nyas_junior_academy_next_window"]
    assert nyas["fall_2026_window"]["conflicting_close_dates_on_official_page"] == [
        "2026-07-02",
        "2026-07-09",
    ]


def test_checked_in_external_validation_audit_is_current() -> None:
    path = Path("artifacts/analysis/external_validation_opportunities.json")
    assert json.loads(path.read_text(encoding="utf-8")) == MODULE.build()
