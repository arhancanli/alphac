#!/usr/bin/env python3
"""Bind FOMC decisions to dated annual schedules and preserve the 2020 cancellation.

This audit opens no market data or returns. It treats each annual Federal Reserve schedule press
release as first-known evidence and requires the eventual return identity to include all 80
scheduled slots, including March 17-18, 2020 as an explicit cancellation rather than silently
dropping it because no regular statement was released.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import httpx
import pandas as pd

EVENTS: Final = Path("artifacts/feasibility/pre_fomc_announcement_drift/events.parquet")
RAW_DIR: Final = Path("data/raw/pre_fomc_announcement_drift/annual_schedule_lineage")
EVENTS_OUT: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/annual_schedule_events.parquet"
)
RESULT: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/annual_schedule_lineage.json"
)
HISTORICAL_2020: Final = (
    "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
)
CANCELLATION_TRIGGER: Final = (
    "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200315a.htm"
)
SCHEDULE_ANNOUNCEMENTS: Final[dict[int, str]] = {
    2016: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20150511a.htm",
    2017: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20160628a.htm",
    2018: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20170511b.htm",
    2019: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20180525a.htm",
    2020: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20190517a.htm",
    2021: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200702a.htm",
    2022: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20210604a.htm",
    2023: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20220624a.htm",
    2024: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20230623a.htm",
    2025: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm",
}
UA: Final = "Canli Capital quantitative research research@canlicapital.com"
MONTHS: Final = {
    name: number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
MONTH_PATTERN: Final = "|".join(MONTHS)
OLD_RANGE: Final = re.compile(
    rf"({MONTH_PATTERN})\s+(\d{{1,2}})-(?:({MONTH_PATTERN})\s+)?(\d{{1,2}})"
)
NEW_RANGE: Final = re.compile(
    rf"(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+({MONTH_PATTERN})\s+"
    rf"(\d{{1,2}}),\s+and\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+"
    rf"({MONTH_PATTERN})\s+(\d{{1,2}})"
)
URL_DATE: Final = re.compile(r"monetary(20\d{6})[a-z0-9]*\.htm")
CANCELLED_DATE: Final = date(2020, 3, 18)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def fetch(url: str) -> bytes:
    error: Exception | None = None
    for attempt in range(5):
        try:
            with httpx.Client(
                timeout=60.0,
                follow_redirects=True,
                headers={"User-Agent": UA},
            ) as client:
                response = client.get(url)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        "retryable Federal Reserve response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.content
        except (httpx.HTTPError, OSError) as exc:
            error = exc
            time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"Federal Reserve request failed after retries: {url}") from error


def clean_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def publication_date(url: str) -> date:
    match = URL_DATE.search(url)
    if match is None:
        raise ValueError(f"no publication date in Federal Reserve URL: {url}")
    return datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=UTC).date()


def parse_annual_schedule(raw: bytes, target_year: int) -> list[date]:
    text = clean_text(raw)
    explicit_marker = f"For {target_year}:"
    ordinary_marker = f"schedule for {target_year}:"
    marker = explicit_marker if explicit_marker in text else ordinary_marker
    if marker not in text:
        raise ValueError(f"annual schedule marker absent for {target_year}")
    section = text.split(marker, 1)[1]
    section = section.split(f"For {target_year + 1}:", 1)[0]
    section = section.split("For media inquiries", 1)[0]
    modern = NEW_RANGE.findall(section)
    ranges = modern if modern else OLD_RANGE.findall(section)
    if len(ranges) not in {8, 9}:
        raise ValueError(f"expected 8 target meetings plus optional carry, found {len(ranges)}")
    meetings = []
    for first_month, _, second_month, second_day in ranges[:8]:
        end_month = second_month or first_month
        meetings.append(date(target_year, MONTHS[end_month], int(second_day)))
    if len(meetings) != 8 or len(set(meetings)) != 8:
        raise ValueError(f"invalid annual FOMC schedule for {target_year}: {meetings}")
    return meetings


def prior_sessions(publication: date, event: date) -> int:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(pd.Timestamp(publication), pd.Timestamp(event))
    return int((sessions < pd.Timestamp(event)).sum())


def summarize(
    completed_events: pd.DataFrame,
    schedule_documents: list[dict[str, Any]],
    historical_2020_raw: bytes,
    cancellation_trigger_raw: bytes,
) -> tuple[dict[str, Any], pd.DataFrame]:
    completed = set(pd.to_datetime(completed_events["decision_date"]).dt.date)
    rows = []
    for document in schedule_documents:
        for decision_date in document["decision_dates"]:
            rows.append(
                {
                    "target_year": document["target_year"],
                    "scheduled_decision_date": decision_date,
                    "initial_publication_date": document["publication_date"],
                    "initial_publication_lead_sessions": prior_sessions(
                        document["publication_date"], decision_date
                    ),
                    "schedule_url": document["url"],
                    "schedule_sha256": document["sha256"],
                    "event_status": (
                        "CANCELLED_AFTER_UNSCHEDULED_DECISION"
                        if decision_date == CANCELLED_DATE
                        else "COMPLETED_REGULAR_DECISION"
                    ),
                }
            )
    frame = pd.DataFrame(rows).sort_values("scheduled_decision_date")
    scheduled = set(frame["scheduled_decision_date"])
    schedule_only = sorted(scheduled - completed)
    completed_only = sorted(completed - scheduled)
    historical_text = clean_text(historical_2020_raw).lower()
    cancellation_text = clean_text(cancellation_trigger_raw)
    cancellation_release_match = re.search(
        r"For release at\s+5:00\s+p\.m\.\s+EDT", cancellation_text, re.I
    )
    cancellation_publication = publication_date(CANCELLATION_TRIGGER)
    cancellation_lead = prior_sessions(cancellation_publication, CANCELLED_DATE)
    gates = {
        "ten_annual_schedule_sources_hash_bound": len(schedule_documents) == 10
        and all(document["sha256"] for document in schedule_documents),
        "eight_scheduled_slots_per_year": len(frame) == 80
        and bool(frame.groupby("target_year").size().eq(8).all()),
        "every_completed_regular_decision_in_initial_schedule": not completed_only,
        "only_schedule_without_regular_statement_is_cancelled_2020_meeting": schedule_only
        == [CANCELLED_DATE],
        "official_history_marks_2020_meeting_cancelled": (
            "march 17-18 (cancelled) meeting - 2020" in historical_text
        ),
        "cancellation_trigger_timestamp_bound": bool(cancellation_release_match),
        "all_initial_schedule_dates_published_before_target_year": all(
            document["publication_date"] < date(document["target_year"], 1, 1)
            for document in schedule_documents
        ),
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    result = {
        "schema": "canli.feasibility.pre-fomc-schedule-lineage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_annual_schedule_lineage_no_prices_no_returns",
        "target_years": [2016, 2025],
        "annual_schedule_sources": len(schedule_documents),
        "scheduled_slots": len(frame),
        "completed_regular_decisions": len(completed),
        "explicit_cancellations": len(schedule_only),
        "schedule_only_dates": list(map(str, schedule_only)),
        "completed_only_dates": list(map(str, completed_only)),
        "minimum_initial_publication_lead_sessions": int(
            frame["initial_publication_lead_sessions"].min()
        ),
        "cancellation": {
            "scheduled_decision_date": str(CANCELLED_DATE),
            "public_trigger_date": str(cancellation_publication),
            "public_trigger_release_time": "5:00 p.m. EDT",
            "sessions_before_scheduled_decision": cancellation_lead,
            "historical_page_url": HISTORICAL_2020,
            "historical_page_sha256": sha256_bytes(historical_2020_raw),
            "trigger_url": CANCELLATION_TRIGGER,
            "trigger_sha256": sha256_bytes(cancellation_trigger_raw),
            "required_return_state": "CANCELLED_NO_ENTRY_OR_FLATTEN_AT_NEXT_ELIGIBLE_OPEN",
        },
        "gates": gates,
        "decision": (
            "PASS_TO_RETURN_PREREGISTRATION"
            if all(gates.values())
            else "CALENDAR_LINEAGE_REQUIRED"
        ),
        "return_identity_requirement": (
            "Use all 80 scheduled slots and preserve March 17-18, 2020 as a cancellation; "
            "do not test only the 79 ex-post completed statements."
        ),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }
    return result, frame


def load_or_fetch(raw_dir: Path, name: str, url: str) -> bytes:
    path = raw_dir / name
    if path.exists():
        return path.read_bytes()
    raw = fetch(url)
    atomic_write(path, raw)
    return raw


def run(
    events_path: Path,
    raw_dir: Path,
    events_out: Path,
    result_path: Path,
) -> dict[str, Any]:
    documents = []
    for target_year, url in sorted(SCHEDULE_ANNOUNCEMENTS.items()):
        raw = load_or_fetch(raw_dir, f"schedule-{target_year}.html", url)
        pub_date = publication_date(url)
        text = clean_text(raw)
        display_date = pub_date.strftime("%B %d, %Y")
        if display_date not in text and display_date.replace(" 0", " ") not in text:
            raise ValueError(f"page publication date does not cross-check URL for {target_year}")
        documents.append(
            {
                "target_year": target_year,
                "url": url,
                "publication_date": pub_date,
                "sha256": sha256_bytes(raw),
                "decision_dates": parse_annual_schedule(raw, target_year),
            }
        )
    historical_raw = load_or_fetch(raw_dir, "fomc-historical-2020.html", HISTORICAL_2020)
    trigger_raw = load_or_fetch(
        raw_dir,
        "cancellation-trigger-2020-03-15.html",
        CANCELLATION_TRIGGER,
    )
    result, frame = summarize(
        pd.read_parquet(events_path), documents, historical_raw, trigger_raw
    )
    events_out.parent.mkdir(parents=True, exist_ok=True)
    temporary_events = events_out.with_suffix(events_out.suffix + ".tmp")
    frame.to_parquet(temporary_events, index=False, compression="zstd")
    temporary_events.replace(events_out)
    result["events_file"] = str(events_out)
    result["events_sha256"] = sha256_bytes(events_out.read_bytes())
    result["completed_event_manifest_sha256"] = sha256_bytes(events_path.read_bytes())
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_result.write_text(json.dumps(result, indent=2) + "\n")
    temporary_result.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=EVENTS)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--events-out", type=Path, default=EVENTS_OUT)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    result = run(args.events, args.raw_dir, args.events_out, args.result)
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_RETURN_PREREGISTRATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
