#!/usr/bin/env python3
"""Seal the current, official-source external-validation opportunity audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "artifacts/analysis/external_validation_opportunities.json"
SCHEMA: Final = "canli.alphac-external-validation-opportunities.v3"


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build() -> dict[str, Any]:
    opportunities: list[dict[str, Any]] = [
        {
            "priority": 1,
            "id": "regeneron_isef_2027",
            "name": "Regeneron ISEF 2027 through an affiliated fair",
            "kind": "SCIENTIFIC_COMPETITION",
            "fit": (
                "A new, narrow experiment on provenance, overfitting control, or "
                "quantitative-research methodology."
            ),
            "state": "POTENTIAL_ELIGIBILITY_NO_UAE_FAIR_IN_CURRENT_DIRECTORY_2027_PENDING",
            "public_status": (
                "The official 2025-2026 directory returns no UAE fair; the 2026-2027 "
                "directory and personal eligibility remain unresolved."
            ),
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "grade": "9-12 or equivalent",
                "age": "must not have reached 20 on or before May 1 preceding ISEF",
                "qualification": "selection by one ISEF-affiliated fair",
                "team_size": "1-3",
                "research_window": "no more than 12 continuous months; no work before 2026-01-01",
            },
            "ai_boundary": (
                "Generative AI may help develop ideas and may produce initial code or identify "
                "statistical tools only under the official logging and citation conditions. It "
                "may not initially write the research plan, abstract, paper, or poster; add "
                "substantive points or conclusions; or generate citations."
            ),
            "global_calendar": {
                "last_affiliated_fair_date": "2027-04-12",
                "abstract_rewrite_deadline": "2027-04-16",
                "isef_event": {"starts": "2027-05-08", "ends": "2027-05-14"},
            },
            "affiliated_fair_directory_query": {
                "directory_cycle": "2025-2026",
                "country": "United Arab Emirates",
                "fair_type": "ISEF",
                "result": "NO_FAIRS_MATCH_YOUR_SEARCH_CRITERIA",
                "result_count": 0,
                "checked_on": "2026-08-26",
                "interpretation": (
                    "This establishes only that the current public directory lists no UAE "
                    "ISEF fair. It does not establish the 2026-2027 network, which the "
                    "Society says is populated as fairs complete annual affiliation."
                ),
            },
            "exact_deadline": None,
            "unknowns": [
                "Arhan's grade and age on the governing dates",
                "the affiliated fair serving Arhan's school or UAE territory",
                "the affiliated fair deadline and preapproval procedure",
                "adult sponsor assignment",
            ],
            "next_action": (
                "Recheck the official directory as 2026-2027 affiliations appear, and ask the "
                "school or Society for Science which fair, if any, serves the UAE. Resolve that "
                "route and an adult sponsor before freezing or beginning the competition-specific "
                "experiment."
            ),
            "official_sources": [
                "https://www.societyforscience.org/isef/international-rules/",
                "https://www.societyforscience.org/isef/affiliated-fair-network/",
                "https://www.societyforscience.org/isef/affiliated-fair-guidelines/requirements/",
                "https://www.societyforscience.org/isef/forms/",
                "https://findafair.societyforscience.org/",
            ],
        },
        {
            "priority": 2,
            "id": "wharton_investment_2026_2027",
            "name": "Wharton Global High School Investment Competition 2026-2027",
            "kind": "INVESTMENT_COMPETITION",
            "fit": "A client-centered team portfolio thesis using ALPHAC's evidence discipline.",
            "state": "OPEN_BUT_TEAM_AND_ADVISOR_UNRESOLVED",
            "public_status": (
                "Registration closes September 11 at 5:00 p.m. ET; the team and school "
                "advisor are unresolved."
            ),
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "grade": "9-12; no secondary-school diploma before competition begins",
                "team_size": "4-6 students from the same school",
                "team_leader": "at least 16 years old at the start of the competition",
                "advisor": "one teacher or educator at the team's high school",
                "registration_actor": "advisor, not student",
            },
            "ai_boundary": (
                "Generative AI may be used for ideas and brainstorming, but teams may not submit "
                "AI-generated work as their own. Any included AI-generated material must be cited."
            ),
            "window_opens": "2026-08-10",
            "exact_deadline": "2026-09-11T17:00:00-04:00",
            "competition_calendar": {
                "registered_team_instructions": "2026-09-15",
                "competition_begins": "2026-09-28",
                "official_team_roster": "2026-10-09T17:00:00-04:00",
                "investment_policy_statement": "2026-11-06T17:00:00-05:00",
                "final_report_and_school_documentation": "2026-12-04T17:00:00-05:00",
            },
            "unknowns": [
                "Arhan's grade and school status",
                "whether Arhan or another eligible teammate can serve as the age-16 team leader",
                "three to five eligible same-school teammates",
                "teacher-advisor assignment",
                "whether the school can complete advisor registration before the deadline",
            ],
            "next_action": (
                "Resolve the same-school team and teacher-advisor immediately; have the advisor "
                "independently recheck the official calendar before any authorized registration."
            ),
            "official_sources": [
                "https://globalyouth.wharton.upenn.edu/competitions/investment-competition/",
                "https://globalyouth.wharton.upenn.edu/competitions/investment-competition/rules-roles/",
            ],
        },
        {
            "priority": 3,
            "id": "diamond_challenge_2027",
            "name": "Diamond Challenge 2027",
            "kind": "VENTURE_COMPETITION",
            "fit": (
                "ALPHAC as research-verification software only if interviews establish a real "
                "customer problem."
            ),
            "state": "WINDOW_NOT_YET_OPEN_TEAM_AND_ADVISOR_UNRESOLVED",
            "public_status": "The window opens September 16; the team and advisor are unresolved.",
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "age": "14-18 at submission deadline",
                "team_size": "2-4 high-school students",
                "advisor": "one adult aged 21 or older",
                "tracks": "business innovation or social innovation",
            },
            "window_opens": "2026-09-16",
            "exact_deadline": "2027-01-14T17:00:00-05:00",
            "competition_calendar": {
                "advancing_teams_notified": "2027-02-10T23:59:00-05:00",
                "finalists_announced": "2027-03-09",
                "summit": {"starts": "2027-04-29", "ends": "2027-04-30"},
            },
            "unknowns": [
                "Arhan's age and high-school status at the deadline",
                "one to three eligible teammates",
                "adult-advisor assignment",
                "customer interviews supporting track and problem selection",
            ],
            "next_action": "Run problem interviews before selecting a track or drafting an entry.",
            "official_sources": ["https://diamondchallenge.org/competition/"],
        },
        {
            "priority": 4,
            "id": "blue_ocean_student_competition_2027",
            "name": "Blue Ocean Student Entrepreneur Competition 2027",
            "kind": "VENTURE_PITCH_COMPETITION",
            "fit": (
                "A concise evidence-first product pitch that defines the research-verification "
                "problem, intended user, alternatives, and tested value proposition."
            ),
            "validation_boundary": (
                "Judging a venture pitch does not validate ALPHAC's software correctness, "
                "research claims, strategy returns, or forward objectives."
            ),
            "state": "REGISTRATION_OPEN_PERSONAL_ELIGIBILITY_UNRESOLVED",
            "public_status": (
                "Registration is open and the pitch deadline is February 21, 2027 at midnight "
                "in the participant's local time; personal eligibility remains unresolved."
            ),
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "age": "14-18 at registration",
                "school_status": "high-school student",
                "location": "worldwide and virtual",
                "team_size": "1-5 students",
                "language": "English",
            },
            "entry_requirements": {
                "course": "complete the official Blue Ocean mini-course",
                "pitch": "English video under five minutes and under 1 GB",
                "playback": "normal speed; artificially accelerated video is prohibited",
            },
            "exact_deadline": "2027-02-21_LOCAL_MIDNIGHT",
            "competition_calendar": {
                "top_100_announced": "2027-04-05",
                "top_30_announced": "2027-04-22",
                "top_10_announced": "2027-05-04",
                "winners_announced": "2027-05-13",
            },
            "unknowns": [
                "Arhan's age and high-school status at registration",
                "whether a solo or team entry best reflects actual contribution",
                (
                    "whether customer evidence supports a distinct market rather than a "
                    "technology demo"
                ),
                "the current competition's AI-assistance and disclosure policy",
            ],
            "next_action": (
                "Use this only as a solo-capable fallback after customer interviews. Recheck "
                "the official rules and AI policy before any authorized submission, and keep "
                "the pitch separate from scientific-validation claims."
            ),
            "official_sources": ["https://blueoceancompetition.org/compete/"],
        },
        {
            "priority": 5,
            "id": "emirates_young_scientist_next_cycle",
            "name": "Emirates Young Scientist Competition, next announced cycle",
            "kind": "SCIENTIFIC_COMPETITION",
            "fit": "A UAE-facing version of a new scientific or computing experiment.",
            "state": "CURRENT_RULES_FOUND_NEXT_CYCLE_DATES_UNRESOLVED",
            "public_status": "The next cycle date and Arhan's eligible entry route are unresolved.",
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "grade": "5-12 in a UAE public, private, or vocational institute",
                "individual": "UAE nationals only",
                "group": "up to three students; at most one non-UAE national",
                "advisor": "designated teacher or project supervisor",
            },
            "exact_deadline": None,
            "unknowns": [
                "Arhan's grade, school type, and nationality",
                "whether an individual or eligible group route exists for Arhan",
                "next-cycle dates and category rules",
                "teacher or supervisor assignment",
            ],
            "next_action": (
                "Resolve nationality and team composition, then wait for a dated next-cycle "
                "Ministry announcement before registration."
            ),
            "official_sources": ["https://e.moe.gov.ae/ords/moe/r/nsti/eysc"],
        },
        {
            "priority": 6,
            "id": "conrad_challenge_2026_2027",
            "name": "Conrad Challenge 2026-2027",
            "kind": "STEM_VENTURE_COMPETITION",
            "fit": "A genuine STEM product innovation, not a repackaged trading-performance story.",
            "state": "CURRENT_CYCLE_CONFIRMED_EXACT_PHASE_DATES_UNRESOLVED",
            "public_status": "The current cycle is confirmed; exact phase dates are unresolved.",
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {"age": "13-18", "cycle": "annual, August through April"},
            "exact_deadline": None,
            "unknowns": [
                "Arhan's age",
                "current team, coach, fee, category, and phase rules",
                "exact 2026-2027 phase deadlines",
                "product and category fit",
            ],
            "next_action": (
                "Do not reuse the 2025-2026 calendar; wait for the official 2026-2027 guide and "
                "rules before committing work."
            ),
            "official_sources": [
                "https://conrad.spacecenter.org/about-challenge/",
                "https://conrad.spacecenter.org/participate/student-innovators/",
            ],
        },
        {
            "priority": 7,
            "id": "nyas_junior_academy_next_window",
            "name": "New York Academy of Sciences Junior Academy, next open cohort",
            "kind": "MENTORED_STEM_PROGRAM",
            "fit": "External teamwork and mentor feedback on a challenge chosen by the program.",
            "state": "FALL_2026_CLOSED_NEXT_EXACT_WINDOW_UNRESOLVED",
            "public_status": "Fall 2026 is closed; the next application window is unresolved.",
            "registration_authorized": False,
            "entry_claimed": False,
            "source_checked_on": "2026-08-26",
            "eligibility": {
                "age": "13-17 and must remain under 18 during the challenge",
                "location": "global virtual",
                "time_commitment": "3-4 hours per week during challenge periods",
                "cost": "free",
            },
            "fall_2026_window": {
                "opened": "2026-04-01",
                "status": "CLOSED",
                "conflicting_close_dates_on_official_page": ["2026-07-02", "2026-07-09"],
            },
            "exact_deadline": None,
            "unknowns": [
                "Arhan's age during the next challenge",
                "the next exact application window",
                "whether a program challenge fits Arhan's intended contribution",
            ],
            "next_action": "Monitor the official page for the next dated application window.",
            "official_sources": [
                "https://www.nyas.org/learning/high-school-research-programs/the-junior-academy/"
            ],
        },
    ]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "owner_and_applicant": "Arhan Canli",
        "verified_on": "2026-08-26",
        "decision": "NO_EXTERNAL_ACTION_AUTHORIZED_ELIGIBILITY_FACTS_REMAIN",
        "owner_facts_required": [
            "date of birth and age on each governing date",
            "current grade and expected graduation date",
            "school name, school type, and school-country status",
            "nationality where a competition uses nationality rules",
            "available same-school teammates",
            "available teacher, adult sponsor, or advisor",
        ],
        "counts": {
            "opportunities": len(opportunities),
            "registered": 0,
            "submitted": 0,
            "awarded": 0,
            "registration_authorized": 0,
            "exact_future_deadlines": sum(
                row.get("exact_deadline") is not None for row in opportunities
            ),
        },
        "opportunity_shortlist": [
            f"{row['priority']}. {row['name']}: {row['public_status']}" for row in opportunities
        ],
        "opportunities": opportunities,
        "claim_boundary": (
            "This is a dated official-source opportunity audit. It proves no personal eligibility, "
            "registration, submission, judging, advancement, award, review, publication, or "
            "Stanford admissions outcome. Rules and deadlines must be rechecked immediately before "
            "any authorized external action."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
